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


class TestBieuMau:
    def _mau(self, session, **kw):
        from src.storage.models import LegalForm
        f = LegalForm(form_key="hopdong-1", source="hopdong", external_id="1",
                      title="HỢP ĐỒNG THỬ", public_slug="bm-hopdong-1",
                      is_business=True, crawl_status="OK", nghiep_vu='["hop_dong"]',
                      **kw)
        session.add(f); session.commit()
        return f

    def test_sinh_trang_va_muc_luc(self, master_session, tmp_path):
        self._mau(master_session)
        html_site.xuat_site(master_session, tmp_path, "v-test")
        assert (tmp_path / "bieu-mau" / "bm-hopdong-1.html").is_file()
        assert (tmp_path / "bieu-mau" / "index.html").is_file()

    def test_canh_bao_da_go_chi_hien_khi_that_su_bi_go(self, master_session, tmp_path):
        """Cùng lớp lỗi đã gặp ở du-lieu.json: cờ đã-gỡ bị lẫn với ID Drive nên
        653/653 mẫu đều bị dán nhãn đỏ."""
        self._mau(master_session,
                  gdrive_docx_link="https://drive.google.com/file/d/A/view")
        html_site.xuat_site(master_session, tmp_path, "v-test")
        t = (tmp_path / "bieu-mau" / "bm-hopdong-1.html").read_text(encoding="utf-8")
        assert "Nguồn đã gỡ" not in t

    def test_docx_dung_truoc_pdf(self, master_session, tmp_path):
        """Biểu mẫu sinh ra để ĐIỀN; PDF không điền được."""
        self._mau(master_session, docx_path="/x/a.docx", pdf_path="/x/a.pdf")
        html_site.xuat_site(master_session, tmp_path, "v-test")
        t = (tmp_path / "bieu-mau" / "bm-hopdong-1.html").read_text(encoding="utf-8")
        assert t.index("a.docx") < t.index("a.pdf")

    def test_khong_bao_gio_doc_html_goc_cua_tvpl(self, master_session, tmp_path):
        """body_html_path là HTML gốc TVPL — nguyên liệu nội bộ, không được đăng.

        Kiểm TRUY CẬP THUỘC TÍNH chứ không kiểm chuỗi: bản trước bắt nhầm chính
        dòng chú thích dặn đừng đọc nó.
        """
        import inspect
        import re
        ma = inspect.getsource(html_site.trang_bieu_mau)
        # bỏ chú thích và docstring trước khi soi
        ma = re.sub(r"#.*", "", ma)
        ma = re.sub(r'""".*?"""', "", ma, flags=re.S)
        assert "body_html_path" not in ma

    def test_than_mau_that_su_thanh_html(self, master_session, tmp_path):
        md = tmp_path / "than.md"
        md.write_text("Họ và tên:......\n\n| a | b |\n|---|---|\n| 1 | 2 |",
                      encoding="utf-8")
        self._mau(master_session, body_md_path=str(md))
        html_site.xuat_site(master_session, tmp_path / "out", "v-test")
        t = (tmp_path / "out" / "bieu-mau" / "bm-hopdong-1.html").read_text(encoding="utf-8")
        assert "<table>" in t and "Họ và tên" in t


class TestThuTuGanSlug:
    def test_bieu_mau_kem_theo_hien_ra_du_chay_mot_luot(self, master_session, tmp_path):
        """Lỗi im lặng nhất trong cả bộ: đảo thứ tự thì trang văn bản ghi "chưa
        ghi nhận biểu mẫu nào" — câu hoàn toàn hợp lệ nên không ai phát hiện."""
        import datetime

        from src.storage.models import LegalForm, LegalFormRef

        upsert_document(master_session, {"doc_num": "96/2024/NĐ-CP",
                                         "title": "Nghị định", "moj_id": "5"})
        master_session.commit()
        doc = master_session.query(Document).filter_by(doc_num="96/2024/NĐ-CP").first()
        master_session.add(LegalForm(
            form_key="hopdong-7", source="hopdong", external_id="7",
            title="MẪU KÈM THEO", is_business=True, crawl_status="OK",
            nghiep_vu='["hop_dong"]', updated_on=datetime.date(2024, 1, 1)))
        master_session.add(LegalFormRef(form_key="hopdong-7",
                                        doc_num="96/2024/NĐ-CP",
                                        doc_key=doc.doc_key,
                                        source="truong_can_cu"))
        master_session.commit()

        html_site.xuat_site(master_session, tmp_path, "v-test")
        trang = (tmp_path / "van-ban" / f"{doc.public_slug}.html").read_text(encoding="utf-8")
        assert "MẪU KÈM THEO" in trang
        assert "Chưa ghi nhận biểu mẫu nào" not in trang


class TestGiuUrlCu:
    def test_tro_ly_chuyen_huong_ve_trang_chu(self, master_session, tmp_path):
        """/tro-ly/ đã được chia sẻ khi trợ lý còn ở thư mục con — để nó 404 là
        làm chết link người khác đang giữ."""
        troly = tmp_path / "troly"
        troly.mkdir()
        (troly / "index.html").write_text("<html>app</html>", encoding="utf-8")
        (troly / "du-lieu.json").write_text("{}", encoding="utf-8")

        out = tmp_path / "site"
        html_site.xuat_site(master_session, out, "v-test", tro_ly_dir=troly)

        assert (out / "index.html").read_text(encoding="utf-8") == "<html>app</html>"
        chuyen = (out / "tro-ly" / "index.html").read_text(encoding="utf-8")
        assert 'url=../' in chuyen
        # KHÔNG nhân đôi bộ dữ liệu 1,9 MB
        assert not (out / "tro-ly" / "du-lieu.json").exists()


class TestThuTuXuatTroLy:
    def test_du_lieu_tro_ly_co_bieu_mau_khi_gan_slug_truoc(self, master_session, tmp_path):
        """assistant_export._bieu_mau() chỉ lấy mẫu ĐÃ có public_slug.

        publish_site --html từng gọi xuat_du_lieu() trước gan_slug_bieu_mau(),
        nên du-lieu.json ra 0 biểu mẫu trong khi kho có đủ — trang chủ hiện
        "Biểu mẫu 0". Cùng lớp lỗi thứ tự với mục "Biểu mẫu kèm theo".
        """
        import json as _json

        from src.publish import assistant_export
        from src.storage.models import LegalForm

        master_session.add(LegalForm(
            form_key="hopdong-9", source="hopdong", external_id="9",
            title="MẪU X", is_business=True, crawl_status="OK",
            nghiep_vu='["hop_dong"]'))
        master_session.commit()

        # Sai thứ tự: xuất trước khi gán slug
        assistant_export.xuat_du_lieu(master_session, tmp_path / "truoc")
        goi = _json.loads((tmp_path / "truoc" / "du-lieu.json").read_text(encoding="utf-8"))
        assert goi["bieu_mau"] == [], "chưa gán slug thì phải rỗng"

        # Đúng thứ tự
        html_site.gan_slug_bieu_mau(master_session)
        assistant_export.xuat_du_lieu(master_session, tmp_path / "sau")
        goi = _json.loads((tmp_path / "sau" / "du-lieu.json").read_text(encoding="utf-8"))
        assert [b["k"] for b in goi["bieu_mau"]] == ["hopdong-9"]
