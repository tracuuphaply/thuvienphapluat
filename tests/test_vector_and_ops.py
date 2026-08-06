"""Nhóm #1 (vector search) và #4 (vận hành).

Lỗi gốc:
  - sqlite-vec chưa cài và bảng khai float[768] trong khi model mặc định là
    1536 chiều → tầng vector chưa từng ghi được một dòng nào.
  - Không có khoá chống chạy chồng, không ghi log ra file, backup bỏ quên
    rag.db 22MB, nguồn chết vẫn báo SUCCESS.
"""
import logging
import sqlite3
from pathlib import Path

import pytest

from src.rag.db_rag import HAS_VEC, RAGDatabase
from src.rag.embeddings_api import (
    EMBEDDING_DIMENSIONS,
    active_embedding_model,
    embedding_dimension,
)


class TestSoChieuNhung:
    def test_sqlite_vec_da_cai(self):
        assert HAS_VEC, "sqlite-vec chưa cài — tầng vector không chạy được"

    def test_chieu_khop_voi_model_dang_dung(self, monkeypatch):
        monkeypatch.setenv("V98_API_KEY", "x")
        monkeypatch.delenv("EMBEDDING_DIM", raising=False)
        monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
        assert active_embedding_model() == "text-embedding-3-small"
        assert embedding_dimension() == 1536

    def test_model_gemini_cho_768(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_MODEL", "text-embedding-004")
        monkeypatch.delenv("EMBEDDING_DIM", raising=False)
        assert embedding_dimension() == 768

    def test_model_la_thi_bao_loi_chu_khong_doan(self, monkeypatch):
        """Đoán số chiều sai chính là nguyên nhân tầng vector chết âm thầm."""
        monkeypatch.setenv("EMBEDDING_MODEL", "model-khong-biet")
        monkeypatch.delenv("EMBEDDING_DIM", raising=False)
        with pytest.raises(ValueError, match="Chưa biết số chiều"):
            embedding_dimension()

    def test_ep_bang_bien_moi_truong(self, monkeypatch):
        monkeypatch.setenv("EMBEDDING_DIM", "256")
        assert embedding_dimension() == 256

    def test_moi_model_khai_bao_deu_co_so_chieu_duong(self):
        for model, dim in EMBEDDING_DIMENSIONS.items():
            assert dim > 0, model


@pytest.mark.skipif(not HAS_VEC, reason="cần sqlite-vec")
class TestBangVector:
    def test_bang_duoc_tao_dung_so_chieu(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EMBEDDING_DIM", "1536")
        db = RAGDatabase(db_path=tmp_path / "v.db")
        try:
            sql = db.db.execute(
                "SELECT sql FROM sqlite_master WHERE name='legal_chunks_vec'"
            ).fetchone()["sql"]
            assert "float[1536]" in sql
        finally:
            db.close()

    def test_vector_lech_chieu_bi_tu_choi(self, tmp_path, monkeypatch, chunk_factory):
        """Ghi vector sai chiều phải nổ ngay, không được im lặng bỏ qua."""
        monkeypatch.setenv("EMBEDDING_DIM", "1536")
        db = RAGDatabase(db_path=tmp_path / "v2.db")
        try:
            cid = db.upsert_chunk({
                "doc_id": None, "doc_num": "1/2026/NĐ-CP", "chunk_index": 0,
                "heading": "Điều 1", "content": "x", "char_count": 1,
                "field_name": None, "field_code": None, "industries": [],
                "eff_status": None, "issue_date": None, "doc_type": None,
                "agency_name": None, "content_hash": "h1",
            })
            with pytest.raises(ValueError, match="chiều"):
                db.upsert_vector(cid, [0.1] * 768)
        finally:
            db.close()

    def test_ghi_va_tim_lai_duoc_vector(self, tmp_path, monkeypatch):
        monkeypatch.setenv("EMBEDDING_DIM", "4")
        db = RAGDatabase(db_path=tmp_path / "v3.db")
        try:
            cid = db.upsert_chunk({
                "doc_id": None, "doc_num": "2/2026/NĐ-CP", "chunk_index": 0,
                "heading": "Điều 1", "content": "nội dung", "char_count": 8,
                "field_name": None, "field_code": None, "industries": [],
                "eff_status": None, "issue_date": None, "doc_type": None,
                "agency_name": None, "content_hash": "h2",
            })
            db.upsert_vector(cid, [1.0, 0.0, 0.0, 0.0])
            hits = db.search_vector([1.0, 0.0, 0.0, 0.0], limit=5)
            assert hits and hits[0]["id"] == cid
        finally:
            db.close()

    def test_doi_so_chieu_thi_bang_duoc_dung_lai(self, tmp_path, monkeypatch):
        p = tmp_path / "v4.db"
        monkeypatch.setenv("EMBEDDING_DIM", "4")
        RAGDatabase(db_path=p).close()
        monkeypatch.setenv("EMBEDDING_DIM", "8")
        db = RAGDatabase(db_path=p)
        try:
            sql = db.db.execute(
                "SELECT sql FROM sqlite_master WHERE name='legal_chunks_vec'"
            ).fetchone()["sql"]
            assert "float[8]" in sql
        finally:
            db.close()


class TestEmbedderDuocTruyenXuong:
    """Không truyền embedder thì nhánh vector không bao giờ chạy.

    hybrid_search yêu cầu `and embedder` mới gọi search_vector, nên dù đã cài
    sqlite-vec và nhúng đủ 6124 vector, thiếu tham số này là hybrid thoái hoá
    thành BM25 thuần — đúng lỗi ban đầu.
    """

    def test_report_generator_tu_tao_embedder(self):
        src = Path("src/rag/report_generator.py").read_text(encoding="utf-8")
        assert "_default_embedder()" in src
        assert "embedder=embedder" in src

    def test_telegram_search_truyen_embedder(self):
        src = Path("src/notification/telegram_bot_server.py").read_text(encoding="utf-8")
        idx = src.find("hybrid_search(rag_db, query=query")
        assert idx > 0
        assert "embedder=" in src[idx:idx + 200], "/search chưa truyền embedder"

    def test_khong_co_khoa_thi_tra_none_chu_khong_no(self, monkeypatch):
        from src.rag import report_generator as rg
        for var in ("V98_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        assert rg._default_embedder() is None


class TestVanHanh:
    def test_khoa_chan_chay_chong(self):
        from src.main import pipeline_lock
        with pipeline_lock():
            with pytest.raises(RuntimeError, match="đang giữ"):
                with pipeline_lock():
                    pass

    def test_khoa_duoc_nha_sau_khi_thoat(self):
        from src.main import pipeline_lock
        with pipeline_lock():
            pass
        with pipeline_lock():
            pass  # lấy lại được nghĩa là đã nhả đúng

    def test_log_duoc_ghi_ra_file(self):
        from src.config import DATA_DIR
        from src.main import setup_logging
        setup_logging()
        handlers = logging.getLogger().handlers
        paths = [
            Path(h.baseFilename) for h in handlers if hasattr(h, "baseFilename")
        ]
        assert paths, "không có handler nào ghi ra file — mất log khi đóng terminal"
        assert any(p.parent == DATA_DIR / "logs" for p in paths)

    def test_backup_bao_gom_rag_db_va_san_pham(self):
        from src.config import DATA_DIR, PROJECT_ROOT
        from src.utils.backup import BACKUP_TARGETS
        for cần in ("metadata", "clean_text", "chunks"):
            assert DATA_DIR / cần in BACKUP_TARGETS, f"backup bỏ quên data/{cần}"
        assert PROJECT_ROOT / "Legal-Vault" in BACKUP_TARGETS

    def test_backup_dung_vacuum_into_khong_copy_tho(self):
        """Copy byte thô file .db đang mở có thể tạo bản sao rách và mất WAL."""
        src = Path("src/utils/backup.py").read_text(encoding="utf-8")
        assert "VACUUM INTO" in src

    def test_nguon_chet_khong_con_bao_SUCCESS(self):
        src = Path("src/main.py").read_text(encoding="utf-8")
        idx = src.find("Cả TVPL lẫn MOJ đều không trả về")
        assert idx > 0, "thiếu nhánh xử lý mất nguồn"
        assert 'status="FAILED"' in src[idx:idx + 700]
        assert "send_error_alert" in src[idx:idx + 900]

    def test_run_daily_khong_bo_backup_khi_pipeline_loi(self):
        sh = Path("scripts/run_daily.sh").read_text(encoding="utf-8")
        # Chỉ xét dòng lệnh thật, bỏ qua dòng chú thích giải thích vì sao không dùng -e
        set_lines = [
            ln.strip() for ln in sh.splitlines()
            if ln.strip().startswith("set -")
        ]
        assert set_lines, "script không đặt tuỳ chọn shell nào"
        for ln in set_lines:
            assert "e" not in ln.split()[1].lstrip("-"), \
                f"{ln!r} bật -e nên pipeline lỗi sẽ bỏ luôn bước backup"
        assert "src.utils.backup" in sh

    def test_run_daily_co_dong_bo_vault(self):
        """run_pipeline() không tự sync vault; thiếu bước này vault không bao giờ cập nhật."""
        sh = Path("scripts/run_daily.sh").read_text(encoding="utf-8")
        assert "--sync-vault-only" in sh
        assert "--sync-rag-only" in sh
