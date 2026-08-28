"""
Cổng lĩnh vực VĂN BẢN sau khi mở sang đối tượng cá nhân.

Kho văn bản trước đây chỉ nhận 10 mã lĩnh vực doanh nghiệp, nên nó mỏng đúng ở
chỗ cá nhân cần: đo trên 4.201 văn bản đã có, Vi phạm hành chính 13 bản, Trách
nhiệm hình sự 15, Thủ tục tố tụng 34 — so với Thuế 546 và Thương mại 510. Đó là
hệ quả của cổng cào, không phải của kho.
"""
import pytest

from src.config import (
    BUSINESS_FIELD_CODES,
    CA_NHAN_FIELD_CODES,
    CA_NHAN_FIELDS,
    THEO_DOI_FIELD_CODES,
)
from src.sources.moj_api import (
    _get_primary_field_code,
    get_field_name,
    is_business_document,
    is_individual_document,
    la_van_ban_theo_doi,
    tieu_de_dang_theo_doi,
    title_looks_business,
)


def vb(*ten_linh_vuc: str) -> dict:
    return {"documentFields": [{"name": t} for t in ten_linh_vuc]}


class TestTapMa:
    def test_hai_he_ma_khong_giao_nhau(self):
        """Hai tập rời nhau, nên hợp lại không mã nào bị nuốt.

        Nếu về sau có mã chung, `THEO_DOI_FIELD_CODES` vẫn đúng nhưng
        `_get_primary_field_code` sẽ phải chọn — test này là chỗ phát hiện.
        """
        assert not (BUSINESS_FIELD_CODES & CA_NHAN_FIELD_CODES)
        assert len(THEO_DOI_FIELD_CODES) == len(BUSINESS_FIELD_CODES) + len(CA_NHAN_FIELD_CODES)

    def test_tam_ma_ca_nhan_chon_bang_bang_chung(self):
        """Chốt đúng 8 mã, kèm ba khác biệt so với danh sách phỏng đoán ban đầu."""
        assert sorted(CA_NHAN_FIELD_CODES) == [12, 13, 16, 17, 18, 22, 24, 25]
        # 13 được THÊM: mẫu thật là Luật sư, Trợ giúp pháp lý, Đấu giá tài sản.
        assert 13 in CA_NHAN_FIELD_CODES
        # 15 bị BỎ: dân quân tự vệ, chế độ cán bộ công chức — tổ chức bộ máy.
        assert 15 not in CA_NHAN_FIELD_CODES
        # 26 bị BỎ: Luật Xuất bản, danh hiệu Nghệ nhân — không phải việc cá nhân.
        assert 26 not in CA_NHAN_FIELD_CODES
        # 21 và 23 trông hợp nhưng thật ra là hàng hải/cảng biển và khoáng sản.
        assert 21 not in CA_NHAN_FIELD_CODES
        assert 23 not in CA_NHAN_FIELD_CODES

    def test_moi_ma_co_ten(self):
        assert set(CA_NHAN_FIELDS) == CA_NHAN_FIELD_CODES


class TestCongLinhVuc:
    @pytest.mark.parametrize("ten,ma", [
        ("Hộ tịch, quốc tịch, chứng thực", 25),
        ("Nhà ở và công sở", 12),
        ("Bổ trợ tư pháp", 13),
        ("Hình sự - hành chính", 17),
        ("Thi hành án dân sự", 18),
        ("Y tế", 24),
    ])
    def test_linh_vuc_ca_nhan_duoc_nhan(self, ten, ma):
        d = vb(ten)
        assert is_individual_document(d)
        assert la_van_ban_theo_doi(d)
        assert _get_primary_field_code(d) == ma

    @pytest.mark.parametrize("ten", [
        "Quản lý ngân sách",
        "Tổ chức- Biên chế",
        "Xuất bản, in, phát hành",
        "Hàng hải",
    ])
    def test_linh_vuc_ngoai_pham_vi_van_bi_loai(self, ten):
        """Mở cổng không có nghĩa là mở toang.

        Trang công khai KHÔNG lọc văn bản theo lĩnh vực lần nữa, nên thứ lọt qua
        đây là thứ được đăng thẳng cho người dân đọc.
        """
        d = vb(ten)
        assert not is_individual_document(d)
        assert not la_van_ban_theo_doi(d)

    def test_doanh_nghiep_khong_bi_anh_huong(self):
        d = vb("Thuế")
        assert is_business_document(d)
        assert la_van_ban_theo_doi(d)
        assert _get_primary_field_code(d) == 6

    def test_doanh_nghiep_duoc_uu_tien_khi_van_ban_thuoc_ca_hai(self):
        """Văn bản chạm cả hai bên thì mã chính lấy theo hệ doanh nghiệp.

        Không hợp hai tập rồi lấy min: 12 bên cá nhân là "Nhà ở" còn 12 bên
        doanh nghiệp không tồn tại — min trên tập hợp trả số đúng kiểu mà sai
        nghĩa. Mỗi nhánh chỉ lấy min trong hệ mã của chính nó.
        """
        d = vb("Lao động", "Y tế")
        assert _get_primary_field_code(d) == 10
        assert get_field_name(d) == "Lao động - Tiền lương"

    def test_ten_linh_vuc_ca_nhan_khong_roi_ve_khac(self):
        assert get_field_name(vb("Hộ tịch")) == "Hộ tịch - Quốc tịch - Chứng thực"


class TestTienLocTieuDe:
    """Tiền lọc tiêu đề là cổng DUY NHẤT trước khi tốn một lượt gọi API chi tiết:
    API danh sách của Bộ Tư pháp không trả lĩnh vực."""

    @pytest.mark.parametrize("tieu_de", [
        "Luật Hôn nhân và gia đình số 52/2014/QH13",
        "Bộ luật Tố tụng dân sự số 92/2015/QH13",
        "Luật Cư trú số 68/2020/QH14",
        "Luật Khám bệnh, chữa bệnh số 15/2023/QH15",
    ])
    def test_tieu_de_ca_nhan_qua_duoc(self, tieu_de):
        assert tieu_de_dang_theo_doi({"title": tieu_de})

    def test_tieu_de_doanh_nghiep_van_qua_duoc(self):
        d = {"title": "Luật Doanh nghiệp số 59/2020/QH14"}
        assert title_looks_business(d)
        assert tieu_de_dang_theo_doi(d)

    def test_tieu_de_ngoai_pham_vi_bi_chan(self):
        assert not tieu_de_dang_theo_doi(
            {"title": "Nghị quyết về phân bổ dự toán ngân sách trung ương"}
        )


class TestCauDaoTrinhDuyetChet:
    """Trình duyệt chết phải DỪNG lượt chạy, không đánh hỏng phần còn lại.

    Ngày 28/08/2026 trình duyệt đóng giữa lượt cào biểu mẫu. Bộ cào không có
    cầu dao cho tình huống đó nên nó chạy hết danh sách và ghi 3.917 bản ghi
    FAILED trong vài giây, không một lượt nào chạm tới TVPL. Đọc kho sau đó thấy
    "77% bị chặn" và kết luận nhầm là TVPL siết — MỘT sự cố bị nhân lên gần bốn
    nghìn lần, che mất nguyên nhân thật trong nhiều giờ.
    """

    def test_nhan_ra_loi_trinh_duyet_chet(self):
        from scripts.crawl_forms import DAU_HIEU_TRINH_DUYET_CHET

        that = "Page.goto: Target page, context or browser has been closed"
        assert any(d in that for d in DAU_HIEU_TRINH_DUYET_CHET)

    def test_khong_nham_voi_loi_tu_khoi_duoc(self):
        """Timeout và chặn Cloudflare KHÔNG được coi là trình duyệt chết.

        Hai lỗi đó tự khỏi ở lượt sau; dừng cả lượt vì chúng là bỏ phí phiên
        đang dùng được.
        """
        from scripts.crawl_forms import DAU_HIEU_TRINH_DUYET_CHET

        for lanh in ("Page.goto: Timeout 45000ms exceeded",
                     "Cloudflare đang chặn truy cập tự động",
                     'Navigation to "https://x" is interrupted by another navigation'):
            assert not any(d in lanh for d in DAU_HIEU_TRINH_DUYET_CHET), lanh
