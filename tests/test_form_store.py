"""Ghi biểu mẫu xuống DB và nối căn cứ về kho văn bản.

Chỗ dễ sai nhất ở đây là NỐI CĂN CỨ. Số hiệu văn bản KHÔNG duy nhất toàn quốc —
63 tỉnh đánh số độc lập nên "67/2026/QĐ-UBND" tồn tại ở 18 tỉnh khác nhau. Chọn
bừa một bản là gắn biểu mẫu vào văn bản của tỉnh khác, sai lặng lẽ và không ai
kiểm được. Để trống còn hơn.
"""
import json
from datetime import date

import pytest

from src.forms.store import (
    KetQuaLuu,
    luu_bieu_mau,
    noi_lai_can_cu,
    so_hieu_can_cu_chua_co,
    tim_doc_key,
)
from src.sources.tvpl_forms_parse import (
    REF_TRONG_RUOT_MAU,
    REF_TRUONG_CAN_CU,
    FormDetail,
    FormListItem,
    FormRef,
)
from src.storage.models import Document, LegalForm, LegalFormRef


def them_van_ban(session, doc_num, doc_key, tvpl_id=None, scope="trung_uong"):
    session.add(Document(doc_num=doc_num, doc_key=doc_key, title=f"VB {doc_num}",
                         tvpl_id=tvpl_id, territorial_scope=scope))
    session.commit()


def muc(source="bieumau", eid="47131", **kw):
    return FormListItem(
        source=source, external_id=eid, slug="MAU-X",
        title=kw.get("title", "MẪU GIẤY ĐỀ NGHỊ"),
        url=f"https://thuvienphapluat.vn/{source}/{eid}/MAU-X",
        keywords=kw.get("keywords", ["đăng ký", "doanh nghiệp"]),
        updated_on=kw.get("updated_on", date(2026, 8, 18)),
        field_code=kw.get("field_code", 11),
        form_type_code=kw.get("form_type_code", 3),
    )


def chi_tiet(refs):
    return FormDetail(source="bieumau", external_id="47131", title="MẪU GIẤY ĐỀ NGHỊ",
                      body_html="<p>x</p>", refs=refs)


class TestNoiCanCu:
    def test_uu_tien_id_tvpl_hon_so_hieu(self, master_session):
        """Link căn cứ mang sẵn id TVPL — đường khớp chắc chắn nhất."""
        them_van_ban(master_session, "131/2025/TT-BTC", "tt131::btc", tvpl_id="686963")
        assert tim_doc_key(master_session, "131/2025/TT-BTC", "686963") == "tt131::btc"

    def test_khop_theo_so_hieu_khi_khong_co_id(self, master_session):
        them_van_ban(master_session, "131/2025/TT-BTC", "tt131::btc")
        assert tim_doc_key(master_session, "131/2025/TT-BTC", None) == "tt131::btc"

    def test_trung_so_hieu_nhieu_tinh_thi_de_trong(self, master_session):
        """18 tỉnh cùng có "67/2026/QĐ-UBND". Chọn bừa là gắn nhầm tỉnh."""
        them_van_ban(master_session, "67/2026/QĐ-UBND", "qd67::hanoi", scope="tinh")
        them_van_ban(master_session, "67/2026/QĐ-UBND", "qd67::hue", scope="tinh")
        assert tim_doc_key(master_session, "67/2026/QĐ-UBND", None) is None

    def test_trung_so_hieu_nhung_chi_mot_ban_trung_uong_thi_chot_duoc(
            self, master_session):
        them_van_ban(master_session, "10/2026/NĐ-CP", "nd10::cp", scope="trung_uong")
        them_van_ban(master_session, "10/2026/NĐ-CP", "nd10::tinh", scope="tinh")
        assert tim_doc_key(master_session, "10/2026/NĐ-CP", None) == "nd10::cp"

    def test_chua_co_trong_kho_thi_tra_none_chu_khong_vo(self, master_session):
        """Đo trên mẫu thử thật: 2/2 căn cứ đều chưa có trong kho 4.467 văn bản.

        Nếu đây là lỗi thì kho biểu mẫu gần như rỗng ngay từ đầu.
        """
        assert tim_doc_key(master_session, "187/2026/NĐ-CP", "999999") is None

    def test_nhan_thuan_chu_khong_di_khop(self, master_session):
        assert tim_doc_key(master_session, "Bộ luật Dân sự", None) is None


class TestLuuBieuMau:
    def test_them_moi_dien_du_ten_theo_ma(self, master_session):
        kq = KetQuaLuu()
        f = luu_bieu_mau(master_session, muc(), body_hash="h1", ket_qua=kq)
        master_session.commit()
        assert kq.them_moi == 1
        assert f.field_name == "Doanh nghiệp"
        assert f.form_type_name == "Mẫu văn bản"
        assert json.loads(f.keywords) == ["đăng ký", "doanh nghiệp"]

    def test_anh_xa_sang_ma_van_ban_kem_muc_tin_cay(self, master_session):
        """"Doanh nghiệp" là mã 11 ở biểu mẫu, mã 1 ở văn bản — phải đổi, không giữ."""
        f = luu_bieu_mau(master_session, muc(field_code=11), body_hash="h1")
        master_session.commit()
        assert f.tvpl_field_code == 1
        assert f.tvpl_field_source == "chac"

    def test_khoa_gom_ca_ten_kho_nen_hai_kho_khong_de_len_nhau(self, master_session):
        luu_bieu_mau(master_session, muc("bieumau", "46696"), body_hash="h1")
        luu_bieu_mau(master_session, muc("hopdong", "46696", field_code=None),
                     body_hash="h2")
        master_session.commit()
        assert master_session.query(LegalForm).count() == 2

    def test_noi_dung_khong_doi_thi_giu_nguyen_ket_qua_pheu(self, master_session):
        """Phân loại lại tốn một lượt gọi mô hình cho mỗi mẫu.

        Nội dung không đổi thì kết luận cũng không đổi — đó là toàn bộ cơ chế
        cache của tầng 3.
        """
        f = luu_bieu_mau(master_session, muc(), body_hash="h1")
        f.audience, f.is_business = "doanh_nghiep", True
        master_session.commit()

        kq = KetQuaLuu()
        luu_bieu_mau(master_session, muc(), body_hash="h1", ket_qua=kq)
        master_session.commit()
        assert kq.khong_doi == 1
        assert master_session.query(LegalForm).one().audience == "doanh_nghiep"

    def test_noi_dung_doi_thi_xoa_nhan_cu(self, master_session):
        """Nhãn cũ không còn bảo chứng gì khi ruột mẫu đã khác.

        Giữ lại là để một kết luận lỗi thời nằm đó mà trông vẫn đúng.
        """
        f = luu_bieu_mau(master_session, muc(), body_hash="h1")
        f.audience, f.is_business, f.published_hash = "doanh_nghiep", True, "p1"
        master_session.commit()

        kq = KetQuaLuu()
        luu_bieu_mau(master_session, muc(), body_hash="h2-KHAC", ket_qua=kq)
        master_session.commit()
        f = master_session.query(LegalForm).one()
        assert kq.cap_nhat == 1
        assert f.audience is None and f.is_business is None
        assert f.published_hash is None      # phải đăng lại trang công khai

    def test_ghi_lai_trang_thai_hong_thay_vi_bo_qua(self, master_session):
        luu_bieu_mau(master_session, muc(), crawl_status="EMPTY_BODY",
                     crawl_error="ruột rỗng")
        master_session.commit()
        f = master_session.query(LegalForm).one()
        assert f.crawl_status == "EMPTY_BODY" and f.crawl_error


class TestCanCuCuaBieuMau:
    def test_ghi_lai_ca_can_cu_chua_noi_duoc(self, master_session):
        kq = KetQuaLuu()
        luu_bieu_mau(master_session, muc(),
                     chi_tiet([FormRef("187/2026/NĐ-CP", tvpl_doc_id="1"),
                               FormRef("91/2015/QH13", source=REF_TRONG_RUOT_MAU)]),
                     body_hash="h1", ket_qua=kq)
        master_session.commit()
        assert master_session.query(LegalFormRef).count() == 2
        assert kq.can_cu_chua_co_trong_kho == 2

    def test_ghi_lai_thay_vi_va_tung_dong(self, master_session):
        """TVPL có sửa căn cứ; vá từng dòng để lại căn cứ đã gỡ nằm vĩnh viễn."""
        luu_bieu_mau(master_session, muc(), chi_tiet([FormRef("1/2020/NĐ-CP")]),
                     body_hash="h1")
        master_session.commit()
        luu_bieu_mau(master_session, muc(), chi_tiet([FormRef("2/2021/NĐ-CP")]),
                     body_hash="h2")
        master_session.commit()
        assert [r.doc_num for r in master_session.query(LegalFormRef)] == ["2/2021/NĐ-CP"]

    def test_liet_ke_so_hieu_con_thieu_cho_bo_cao_van_ban(self, master_session):
        luu_bieu_mau(master_session, muc(),
                     chi_tiet([FormRef("187/2026/NĐ-CP"), FormRef("Bộ luật Dân sự")]),
                     body_hash="h1")
        master_session.commit()
        # "Bộ luật Dân sự" không phải số hiệu nên không vào danh sách việc
        assert so_hieu_can_cu_chua_co(master_session) == ["187/2026/NĐ-CP"]

    def test_noi_lai_sau_khi_kho_van_ban_lon_them(self, master_session):
        """Biểu mẫu cào tháng trước phải nối được hôm nay, không phải cào lại."""
        luu_bieu_mau(master_session, muc(), chi_tiet([FormRef("187/2026/NĐ-CP")]),
                     body_hash="h1")
        master_session.commit()
        assert master_session.query(LegalFormRef).one().doc_key is None

        them_van_ban(master_session, "187/2026/NĐ-CP", "nd187::cp")
        assert noi_lai_can_cu(master_session) == 1
        assert master_session.query(LegalFormRef).one().doc_key == "nd187::cp"


@pytest.mark.parametrize("nguon", [REF_TRUONG_CAN_CU, REF_TRONG_RUOT_MAU])
def test_giu_nguon_can_cu_de_biet_do_chac_chan(master_session, nguon):
    """Căn cứ bóc từ lời văn kém chắc hơn căn cứ lấy từ trường riêng của trang."""
    luu_bieu_mau(master_session, muc(), chi_tiet([FormRef("1/2020/NĐ-CP", source=nguon)]),
                 body_hash="h1")
    master_session.commit()
    assert master_session.query(LegalFormRef).one().source == nguon


class TestCongDangCongKhai:
    """MỘT hàm cho mọi bên tiêu thụ trang công khai.

    Trước đây điều kiện `is_business == 1` nằm rải ở sáu chỗ — trang công khai,
    bộ dữ liệu trợ lý, chỉ mục tìm kiếm, lệnh Telegram. Mở sang cá nhân nghĩa là
    sửa đúng sáu chỗ, và sót một chỗ thì mẫu cá nhân có trong kho, có trang, mà
    tìm không ra: không có gì hỏng, không có gì báo.
    """

    def _mau(self, session, key, **kw):
        from src.storage.models import LegalForm

        f = LegalForm(form_key=key, source="hopdong", external_id=key.split("-")[-1],
                      title=f"MẪU {key}", crawl_status="OK", **kw)
        session.add(f)
        session.commit()
        return f

    def test_lay_ca_hai_ben_va_bo_mau_khong_phuc_vu_ai(self, master_session):
        from src.forms.store import loc_dang_cong_khai
        from src.storage.models import LegalForm

        self._mau(master_session, "hopdong-1", is_business=True, is_individual=False)
        self._mau(master_session, "hopdong-2", is_business=False, is_individual=True)
        self._mau(master_session, "hopdong-3", is_business=True, is_individual=True)
        self._mau(master_session, "hopdong-4", is_business=False, is_individual=False)
        self._mau(master_session, "hopdong-5")          # cả hai còn None

        keys = sorted(f.form_key for f in
                      loc_dang_cong_khai(master_session.query(LegalForm)).all())
        assert keys == ["hopdong-1", "hopdong-2", "hopdong-3"]

    def test_mau_phuc_vu_ca_hai_chi_xuat_hien_MOT_lan(self, master_session):
        """Hợp `OR` chứ không phải nối hai truy vấn — nối thì mẫu cả-hai ra hai
        dòng, và trang công khai sinh hai trang cho cùng một biểu mẫu."""
        from src.forms.store import loc_dang_cong_khai
        from src.storage.models import LegalForm

        self._mau(master_session, "hopdong-9", is_business=True, is_individual=True)
        assert loc_dang_cong_khai(master_session.query(LegalForm)).count() == 1
