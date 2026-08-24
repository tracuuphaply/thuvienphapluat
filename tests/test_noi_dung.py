"""Ruột tài liệu cắt thành mảnh cho trang trợ lý.

Hai bất biến đáng khoá nhất ở đây KHÔNG phải là "có sinh ra file không":

  · NGUỒN NÀO ĐƯỢC ĐỌC. `body_html_path` là HTML gốc Thư viện Pháp luật và
    `fulltext_path` là HTML thô Bộ Tư pháp — cả hai là nguyên liệu nội bộ, mang
    theo thẻ và dấu vết trang nguồn. Chỉ hai đường sạch được phép: `body_md_path`
    và `clean_text_path`.

  · CỜ `r` PHẢI KHỚP FILE THẬT. Trang chỉ tải ruột khi cờ có; cờ sai một chiều
    là tài liệu có nội dung mà không ai xem được, sai chiều kia là một lượt 404
    và một dòng đỏ trong bảng điều khiển cho mỗi lần mở.
"""
from datetime import date

import pytest

from src.publish import assistant_export, noi_dung
from src.storage.models import Document, LegalForm


@pytest.fixture
def kho(master_session, tmp_path):
    def vb(slug, md=None, **kw):
        d = Document(
            doc_num=kw.get("so", f"{slug}/2024/NĐ-CP"), doc_key=f"{slug}::x",
            public_slug=slug, title=f"Văn bản {slug}", doc_type="Nghị định",
            is_vbqppl=True, tvpl_field_code=1, eff_state="con_hieu_luc",
            hierarchy_level=5, territorial_scope="trung_uong",
            issue_date=date(2024, 1, 1),
        )
        if md is not None:
            p = tmp_path / f"{slug}.md"
            p.write_text(md, encoding="utf-8")
            d.clean_text_path = str(p)
        master_session.add(d)
        master_session.commit()
        return d

    def bm(slug, md=None, **kw):
        f = LegalForm(
            form_key=kw.get("khoa", slug), source="hopdong", external_id="1",
            title=f"Biểu mẫu {slug}", public_slug=slug, is_business=True,
            crawl_status="OK", nghiep_vu="[]",
        )
        if md is not None:
            p = tmp_path / f"{slug}.md"
            p.write_text(md, encoding="utf-8")
            f.body_md_path = str(p)
        master_session.add(f)
        master_session.commit()
        return f

    return type("Kho", (), {"vb": staticmethod(vb), "bm": staticmethod(bm)})


class TestNguon:
    def test_khong_bao_gio_doc_html_goc(self):
        """Chỉ đọc bản Markdown đã làm sạch, không đọc HTML nguồn."""
        import inspect, re
        src = inspect.getsource(noi_dung)
        # Bỏ chú thích và docstring trước khi soi: hai tên cấm ĐƯỢC PHÉP xuất
        # hiện trong câu văn giải thích vì sao cấm chúng.
        ma = re.sub(r'""".*?"""', "", src, flags=re.S)
        ma = "\n".join(d.split("#")[0] for d in ma.split("\n"))
        assert "body_html_path" not in ma
        assert "fulltext_path" not in ma
        assert "clean_text_path" in ma and "body_md_path" in ma


class TestCoRuot:
    def test_ghi_manh_cho_van_ban_va_bieu_mau(self, master_session, kho, tmp_path):
        kho.vb("vb-1", "**Điều 1.** Nội dung.")
        kho.bm("bm-1", "Kính gửi: ......")
        out = tmp_path / "site"
        tk, cv, cb = noi_dung.xuat_noi_dung(master_session, out)
        assert (tk.van_ban, tk.bieu_mau) == (1, 1)
        assert cv == {"vb-1"} and cb == {"bm-1"}
        assert "<strong>Điều 1.</strong>" in (
            out / "noi-dung" / "van-ban" / "vb-1.html").read_text(encoding="utf-8")

    def test_thieu_file_nguon_thi_dem_vao_thieu_chu_khong_no(
            self, master_session, kho, tmp_path):
        """Đường dẫn trong kho là đường TUYỆT ĐỐI trên máy đã chạy pipeline.

        Dựng ở máy khác thì file không có — chuyện bình thường, không phải lỗi.
        """
        d = kho.vb("vb-1")
        d.clean_text_path = "/khong/he/ton/tai.md"
        master_session.commit()
        tk, cv, _ = noi_dung.xuat_noi_dung(master_session, tmp_path / "site")
        assert tk.van_ban == 0 and tk.thieu_van_ban == 1 and cv == set()

    def test_file_rong_khong_sinh_manh(self, master_session, kho, tmp_path):
        """Mảnh rỗng vẫn là 200, nên trang sẽ hiện một mục "Nội dung" trống trơn."""
        kho.vb("vb-1", "   \n\n  ")
        tk, cv, _ = noi_dung.xuat_noi_dung(master_session, tmp_path / "site")
        assert tk.van_ban == 0 and tk.thieu_van_ban == 1 and cv == set()

    def test_khong_lay_van_ban_chua_dang(self, master_session, kho, tmp_path):
        d = kho.vb("vb-1", "Nội dung.")
        d.public_slug = None
        master_session.commit()
        tk, cv, _ = noi_dung.xuat_noi_dung(master_session, tmp_path / "site")
        assert tk.van_ban == 0 and cv == set()

    def test_cat_dau_trang_bieu_mau_gom_ca_url_nguon(
            self, master_session, kho, tmp_path):
        """Đầu trang mang tiêu đề `#` và URL Thư viện Pháp luật — cả khối phải đi."""
        kho.bm("bm-1",
               "# GIẤY ĐỀ NGHỊ\n\n**Nguồn:** Thư viện Pháp luật — https://thuvienphapluat.vn/x\n\n"
               "> Bản dựng lại từ nội dung biểu mẫu để tiện điền và in.\n\n"
               "**CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM**\n")
        out = tmp_path / "site"
        noi_dung.xuat_noi_dung(master_session, out)
        html = (out / "noi-dung" / "bieu-mau" / "bm-1.html").read_text(encoding="utf-8")
        assert "thuvienphapluat" not in html
        assert "GIẤY ĐỀ NGHỊ" not in html and "# " not in html
        assert "Bản dựng lại" not in html
        assert "CỘNG HOÀ" in html


class TestCoKhopBoDuLieu:
    def test_co_r_dung_bang_tap_manh_da_ghi(self, master_session, kho, tmp_path):
        """Cờ `r` trong du-lieu.json phải khớp ĐÚNG những mảnh đã ghi ra đĩa.

        Lệch một chiều là tài liệu có nội dung mà không ai xem được; lệch chiều
        kia là mỗi lần mở một lượt 404. Cả hai đều im lặng với người dựng trang.
        """
        kho.vb("vb-co", "Có nội dung.")
        kho.vb("vb-khong")
        kho.bm("bm-co", "Có ruột.")
        kho.bm("bm-khong")
        out = tmp_path / "site"
        _, cv, cb = noi_dung.xuat_noi_dung(master_session, out)
        goi = assistant_export.xuat_du_lieu(master_session, out, ruot_vb=cv, ruot_bm=cb)
        import json
        d = json.loads((out / assistant_export.TEN_FILE).read_text(encoding="utf-8"))
        for kho_ten, thu_muc in (("van_ban", "van-ban"), ("bieu_mau", "bieu-mau")):
            for m in d[kho_ten]:
                co_file = (out / "noi-dung" / thu_muc / f"{m['s']}.html").is_file()
                assert bool(m.get("r")) == co_file, f"lệch cờ ở {m['s']}"
        assert goi.van_ban == 2

    def test_khong_truyen_tap_ruot_thi_khong_muc_nao_co_co(
            self, master_session, kho, tmp_path):
        """Đường dựng cũ (không xuất ruột) phải ra bộ dữ liệu không có cờ `r`."""
        kho.vb("vb-1", "Nội dung.")
        out = tmp_path / "site"
        assistant_export.xuat_du_lieu(master_session, out)
        import json
        d = json.loads((out / assistant_export.TEN_FILE).read_text(encoding="utf-8"))
        assert all("r" not in m for m in d["van_ban"])


class TestChiXuatVanBanQuyPham:
    def test_bo_qua_van_ban_khong_phai_qppl(self, master_session, kho, tmp_path):
        """Bộ lọc phải khớp `assistant_export._van_ban()` và `html_site.xuat_van_ban()`,
        cả hai đều lọc `is_vbqppl`.

        Thiếu nó thì ruột của văn bản không phải quy phạm vẫn được ghi ra site —
        thành file mồ côi: không trang nào trỏ tới, không mục nào trong bộ dữ liệu
        trợ lý mang cờ `r`, mà nội dung thì vẫn nằm công khai trên máy chủ.
        """
        d = kho.vb("vb-qppl", "Nội dung quy phạm.")
        k = kho.vb("vb-khac", "Nội dung không quy phạm.")
        k.is_vbqppl = False
        master_session.commit()
        out = tmp_path / "site"
        tk, cv, _ = noi_dung.xuat_noi_dung(master_session, out)
        assert cv == {"vb-qppl"}
        assert not (out / "noi-dung" / "van-ban" / "vb-khac.html").exists()
        assert tk.van_ban == 1
