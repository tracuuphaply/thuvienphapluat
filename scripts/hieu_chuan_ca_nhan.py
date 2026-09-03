"""
Hiệu chuẩn phễu cho đối tượng cá nhân — lấy mẫu, chấm, đo.

    python -m scripts.hieu_chuan_ca_nhan lay-mau --so-mau 200
    python -m scripts.hieu_chuan_ca_nhan cham
    python -m scripts.hieu_chuan_ca_nhan do

VÌ SAO PHẢI HIỆU CHUẨN TRƯỚC KHI CÀO. 18 lĩnh vực liên quan cá nhân cộng lại
11.639 biểu mẫu, nhưng "liên quan cá nhân" là nói về CHỦ ĐỀ, không phải về người
điền. Đo thử trên lĩnh vực 39 (Tư pháp – Hộ tịch, 186 mẫu): 12/12 mẫu đầu đều là
"MẪU BÁO CÁO KẾT QUẢ ĐĂNG KÝ KHAI SINH… TẠI ỦY BAN NHÂN DÂN CẤP XÃ" — mẫu của
UBND gửi lên tỉnh, không mẫu nào do người dân điền. Cào cả 11.639 rồi mới biết
tỉ lệ nhiễu là lặp lại đúng bài học 17.385 mẫu của đợt doanh nghiệp.

LẤY MẪU NGẪU NHIÊN THEO TRANG, không lấy đầu danh sách. TVPL sắp mới-trước, mà
mẫu mới thì phần lớn là biểu báo cáo do các thông tư gần đây ban hành — lấy 200
mẫu đầu là đo một góc kho rồi tưởng đã đo cả kho.

CHIA MẪU THEO CĂN BẬC HAI của số mẫu mỗi lĩnh vực, không chia đều và cũng không
chia theo tỉ lệ. Chia đều thì lĩnh vực 28 mẫu (Hôn nhân – Gia đình) và lĩnh vực
1.860 mẫu (Y tế) cùng được 11 mẫu — lãng phí ở bên nhỏ, quá thưa ở bên lớn. Chia
theo tỉ lệ thì Y tế nuốt 32 mẫu còn Hôn nhân được 0, mà Hôn nhân mới là nhóm việc
cá nhân gặp nhiều nhất.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import random
from collections import Counter
from pathlib import Path

from src.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

TEP_MAU = PROJECT_ROOT / "data" / "hieu_chuan_ca_nhan.json"
MOI_TRANG = 20

#: 18 lĩnh vực liên quan cá nhân, kèm số mẫu đo trực tiếp trên TVPL 24/08/2026.
LINH_VUC_CA_NHAN: dict[int, tuple[str, int]] = {
    47: ("Y tế", 1860),
    17: ("Giao thông vận tải", 1728),
    32: ("Thủ tục tố tụng", 1520),
    35: ("Thuế – Phí – Lệ phí", 1214),
    24: ("Lao động – Tiền lương", 1108),
    18: ("Giáo dục", 805),
    8:  ("Chính sách xã hội", 762),
    2:  ("Bảo hiểm", 644),
    13: ("Đất đai – Nhà ở", 593),
    4:  ("Bổ trợ Tư pháp", 365),
    38: ("Trách nhiệm hình sự", 327),
    10: ("Dân sự", 286),
    42: ("Vi phạm hành chính", 269),
    39: ("Tư pháp – Hộ tịch", 186),
    22: ("Khiếu nại – Tố cáo", 163),
    33: ("Thủ tục hành chính", 150),
    45: ("Xuất nhập cảnh", 131),
    20: ("Hôn nhân – Gia đình – Thừa kế", 28),
}


def phan_bo(so_mau: int) -> dict[int, int]:
    """Chia chỉ tiêu lấy mẫu theo căn bậc hai của quy mô lĩnh vực."""
    can = {ma: math.sqrt(n) for ma, (_, n) in LINH_VUC_CA_NHAN.items()}
    tong = sum(can.values())
    ra = {ma: max(4, round(so_mau * v / tong)) for ma, v in can.items()}
    for ma, (_, n) in LINH_VUC_CA_NHAN.items():
        ra[ma] = min(ra[ma], n)
    return ra


async def lay_mau(so_mau: int, seed: int) -> None:
    """Lấy mẫu tiêu đề từ các trang NGẪU NHIÊN của từng lĩnh vực."""
    from src.sources.tvpl_forms import TVPLFormCrawler, url_bieu_mau
    from src.sources.tvpl_forms_parse import tach_danh_sach

    rng = random.Random(seed)
    chi_tieu = phan_bo(so_mau)
    c = TVPLFormCrawler()
    await c.chuan_bi(dang_nhap=True)
    ra: list[dict] = []
    try:
        for ma, can_lay in chi_tieu.items():
            ten, tong = LINH_VUC_CA_NHAN[ma]
            so_trang = max(1, math.ceil(tong / MOI_TRANG))
            # Bốc trang không lặp; mỗi trang cho tối đa 20 mẫu nên số trang cần
            # bốc là trần(can_lay / 20), lấy dư 1 trang cho chắc.
            can_trang = min(so_trang, math.ceil(can_lay / MOI_TRANG) + 1)
            trang_chon = rng.sample(range(1, so_trang + 1), can_trang)
            gom: list = []
            for t in trang_chon:
                try:
                    html = await c.lay_html(url_bieu_mau(field=ma, page=t))
                    gom.extend(tach_danh_sach(html))
                except Exception as e:                    # noqa: BLE001
                    logger.warning("lĩnh vực %s trang %s hỏng: %s", ma, t, e)
                await asyncio.sleep(1.5)
            rng.shuffle(gom)
            for it in gom[:can_lay]:
                ra.append({"form_key": it.form_key, "url": it.url,
                           "title": it.title, "field_code": ma,
                           "linh_vuc": ten})
            print(f"  {ma:2} {ten:32} lấy {min(len(gom), can_lay):3}/{can_lay:3} "
                  f"từ {len(trang_chon)} trang", flush=True)
    finally:
        await c.stop()

    TEP_MAU.parent.mkdir(parents=True, exist_ok=True)
    TEP_MAU.write_text(json.dumps(ra, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nĐã ghi {len(ra)} mẫu vào {TEP_MAU}")


def cham() -> None:
    """Chấm tầng 2 trên TIÊU ĐỀ của mẫu đã lấy, ghi kết quả vào cùng tệp.

    CHỈ TIÊU ĐỀ, chưa có ruột mẫu. Đây là giới hạn có ý thức: tải ruột cho 200
    mẫu là 200 lượt qua Cloudflare, mà tiêu đề đã mang trọng số 3 trong khi mỗi
    từ khoá trong ruột chỉ được 1. Con số đo ra là CẬN DƯỚI của tầng 2 — có ruột
    thì chỉ tốt lên. Nói rõ ở đây vì một cận dưới bị đọc thành số thật là cách
    nhanh nhất để kết luận sai về bộ từ khoá.
    """
    from src.forms.relevance import quyet_dinh_quy_tac

    ds = json.loads(TEP_MAU.read_text(encoding="utf-8"))
    for m in ds:
        q = quyet_dinh_quy_tac(m["title"] or "")
        m["may_doan"] = {
            "audience": q.audience,
            "dn": q.cho_doanh_nghiep,
            "cn": q.cho_ca_nhan,
            "diem": [q.diem_giu, q.diem_ca_nhan, q.diem_loai],
            "dau_hieu": (q.dau_hieu_giu + q.dau_hieu_ca_nhan + q.dau_hieu_loai)[:5],
        }
    TEP_MAU.write_text(json.dumps(ds, ensure_ascii=False, indent=1), encoding="utf-8")

    dem = Counter(
        "cả hai" if m["may_doan"]["dn"] and m["may_doan"]["cn"]
        else "doanh nghiệp" if m["may_doan"]["dn"]
        else "cá nhân" if m["may_doan"]["cn"]
        else str(m["may_doan"]["audience"] or "chưa quyết")
        for m in ds
    )
    print(f"Đã chấm {len(ds)} mẫu:")
    for k, v in dem.most_common():
        print(f"  {v:4}  {k}")


def do() -> None:
    """So nhãn tay với kết quả tầng 2, in độ chính xác và độ phủ."""
    ds = json.loads(TEP_MAU.read_text(encoding="utf-8"))
    co_nhan = [m for m in ds if m.get("nhan_tay")]
    if not co_nhan:
        print("Chưa có nhãn tay. Điền trường 'nhan_tay' "
              "(ca_nhan | doanh_nghiep | ca_hai | co_quan) rồi chạy lại.")
        return

    def du_doan(m):
        d, c = m["may_doan"]["dn"], m["may_doan"]["cn"]
        if d and c:
            return "ca_hai"
        if d:
            return "doanh_nghiep"
        if c:
            return "ca_nhan"
        return "co_quan" if m["may_doan"]["audience"] == "co_quan_nha_nuoc" else "chua_quyet"

    print(f"Đo trên {len(co_nhan)} mẫu đã gán nhãn tay\n")
    for nhom in ("ca_nhan", "doanh_nghiep", "ca_hai", "co_quan"):
        that = [m for m in co_nhan if m["nhan_tay"] == nhom]
        doan = [m for m in co_nhan if du_doan(m) == nhom]
        dung = [m for m in doan if m["nhan_tay"] == nhom]
        cx = len(dung) / len(doan) * 100 if doan else 0.0
        dp = len(dung) / len(that) * 100 if that else 0.0
        print(f"  {nhom:14} thật {len(that):3} · máy đoán {len(doan):3} · "
              f"chính xác {cx:5.1f}% · độ phủ {dp:5.1f}%")

    # PHÉP ĐO THẬT SỰ QUAN TRỌNG là nhị phân "có thuộc kho cá nhân không".
    # Bảng bốn nhóm ở trên chấm mẫu `ca_hai` bị đoán thành `ca_nhan` là SAI, mà
    # với câu hỏi "mẫu này có phục vụ cá nhân không" thì đó là ĐÚNG — hợp đồng
    # thuê nhà phục vụ cả hai bên, xếp nó vào kho cá nhân không sai chỗ nào.
    that_cn = [m for m in co_nhan if m["nhan_tay"] in ("ca_nhan", "ca_hai")]
    doan_cn = [m for m in co_nhan if m["may_doan"]["cn"]]
    dung_cn = [m for m in doan_cn if m["nhan_tay"] in ("ca_nhan", "ca_hai")]
    cx = len(dung_cn) / len(doan_cn) * 100 if doan_cn else 0.0
    dp = len(dung_cn) / len(that_cn) * 100 if that_cn else 0.0
    f1 = 2 * cx * dp / (cx + dp) if (cx + dp) else 0.0
    print(f"\n  PHỤC VỤ CÁ NHÂN (nhị phân): thật {len(that_cn)} · máy đoán "
          f"{len(doan_cn)} · chính xác {cx:.1f}% · độ phủ {dp:.1f}% · F1 {f1:.1f}")

    chua = [m for m in co_nhan if du_doan(m) == "chua_quyet"]
    print(f"\n  chưa quyết được: {len(chua)}/{len(co_nhan)} "
          f"({len(chua)/len(co_nhan)*100:.0f}%) — phần này cần tầng 3")
    if chua:
        print("  ví dụ:")
        for m in chua[:6]:
            print(f"    [{m['nhan_tay']:12}] {m['title'][:62]}")


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("lenh", choices=["lay-mau", "cham", "do"])
    ap.add_argument("--so-mau", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20260826,
                    help="Cố định để lấy lại đúng bộ mẫu cũ khi cần đo lại")
    args = ap.parse_args()

    if args.lenh == "lay-mau":
        asyncio.run(lay_mau(args.so_mau, args.seed))
    elif args.lenh == "cham":
        cham()
    else:
        do()


if __name__ == "__main__":
    main()
