"""Bộ sinh HTML thẳng — thay Quartz.

Lằn ranh quan trọng nhất ở đây là HỢP ĐỒNG URL. Các địa chỉ `/van-ban/*` đã in
trong báo cáo PDF phát cho khách; đổi bố cục file là làm chết link trong những
bản PDF không thu hồi lại được. Nên phần lớn test dưới đây kiểm ĐƯỜNG DẪN chứ
không kiểm giao diện.
"""
from pathlib import Path

import pytest

from src.publish import html_site, site_exporter
from src.storage.models import Document
from src.storage.database import upsert_document


@pytest.fixture()
def kho(master_session):
    for d in [
        {"doc_num": "135/2025/QH15", "title": "Luật Xây dựng",
         "agency_name": "Quốc hội", "moj_id": "1"},
        {"doc_num": "96/2024/NĐ-CP", "title": 'Nghị định "trích dẫn" & ký tự lạ',
         "agency_name": "Chính phủ", "moj_id": "2"},
    ]:
        upsert_document(master_session, d)
    master_session.commit()
    return master_session


def _xuat(session, tmp_path) -> Path:
    html_site.xuat_site(session, tmp_path, "v-test")
    return tmp_path


class TestHopDongURL:
    """Bố cục file phải trùng KHÍT bản Quartz sinh ra."""

    def test_van_ban_la_slug_cham_html(self, kho, tmp_path):
        out = _xuat(kho, tmp_path)
        doc = kho.query(Document).filter(Document.doc_num == "135/2025/QH15").first()
        assert (out / "van-ban" / f"{doc.public_slug}.html").is_file()
        # KHÔNG phải dạng thư mục — Quartz ghi {slug}.html, không phải {slug}/index.html
        assert not (out / "van-ban" / doc.public_slug).is_dir()

    def test_co_trang_thu_muc_van_ban(self, kho, tmp_path):
        assert (_xuat(kho, tmp_path) / "van-ban" / "index.html").is_file()

    def test_co_404_va_tai_nguyen_dung_chung(self, kho, tmp_path):
        out = _xuat(kho, tmp_path)
        assert (out / "404.html").is_file()
        assert (out / "static" / "trang.css").is_file()
        assert (out / "static" / "tim.js").is_file()

    def test_css_khong_nhung_vao_tung_trang(self, kho, tmp_path):
        """4.939 bản sao của cùng một khối CSS là 4.939 lần mất cache."""
        out = _xuat(kho, tmp_path)
        trang = next((out / "van-ban").glob("*.html")).read_text(encoding="utf-8")
        assert "static/trang.css" in trang
        assert "--nen-2:#202020" not in trang


class TestBoLocTrungKhop:
    def test_khong_dang_van_ban_so_hieu_rac(self, master_session, tmp_path):
        """"Không số" là chỗ dồn mọi số hiệu không parse được, không phải văn bản."""
        upsert_document(master_session, {"doc_num": "Không số", "title": "Hiến pháp",
                                         "moj_id": "9"})
        master_session.commit()
        out = _xuat(master_session, tmp_path)
        assert not list((out / "van-ban").glob("khong-so*.html"))

    def test_slug_phan_giai_duoc_thi_trang_phai_ton_tai(self, kho, tmp_path):
        """Đây đúng lỗi F3: bảng tra slug rộng hơn bộ lọc đăng trang, nên link
        phân giải được mà trang không bao giờ được ghi."""
        out = _xuat(kho, tmp_path)
        for slug in site_exporter.build_slug_index(kho).values():
            if slug:
                assert (out / "van-ban" / f"{slug}.html").is_file(), slug


class TestAnToan:
    def test_thoat_html_trong_tieu_de(self, kho, tmp_path):
        """Tiêu đề văn bản có dấu ngoặc kép và & thật — không thoát là chèn HTML."""
        out = _xuat(kho, tmp_path)
        doc = kho.query(Document).filter(Document.doc_num == "96/2024/NĐ-CP").first()
        trang = (out / "van-ban" / f"{doc.public_slug}.html").read_text(encoding="utf-8")
        assert "&amp;" in trang
        assert '"trích dẫn"' not in trang

    def test_moi_trang_deu_co_canh_bao_khong_chinh_thuc(self, kho, tmp_path):
        out = _xuat(kho, tmp_path)
        for f in (out / "van-ban").glob("*.html"):
            assert "Bản sao không chính thức" in f.read_text(encoding="utf-8"), f
