"""Nhóm — đoạn văn bản khoá theo doc_key.

Số hiệu chỉ duy nhất trong phạm vi một cơ quan. Khoá đoạn theo số hiệu khiến hai
văn bản của hai tỉnh dùng chung MỘT tập đoạn — đã hỏng thật: 46 đoạn mang số
hiệu 42/2026/QĐ-UBND là hỗn hợp của Phú Thọ và TP.HCM, đoạn của bên nạp sau đè
lên bên nạp trước rồi để lại phần đuôi của bên kia.

Hỏng ở tầng này lan ra khắp hệ thống: điểm tác động ngành tính trên tập đoạn
trộn lẫn, báo cáo đọc toàn văn của cả hai tỉnh, và một Quyết định bị bãi bỏ kéo
theo văn bản cùng số hiệu của tỉnh khác biến mất khỏi kết quả truy xuất.
"""
import pytest


def _doan(rag_db, doc_key, doc_num, chunk_index, content, **kw):
    data = {
        "doc_key": doc_key, "doc_num": doc_num, "chunk_index": chunk_index,
        "heading": kw.get("heading", f"Điều {chunk_index}"), "content": content,
        "char_count": len(content), "industries": kw.get("industries", []),
        "content_hash": kw.get("content_hash", f"h{doc_key}{chunk_index}"),
        "eff_status": kw.get("eff_status"),
    }
    return rag_db.upsert_chunk(data)


class TestKhoaDoanTheoDocKey:
    def test_hai_tinh_trung_so_hieu_giu_doan_rieng(self, rag_db):
        """Đây là ca đã làm hỏng dữ liệu thật."""
        a = _doan(rag_db, "42/2026/qđ-ubnd::ubnd tỉnh phú thọ",
                  "42/2026/QĐ-UBND", 0, "Quy định của Phú Thọ")
        b = _doan(rag_db, "42/2026/qđ-ubnd::ubnd thành phố hồ chí minh",
                  "42/2026/QĐ-UBND", 0, "Quy định của TP.HCM")
        assert a != b

        noi_dung = {
            r["doc_key"]: r["content"] for r in rag_db.db.execute(
                "SELECT doc_key, content FROM legal_chunks WHERE doc_num=?",
                ("42/2026/QĐ-UBND",))
        }
        assert noi_dung == {
            "42/2026/qđ-ubnd::ubnd tỉnh phú thọ": "Quy định của Phú Thọ",
            "42/2026/qđ-ubnd::ubnd thành phố hồ chí minh": "Quy định của TP.HCM",
        }

    def test_cung_van_ban_nap_lai_thi_ghi_de(self, rag_db):
        key = "292/2026/nđ-cp::chính phủ"
        a = _doan(rag_db, key, "292/2026/NĐ-CP", 0, "bản cũ")
        b = _doan(rag_db, key, "292/2026/NĐ-CP", 0, "bản mới")
        assert a == b
        assert rag_db.db.execute(
            "SELECT content FROM legal_chunks WHERE id=?", (a,)
        ).fetchone()["content"] == "bản mới"

    def test_thieu_doc_key_thi_lui_ve_so_hieu(self, rag_db):
        """Không được để đoạn thiếu doc_key lọt qua ràng buộc duy nhất.

        Cột NULL làm UNIQUE mất tác dụng hoàn toàn — đúng cái bẫy đã khiến
        legal_graph phình từ 7.926 lên 10.889 cạnh trong một lượt đồng bộ.
        """
        for _ in range(3):
            _doan(rag_db, None, "83/2015/QH13", 0, "nội dung")
        assert rag_db.db.execute("SELECT COUNT(*) FROM legal_chunks").fetchone()[0] == 1

    def test_khong_xoa_doc_key_khi_nap_lai_thieu(self, rag_db):
        """Bên gọi không truyền doc_key thì giữ nguyên, không xoá trắng."""
        key = "292/2026/nđ-cp::chính phủ"
        _doan(rag_db, key, "292/2026/NĐ-CP", 0, "v1")
        _doan(rag_db, None, key, 0, "v2")  # tra bằng chính doc_key
        assert rag_db.db.execute(
            "SELECT doc_key FROM legal_chunks"
        ).fetchone()["doc_key"] == key


class TestDonDoanThua:
    """Nạp lại một văn bản ngắn đi chỉ ghi đè các đoạn đầu.

    Phần đuôi của bản cũ nằm lại vĩnh viễn và vẫn được truy xuất như luật hiện
    hành. Đó chính là cách 46 đoạn của hai tỉnh trộn vào nhau.
    """

    def test_xoa_dung_phan_duoi(self, rag_db):
        key = "292/2026/nđ-cp::chính phủ"
        for i in range(5):
            _doan(rag_db, key, "292/2026/NĐ-CP", i, f"điều {i}")

        assert rag_db.delete_stale_chunks(key, 3) == 2
        con_lai = [r["chunk_index"] for r in rag_db.db.execute(
            "SELECT chunk_index FROM legal_chunks ORDER BY chunk_index")]
        assert con_lai == [0, 1, 2]

    def test_khong_dung_toi_van_ban_khac(self, rag_db):
        _doan(rag_db, "a::x", "A", 0, "của A")
        _doan(rag_db, "b::y", "B", 0, "của B")
        rag_db.delete_stale_chunks("a::x", 0)
        assert [r["doc_key"] for r in rag_db.db.execute(
            "SELECT doc_key FROM legal_chunks")] == ["b::y"]

    def test_khong_con_thua_thi_khong_lam_gi(self, rag_db):
        _doan(rag_db, "a::x", "A", 0, "của A")
        assert rag_db.delete_stale_chunks("a::x", 1) == 0

    @pytest.mark.skipif(
        not __import__("src.rag.db_rag", fromlist=["HAS_VEC"]).HAS_VEC,
        reason="chưa cài sqlite-vec",
    )
    def test_xoa_ca_vector_khong_de_lai_mo_coi(self, rag_db):
        """Vector mồ côi vẫn được tìm thấy rồi JOIN ra rỗng — kết quả biến mất
        mà không có dòng log nào giải thích.
        """
        from src.rag.embeddings_api import embedding_dimension

        cid = _doan(rag_db, "a::x", "A", 0, "của A")
        rag_db.upsert_vector(cid, [0.1] * embedding_dimension())
        assert rag_db.db.execute(
            "SELECT COUNT(*) FROM legal_chunks_vec").fetchone()[0] == 1

        rag_db.delete_stale_chunks("a::x", 0)
        assert rag_db.db.execute(
            "SELECT COUNT(*) FROM legal_chunks_vec").fetchone()[0] == 0


@pytest.mark.skipif(
    not __import__("src.rag.db_rag", fromlist=["HAS_VEC"]).HAS_VEC,
    reason="chưa cài sqlite-vec",
)
class TestVectorMoCoi:
    """Vector không còn đoạn tương ứng vẫn được tìm thấy rồi JOIN ra rỗng.

    Kết quả biến mất giữa chừng mà không có dòng log nào. Đo được 458 vector
    như vậy sau một lượt index: `pending_embeddings` gom suốt cả lượt rồi mới
    nhúng ở cuối, còn delete_stale_chunks chạy ngay sau mỗi file — đoạn vào
    hàng đợi rồi mới bị xoá vẫn được ghi vector.
    """

    def _vec(self, rag_db, chunk_id):
        from src.rag.embeddings_api import embedding_dimension

        rag_db.upsert_vector(chunk_id, [0.1] * embedding_dimension())

    def test_don_duoc_vector_mo_coi(self, rag_db):
        cid = _doan(rag_db, "a::x", "A", 0, "nội dung")
        self._vec(rag_db, cid)
        rag_db.db.execute("DELETE FROM legal_chunks WHERE id = ?", (cid,))
        rag_db.db.commit()

        assert rag_db.db.execute(
            "SELECT COUNT(*) FROM legal_chunks_vec").fetchone()[0] == 1
        assert rag_db.delete_orphan_vectors() == 1
        assert rag_db.db.execute(
            "SELECT COUNT(*) FROM legal_chunks_vec").fetchone()[0] == 0

    def test_khong_dung_toi_vector_con_song(self, rag_db):
        song = _doan(rag_db, "a::x", "A", 0, "còn")
        chet = _doan(rag_db, "b::y", "B", 0, "mất")
        self._vec(rag_db, song)
        self._vec(rag_db, chet)
        rag_db.db.execute("DELETE FROM legal_chunks WHERE id = ?", (chet,))
        rag_db.db.commit()

        rag_db.delete_orphan_vectors()
        con = [r[0] for r in rag_db.db.execute(
            "SELECT rowid FROM legal_chunks_vec").fetchall()]
        assert con == [song]

    def test_khong_co_mo_coi_thi_khong_lam_gi(self, rag_db):
        self._vec(rag_db, _doan(rag_db, "a::x", "A", 0, "x"))
        assert rag_db.delete_orphan_vectors() == 0


class TestThamDinhHieuLucTheoDocKey:
    def test_van_ban_bi_bai_bo_khong_keo_theo_tinh_khac(self, rag_db, edge_factory):
        """Trước khi đoạn có doc_key, một Quyết định tỉnh bị bãi bỏ làm văn bản
        cùng số hiệu của tỉnh khác cũng biến mất khỏi kết quả.
        """
        from src.rag.graph_traversal import validate_results

        hue = "64/2026/qđ-ubnd::ubnd thành phố huế"
        tay_ninh = "64/2026/qđ-ubnd::ubnd tỉnh tây ninh"
        _doan(rag_db, hue, "64/2026/QĐ-UBND", 0, "của Huế", eff_status="Còn hiệu lực")
        _doan(rag_db, tay_ninh, "64/2026/QĐ-UBND", 0, "của Tây Ninh",
              eff_status="Còn hiệu lực")
        edge_factory("99/2026/QĐ-UBND", "64/2026/QĐ-UBND", "Bãi bỏ",
                     target_key=hue)

        giu = validate_results(rag_db, [
            {"doc_num": "64/2026/QĐ-UBND", "doc_key": hue, "content": "của Huế"},
            {"doc_num": "64/2026/QĐ-UBND", "doc_key": tay_ninh, "content": "của Tây Ninh"},
        ])
        assert [c["doc_key"] for c in giu] == [tay_ninh]

    def test_document_status_theo_dung_van_ban(self, rag_db):
        from src.rag.graph_traversal import document_status

        hue = "64/2026/qđ-ubnd::ubnd thành phố huế"
        tay_ninh = "64/2026/qđ-ubnd::ubnd tỉnh tây ninh"
        _doan(rag_db, hue, "64/2026/QĐ-UBND", 0, "x",
              eff_status="Hết hiệu lực toàn bộ")
        _doan(rag_db, tay_ninh, "64/2026/QĐ-UBND", 0, "y",
              eff_status="Còn hiệu lực")

        assert document_status(rag_db, "64/2026/QĐ-UBND", hue) == "Hết hiệu lực toàn bộ"
        assert document_status(rag_db, "64/2026/QĐ-UBND", tay_ninh) == "Còn hiệu lực"

    def test_get_full_context_khong_tron_hai_van_ban(self, rag_db):
        from src.rag.graph_traversal import get_full_context

        hue = "64/2026/qđ-ubnd::ubnd thành phố huế"
        _doan(rag_db, hue, "64/2026/QĐ-UBND", 0, "của Huế")
        _doan(rag_db, "64/2026/qđ-ubnd::ubnd tỉnh tây ninh",
              "64/2026/QĐ-UBND", 0, "của Tây Ninh")

        rieng = get_full_context(rag_db, "64/2026/QĐ-UBND", doc_key=hue)
        assert [c["content"] for c in rieng["chunks"]] == ["của Huế"]
        # Không chỉ đích danh thì vẫn gom cả hai — hành vi cũ, giữ nguyên.
        assert len(get_full_context(rag_db, "64/2026/QĐ-UBND")["chunks"]) == 2
