"""
Biểu đồ cho báo cáo — dựng từ số liệu thật, không để mô hình vẽ.

VÌ SAO CODE VẼ CHỨ KHÔNG PHẢI MÔ HÌNH: cùng lý do link do code chèn. Một biểu
đồ do mô hình sinh là một biểu đồ bịa — và biểu đồ bịa nguy hiểm hơn câu văn
bịa, vì người đọc tin vào hình hơn tin vào chữ, lại không có cách nào kiểm.
Mục 7 của prompt vì vậy cấm mô hình tự vẽ biểu đồ bằng ký tự.

Nguồn số liệu là `payload["danh_sach_van_ban"]` — khối dữ kiện mà CHÍNH mô hình
đã nhận. Nhờ vậy biểu đồ và phần chữ không thể nói hai chuyện khác nhau; lấy
lại từ DB bằng một truy vấn riêng thì chúng trôi khỏi nhau ngay khi bộ truy
xuất đổi.

Mỗi biểu đồ đều có ngưỡng tối thiểu. Biểu đồ hai cột trông như lỗi in, và một
biểu đồ vô nghĩa làm hỏng uy tín của cả bản báo cáo nhiều hơn là không có biểu
đồ nào.
"""
from __future__ import annotations

import collections
import logging
from datetime import date

from src.utils.report_theme import (
    Figure, bar_counts, bar_status, timeline_effective_dates,
)

logger = logging.getLogger(__name__)

# Dưới ngưỡng này thì không vẽ. Đo bằng mắt trên bản in: 3 nhóm là ranh giới mà
# biểu đồ cột bắt đầu nói được điều gì đó thay vì chỉ lặp lại con số trong bảng.
TOI_THIEU_NHOM = 3
TOI_THIEU_VAN_BAN = 4


def _nhan_hieu_luc(vb: dict) -> str:
    """Nhãn tình trạng hiệu lực, ưu tiên cờ đã chuẩn hoá.

    `tinh_trang_hieu_luc_chuan_hoa` là bản đã chuẩn hoá; `eff_status` là chuỗi
    tự do của Bộ Tư pháp, cùng một tình trạng có nhiều cách viết nên vẽ ra sẽ
    thành nhiều cột cho cùng một thứ.

    Tên khoá phải khớp context.document_facts(). Bản đầu tôi đoán là
    "eff_state_dien_giai" — không tồn tại, nên nó âm thầm rơi xuống nhánh dự
    phòng và nhóm theo đúng chuỗi tự do mà đoạn trên nói là không được dùng.
    Biểu đồ vẫn vẽ ra, chỉ là vẽ sai. Đây là lần thứ hai trong cùng file này
    tôi mắc lỗi đoán tên khoá; xem thêm _theo_nganh().
    """
    return (vb.get("tinh_trang_hieu_luc_chuan_hoa") or vb.get("eff_status")
            or "Chưa xác định")


def _theo_loai(ds: list[dict]) -> Figure | None:
    dem = collections.Counter(vb.get("doc_type") or "Chưa phân loại" for vb in ds)
    if len(dem) < TOI_THIEU_NHOM:
        return None
    top = dem.most_common(7)
    return Figure(
        0,
        f"Các văn bản trong báo cáo này thuộc loại gì ({len(ds)} văn bản)",
        bar_counts([k for k, _ in top], [v for _, v in top]),
    )


def _theo_hieu_luc(ds: list[dict]) -> Figure | None:
    dem = collections.Counter(_nhan_hieu_luc(vb) for vb in ds)
    if len(dem) < 2 or len(ds) < TOI_THIEU_VAN_BAN:
        return None
    return Figure(
        0,
        "Bao nhiêu văn bản còn đang áp dụng, bao nhiêu đã bị thay hoặc bỏ",
        bar_status(dict(dem)),
    )


def _moc_sap_toi(ds: list[dict], hom_nay: date | None = None) -> Figure | None:
    """Các mốc bắt đầu áp dụng từ hôm nay trở đi — phần hành động được nhất."""
    hom_nay = hom_nay or date.today()
    dem: collections.Counter = collections.Counter()
    for vb in ds:
        try:
            ngay = date.fromisoformat((vb.get("eff_from") or "")[:10])
        except ValueError:
            continue
        if ngay >= hom_nay:
            dem[f"{ngay.month:02d}/{str(ngay.year)[2:]}"] += 1

    if len(dem) < TOI_THIEU_NHOM or sum(dem.values()) < TOI_THIEU_VAN_BAN:
        if dem:
            logger.info("Bỏ biểu đồ mốc hiệu lực: chỉ %d mốc / %d văn bản",
                        len(dem), sum(dem.values()))
        return None

    thang = sorted(dem, key=lambda m: (m[3:], m[:2]))[:8]
    return Figure(
        0,
        "Những mốc bạn cần chuẩn bị trước — số văn bản bắt đầu áp dụng theo tháng",
        timeline_effective_dates(thang, [dem[m] for m in thang]),
    )


def _theo_nganh(payload: dict) -> Figure | None:
    """Văn bản trong báo cáo chạm mạnh nhất tới ngành nào.

    Chỉ có nghĩa với báo cáo (b): nó gom văn bản mới của nhiều ngành, nên câu
    hỏi "ngành nào lãnh nhiều nhất" là câu hỏi thật. Báo cáo (a) và (c) vốn đã
    chỉ nói về một ngành, vẽ ra chỉ là một cột.
    """
    # Tên trường phải khớp context.industry_impact(). Bản đầu tôi đoán là
    # "impact_pct_doc" — tên cột trong SQL — nhưng hàm đó đổi tên khi trả ra,
    # nên biểu đồ này lặng lẽ không bao giờ hiện. Không có gì báo lỗi: payload
    # vẫn hợp lệ, biểu đồ chỉ đơn giản là vắng mặt.
    diem = payload.get("diem_tac_dong_nganh") or []
    gop: collections.Counter = collections.Counter()
    for d in diem:
        ten = d.get("ten_nganh") or d.get("ma_nganh")
        pct = d.get("ty_trong_tac_dong")
        if ten and isinstance(pct, (int, float)):
            gop[ten] += float(pct)
    if len(gop) < TOI_THIEU_NHOM:
        return None
    top = gop.most_common(8)
    return Figure(
        0,
        "Ngành nào chịu ảnh hưởng nhiều nhất từ các văn bản trong báo cáo này",
        bar_counts([k for k, _ in top], [round(v) for _, v in top]),
    )


def build_figures(kind: str, payload: dict) -> list[Figure]:
    """Biểu đồ cho một báo cáo, chọn theo loại.

    Trước hàm này, worker gọi build_report_pdf mà KHÔNG truyền figures — nghĩa
    là mọi báo cáo do hệ thống tự sinh đều không có biểu đồ nào, trong khi
    script chạy tay thì có. Người dùng chỉ thấy bản tự sinh.
    """
    ds = payload.get("danh_sach_van_ban") or []
    if not ds:
        return []

    ung_vien = [_theo_loai(ds), _theo_hieu_luc(ds), _moc_sap_toi(ds)]
    if kind == "b":
        ung_vien.insert(0, _theo_nganh(payload))

    figs = [f for f in ung_vien if f is not None]
    # Đánh số lại liên tục: bộ dựng PDF in "BIỂU ĐỒ {number}" nguyên văn, nên
    # số nhảy cóc khi một biểu đồ bị bỏ là lỗi hiện ra tận bản in.
    for i, f in enumerate(figs, 1):
        f.number = i
    return figs
