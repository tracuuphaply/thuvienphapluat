"""Nhóm — đồ thị quan hệ khoá theo doc_key.

Số hiệu chỉ duy nhất trong phạm vi một cơ quan. Khoá đồ thị theo số hiệu khiến
hai văn bản của hai tỉnh khác nhau gộp thành MỘT cạnh — đã gặp thật:
"64/2026/QĐ-UBND" của Huế và của Tây Ninh cùng "Căn cứ" 72/2025/QH15.

Hậu quả không chỉ là lệch một con số: `impact_analysis("64/2026/QĐ-UBND")` không
phân biệt nổi hai văn bản, nên báo cáo cho doanh nghiệp ở Huế có thể dẫn quan hệ
pháp lý của một văn bản Tây Ninh.
"""
import pytest


@pytest.fixture
def graph(rag_db):
    return rag_db


class TestKhoaTheoDocKey:
    def test_hai_tinh_trung_so_hieu_ra_hai_canh(self, graph):
        """Đây là ca đã làm hỏng đồ thị thật."""
        for agency in ("ubnd thành phố huế", "ubnd tỉnh tây ninh"):
            graph.upsert_graph_edge(
                source_doc_key=f"64/2026/qđ-ubnd::{agency}",
                source_doc_num="64/2026/QĐ-UBND",
                target_doc_key="72/2025/qh15::quốc hội",
                target_doc_num="72/2025/QH15",
                relation_type="Căn cứ",
            )
        n = graph.db.execute(
            "SELECT COUNT(*) FROM legal_graph WHERE source_doc_num='64/2026/QĐ-UBND'"
        ).fetchone()[0]
        assert n == 2, "hai văn bản khác nhau bị gộp thành một cạnh"

    def test_cung_van_ban_ghi_lai_khong_nhan_doi(self, graph):
        for _ in range(3):
            graph.upsert_graph_edge(
                source_doc_key="292/2026/nđ-cp::chính phủ",
                source_doc_num="292/2026/NĐ-CP",
                target_doc_key="83/2015/qh13::quốc hội",
                target_doc_num="83/2015/QH13",
                relation_type="Căn cứ",
            )
        assert graph.db.execute("SELECT COUNT(*) FROM legal_graph").fetchone()[0] == 1

    def test_canh_treo_cua_cung_mot_nguon_khong_gop_nhau(self, graph):
        """target_doc_key NULL khi đích chưa có trong kho.

        Nếu khoá duy nhất chỉ gồm (source_key, target_key, relation) thì mọi
        cạnh treo của cùng một nguồn sẽ gộp làm một — mất sạch danh sách văn bản
        cần kéo về ở bước bao đóng.
        """
        for target in ("83/2015/QH13", "72/2010/QĐ-TTg", "45/2013/QH13"):
            graph.upsert_graph_edge(
                source_doc_key="292/2026/nđ-cp::chính phủ",
                source_doc_num="292/2026/NĐ-CP",
                target_doc_key=None,
                target_doc_num=target,
                relation_type="Căn cứ",
            )
        assert graph.db.execute("SELECT COUNT(*) FROM legal_graph").fetchone()[0] == 3

    def test_canh_treo_ghi_lai_khong_nhan_doi(self, graph):
        """Ràng buộc UNIQUE thường KHÔNG chặn được ca này.

        SQL coi mỗi NULL là một giá trị riêng, nên
        UNIQUE(..., target_doc_key, ...) hoàn toàn vô hiệu với cạnh treo — mà
        cạnh treo chiếm 2.963/7.926 cạnh trong kho thật. Đồng bộ chạy hằng ngày
        sẽ chèn thêm một bản sao mỗi lần: một lượt đã đẩy 7.926 cạnh lên 10.889.
        Vì vậy khoá duy nhất phải là chỉ mục biểu thức có COALESCE.
        """
        for _ in range(3):
            graph.upsert_graph_edge(
                source_doc_key="292/2026/nđ-cp::chính phủ",
                source_doc_num="292/2026/NĐ-CP",
                target_doc_key=None, target_doc_num="83/2015/QH13",
                relation_type="Căn cứ",
            )
        assert graph.db.execute("SELECT COUNT(*) FROM legal_graph").fetchone()[0] == 1

    def test_canh_treo_khac_canh_da_phan_giai(self, graph):
        """COALESCE gom NULL về '' — phải chắc '' không đụng doc_key thật nào."""
        for key in (None, "83/2015/qh13::quốc hội"):
            graph.upsert_graph_edge(
                source_doc_key="292/2026/nđ-cp::chính phủ",
                source_doc_num="292/2026/NĐ-CP",
                target_doc_key=key, target_doc_num="83/2015/QH13",
                relation_type="Căn cứ",
            )
        assert graph.db.execute("SELECT COUNT(*) FROM legal_graph").fetchone()[0] == 2

    def test_cung_dich_khac_quan_he_la_hai_canh(self, graph):
        for rel in ("Căn cứ", "Sửa đổi, bổ sung"):
            graph.upsert_graph_edge(
                source_doc_key="a::x", source_doc_num="A",
                target_doc_key="b::y", target_doc_num="B", relation_type=rel,
            )
        assert graph.db.execute("SELECT COUNT(*) FROM legal_graph").fetchone()[0] == 2

    def test_luu_ca_so_hieu_de_tra_cuu_theo_so_hieu(self, graph):
        """Người dùng gõ số hiệu chứ không gõ doc_key, nên vẫn phải tra được."""
        graph.upsert_graph_edge(
            source_doc_key="292/2026/nđ-cp::chính phủ",
            source_doc_num="292/2026/NĐ-CP",
            target_doc_key=None, target_doc_num="83/2015/QH13",
            relation_type="Căn cứ",
        )
        row = graph.db.execute(
            "SELECT source_doc_num, target_doc_num FROM legal_graph"
        ).fetchone()
        assert row["source_doc_num"] == "292/2026/NĐ-CP"
        assert row["target_doc_num"] == "83/2015/QH13"


class TestDongBoDoThi:
    """Nạp lại đồ thị phải XOÁ cạnh không còn, không chỉ thêm cạnh mới.

    Khi một cạnh được nối lại sang đích khác, hàng cũ nằm lại vĩnh viễn. Đã xảy
    ra thật: sửa 246 cạnh xong thì rag.db có 11.323 cạnh trong khi kho chính chỉ
    có 10.751 — đồ thị khẳng định 572 quan hệ pháp lý không còn tồn tại.
    """

    def test_canh_doi_dich_thi_ban_cu_bi_xoa(self, master_session, rag_db):
        from src.rag.rag_indexer import sync_graph_edges
        from src.storage.database import insert_references, upsert_document
        from src.storage.models import DocumentReference

        src, _ = upsert_document(master_session, {
            "doc_num": "01/2026/NĐ-CP", "title": "A", "agency_name": "Chính phủ"})
        cu, _ = upsert_document(master_session, {
            "doc_num": "64/2026/QĐ-UBND", "title": "Huế",
            "agency_name": "UBND Thành phố Huế", "moj_id": "111"})
        moi, _ = upsert_document(master_session, {
            "doc_num": "64/2026/QĐ-UBND", "title": "Tây Ninh",
            "agency_name": "UBND Tỉnh Tây Ninh", "moj_id": "222"})
        master_session.flush()
        insert_references(master_session, src.id, [{
            "target_doc_num": "64/2026/QĐ-UBND", "relation_type": "Bãi bỏ",
            "target_moj_id": "222"}])
        canh = master_session.query(DocumentReference).one()
        canh.target_doc_id = cu.id
        master_session.commit()

        sync_graph_edges(master_session, rag_db)
        assert rag_db.db.execute(
            "SELECT target_doc_key FROM legal_graph").fetchone()[0] == cu.doc_key

        canh.target_doc_id = moi.id
        master_session.commit()
        sync_graph_edges(master_session, rag_db)

        rows = rag_db.db.execute("SELECT target_doc_key FROM legal_graph").fetchall()
        assert [r[0] for r in rows] == [moi.doc_key], "cạnh cũ vẫn còn"

    def test_canh_bi_xoa_o_kho_chinh_thi_bien_mat(self, master_session, rag_db):
        from src.rag.rag_indexer import sync_graph_edges
        from src.storage.database import insert_references, upsert_document
        from src.storage.models import DocumentReference

        src, _ = upsert_document(master_session, {
            "doc_num": "01/2026/NĐ-CP", "title": "A", "agency_name": "Chính phủ"})
        master_session.flush()
        insert_references(master_session, src.id, [
            {"target_doc_num": "83/2015/QH13", "relation_type": "Căn cứ"},
            {"target_doc_num": "45/2013/QH13", "relation_type": "Căn cứ"},
        ])
        master_session.commit()
        sync_graph_edges(master_session, rag_db)
        assert rag_db.db.execute("SELECT COUNT(*) FROM legal_graph").fetchone()[0] == 2

        master_session.query(DocumentReference).filter_by(
            target_doc_num="45/2013/QH13").delete()
        master_session.commit()
        sync_graph_edges(master_session, rag_db)
        assert rag_db.db.execute("SELECT COUNT(*) FROM legal_graph").fetchone()[0] == 1


class TestTruyVetVanChay:
    """Các hàm truy vết nhận số hiệu làm đầu vào — phải giữ nguyên hành vi đó."""

    def _seed(self, graph):
        graph.upsert_graph_edge(
            source_doc_key="292/2026/nđ-cp::chính phủ",
            source_doc_num="292/2026/NĐ-CP",
            target_doc_key="83/2015/qh13::quốc hội",
            target_doc_num="83/2015/QH13",
            relation_type="Thay thế",
        )

    def test_impact_analysis_theo_ca_hai_chieu(self, graph):
        from src.rag.graph_traversal import impact_analysis

        self._seed(graph)
        xuoi = impact_analysis(graph, "292/2026/NĐ-CP")
        nguoc = impact_analysis(graph, "83/2015/QH13")
        assert [a.doc_num for a in xuoi] == ["83/2015/QH13"]
        assert [a.doc_num for a in nguoc] == ["292/2026/NĐ-CP"]
        assert "bị thay thế bởi" in nguoc[0].relation

    def test_effect_warnings_bat_duoc_van_ban_bi_thay_the(self, graph):
        from src.rag.graph_traversal import effect_warnings

        self._seed(graph)
        w = effect_warnings(graph, "83/2015/QH13")
        assert w["terminated_by"] and w["terminated_by"][0][0] == "292/2026/NĐ-CP"

    def test_chi_dich_danh_mot_tinh_thi_khong_lay_cua_tinh_khac(self, graph):
        """Giá trị thật của việc đổi khoá: tách được hai văn bản trùng số hiệu."""
        from src.rag.graph_traversal import impact_analysis

        for agency, target in (("huế", "10/2020/QĐ-UBND"), ("tây ninh", "20/2020/QĐ-UBND")):
            graph.upsert_graph_edge(
                source_doc_key=f"64/2026/qđ-ubnd::ubnd {agency}",
                source_doc_num="64/2026/QĐ-UBND",
                target_doc_key=None, target_doc_num=target,
                relation_type="Bãi bỏ",
            )
        chi_hue = impact_analysis(
            graph, "64/2026/QĐ-UBND", doc_key="64/2026/qđ-ubnd::ubnd huế")
        assert [a.doc_num for a in chi_hue] == ["10/2020/QĐ-UBND"]
        assert len(impact_analysis(graph, "64/2026/QĐ-UBND")) == 2

    def _hai_tinh_cung_bai_bo(self, graph):
        for agency in ("huế", "tây ninh"):
            graph.upsert_graph_edge(
                source_doc_key=f"64/2026/qđ-ubnd::ubnd {agency}",
                source_doc_num="64/2026/QĐ-UBND",
                target_doc_key="10/2020/qđ-ubnd::x", target_doc_num="10/2020/QĐ-UBND",
                relation_type="Sửa đổi, bổ sung",
            )

    def test_giu_ca_hai_van_ban_va_phan_biet_duoc_bang_doc_key(self, graph):
        """Không được gộp theo số hiệu — gộp là làm biến mất một văn bản thật."""
        from src.rag.graph_traversal import impact_analysis

        self._hai_tinh_cung_bai_bo(graph)
        ra = impact_analysis(graph, "10/2020/QĐ-UBND")
        assert [a.doc_num for a in ra] == ["64/2026/QĐ-UBND"] * 2
        assert len({a.doc_key for a in ra}) == 2

    def test_canh_bao_khong_liet_ke_mot_so_hieu_hai_lan(self, graph):
        """effect_warnings bỏ doc_key để dựng câu chữ, nên phải khử trùng —
        "bị sửa đổi bởi: 64/2026/QĐ-UBND, 64/2026/QĐ-UBND" đọc như hệ thống hỏng.
        """
        from src.rag.graph_traversal import effect_warnings

        self._hai_tinh_cung_bai_bo(graph)
        assert effect_warnings(graph, "10/2020/QĐ-UBND")["amended_by"] == [
            ("64/2026/QĐ-UBND", "Sửa đổi, bổ sung")
        ]

    def test_cascade_retrieve_di_duoc_hai_tang(self, graph):
        from src.rag.graph_traversal import cascade_retrieve

        self._seed(graph)
        graph.upsert_graph_edge(
            source_doc_key="83/2015/qh13::quốc hội", source_doc_num="83/2015/QH13",
            target_doc_key="45/2013/qh13::quốc hội", target_doc_num="45/2013/QH13",
            relation_type="Căn cứ",
        )
        edges = cascade_retrieve(graph, "292/2026/NĐ-CP", max_depth=2)
        assert {(e.source, e.target) for e in edges} == {
            ("292/2026/NĐ-CP", "83/2015/QH13"),
            ("83/2015/QH13", "45/2013/QH13"),
        }
