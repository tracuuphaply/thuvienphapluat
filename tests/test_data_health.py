"""Kiểm tra sức khoẻ dữ liệu thật trong data/ và Legal-Vault/.

Khác với các test đơn vị, nhóm này chạy trên kho thật để bắt hồi quy sau mỗi
lần cào hoặc reindex. Tự bỏ qua khi chưa có dữ liệu (máy mới, CI).

Chạy riêng:  pytest -m data
Bỏ qua:      pytest -m "not data"
"""
import re
import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.data

MASTER_DB = Path("data/legal_docs.db")
RAG_DB = Path("data/rag.db")
VAULT_DOCS = Path("Legal-Vault/Documents")


def _conn(path: Path):
    if not path.exists():
        pytest.skip(f"chưa có {path}")
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    return c


class TestDoThiQuanHe:
    def test_khong_van_ban_cap_tinh_nao_bai_bo_luat_quoc_hoi(self):
        """Vi phạm thứ bậc pháp lý — dấu hiệu bảng ánh xạ referenceType lại sai.

        Trước khi sửa có hàng trăm ca như thế này: Quyết định UBND tỉnh "bãi bỏ"
        Luật Tổ chức chính quyền địa phương, thực chất chỉ là câu "Căn cứ".
        """
        with _conn(MASTER_DB) as c:
            vi_pham = c.execute("""
                SELECT d.doc_num, r.relation_type, r.target_doc_num
                FROM document_references r JOIN documents d ON d.id = r.source_doc_id
                WHERE r.relation_type IN ('Bãi bỏ','Thay thế','Hủy bỏ','Đình chỉ')
                  AND r.target_doc_num LIKE '%/QH%'
                  AND (d.doc_num LIKE '%QĐ-UBND' OR d.doc_num LIKE '%NQ-HĐND')
            """).fetchall()
        assert not vi_pham, f"{len(vi_pham)} ca vi phạm thứ bậc, ví dụ: {tuple(vi_pham[0])}"

    def test_can_cu_phai_la_quan_he_pho_bien_nhat(self):
        """Mọi văn bản đều mở đầu bằng 'Căn cứ...' nên đây phải là nhãn áp đảo.

        Nếu 'Bãi bỏ' vượt lên dẫn đầu thì gần như chắc chắn mã 3 lại bị gán sai.
        """
        with _conn(MASTER_DB) as c:
            rows = c.execute("""
                SELECT relation_type, COUNT(*) n FROM document_references
                GROUP BY 1 ORDER BY 2 DESC
            """).fetchall()
        if not rows:
            pytest.skip("đồ thị trống")
        assert rows[0]["relation_type"] == "Căn cứ", \
            f"nhãn áp đảo đang là {rows[0]['relation_type']!r} — nghi ngờ ánh xạ sai"

    def test_ty_le_bai_bo_khong_bat_thuong(self):
        with _conn(MASTER_DB) as c:
            total = c.execute("SELECT COUNT(*) FROM document_references").fetchone()[0]
            bai_bo = c.execute(
                "SELECT COUNT(*) FROM document_references WHERE relation_type='Bãi bỏ'"
            ).fetchone()[0]
        if total == 0:
            pytest.skip("đồ thị trống")
        assert bai_bo / total < 0.30, f"Bãi bỏ chiếm {100*bai_bo//total}% — trước khi sửa là 82%"

    def test_hai_kho_do_thi_dong_bo(self):
        with _conn(MASTER_DB) as c:
            master = c.execute("SELECT COUNT(*) FROM document_references").fetchone()[0]
        with _conn(RAG_DB) as c:
            rag = c.execute("SELECT COUNT(*) FROM legal_graph").fetchone()[0]
        assert master == rag, f"legal_docs.db có {master} cạnh nhưng rag.db có {rag}"


class TestMetadataRagIndex:
    def test_chunk_khong_bi_mat_metadata(self):
        """Toàn bộ 6124 chunk từng có eff_status/issue_date NULL vì lỗi ghép đường dẫn."""
        with _conn(RAG_DB) as c:
            row = c.execute("""
                SELECT COUNT(*) tong,
                       SUM(eff_status IS NULL) thieu_eff,
                       SUM(issue_date IS NULL) thieu_ngay
                FROM legal_chunks
            """).fetchone()
        if row["tong"] == 0:
            pytest.skip("chưa index")
        assert row["thieu_eff"] / row["tong"] < 0.05, \
            f"{row['thieu_eff']}/{row['tong']} chunk thiếu eff_status"
        assert row["thieu_ngay"] / row["tong"] < 0.05

    def test_moi_nganh_deu_co_van_ban(self):
        """Đo ở cấp VĂN BẢN, không phải cấp đoạn.

        Rất nhiều đoạn là phần mở đầu, quốc hiệu, chữ ký, phụ lục — không thuộc
        ngành nào là đúng. Điều đáng lo là một ngành không có văn bản nào: trước
        khi sửa bộ phân loại, Giao thông chỉ có 3 và Nông nghiệp 5 văn bản,
        trong khi Năng lượng phình lên 97 vì khớp nhầm chữ "nhà nước".
        """
        import json as _json
        from src.obsidian.config_obsidian import INDUSTRY_MAP

        with _conn(RAG_DB) as c:
            rows = c.execute("SELECT doc_num, industries FROM legal_chunks").fetchall()
        if not rows:
            pytest.skip("chưa index")

        docs_per_industry = {name: set() for name in INDUSTRY_MAP}
        for row in rows:
            for name in _json.loads(row["industries"] or "[]"):
                docs_per_industry.setdefault(name, set()).add(row["doc_num"])

        rong = [n for n, d in docs_per_industry.items() if not d]
        assert not rong, f"ngành không có văn bản nào: {rong}"

    def test_ty_le_doan_duoc_gan_nganh_hop_ly(self):
        with _conn(RAG_DB) as c:
            row = c.execute("""
                SELECT COUNT(*) tong,
                       SUM(industries IS NOT NULL AND industries <> '[]') co_nganh
                FROM legal_chunks
            """).fetchone()
        if row["tong"] == 0:
            pytest.skip("chưa index")
        ty_le = row["co_nganh"] / row["tong"]
        assert ty_le > 0.25, f"chỉ {100*ty_le:.0f}% đoạn gắn được ngành — bộ phân loại quá chặt"

    def test_fts_dong_bo_voi_bang_chunk(self):
        with _conn(RAG_DB) as c:
            n = c.execute("SELECT COUNT(*) FROM legal_chunks").fetchone()[0]
            f = c.execute("SELECT COUNT(*) FROM legal_chunks_fts").fetchone()[0]
        assert n == f, f"legal_chunks {n} ≠ FTS {f}"


class TestTruyXuatTheoNganh:
    def test_moi_nganh_deu_truy_xuat_duoc(self):
        """4/10 ngành từng trả về 0 chunk vì ký tự '&' làm vỡ truy vấn FTS."""
        if not RAG_DB.exists():
            pytest.skip("chưa có rag.db")
        from src.obsidian.config_obsidian import INDUSTRY_MAP
        from src.rag.db_rag import RAGDatabase
        from src.rag.hybrid_search import industry_search

        db = RAGDatabase()
        try:
            rong = [
                nganh for nganh in INDUSTRY_MAP
                if not industry_search(db, nganh, limit=10)
            ]
        finally:
            db.close()
        assert not rong, f"các ngành không truy xuất được gì: {rong}"


class TestVault:
    def test_phan_lon_file_vault_co_noi_dung(self):
        """314/314 file từng rỗng phần '## Nội dung' vì lỗi ghép đường dẫn UUID."""
        if not VAULT_DOCS.exists():
            pytest.skip("chưa có vault")
        files = list(VAULT_DOCS.glob("*.md"))
        if not files:
            pytest.skip("vault trống")
        co_noi_dung = 0
        for f in files:
            t = f.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r"##\s*Nội dung(.*?)(?=\n##\s|\Z)", t, re.S)
            if m and len(m.group(1).strip()) >= 50:
                co_noi_dung += 1
        assert co_noi_dung / len(files) > 0.5, \
            f"chỉ {co_noi_dung}/{len(files)} file có nội dung"

    def test_khong_con_ky_tu_xuong_dong_bi_escape(self):
        if not VAULT_DOCS.exists():
            pytest.skip("chưa có vault")
        dinh_loi = [
            f.name for f in VAULT_DOCS.glob("*.md")
            if "\\n- " in f.read_text(encoding="utf-8", errors="ignore")
        ]
        assert not dinh_loi, f"{len(dinh_loi)} file còn '\\n' nguyên văn, ví dụ {dinh_loi[:3]}"

    def test_khong_co_file_rong_o_goc_vault(self):
        """File rỗng ở gốc là dấu vết người dùng bấm vào wikilink gãy."""
        root = Path("Legal-Vault")
        if not root.exists():
            pytest.skip("chưa có vault")
        rong = [
            f.name for f in root.glob("*.md")
            if f.stat().st_size == 0
        ]
        assert not rong, f"file rỗng ở gốc vault: {rong}"


class TestVectorSearchThucTe:
    """Nhóm #1 — tìm kiếm ngữ nghĩa trên kho thật.

    Trước khi sửa: 0/6124 chunk có vector (sqlite-vec chưa cài, bảng khai 768
    chiều trong khi model 1536 chiều), nên "hybrid search" chỉ là BM25 thuần.
    """

    def test_co_vector_trong_kho(self):
        from src.rag.db_rag import HAS_VEC, RAGDatabase
        if not HAS_VEC:
            pytest.skip("chưa cài sqlite-vec")
        db = RAGDatabase()
        try:
            n = db.db.execute("SELECT COUNT(*) FROM legal_chunks_vec").fetchone()[0]
        finally:
            db.close()
        assert n > 0, "không có vector nào — tầng ngữ nghĩa vẫn chết"

    def test_cau_hoi_dien_dat_tu_nhien_tim_duoc_dieu_khoan(self):
        """Câu hỏi dùng từ ngữ khác luật — đúng chỗ BM25 bất lực.

        Đo thực tế: BM25 thuần trả 0 kết quả, hybrid trả 5 kết quả đều đúng
        về "tạm ngừng kinh doanh".
        """
        import src.config  # nạp .env
        from src.rag.db_rag import HAS_VEC, RAGDatabase
        from src.rag.embeddings_api import EmbeddingAPI
        from src.rag.hybrid_search import hybrid_search

        if not HAS_VEC:
            pytest.skip("chưa cài sqlite-vec")
        embedder = EmbeddingAPI()
        if not embedder.api_key:
            pytest.skip("chưa cấu hình khoá API nhúng")

        db = RAGDatabase()
        try:
            q = "doanh nghiệp phải làm gì khi muốn tạm ngừng kinh doanh"
            ket_qua = hybrid_search(db, query=q, limit=5, embedder=embedder)
            assert ket_qua, "hybrid search không trả về gì"
            assert any(r.vec_rank is not None for r in ket_qua), \
                "không kết quả nào đến từ tầng vector — hybrid vẫn chỉ là BM25"
        finally:
            db.close()
