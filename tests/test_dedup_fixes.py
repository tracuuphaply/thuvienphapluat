"""Gộp trigger không được đánh rơi văn bản trùng số hiệu khác tỉnh.

Lỗi gốc: khoá gộp chỉ là số hiệu chuẩn hoá → hai tỉnh cùng "40/2026/QĐ-UBND"
gộp vào một khoá, cái sau ghi đè cái trước → một tỉnh không bao giờ vào hàng đợi
cào/thông báo. Đúng cái mất dữ liệu mà doc_key sinh ra để chặn, tái diễn ở tầng
gộp trigger.
"""
from src.pipeline.deduplicator import merge_triggers


def test_hai_tinh_trung_so_hieu_deu_giu_lai():
    moj = [
        {"doc_num": "40/2026/QĐ-UBND", "moj_id": "111",
         "agency_name": "UBND Hà Nội",
         "title": "Quyết định về phí lệ phí đầu tư kinh doanh"},
        {"doc_num": "40/2026/QĐ-UBND", "moj_id": "222",
         "agency_name": "UBND TP.HCM",
         "title": "Quyết định về phí lệ phí đầu tư kinh doanh"},
    ]
    out = merge_triggers([], moj)
    assert len(out) == 2, "phải giữ CẢ HAI tỉnh"
    assert sorted(d["moj_id"] for d in out) == ["111", "222"]


def test_gop_tvpl_va_moj_khi_khong_nhap_nhang():
    """Ca thường: một văn bản trung ương có ở cả TVPL lẫn MOJ → gộp làm MỘT."""
    tvpl = [{"title": "Nghị định 100/2026/NĐ-CP về đăng ký kinh doanh",
             "tvpl_id": "t1", "tvpl_url": "u1", "field_code": 1}]
    moj = [{"doc_num": "100/2026/NĐ-CP", "moj_id": "m1",
            "agency_name": "Chính phủ", "title": "Nghị định về đăng ký kinh doanh"}]
    out = merge_triggers(tvpl, moj)
    assert len(out) == 1, "một văn bản, hai nguồn → một ứng viên"
    e = out[0]
    assert e.get("tvpl_id") == "t1" and e.get("moj_id") == "m1"
    assert e.get("source_tvpl") and e.get("source_moj")
