"""Nhóm — trang tra cứu công khai.

Mục đích của trang này là để người đọc báo cáo KIỂM CHỨNG được mọi số hiệu được
trích dẫn. Vì vậy hai thứ tuyệt đối không được sai:
  - không đăng thứ không nên đăng (toàn văn, văn bản không phải QPPL, rác)
  - không phát ra link chết, vì một báo cáo trỏ tới 404 làm người đọc nghi ngờ
    cả những phần đúng
"""
import pytest

from src.publish import links, site_exporter
from src.storage.database import upsert_document


@pytest.fixture
def kho(master_session):
    docs = [
        {"doc_num": "135/2025/QH15", "title": "Luật Xây dựng",
         "agency_name": "Quốc hội", "eff_status": "Còn hiệu lực", "moj_id": "1"},
        {"doc_num": "410/TB-VPCP", "title": "Thông báo kết luận",
         "agency_name": "Văn phòng Chính phủ", "moj_id": "2"},
        {"doc_num": "40/2026/QĐ-UBND", "title": "QĐ tỉnh A",
         "agency_name": "UBND Tỉnh Cà Mau", "moj_id": "3"},
        {"doc_num": "40/2026/QĐ-UBND", "title": "QĐ tỉnh B",
         "agency_name": "UBND Tỉnh Lai Châu", "moj_id": "4"},
    ]
    for d in docs:
        upsert_document(master_session, d)
    master_session.commit()
    return master_session


class TestNoiDungTrang:
    def _render(self, session, doc_num, impacts=None):
        from src.storage.models import Document

        doc = session.query(Document).filter(Document.doc_num == doc_num).first()
        return site_exporter.render_page(
            session, doc, impacts or [], site_exporter.build_slug_index(session)
        )

    def test_khong_dang_toan_van(self, kho):
        """Trang chỉ có dữ kiện; toàn văn ở nguồn chính thức."""
        page = self._render(kho, "135/2025/QH15")
        assert "## Dữ kiện" in page
        assert "## Nội dung" not in page

    def test_luon_co_tuyen_bo_khong_chinh_thuc(self, kho):
        assert "Bản sao không chính thức" in self._render(kho, "135/2025/QH15")

    def test_luon_co_muc_nguon_goc(self, kho):
        """Không ghi được nguồn thì trang mất hết giá trị kiểm chứng."""
        page = self._render(kho, "135/2025/QH15")
        assert "## Nguồn gốc" in page

    def test_bang_tac_dong_luon_kem_cau_gioi_han(self, kho):
        """Thiếu câu này thì con số bị đọc thành chi phí kinh tế."""
        page = self._render(kho, "135/2025/QH15", impacts=[
            {"vsic_code": "F", "impact_pct_doc": 25.7, "impact_pct_industry": 98.9}
        ])
        assert "không** đo chi phí kinh tế" in page
        assert "Xây dựng (F)" in page

    def test_chua_cham_diem_thi_noi_ro_chu_khong_de_bang_rong(self, kho):
        assert "Chưa chấm điểm tác động" in self._render(kho, "135/2025/QH15")

    def test_co_quan_suy_tu_so_hieu_khi_kho_chua_co(self, master_session):
        """Bảng thứ bậc đã biết /NĐ-CP là Chính phủ — hiện "Chưa xác định" là

        bỏ phí một dữ kiện chắc chắn đúng.
        """
        from src.storage.models import Document

        upsert_document(master_session, {
            "doc_num": "292/2026/NĐ-CP", "title": "Nghị định thử", "moj_id": "9",
        })
        master_session.commit()
        doc = master_session.query(Document).first()
        page = site_exporter.render_page(master_session, doc, [], {})
        assert "Chính phủ" in page


class TestVanBanNguCanh:
    """Văn bản kéo về theo dẫn chiếu phải tự nói nó là gì.

    3.255/4.200 trang là văn bản ngữ cảnh và 2.134 trong số đó đã hết hiệu lực
    toàn bộ. Người mở thẳng từ Google hoặc từ một link trong báo cáo không có
    gì để biết mình không đang đọc luật hiện hành.
    """

    def _doc(self, session, **kw):
        from src.storage.models import Document

        upsert_document(session, {"doc_num": "83/2015/QH13", "title": "Luật cũ",
                                  "agency_name": "Quốc hội", "moj_id": "9", **kw})
        session.commit()
        return session.query(Document).filter_by(doc_num="83/2015/QH13").first()

    def _render(self, session, doc):
        return site_exporter.render_page(
            session, doc, [], site_exporter.build_slug_index(session))

    def test_trang_ngu_canh_co_canh_bao(self, master_session):
        page = self._render(master_session,
                            self._doc(master_session, is_closure_node=True))
        assert "Văn bản ngữ cảnh" in page
        assert "la_van_ban_ngu_canh: True" in page
        assert "van-ban-ngu-canh" in page

    def test_trang_nghiep_vu_khong_co_canh_bao_thua(self, master_session):
        page = self._render(master_session,
                            self._doc(master_session, is_closure_node=False))
        assert "Văn bản ngữ cảnh" not in page
        assert "la_van_ban_ngu_canh: False" in page

    def test_chi_muc_khong_liet_ke_van_ban_ngu_canh(self, master_session, tmp_path):
        from src.publish import moc_static

        import datetime

        upsert_document(master_session, {
            "doc_num": "01/2026/NĐ-CP", "title": "Nghị định nghiệp vụ",
            "agency_name": "Chính phủ", "moj_id": "10", "is_closure_node": False,
            "issue_date": datetime.date(2026, 1, 5)})
        upsert_document(master_session, {
            "doc_num": "02/2020/NĐ-CP", "title": "Nghị định nền",
            "agency_name": "Chính phủ", "moj_id": "11", "is_closure_node": True,
            "issue_date": datetime.date(2020, 2, 3)})
        master_session.commit()

        moc_static.export_indexes(master_session, tmp_path, "v-test")
        noi_dung = "\n".join(p.read_text(encoding="utf-8")
                             for p in tmp_path.rglob("*.md"))
        assert "01/2026/NĐ-CP" in noi_dung
        assert "02/2020/NĐ-CP" not in noi_dung, (
            "văn bản ngữ cảnh chôn mất phần cần đọc trong chỉ mục"
        )

    def test_bang_hieu_luc_cong_dung_bang_con_so_neu_ra(self, master_session, tmp_path):
        """Trang chủ nêu một con số rồi bày bảng — hai thứ phải là cùng một tập.

        Bản trước đếm `docs` cho dòng tổng nhưng truy vấn lại toàn bộ kho cho
        bảng, nên trang chủ ghi "946 văn bản" trên một bảng cộng ra 4.201.
        Người đọc không có cách nào biết đó là hai tập khác nhau.
        """
        import datetime
        import re

        from src.publish import moc_static

        for i, (num, nen) in enumerate([("01/2026/NĐ-CP", False),
                                        ("03/2026/NĐ-CP", False),
                                        ("02/2020/NĐ-CP", True)]):
            upsert_document(master_session, {
                "doc_num": num, "title": f"Nghị định {i}", "agency_name": "Chính phủ",
                "moj_id": str(20 + i), "is_closure_node": nen,
                "issue_date": datetime.date(2026, 1, 5)})
        master_session.commit()

        moc_static.export_indexes(master_session, tmp_path, "v-test")
        home = (tmp_path / "index.md").read_text(encoding="utf-8")

        neu_ra = int(re.search(r"\*\*(\d+)\*\* văn bản trong danh mục", home).group(1))
        tong_bang = sum(int(m) for m in re.findall(r"\|\s*(\d+)\s*\|", home))
        assert tong_bang == neu_ra, home


class TestPhanGiaiWikilink:
    def test_so_hieu_duy_nhat_thi_phan_giai_duoc(self, kho):
        index = site_exporter.build_slug_index(kho)
        assert "135/2025/QH15" in index

    def test_so_hieu_trung_giua_cac_tinh_thi_khong_phan_giai(self, kho):
        """Trỏ nhầm sang văn bản của tỉnh khác tệ hơn để link chưa phân giải."""
        assert "40/2026/QĐ-UBND" not in site_exporter.build_slug_index(kho)


class TestLinkVeTrangCongKhai:
    def test_khong_cau_hinh_thi_khong_phat_link(self, kho, monkeypatch):
        monkeypatch.setattr(links, "PUBLIC_VAULT_BASE_URL", "")
        assert links.resolve_links(kho, ["135/2025/QH15"]) == {}

    def test_chua_dang_thi_khong_phat_link(self, kho, monkeypatch):
        """published_hash NULL = trang chưa tồn tại. Link 404 làm người đọc

        nghi ngờ cả những phần đúng của báo cáo.
        """
        monkeypatch.setattr(links, "PUBLIC_VAULT_BASE_URL", "https://x.io/v")
        assert links.resolve_links(kho, ["135/2025/QH15"]) == {}

    def test_da_dang_thi_phat_link(self, kho, monkeypatch):
        from src.storage.models import Document

        monkeypatch.setattr(links, "PUBLIC_VAULT_BASE_URL", "https://x.io/v")
        doc = kho.query(Document).filter(Document.doc_num == "135/2025/QH15").first()
        doc.published_hash = "abc"
        kho.commit()
        url = links.resolve_links(kho, ["135/2025/QH15"])["135/2025/QH15"]
        assert url == "https://x.io/v/van-ban/135-2025-qh15"

    def test_so_hieu_bia_khong_bao_gio_ra_link(self, kho, monkeypatch):
        """URL do mô hình sinh là URL bịa — ở đây code tra bảng nên bịa là

        bất khả thi về mặt cấu trúc.
        """
        monkeypatch.setattr(links, "PUBLIC_VAULT_BASE_URL", "https://x.io/v")
        rows = dict(links.appendix_rows(kho, "Theo 99/9999/XX-YY thì..."))
        assert rows.get("99/9999/XX-YY") == ""

    def test_so_hieu_trung_tinh_khong_ra_link(self, kho, monkeypatch):
        from src.storage.models import Document

        monkeypatch.setattr(links, "PUBLIC_VAULT_BASE_URL", "https://x.io/v")
        for doc in kho.query(Document).filter(
            Document.doc_num == "40/2026/QĐ-UBND"
        ).all():
            doc.published_hash = "abc"
        kho.commit()
        assert links.resolve_links(kho, ["40/2026/QĐ-UBND"]) == {}


class TestChiDangVanBanQPPL:
    def test_loai_so_hieu_rac(self):
        assert "Không số" in site_exporter.JUNK_TARGETS

    def test_ghi_nhan_ban_da_dang_de_lan_sau_khong_ghi_lai(self, kho, tmp_path):
        """Chỉ ghi trang có nội dung đổi — commit publish phải nhỏ."""
        from src.config import impact_scorer_version

        first = site_exporter.export_documents(kho, tmp_path, impact_scorer_version())
        kho.commit()
        second = site_exporter.export_documents(kho, tmp_path, impact_scorer_version())
        assert first.written > 0
        assert second.written == 0 and second.unchanged == first.written


# ──────────────────────────────────────────────
# Dọn trang mồ côi
# ──────────────────────────────────────────────

class TestDonTrangMoCoi:
    def test_xoa_trang_khong_con_van_ban_tuong_ung(self, tmp_path):
        """Slug đổi hoặc văn bản thôi đủ điều kiện đăng thì trang cũ phải biến mất.

        Đo trên kho thật lúc thêm hàm này: 593/4.793 file là trang mồ côi tích
        lại qua các lần vá quy tắc tạo slug.
        """
        # Không lấy ca đổi-chữ-hoa làm ví dụ: macOS không phân biệt hoa/thường
        # ở tên file nên "X.md" và "x.md" là cùng một file, đổi tên slug sang
        # chữ thường không sinh ra file mồ côi nào trên máy này. Ca mồ côi thật
        # là slug đổi hình dạng (vá quy tắc tạo slug) và văn bản bị phân loại
        # lại thành không-phải-QPPL.
        for ten in ("292-2026-ndd-cp", "292-2026-nd-cp--a1b2", "cu-khong-con"):
            (tmp_path / f"{ten}.md").write_text("x", encoding="utf-8")

        n = site_exporter.remove_orphan_pages(tmp_path, {"292-2026-ndd-cp"})

        assert n == 2
        assert (tmp_path / "292-2026-ndd-cp.md").exists()
        assert not (tmp_path / "cu-khong-con.md").exists()

    def test_tap_rong_thi_khong_xoa_gi(self, tmp_path):
        """Tập slug hợp lệ rỗng nghĩa là lượt chạy vừa hỏng, không phải kho rỗng.

        Xoá lúc đó là xoá sạch trang công khai vì một lỗi tạm thời.
        """
        (tmp_path / "292-2026-ndd-cp.md").write_text("x", encoding="utf-8")

        assert site_exporter.remove_orphan_pages(tmp_path, set()) == 0
        assert (tmp_path / "292-2026-ndd-cp.md").exists()

    def test_khong_dung_toi_file_khac_dinh_dang(self, tmp_path):
        """Ảnh và file phụ trợ trong thư mục không phải trang mồ côi."""
        (tmp_path / "292-2026-ndd-cp.md").write_text("x", encoding="utf-8")
        (tmp_path / "so-do.png").write_bytes(b"\x89PNG")

        site_exporter.remove_orphan_pages(tmp_path, {"292-2026-ndd-cp"})

        assert (tmp_path / "so-do.png").exists()
