"""Nhóm — lĩnh vực theo danh mục Thư viện Pháp luật.

Cây thư mục Drive từng lấy tầng 1 từ `field_name` của Bộ Tư pháp. Trường đó là
văn bản tự do: 4.466 văn bản rơi vào 203 giá trị, trong đó 75 giá trị chỉ có
ĐÚNG MỘT văn bản — 203 nhánh gốc, phần lớn chứa một file, và số nhánh còn tăng
theo mỗi văn bản mới. Danh mục TVPL là tập đóng 27 nhóm nên cây có biên.
"""
import pytest

from src.legal.field_mapper import (
    NGUON_KHAC, NGUON_MOJ, NGUON_TU_KHOA, NGUON_TVPL, phan_loai,
)
from src.legal.tvpl_fields import MA_KHAC, TVPL_FIELDS, TEN_THEO_MA, thu_muc


class TestDanhMuc:
    def test_du_27_linh_vuc_ma_lien_mach(self):
        assert len(TVPL_FIELDS) == 27
        assert sorted(lv["ma"] for lv in TVPL_FIELDS) == list(range(1, 28))

    def test_khong_trung_ten(self):
        ten = [lv["ten"] for lv in TVPL_FIELDS]
        assert len(set(ten)) == len(ten)

    def test_thu_muc_co_ma_de_sap_xep_on_dinh(self):
        """Drive sắp theo bảng chữ cái. Không có mã thì thứ tự đổi mỗi khi TVPL
        đổi tên một nhóm, và không khớp thứ tự trên chính trang TVPL.
        """
        assert thu_muc(6) == "06. Thuế - Phí - Lệ Phí"
        assert thu_muc(27) == "27. Lĩnh vực khác"

    @pytest.mark.parametrize("ma", [None, 0, 99, -1])
    def test_ma_la_roi_ve_linh_vuc_khac(self, ma):
        assert thu_muc(ma) == thu_muc(MA_KHAC)


class TestBaTangPhanLoai:
    def test_ma_tvpl_thang_moi_thu(self):
        """TVPL đã gán thì đó là dữ kiện, không suy diễn thêm."""
        kq = phan_loai(1, "Đất đai", "Luật Xây dựng")
        assert (kq.ma, kq.nguon) == (1, NGUON_TVPL)

    def test_ten_bo_tu_phap_duoc_anh_xa(self):
        kq = phan_loai(None, "Đất đai", None)
        assert (kq.ma, kq.nguon) == (23, NGUON_MOJ)

    def test_ten_ghep_hai_linh_vuc_van_xep_duoc(self):
        """Bộ Tư pháp ghép hai lĩnh vực bằng dấu chấm phẩy."""
        kq = phan_loai(None, "Quản lý ngân sách; Quản lý tài sản công", None)
        assert kq.ma == 19

    def test_khong_co_ten_thi_suy_tu_tieu_de(self):
        kq = phan_loai(None, "Chưa phân loại", "Luật Sở hữu trí tuệ")
        assert (kq.ma, kq.nguon) == (14, NGUON_TU_KHOA)

    def test_khong_suy_duoc_thi_noi_khong_biet(self):
        kq = phan_loai(None, "Chưa phân loại", "Quyết định về việc ban hành")
        assert (kq.ma, kq.nguon) == (MA_KHAC, NGUON_KHAC)


class TestTuDongAmSauKhiBoDau:
    """Bỏ dấu tiếng Việt tạo ra từ đồng âm; token ngắn thì sai hàng loạt.

    Ba ca đo được trên kho thật, tổng hơn 100 văn bản bị xếp sai.
    """

    def test_thuoc_khong_con_keo_ve_y_te(self):
        """"thuộc" (thuộc thẩm quyền) từng khớp từ khoá "thuốc": 68/68 sai."""
        kq = phan_loai(None, None,
                       "Quy định tổ chức các cơ quan chuyên môn thuộc Ủy ban nhân dân")
        assert kq.ma != 24, "lại khớp nhầm 'thuộc' thành 'thuốc'"

    def test_luat_sua_doi_khong_thanh_dich_vu_phap_ly(self):
        """"luật sửa đổi" từng khớp "luật sư": mọi luật sửa đổi bị xếp nhầm."""
        kq = phan_loai(None, None, "Luật sửa đổi, bổ sung một số điều của Luật Đất đai")
        assert kq.ma != 13

    def test_van_bat_dung_luat_su_that(self):
        kq = phan_loai(None, None, "Nghị định quy định về tổ chức hành nghề luật sư")
        assert kq.ma == 13

    def test_xay_dung_chuong_trinh_khong_thanh_nganh_xay_dung(self):
        kq = phan_loai(None, None,
                       "Quy chế xây dựng, quản lý và thực hiện Chương trình xúc tiến")
        assert kq.ma != 20

    def test_van_bat_dung_luat_xay_dung(self):
        assert phan_loai(None, None, "Luật Xây dựng số 135/2025/QH15").ma == 20


class TestThuMucDrive:
    def test_uu_tien_cot_da_tinh_san(self):
        from src.storage.gdrive import linh_vuc_thu_muc

        assert linh_vuc_thu_muc({"tvpl_field_code": 6}) == "06. Thuế - Phí - Lệ Phí"

    def test_chua_co_cot_thi_tu_suy(self):
        from src.storage.gdrive import linh_vuc_thu_muc

        assert linh_vuc_thu_muc({"field_name": "Đất đai"}) \
            == "23. Tài nguyên - Môi trường"

    def test_rong_hoan_toan_van_ra_ten_hop_le(self):
        from src.storage.gdrive import linh_vuc_thu_muc

        assert linh_vuc_thu_muc({}) == "27. Lĩnh vực khác"

    def test_khong_con_dung_field_name_lam_tang_mot(self):
        """Chặn việc quay lại dùng trường tự do của Bộ Tư pháp."""
        import inspect

        from src.storage import gdrive

        src = inspect.getsource(gdrive.ensure_folder_path)
        assert 'doc_data.get("field_name")' not in src
