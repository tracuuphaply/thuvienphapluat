"""Đề xuất #1 — bảng ánh xạ referenceType.

Lỗi gốc: mã 3 là "Căn cứ" nhưng bị gán "Bãi bỏ", khiến 82% cạnh đồ thị sai và
hàng trăm văn bản cấp tỉnh trông như đang bãi bỏ luật Quốc hội.
"""
import pytest

from src.sources.moj_api import (
    REFERENCE_TYPE_LABELS,
    UNVERIFIED_RELATION,
    parse_doc_detail,
    relation_label,
)


def test_ma_3_la_can_cu_khong_phai_bai_bo():
    """Bằng chứng: 1188 mẫu, 84% đứng sau chữ "Căn cứ"; chỉ 5% đích hết hiệu lực."""
    assert relation_label(3) == "Căn cứ"
    assert relation_label(3) != "Bãi bỏ"


@pytest.mark.parametrize(
    "code,expected",
    [
        (1, "Bãi bỏ"),           # 66% văn bản đích đã có effTo
        (3, "Căn cứ"),
        (9, "Căn cứ"),
        (10, "Sửa đổi, bổ sung"),  # 95% mẫu, 0% đích hết hiệu lực
        (12, "Thay thế"),          # 95% đích hết hiệu lực
    ],
)
def test_cac_ma_da_kiem_chung(code, expected):
    assert relation_label(code) == expected


@pytest.mark.parametrize("code", [4, 5, 7, 8, 11, 99, None])
def test_ma_chua_kiem_chung_khong_bi_doan_bua(code):
    """Mã thiếu bằng chứng phải lộ ra là chưa biết, không được gán nhãn có thật.

    Gán bừa một quan hệ chấm dứt hiệu lực cho mã chưa rõ chính là cách lỗi cũ
    phát sinh — thà nói "chưa xác định" còn hơn nói sai.
    """
    label = relation_label(code)
    assert label.startswith(UNVERIFIED_RELATION)
    assert label not in ("Bãi bỏ", "Thay thế", "Hủy bỏ", "Đình chỉ", "Sửa đổi, bổ sung")


def test_khong_con_nhan_cham_dut_nao_chua_duoc_kiem_chung():
    """Chỉ những mã đã kiểm chứng mới được mang nhãn làm mất hiệu lực."""
    terminating = {"Bãi bỏ", "Thay thế", "Hủy bỏ", "Đình chỉ"}
    for code, label in REFERENCE_TYPE_LABELS.items():
        if label in terminating:
            assert code in (1, 12), f"mã {code} mang nhãn chấm dứt {label!r} mà chưa kiểm chứng"


def test_parse_doc_detail_dung_nhan_moi():
    """Payload thật của gateway: căn cứ luật, không phải bãi bỏ luật."""
    payload = {
        "data": {
            "docNum": "40/2026/QĐ-UBND",
            "references": [
                {
                    "targetDocument": {"docNum": "72/2025/QH15"},
                    "referenceType": 3,
                },
                {
                    "targetDocument": {"docNum": "122/2021/NĐ-CP"},
                    "referenceType": 10,
                },
            ],
        }
    }
    refs = parse_doc_detail(payload)["references"]
    by_target = {r["target_doc_num"]: r["relation_type"] for r in refs}
    assert by_target["72/2025/QH15"] == "Căn cứ"
    assert by_target["122/2021/NĐ-CP"] == "Sửa đổi, bổ sung"


def test_nhan_dang_chu_uu_tien_hon_ma_so():
    """Nguồn trả nhãn chữ sẵn thì dùng luôn, không map lại."""
    payload = {
        "data": {
            "references": [
                {"docNum": "01/2020/NĐ-CP", "relationType": "Thay thế", "referenceType": 3}
            ]
        }
    }
    refs = parse_doc_detail(payload)["references"]
    assert refs[0]["relation_type"] == "Thay thế"


class TestCoQuanBanHanh:
    """`agencyName` là cơ quan ban hành; `organization` chỉ là đơn vị quản lý bản ghi.

    Lấy nhầm thứ tự khiến Luật Ngân sách nhà nước 89/2025/QH15 bị ghi là do
    "Bộ Tài chính" ban hành thay vì Quốc hội — sai dữ kiện pháp lý ngay trong
    bảng kiểm hiệu lực của báo cáo. Toàn bộ 144 đạo Luật trong kho đều dính.
    """

    def test_uu_tien_agencyName_hon_organization(self):
        from src.sources.moj_api import parse_doc_summary
        got = parse_doc_summary({
            "docNum": "89/2025/QH15",
            "title": "Luật Ngân sách nhà nước số 89/2025/QH15",
            "agencyName": "Quốc hội",
            "organization": {"name": "Bộ Tài chính"},
        })
        assert got["agency_name"] == "Quốc hội"

    def test_nghi_dinh_thuoc_chinh_phu(self):
        from src.sources.moj_api import parse_doc_summary
        got = parse_doc_summary({
            "docNum": "292/2026/NĐ-CP", "title": "Nghị định",
            "agencyName": "Chính phủ",
            "organization": {"name": "Bộ Công thương"},
        })
        assert got["agency_name"] == "Chính phủ"

    def test_cap_tinh_giu_duoc_ten_tinh(self):
        """doc_key dựa vào trường này — mất tên tỉnh là các tỉnh đụng khoá nhau."""
        from src.sources.moj_api import parse_doc_summary
        from src.storage.database import make_doc_key

        a = parse_doc_summary({
            "docNum": "67/2026/QĐ-UBND", "title": "QĐ",
            "agencyName": "UBND Tỉnh Quảng Ngãi", "organization": {"name": "Quảng Ngãi"},
        })
        b = parse_doc_summary({
            "docNum": "67/2026/QĐ-UBND", "title": "QĐ",
            "agencyName": "UBND Tỉnh Lạng Sơn", "organization": {"name": "Lạng Sơn"},
        })
        assert a["agency_name"] != b["agency_name"]
        assert make_doc_key(a["doc_num"], a["agency_name"]) != \
               make_doc_key(b["doc_num"], b["agency_name"])

    def test_thieu_agencyName_thi_lui_ve_organization(self):
        from src.sources.moj_api import parse_doc_summary
        got = parse_doc_summary({
            "docNum": "1/2026/QĐ", "title": "x",
            "organization": {"name": "Bộ Tài chính"},
        })
        assert got["agency_name"] == "Bộ Tài chính"


class TestSuyCoQuanTuSoHieu:
    """Số hiệu mã hoá sẵn cơ quan ban hành — đây là quy tắc pháp lý.

    Dữ liệu Bộ Tư pháp có chỗ ghi sai: Luật Xây dựng 135/2025/QH15 được ghi do
    "Bộ Xây dựng" ban hành. Một đạo Luật luôn do Quốc hội ban hành, nên khi số
    hiệu và trường agencyName mâu thuẫn thì số hiệu thắng.
    """

    @pytest.mark.parametrize("doc_num,expected", [
        ("89/2025/QH15", "Quốc hội"),
        ("135/2025/QH15", "Quốc hội"),
        ("292/2026/NĐ-CP", "Chính phủ"),
        ("12/2026/QĐ-TTg", "Thủ tướng Chính phủ"),
        ("45/2024/UBTVQH15", "Ủy ban Thường vụ Quốc hội"),
        ("28/2005/PL-UBTVQH11", "Ủy ban Thường vụ Quốc hội"),
    ])
    def test_suy_dung_co_quan(self, doc_num, expected):
        from src.sources.moj_api import agency_from_doc_num
        assert agency_from_doc_num(doc_num) == expected

    @pytest.mark.parametrize("doc_num", [
        "101/2026/TT-BTC",      # thông tư — cơ quan thay đổi theo bộ
        "67/2026/QĐ-UBND",      # cấp tỉnh — phải giữ tên tỉnh từ nguồn
        "23/2026/NQ-HĐND",
        "1016/QĐ-UBND",
        "32-LCT/HĐNN8",
        "",
    ])
    def test_hau_to_khong_xac_dinh_thi_giu_nguyen_nguon(self, doc_num):
        from src.sources.moj_api import agency_from_doc_num
        assert agency_from_doc_num(doc_num) == ""

    def test_ghi_de_khi_nguon_mau_thuan(self):
        from src.sources.moj_api import parse_doc_summary
        got = parse_doc_summary({
            "docNum": "135/2025/QH15", "title": "Luật Xây dựng",
            "agencyName": "Bộ Xây dựng", "organization": {"name": "Bộ Xây dựng"},
        })
        assert got["agency_name"] == "Quốc hội"

    def test_khong_dung_vao_thong_tu_va_cap_tinh(self):
        from src.sources.moj_api import parse_doc_summary
        assert parse_doc_summary({
            "docNum": "101/2026/TT-BTC", "title": "TT", "agencyName": "Bộ Tài chính",
        })["agency_name"] == "Bộ Tài chính"
        assert parse_doc_summary({
            "docNum": "67/2026/QĐ-UBND", "title": "QĐ", "agencyName": "UBND Tỉnh Lạng Sơn",
        })["agency_name"] == "UBND Tỉnh Lạng Sơn"
