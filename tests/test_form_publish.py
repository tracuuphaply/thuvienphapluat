"""Trang tra cứu công khai cho biểu mẫu.

CHỐT QUAN TRỌNG NHẤT Ở ĐÂY LÀ RANH GIỚI BẢN QUYỀN. Trang biểu mẫu có đăng NỘI
DUNG — khác trang văn bản vốn chỉ đăng dữ kiện — nên phải chứng minh được thứ
được đăng là bản DỰNG LẠI của mình, không phải bản HTML của Thư viện Pháp luật,
và mọi trang đều mang khối ghi nguồn kèm link ngược.
"""
import json
from datetime import date
from pathlib import Path

import pytest

from src.publish import form_exporter, site_exporter
from src.storage.models import Document, LegalForm, LegalFormRef


@pytest.fixture
def form_da_dung(master_session, tmp_path):
    """Một biểu mẫu đã cào, đã phân loại, đã dựng file."""
    md = tmp_path / "hopdong-46696.md"
    md.write_text(
        "# HỢP ĐỒNG KHOÁN VIỆC\n\n"
        "**Nguồn:** Thư viện Pháp luật — https://thuvienphapluat.vn/hopdong/46696/x\n\n"
        "> Bản dựng lại từ nội dung biểu mẫu để tiện điền và in.\n\n"
        "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n\nBÊN A (Bên giao khoán)\n",
        encoding="utf-8",
    )
    docx = tmp_path / "hopdong-46696.docx"
    pdf = tmp_path / "hopdong-46696.pdf"
    docx.write_bytes(b"docx")
    pdf.write_bytes(b"pdf")

    f = LegalForm(
        form_key="hopdong-46696", source="hopdong", external_id="46696",
        title="HỢP ĐỒNG KHOÁN VIỆC",
        url="https://thuvienphapluat.vn/hopdong/46696/HOP-DONG-KHOAN-VIEC",
        nghiep_vu=json.dumps(["hop_dong", "lao_dong_bhxh"]),
        is_business=True, audience="doanh_nghiep", crawl_status="OK",
        form_type_code=6, updated_on=date(2026, 8, 8),
        body_html_path=str(tmp_path / "goc.html"),
        body_md_path=str(md), docx_path=str(docx), pdf_path=str(pdf),
    )
    master_session.add(f)
    master_session.add(LegalFormRef(form_key="hopdong-46696",
                                    doc_num="91/2015/QH13",
                                    source="trong_ruot_mau"))
    master_session.commit()
    return f


class TestSlug:
    def test_slug_suy_tu_ma_khong_suy_tu_tieu_de(self, form_da_dung):
        """URL đã phát ra trong tin nhắn Telegram không được đổi.

        TVPL sửa chữ trong tiêu đề thường xuyên; suy slug từ tiêu đề là mỗi lần
        họ sửa một chữ thì link cũ thành 404.
        """
        slug = form_exporter.public_slug_bieu_mau(form_da_dung)
        form_da_dung.title = "HỢP ĐỒNG KHOÁN VIỆC (sửa tên)"
        assert form_exporter.public_slug_bieu_mau(form_da_dung) == slug

    def test_slug_gom_ca_ten_kho(self, master_session):
        a = LegalForm(form_key="bieumau-46696", source="bieumau",
                      external_id="46696", title="A")
        b = LegalForm(form_key="hopdong-46696", source="hopdong",
                      external_id="46696", title="B")
        assert (form_exporter.public_slug_bieu_mau(a)
                != form_exporter.public_slug_bieu_mau(b))

    def test_slug_chu_thuong_khong_dau(self):
        f = LegalForm(form_key="hopdong-1", source="hopdong", external_id="1",
                      title="X")
        slug = form_exporter.public_slug_bieu_mau(f)
        assert slug == slug.lower()
        assert slug.isascii()


class TestTrangBieuMau:
    def test_khong_dang_html_goc_cua_tvpl(self, master_session, form_da_dung):
        """Ruột mẫu lấy từ bản Markdown ĐÃ DỰNG LẠI, không từ body_html_path.

        Đọc từ HTML gốc là đăng lại nguyên công chuyển đổi của TVPL — đúng thứ
        mà cả thiết kế này tránh.
        """
        Path(form_da_dung.body_html_path).write_text(
            "<div>DAU_VET_HTML_GOC_TVPL</div>", encoding="utf-8")
        page = form_exporter.render_form_page(master_session, form_da_dung, {})
        assert "DAU_VET_HTML_GOC_TVPL" not in page
        assert "BÊN A (Bên giao khoán)" in page

    def test_luon_co_khoi_ghi_nguon_va_link_nguoc(self, master_session, form_da_dung):
        page = form_exporter.render_form_page(master_session, form_da_dung, {})
        assert "Bản dựng lại" in page
        assert "văn bản gốc" in page
        assert form_da_dung.url in page

    def test_ban_kho_giu_dung_truoc_trang_TVPL(self, master_session, form_da_dung):
        """Trang gốc vẫn ghi — ghi nguồn là việc phải làm — nhưng nó KHÔNG còn là
        đường duy nhất lấy biểu mẫu. Trỏ người đọc về Thư viện Pháp luật là đẩy
        họ ra khỏi kho của mình, tới một trang có tường Cloudflare và có thể gỡ
        mẫu bất cứ lúc nào."""
        form_da_dung.gdrive_docx_link = "https://drive.google.com/file/d/1AbC_dEf-2345/view"
        master_session.commit()
        page = form_exporter.render_form_page(master_session, form_da_dung, {})
        assert page.index(form_da_dung.gdrive_docx_link) < page.index(form_da_dung.url)

    def test_ban_word_lay_tu_drive_khi_da_tai_len(self, master_session, form_da_dung):
        """Bản Word là bản ĐIỀN ĐƯỢC. Drive xem trước và tải về được ngay trên
        trình duyệt, còn file trong repo thì tuỳ trình duyệt mà mở hay tải."""
        form_da_dung.gdrive_docx_link = "https://drive.google.com/file/d/1AbC_dEf-2345/view"
        master_session.commit()
        khoi = form_exporter._khoi_tai_ve(form_da_dung)
        assert "drive.google.com/file/d/1AbC_dEf-2345" in khoi
        assert khoi.index("drive.google.com") < khoi.index("hopdong-46696.docx")
        assert "hopdong-46696.pdf" in khoi          # PDF vẫn lấy từ repo

    def test_ban_repo_van_co_link_khi_da_co_drive(self, master_session, form_da_dung):
        """Bản .docx trong repo là dự phòng cho link Drive — nhưng chỉ dự phòng
        được khi TỚI ĐƯỢC. Có lúc trang thôi trỏ tới nó mà bộ chép vẫn chép: 653
        file .docx (26,8 MB) nằm trong repo công khai không ai tới được, tính vào
        dung lượng clone mà không cứu được ai lúc link Drive hỏng."""
        form_da_dung.gdrive_docx_link = "https://drive.google.com/file/d/1AbC_dEf-2345/view"
        master_session.commit()
        khoi = form_exporter._khoi_tai_ve(form_da_dung)
        assert "(./hopdong-46696.docx)" in khoi
        assert "kho trang" in khoi

    def test_chua_tai_len_drive_thi_van_dung_ban_trong_repo(self, master_session, form_da_dung):
        khoi = form_exporter._khoi_tai_ve(form_da_dung)
        assert "hopdong-46696.docx" in khoi

    def test_docx_dung_truoc_pdf_trong_khoi_tai_ve(self, master_session, form_da_dung):
        page = form_exporter.render_form_page(master_session, form_da_dung, {})
        vt_docx = page.index("hopdong-46696.docx")
        vt_pdf = page.index("hopdong-46696.pdf")
        assert vt_docx < vt_pdf
        assert "điền được" in page

    def test_can_cu_da_co_trong_kho_thanh_wikilink(self, master_session,
                                                   form_da_dung):
        page = form_exporter.render_form_page(
            master_session, form_da_dung, {"91/2015/QH13": "91-2015-qh13"})
        assert "[[91-2015-qh13|91/2015/QH13]]" in page

    def test_can_cu_chua_co_van_hien_ra_kem_ghi_chu(self, master_session,
                                                    form_da_dung):
        """Người đọc cần biết biểu mẫu dựa trên văn bản nào, kể cả khi kho chưa có."""
        page = form_exporter.render_form_page(master_session, form_da_dung, {})
        assert "91/2015/QH13" in page
        assert "chưa có trong kho" in page

    def test_gan_nhan_nghiep_vu_vao_tags(self, master_session, form_da_dung):
        page = form_exporter.render_form_page(master_session, form_da_dung, {})
        assert "nv-hop-dong" in page
        assert "nv-lao-dong-bhxh" in page


class TestXuatCaKho:
    def test_chi_dang_mau_doanh_nghiep(self, master_session, form_da_dung,
                                       tmp_path):
        master_session.add(LegalForm(
            form_key="bieumau-47156", source="bieumau", external_id="47156",
            title="MẪU BÁO CÁO NGÂN SÁCH CỦA KHO BẠC NHÀ NƯỚC",
            is_business=False, crawl_status="OK",
            body_md_path=str(tmp_path / "x.md"),
        ))
        master_session.commit()
        out = tmp_path / "content"
        form_exporter.export_forms(master_session, out)
        tap = {p.stem for p in (out / "bieu-mau").glob("*.md")}
        assert any("46696" in t for t in tap)
        assert not any("47156" in t for t in tap)

    def test_khong_ghi_trang_rong_khi_chua_dung_file(self, master_session,
                                                    tmp_path):
        """Trang trống dưới URL trông như chính thức còn tệ hơn không có trang."""
        master_session.add(LegalForm(
            form_key="hopdong-7", source="hopdong", external_id="7",
            title="HỢP ĐỒNG X", is_business=True, crawl_status="OK",
        ))
        master_session.commit()
        out = tmp_path / "content"
        stats = form_exporter.export_forms(master_session, out)
        assert stats.skipped_no_content == 1
        assert stats.written == 0

    def test_khong_ghi_lai_khi_noi_dung_khong_doi(self, master_session,
                                                 form_da_dung, tmp_path):
        out = tmp_path / "content"
        assert form_exporter.export_forms(master_session, out).written == 1
        master_session.commit()
        lan_hai = form_exporter.export_forms(master_session, out)
        assert lan_hai.written == 0 and lan_hai.unchanged == 1

    def test_sinh_trang_muc_luc_theo_nghiep_vu(self, master_session,
                                               form_da_dung, tmp_path):
        out = tmp_path / "content"
        form_exporter.export_forms(master_session, out)
        muc_luc = (out / "bieu-mau" / "index.md").read_text(encoding="utf-8")
        assert "Hợp đồng và giao dịch" in muc_luc
        assert "Lao động, tiền lương, bảo hiểm xã hội" in muc_luc

    def test_chep_file_tai_ve_sang_thu_muc_trang(self, master_session,
                                                 form_da_dung, tmp_path):
        """Trang công khai đẩy sang repo KHÁC — link tượng trưng không đi qua git."""
        out = tmp_path / "content"
        assert form_exporter.sao_chep_file_tai_ve(master_session, out) == 2
        assert (out / "bieu-mau" / "hopdong-46696.docx").exists()

    def test_moi_file_chep_sang_deu_co_duong_toi_tu_trang(self, master_session,
                                                          form_da_dung, tmp_path):
        """Chép file sang repo công khai và trỏ link tới nó là hai hàm KHÁC nhau.

        Sửa một bên mà quên bên kia thì file thành mồ côi trong im lặng — không
        có gì hỏng, không có gì báo, chỉ có dung lượng repo phình ra vì những
        file không trang nào tới được. Chốt ở đây để lần sau kêu lên.
        """
        form_da_dung.gdrive_docx_link = "https://drive.google.com/file/d/1AbC_dEf-2345/view"
        master_session.commit()
        out = tmp_path / "content"
        form_exporter.export_forms(master_session, out)
        form_exporter.sao_chep_file_tai_ve(master_session, out)

        forms_dir = out / "bieu-mau"
        trang = "\n".join(p.read_text(encoding="utf-8")
                          for p in forms_dir.glob("*.md"))
        mo_coi = [f.name for f in forms_dir.iterdir()
                  if f.suffix in (".docx", ".pdf") and f.name not in trang]
        assert not mo_coi, f"chép sang nhưng không trang nào trỏ tới: {mo_coi}"

    def test_xoa_trang_mo_coi(self, master_session, form_da_dung, tmp_path):
        out = tmp_path / "content"
        form_exporter.export_forms(master_session, out)
        (out / "bieu-mau" / "bm-hopdong-99999.md").write_text("cũ", encoding="utf-8")
        stats = form_exporter.export_forms(master_session, out)
        assert stats.orphan_removed == 1


class TestNoiNguocTuTrangVanBan:
    def test_trang_van_ban_liet_ke_bieu_mau_kem_theo(self, master_session,
                                                     form_da_dung):
        """Người đọc biết Thông tư bắt nộp báo cáo; thứ họ cần tiếp là ĐÚNG tờ mẫu."""
        doc = Document(doc_num="91/2015/QH13", doc_key="91-2015-qh13::qh",
                       title="Bộ luật Dân sự", public_slug="91-2015-qh13")
        master_session.add(doc)
        master_session.commit()

        master_session.query(LegalFormRef).filter_by(
            form_key="hopdong-46696").update({"doc_key": doc.doc_key})
        form_da_dung.public_slug = form_exporter.public_slug_bieu_mau(form_da_dung)
        master_session.commit()

        page = site_exporter.render_page(master_session, doc, [], {})
        assert "Biểu mẫu kèm theo" in page
        assert form_da_dung.public_slug in page

    def test_khong_co_bieu_mau_thi_noi_ro_chu_khong_de_trong(self, master_session):
        doc = Document(doc_num="1/2020/NĐ-CP", doc_key="nd1::cp", title="X",
                       public_slug="1-2020-ndd-cp")
        master_session.add(doc)
        master_session.commit()
        page = site_exporter.render_page(master_session, doc, [], {})
        assert "Chưa ghi nhận biểu mẫu nào" in page

    def test_khong_liet_ke_mau_chua_dang(self, master_session, form_da_dung):
        """Link tới trang chưa tồn tại là link gãy — tệ hơn không có link."""
        doc = Document(doc_num="91/2015/QH13", doc_key="91-2015-qh13::qh",
                       title="Bộ luật Dân sự", public_slug="91-2015-qh13")
        master_session.add(doc)
        master_session.query(LegalFormRef).filter_by(
            form_key="hopdong-46696").update({"doc_key": doc.doc_key})
        form_da_dung.public_slug = None
        master_session.commit()
        page = site_exporter.render_page(master_session, doc, [], {})
        assert "Chưa ghi nhận biểu mẫu nào" in page


class TestThuTuDangTrang:
    def test_bieu_mau_phai_dang_TRUOC_van_ban(self, master_session, form_da_dung,
                                              tmp_path):
        """LỖI ĐÃ XẢY RA THẬT, VÀ NÓ IM LẶNG.

        `export_forms()` là nơi gán `LegalForm.public_slug`, mà mục "Biểu mẫu kèm
        theo" chỉ liệt kê mẫu ĐÃ có slug. Đăng văn bản trước thì mọi trang văn bản
        ghi "Chưa ghi nhận biểu mẫu nào kèm theo văn bản này" dù quan hệ đã có
        trong kho — và câu đó cũng là câu hợp lệ nên không ai phát hiện.

        Đo lần chạy thật ngày 18/08/2026: 4.200 trang văn bản đăng xong đều rỗng
        mục biểu mẫu, trong khi 20 trang biểu mẫu đều trỏ ngược về đúng văn bản.
        """
        doc = Document(doc_num="96/2024/NĐ-CP", doc_key="nd96::cp",
                       title="Nghị định 96", public_slug="96-2024-ndd-cp")
        master_session.add(doc)
        master_session.query(LegalFormRef).filter_by(
            form_key="hopdong-46696").update({"doc_key": doc.doc_key})
        master_session.commit()

        out = tmp_path / "content"

        # Thứ tự SAI: văn bản trước
        trang_sai = site_exporter.render_page(master_session, doc, [], {})
        assert "Chưa ghi nhận biểu mẫu nào" in trang_sai

        # Thứ tự ĐÚNG: biểu mẫu trước để có slug
        form_exporter.export_forms(master_session, out)
        master_session.flush()
        trang_dung = site_exporter.render_page(master_session, doc, [], {})
        assert "Chưa ghi nhận biểu mẫu nào" not in trang_dung
        assert form_da_dung.public_slug in trang_dung


class TestDangMauCaNhan:
    def test_mau_chi_phuc_vu_ca_nhan_van_duoc_dang(self, master_session, form_da_dung,
                                                    tmp_path):
        """Cổng đăng là "phục vụ NGƯỜI ĐỌC THẬT", không phải "phục vụ doanh
        nghiệp". Mẫu ly hôn không phải mẫu doanh nghiệp, nhưng nó là mẫu mà một
        người thật phải điền — đó mới là điều kiện."""
        form_da_dung.is_business = False
        form_da_dung.is_individual = True
        master_session.commit()
        out = tmp_path / "content"
        assert form_exporter.export_forms(master_session, out).written == 1
        assert (out / "bieu-mau" / f"{form_da_dung.public_slug}.md").exists()

    def test_mau_khong_phuc_vu_ai_thi_khong_dang(self, master_session, form_da_dung,
                                                 tmp_path):
        form_da_dung.is_business = False
        form_da_dung.is_individual = False
        master_session.commit()
        out = form_exporter.export_forms(master_session, tmp_path / "content")
        assert out.written == 0
