"""Lệnh /bieumau trên Telegram và chỉ mục tìm kiếm biểu mẫu.

Cùng lối với tests/test_report_commands.py: gọi thẳng lớp lõi, không dựng bot,
không đụng mạng. Lớp lõi trả về `KetQua(van_ban, file_dinh_kem, file_bo_sung)` —
đúng hợp đồng mà `_tra_loi()` của telegram_bot_server tiêu thụ.
"""
import json
from datetime import date

import pytest

from src.forms import search
from src.legal.form_taxonomy import NGHIEP_VU
from src.notification import form_commands
from src.storage.models import LegalForm, LegalFormRef


@pytest.fixture
def rag_tam(tmp_path, monkeypatch):
    """Chỉ mục FTS trên file tạm, không đụng data/rag.db thật."""
    p = tmp_path / "rag_forms.db"
    monkeypatch.setattr(search, "RAG_DB_PATH", p)
    return p


@pytest.fixture
def kho(master_session, rag_tam, tmp_path):
    """Vài biểu mẫu doanh nghiệp, đã lập chỉ mục."""
    def _them(form_key, title, nghiep_vu, is_business=True, source="hopdong",
              keywords=None, co_file=True):
        f = LegalForm(
            form_key=form_key, source=source,
            external_id=form_key.split("-")[-1],
            title=title, url=f"https://thuvienphapluat.vn/{source}/x",
            keywords=json.dumps(keywords or [], ensure_ascii=False),
            nghiep_vu=json.dumps(nghiep_vu, ensure_ascii=False),
            is_business=is_business, crawl_status="OK",
            updated_on=date(2026, 8, 18), form_type_code=6,
        )
        if co_file:
            docx = tmp_path / f"{form_key}.docx"
            pdf = tmp_path / f"{form_key}.pdf"
            docx.write_bytes(b"docx")
            pdf.write_bytes(b"pdf")
            f.docx_path, f.pdf_path = str(docx), str(pdf)
        master_session.add(f)
        return f

    _them("hopdong-1", "HỢP ĐỒNG LAO ĐỘNG KHÔNG XÁC ĐỊNH THỜI HẠN",
          ["lao_dong_bhxh", "hop_dong"], keywords=["lao động", "hợp đồng"])
    _them("hopdong-2", "HỢP ĐỒNG KHOÁN VIỆC", ["hop_dong"])
    _them("bieumau-3", "MẪU TỜ KHAI THUẾ GIÁ TRỊ GIA TĂNG", ["thue_hoa_don"],
          source="bieumau", keywords=["thuế", "hóa đơn"])
    _them("bieumau-9", "MẪU BÁO CÁO NGÂN SÁCH CỦA KHO BẠC NHÀ NƯỚC", [],
          is_business=False, source="bieumau")
    master_session.commit()
    search.dung_lai_chi_muc(master_session, db_path=rag_tam)
    return master_session


class TestHuongDan:
    def test_liet_ke_nhom_co_mau_kem_so_luong(self, kho):
        kq = form_commands.xu_ly(kho, [])
        assert "lao_dong_bhxh" in kq.van_ban
        assert "hop_dong" in kq.van_ban
        assert "thue_hoa_don" in kq.van_ban

    def test_khong_liet_ke_nhom_rong(self, kho):
        """Menu 12 nhóm mà 9 nhóm trống chỉ làm người dùng bấm vào ngõ cụt."""
        kq = form_commands.xu_ly(kho, [])
        assert "xnk_hai_quan" not in kq.van_ban

    def test_kho_rong_thi_chi_duong_chu_khong_bao_loi(self, master_session, rag_tam):
        kq = form_commands.xu_ly(master_session, [])
        assert "trống" in kq.van_ban
        assert "crawl_forms" in kq.van_ban


class TestTim:
    def test_tim_theo_tu_khoa(self, kho):
        kq = form_commands.xu_ly(kho, ["hợp", "đồng", "lao", "động"])
        assert "hopdong-1" in kq.van_ban

    def test_tim_khong_dau_van_ra(self, kho):
        """Người dùng gõ Telegram trên điện thoại thường bỏ dấu.

        `remove_diacritics 2` của FTS5 lo phần này; LIKE thì không khớp gì cả.
        """
        kq = form_commands.xu_ly(kho, ["hop", "dong", "lao", "dong"])
        assert "hopdong-1" in kq.van_ban

    def test_khong_tra_mau_ngoai_nhom_doanh_nghiep(self, kho):
        """Mẫu Kho bạc có trong DB nhưng KHÔNG được vào chỉ mục tra cứu.

        Nạp nó vào đây là phá đúng thứ phễu ba tầng vừa lọc ra.
        """
        kq = form_commands.xu_ly(kho, ["ngân", "sách", "kho", "bạc"])
        assert "bieumau-9" not in kq.van_ban

    def test_khong_thay_thi_chi_duong(self, kho):
        kq = form_commands.xu_ly(kho, ["không", "có", "gì", "khớp", "đâu"])
        assert "Không thấy" in kq.van_ban
        assert "/bieumau" in kq.van_ban

    def test_ky_tu_dac_biet_khong_lam_vo_fts(self, kho):
        """Câu "Xây dựng & Bất động sản" từng ném lỗi cú pháp FTS5.

        Dùng lại build_fts_query() nên mọi token đều là dữ liệu, không toán tử.
        """
        kq = form_commands.xu_ly(kho, ["hợp", "đồng", "&", "lao", "động"])
        assert "hopdong-1" in kq.van_ban


class TestLietKeNhom:
    def test_liet_ke_dung_nhom(self, kho):
        kq = form_commands.xu_ly(kho, ["nhom", "hop_dong"])
        assert "hopdong-1" in kq.van_ban and "hopdong-2" in kq.van_ban
        assert "bieumau-3" not in kq.van_ban

    def test_ma_nhom_la_thi_liet_ke_ma_hop_le(self, kho):
        kq = form_commands.xu_ly(kho, ["nhom", "bịa_ra"])
        assert "Không có nhóm" in kq.van_ban
        for ma in NGHIEP_VU:
            assert ma in kq.van_ban

    def test_nhom_rong_khong_bao_loi(self, kho):
        kq = form_commands.xu_ly(kho, ["nhom", "shtt"])
        assert "chưa có biểu mẫu" in kq.van_ban


class TestGuiFile:
    def test_docx_dung_truoc_pdf(self, kho):
        """Biểu mẫu là để ĐIỀN. Gửi PDF trước là gửi bản không điền được trước."""
        kq = form_commands.xu_ly(kho, ["hopdong-1"])
        assert kq.file_dinh_kem.endswith(".docx")
        assert kq.file_bo_sung[0].endswith(".pdf")

    def test_hien_can_cu_va_nguon(self, kho):
        kho.add(LegalFormRef(form_key="hopdong-1", doc_num="45/2019/QH14",
                             source="trong_ruot_mau"))
        kho.commit()
        kq = form_commands.xu_ly(kho, ["hopdong-1"])
        assert "45/2019/QH14" in kq.van_ban
        assert "thuvienphapluat.vn" in kq.van_ban

    def test_ma_khong_ton_tai(self, kho):
        kq = form_commands.xu_ly(kho, ["hopdong-99999"])
        assert "Không có biểu mẫu" in kq.van_ban
        assert kq.file_dinh_kem is None

    def test_canh_bao_khi_mau_khong_thuoc_nhom_doanh_nghiep(self, kho):
        """Tra được bằng mã, nhưng phải biết mình đang cầm mẫu không dành cho mình."""
        kq = form_commands.xu_ly(kho, ["bieumau-9"])
        assert "không thuộc nhóm doanh nghiệp" in kq.van_ban

    def test_chua_dung_file_thi_noi_ro_cach_sua(self, master_session, rag_tam):
        master_session.add(LegalForm(
            form_key="hopdong-7", source="hopdong", external_id="7",
            title="HỢP ĐỒNG X", is_business=True, crawl_status="OK",
            url="https://x/",
        ))
        master_session.commit()
        kq = form_commands.xu_ly(master_session, ["hopdong-7"])
        assert kq.file_dinh_kem is None
        assert "build_forms" in kq.van_ban


class TestDinhTuyen:
    def test_ma_bieu_mau_nhan_ra_bang_tien_to_kho(self, kho):
        """"hợp đồng thuê - mượn" cũng có gạch nối, nhưng là câu tìm kiếm."""
        kq = form_commands.xu_ly(kho, ["hợp", "đồng", "thuê", "-", "mượn"])
        assert "biểu mẫu khớp" in kq.van_ban or "Không thấy" in kq.van_ban
        assert kq.file_dinh_kem is None

    def test_khoang_trang_thua_khong_lam_vo(self, kho):
        assert form_commands.xu_ly(kho, ["  ", ""]).van_ban == \
            form_commands.xu_ly(kho, []).van_ban


class TestChiMuc:
    def test_dung_lai_chi_muc_chi_nap_mau_doanh_nghiep(self, kho, rag_tam):
        assert search.dung_lai_chi_muc(kho, db_path=rag_tam) == 3

    def test_dem_theo_nghiep_vu_dem_ca_hai_nhom(self, kho):
        """Một mẫu hai nhóm được đếm ở CẢ HAI — đây là số để bấm, không để cộng."""
        dem = search.dem_theo_nghiep_vu(kho)
        assert dem["hop_dong"] == 2
        assert dem["lao_dong_bhxh"] == 1

    def test_cau_rong_tra_ve_rong_chu_khong_tra_tat_ca(self, rag_tam):
        assert search.tim("!!!", db_path=rag_tam) == []
