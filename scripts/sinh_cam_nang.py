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
from src.rag.reports.llm import LLMUnavailable

logger = logging.getLogger(__name__)

MAC_DINH_LIMIT = 20

#: DB đối chiếu trích dẫn là file TẠM, dựng lại được từ chỉ mục vault mỗi lượt
#: chạy — để chung chỗ với nhớ đệm toàn văn dưới data/ (đã gitignore), không vứt
#: ra gốc repo cạnh sổ trạng thái.
DB_DOI_CHIEU = PROJECT_ROOT / "data" / "cam-nang" / "so-hieu-vault.db"


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
        print("Không có biểu mẫu nào cần sinh bài. Dùng --tat-ca để sinh lại.")
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
        except LLMUnavailable as e:
            # Không có mô hình thì mọi biểu mẫu còn lại cũng hỏng như nhau —
            # chạy tiếp chỉ in ra n dòng lỗi giống hệt nhau.
            print(f"    DỪNG: {e}", file=sys.stderr)
            hong.append((bm.form_key, str(e)))
            break
        except SinhThatBai as e:
            print(f"    BỎ: {e}")
            hong.append((bm.form_key, str(e)))
            continue

        kq = cong.cong_hop_dong(bai.ban_ghi())
        if not kq:
            print(f"    BỎ: không qua hợp đồng — {kq.ly_do}")
            if not bai.citation_ok:
                truot_trich_dan.append(bm.form_key)
                print(f"         số hiệu lạ: {', '.join(bai.so_hieu_la[:5])}")
            hong.append((bm.form_key, kq.ly_do))
            # Vẫn ghi sổ: lần sau `can_sinh_lai` thấy citation_ok=false và sinh
            # lại — bài trượt cổng chưa bao giờ tới được bên xuất bản.
            so.ghi_nhan(bm.form_key, bm.nguon_hash(), bai.citation_ok)
            continue

        ban_ghi.append(bai.ban_ghi())
        so.ghi_nhan(bm.form_key, bm.nguon_hash(), True)
        print(f"    ✓ {bai.tieu_de[:70]}")
        print(f"      {len(bai.than_bai)} ký tự · {bai.so_hieu_dat} số hiệu đối "
              f"chiếu đạt{' · đã sinh lại tiêu đề' if bai.sinh_lai else ''}")

    # Ghi ĐÚNG mảng ở gốc, dạng chính của §1 hợp đồng. Không thêm khối metadata
    # bọc ngoài: bên nhận đọc được cả `{bai:[…]}` lẫn `{data:[…]}`, nhưng một
    # khoá lạ nằm cạnh thì không có gì bảo đảm nó được bỏ qua.
    duong_dan = Path(args.out)
    duong_dan.parent.mkdir(parents=True, exist_ok=True)
    duong_dan.write_text(
        json.dumps(ban_ghi, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
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
