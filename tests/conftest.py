"""Fixtures dùng chung. Mọi test đều chạy trên DB tạm, không đụng data/ thật."""
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.db_rag import RAGDatabase  # noqa: E402
from src.storage.models import Base  # noqa: E402


@pytest.fixture
def rag_db(tmp_path):
    """RAGDatabase trống trên file tạm."""
    db = RAGDatabase(db_path=tmp_path / "rag_test.db")
    yield db
    db.close()


@pytest.fixture
def master_session(tmp_path):
    """Session SQLAlchemy trên SQLite tạm với schema đầy đủ."""
    engine = create_engine(f"sqlite:///{tmp_path / 'master_test.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def chunk_factory(rag_db):
    """Tạo nhanh chunk trong rag.db test."""
    def _make(doc_num: str, content: str, heading: str = "Điều 1. Thử nghiệm", **kw):
        data = {
            "doc_id": kw.get("doc_id"),
            "doc_num": doc_num,
            "chunk_index": kw.get("chunk_index", 0),
            "heading": heading,
            "content": content,
            "char_count": len(content),
            "field_name": kw.get("field_name"),
            "field_code": kw.get("field_code"),
            "industries": kw.get("industries", []),
            "eff_status": kw.get("eff_status"),
            "issue_date": kw.get("issue_date"),
            "doc_type": kw.get("doc_type"),
            "agency_name": kw.get("agency_name"),
            "content_hash": kw.get("content_hash", f"h-{doc_num}-{kw.get('chunk_index', 0)}"),
        }
        return rag_db.upsert_chunk(data)
    return _make


@pytest.fixture
def edge_factory(rag_db):
    """Tạo nhanh cạnh quan hệ trong legal_graph test."""
    def _make(source: str, target: str, relation: str):
        rag_db.db.execute(
            """INSERT OR REPLACE INTO legal_graph
               (source_doc_num, target_doc_num, relation_type, confidence)
               VALUES (?, ?, ?, 1.0)""",
            (source, target, relation),
        )
        rag_db.db.commit()
    return _make
