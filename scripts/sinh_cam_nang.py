"""
Sinh `bai.json` — thân bài Cẩm nang cho biểu mẫu, giao sang bên xuất bản.

    # đối chiếu kho, không gọi mô hình, không tốn tiền
    python -m scripts.sinh_cam_nang --vault ../legal-vault-public --soi

    # sinh thử 3 bài
    python -m scripts.sinh_cam_nang --vault ../legal-vault-public --limit 3

    # chỉ nhóm viết được bài sâu nhất (có căn cứ + có toàn văn trên Drive)
    python -m scripts.sinh_cam_nang --vault ../legal-vault-public \
        --co-toan-van --limit 20 --out bai.json

Bên nhận chạy:

    npm run import:phapluat -- --dir <legal-vault-public> --generated bai.json

Mọi bài tạo ra bên đó đều `status='draft'`. Bộ nhập KHÔNG BAO GIỜ tự xuất bản —
duyệt bài vẫn là việc của người, đó là chốt chặn cuối giữa "có nội dung" và
"đăng nội dung sai lên trang public". Script này cũng không tự đẩy file đi đâu.

TRẦN SẢN LƯỢNG. Kế hoạch nội dung đặt ≤ ~150 bài/tháng cho TOÀN hệ thống, gồm cả
bài auto-content; Cẩm nang chỉ nên chiếm phần nhỏ trong đó. `--limit` mặc định
20 là cố ý — một máy in bài chạy vô nghĩa chính là scaled content, và đó là thứ
làm hỏng 653 bài lần trước.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from src.camnang import cong
from src.camnang.kho import KhoKhongDoc, chon_ung_vien, db_so_hieu_tu_kho, doc_kho
from src.camnang.sinh import SinhThatBai, sinh_bai
from src.camnang.trang_thai import DUONG_DAN_MAC_DINH, SoTrangThai
from src.config import PROJECT_ROOT, cam_nang_max_tokens, cam_nang_model
from src.rag.reports.llm import LLMUnavailable, call_report_llm

logger = logging.getLogger(__name__)

MAC_DINH_LIMIT = 20

#: DB đối chiếu trích dẫn là file TẠM, dựng lại được từ chỉ mục vault mỗi lượt
#: chạy — để chung chỗ với nhớ đệm toàn văn dưới data/ (đã gitignore), không vứt
#: ra gốc repo cạnh sổ trạng thái.
DB_DOI_CHIEU = PROJECT_ROOT / "data" / "cam-nang" / "so-hieu-vault.db"


def _ghi_dau_ra(duong_dan: Path, ban_ghi: list[dict]) -> Path:
    """Ghi ĐÚNG mảng ở gốc, dạng chính của §1 hợp đồng.

    Không thêm khối metadata bọc ngoài: bên nhận đọc được cả `{bai:[…]}` lẫn
    `{data:[…]}`, nhưng một khoá lạ nằm cạnh thì không có gì bảo đảm nó được bỏ
    qua. Một hàm dùng chung cho mọi đường ra, kể cả đường "không có gì để sinh" —
    hai chỗ ghi khác nhau là hai chỗ để quên mất một chỗ.
    """
    duong_dan.parent.mkdir(parents=True, exist_ok=True)
    duong_dan.write_text(
        json.dumps(ban_ghi, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return duong_dan


def _kiem_khoa(model: str) -> int:
    """Gọi mô hình một lượt CỰC NGẮN để biết khoá và tên model có dùng được không.

    VÌ SAO ĐÁNG MỘT LƯỢT GỌI: sai tên model hay hết hạn khoá đều chỉ lộ ra ở
    lượt gọi đầu tiên — mà lượt đó nằm giữa một lượt chạy đã tải xong toàn văn
    và đang viết bài thứ nhất. Biết trước bằng 5 token rẻ hơn nhiều so với biết
    sau khi đã đốt vài lượt sinh bài, nhất là khi gateway đổi danh mục model.
    """
    from src.config import openai_api_base

    print(f"Gateway : {openai_api_base()}")
    print(f"Model   : {model}")
    try:
        kq = call_report_llm(
            "Trả lời đúng một từ.", "Nói: xong", model=model, max_tokens=16,
        )
    except LLMUnavailable as e:
        print(f"\n✗ KHÔNG DÙNG ĐƯỢC: {e}", file=sys.stderr)
        print("\nKiểm lại theo thứ tự:", file=sys.stderr)
        print("  1. Khoá đã khai chưa (V98_API_KEY hoặc OPENAI_API_KEY)?",
              file=sys.stderr)
        print("  2. Tên model có đúng danh mục gateway không? Đặt lại bằng",
              file=sys.stderr)
        print("     CAM_NANG_MODEL=<tên đúng> hoặc cờ --model.", file=sys.stderr)
        print("  3. OPENAI_API_BASE có trỏ đúng gateway không?", file=sys.stderr)
        return 2

    print(f"\n✓ Gọi được. Mô hình trả về: {kq.text.strip()[:80]!r}")
    print(f"  model thật gateway dùng: {kq.model}")
    return 0


def _bang_soi(kho, ung_vien) -> None:
    """In đối chiếu kho — biểu mẫu nào viết được bài sâu, nhóm nào chỉ soi mẫu."""
    co_toan_van = sum(1 for u in ung_vien if u.co_toan_van)
    co_can_cu = sum(1 for u in ung_vien if u.can_cu_khop)
    theo_hieu_luc: dict[str, int] = {}
    for u in ung_vien:
        theo_hieu_luc[u.bieu_mau.hieu_luc] = theo_hieu_luc.get(u.bieu_mau.hieu_luc, 0) + 1

    print(f"=== Kho vault (xuất lúc {kho.tao_luc or 'không rõ'}) ===")
    print(f"  biểu mẫu trong chỉ mục : {len(kho.bieu_mau)}")
    print(f"  văn bản trong chỉ mục  : {len(kho.van_ban)}")
    print(f"  ứng viên viết được bài : {len(ung_vien)}")
    print(f"    có căn cứ khớp kho   : {co_can_cu}")
    print(f"    có toàn văn trên Drive: {co_toan_van}   ← nhóm nên chạy trước")
    print("  phân bố hiệu lực:")
    for ma, dem in sorted(theo_hieu_luc.items(), key=lambda kv: -kv[1]):
        print(f"    {kho.hieu_luc_bm.get(ma, ma):<24} {dem}")

    print("\n=== 10 ứng viên đầu bảng ===")
    for u in ung_vien[:10]:
        co = "toàn văn" if u.co_toan_van else ("căn cứ" if u.can_cu_khop else "chỉ mẫu")
        print(f"  [{u.diem:>3}] {u.bieu_mau.form_key:<18} {co:<9} "
              f"{u.bieu_mau.tieu_de[:64]}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vault", required=True,
                    help="Gốc checkout legal-vault-public (bắt buộc)")
    ap.add_argument("--out", default="bai.json", help="File JSON đầu ra")
    ap.add_argument("--limit", type=int, default=MAC_DINH_LIMIT,
                    help=f"Số bài tối đa một lượt (mặc định {MAC_DINH_LIMIT})")
    ap.add_argument("--soi", action="store_true",
                    help="Đối chiếu kho và in bảng, KHÔNG gọi mô hình")
    ap.add_argument("--kiem-khoa", action="store_true",
                    help="Gọi mô hình MỘT lượt cực ngắn để kiểm khoá + tên model, "
                         "rồi dừng. Dùng trước khi chạy thật.")
    ap.add_argument("--co-toan-van", action="store_true",
                    help="Chỉ biểu mẫu có căn cứ kèm toàn văn trên Drive")
    ap.add_argument("--nghiep-vu", default="",
                    help="Lọc theo nhóm nghiệp vụ, vd hop_dong")
    ap.add_argument("--hieu-luc", default="",
                    help="Lọc theo cờ hiệu lực biểu mẫu, vd con_hieu_luc")
    ap.add_argument("--form-key", action="append", default=[],
                    help="Chỉ sinh cho form_key này (lặp lại được)")
    ap.add_argument("--tat-ca", action="store_true",
                    help="Sinh cả biểu mẫu đã có bài và nguồn chưa đổi")
    ap.add_argument("--khong-toan-van", action="store_true",
                    help="Không tải toàn văn từ Drive (bài sẽ nông hơn)")
    ap.add_argument("--trang-thai", default=str(DUONG_DAN_MAC_DINH),
                    help="Sổ da-sinh.json theo dõi nguồn đã đổi hay chưa")
    ap.add_argument("--model", default="", help="Ghi đè CAM_NANG_MODEL")
    ap.add_argument("--db", default="",
                    help="SQLite có bảng documents để đối chiếu trích dẫn. "
                         "Bỏ trống = dựng từ chính chỉ mục vault")
    args = ap.parse_args()

    # `--limit -1` không phải "không giới hạn": `ds[:-1]` sinh TẤT CẢ TRỪ biểu
    # mẫu cuối. Trần sản lượng mà fail-open thì đúng là thứ nó tồn tại để chặn.
    if args.limit < 1:
        print(f"LỖI: --limit phải >= 1 (nhận {args.limit}).", file=sys.stderr)
        return 2

    try:
        kho = doc_kho(args.vault)
    except KhoKhongDoc as e:
        print(f"LỖI: {e}", file=sys.stderr)
        return 2

    ung_vien = chon_ung_vien(
        kho,
        nghiep_vu=args.nghiep_vu,
        hieu_luc=args.hieu_luc,
        chi_co_toan_van=args.co_toan_van,
    )
    if args.form_key:
        chon = set(args.form_key)
        ung_vien = [u for u in ung_vien if u.bieu_mau.form_key in chon]
        thieu = chon - {u.bieu_mau.form_key for u in ung_vien}
        if thieu:
            # Báo to chứ không im lặng: form_key không khớp kho là lỗi bên nhận
            # cũng sẽ mắc, và ở đó nó chỉ hiện thành một dòng "bỏ".
            print(f"CẢNH BÁO: {len(thieu)} form_key không có trong kho hoặc "
                  f"không đủ điều kiện: {', '.join(sorted(thieu))}", file=sys.stderr)

    if args.soi:
        _bang_soi(kho, ung_vien)
        return 0

    if args.kiem_khoa:
        return _kiem_khoa(args.model or cam_nang_model())

    so = SoTrangThai(Path(args.trang_thai))
    if not args.tat_ca:
        truoc = len(ung_vien)
        ung_vien = [u for u in ung_vien
                    if so.can_sinh_lai(u.bieu_mau.form_key,
                                       u.bieu_mau.nguon_hash())]
        bo_qua = truoc - len(ung_vien)
        if bo_qua:
            logger.info("Bỏ qua %d biểu mẫu đã có bài và nguồn chưa đổi", bo_qua)

    ung_vien = ung_vien[:args.limit]
    if not ung_vien:
        # GHI FILE RỖNG chứ không thoát tay không. "Không có gì đổi" là trạng
        # thái BÌNH THƯỜNG của mọi lượt chạy theo lịch sau lượt đầu — thoát mà
        # không để lại file khiến bước kế tiếp (`json.load(bai.json)`) vỡ bằng
        # FileNotFoundError đúng ở đường chạy hay gặp nhất.
        _ghi_dau_ra(Path(args.out), [])
        print("Không có biểu mẫu nào cần sinh bài. Dùng --tat-ca để sinh lại.")
        print(f"Đã ghi mảng rỗng vào {args.out}.")
        return 0

    # Cổng trích dẫn phải có kho để đối chiếu. `data/legal_docs.db` không nằm
    # trong git nên trên CI nó vắng mặt — dựng từ chỉ mục vault thì pipeline
    # chạy được ở mọi nơi có checkout, và đối chiếu đúng tập văn bản mà bên xuất
    # bản có trang để dẫn tới.
    db_path = Path(args.db) if args.db else db_so_hieu_tu_kho(kho, DB_DOI_CHIEU)

    model = args.model or cam_nang_model()
    print(f"Sinh {len(ung_vien)} bài bằng {model}…\n")

    ban_ghi: list[dict] = []
    hong: list[tuple[str, str]] = []
    truot_trich_dan: list[str] = []

    for i, u in enumerate(ung_vien, 1):
        bm = u.bieu_mau
        print(f"[{i}/{len(ung_vien)}] {bm.form_key} — {bm.tieu_de[:60]}")
        try:
            bai = sinh_bai(
                u, kho,
                tai_toan_van_ve=not args.khong_toan_van,
                db_path=db_path,
                model=model,
                max_tokens=cam_nang_max_tokens(),
            )
        except (LLMUnavailable, cong.KhoDoiChieuHong) as e:
            # Không có mô hình, hoặc không mở được kho đối chiếu — cả hai đều là
            # hỏng TOÀN CỤC: mọi biểu mẫu còn lại sẽ hỏng y hệt, chạy tiếp chỉ in
            # ra n dòng lỗi giống nhau. Dừng vòng lặp chứ KHÔNG để lỗi thoát ra
            # ngoài: những bài đã sinh xong trước đó vẫn phải được ghi ra file,
            # nếu không là đốt tiền mô hình rồi vứt kết quả.
            print(f"    DỪNG: {e}", file=sys.stderr)
            hong.append((bm.form_key, str(e)))
            break
        except SinhThatBai as e:
            print(f"    BỎ: {e}")
            hong.append((bm.form_key, str(e)))
            continue

        kq = cong.cong_hop_dong(bai.ban_ghi(), ruot_mau_len=len(bm.ruot_mau))
        if not kq:
            print(f"    BỎ: không qua hợp đồng — {kq.ly_do}")
            if not bai.citation_ok:
                truot_trich_dan.append(bm.form_key)
                print(f"         số hiệu lạ: {', '.join(bai.so_hieu_la[:5])}")
            hong.append((bm.form_key, kq.ly_do))
            # Ghi sổ với cờ FALSE, bất kể vì sao trượt. Cờ trong sổ trả lời đúng
            # một câu: "biểu mẫu này đã có bài giao đi được chưa?" — trượt hợp
            # đồng thì chưa, kể cả khi trượt vì mô tả quá dài chứ không phải vì
            # trích dẫn. Ghi `bai.citation_ok` (có thể là True) làm
            # `can_sinh_lai` trả False ở lượt sau, và biểu mẫu đó VĨNH VIỄN
            # không có bài mà không ai thấy.
            so.ghi_nhan(bm.form_key, bm.nguon_hash(), False)
            continue

        ban_ghi.append(bai.ban_ghi())
        so.ghi_nhan(bm.form_key, bm.nguon_hash(), True)
        print(f"    ✓ {bai.tieu_de[:70]}")
        print(f"      {len(bai.than_bai)} ký tự · {bai.so_hieu_dat} số hiệu đối "
              f"chiếu đạt{' · đã sinh lại tiêu đề' if bai.sinh_lai else ''}")

    duong_dan = _ghi_dau_ra(Path(args.out), ban_ghi)
    so_trang_thai = so.luu()

    print("\n=== Kết quả ===")
    print(f"  bài giao được    {len(ban_ghi)}")
    print(f"  bỏ               {len(hong)}")
    if truot_trich_dan:
        print(f"  trượt cổng trích dẫn: {', '.join(truot_trich_dan)}")
    print(f"  đầu ra           {duong_dan}")
    print(f"  sổ trạng thái    {so_trang_thai} ({len(so)} biểu mẫu)")
    if ban_ghi:
        print("\nBên xuất bản chạy:")
        print(f"  npm run import:phapluat -- --dir <legal-vault-public> "
              f"--generated {duong_dan.name}")
        print("Bài vào dạng NHÁP; duyệt tay ở /admin/cam-nang rồi mới xuất bản.")
    return 0 if ban_ghi or not ung_vien else 1


if __name__ == "__main__":
    raise SystemExit(main())
