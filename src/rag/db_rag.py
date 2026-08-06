import re
import sqlite3
import json
import logging
import struct
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    import sqlite_vec
    HAS_VEC = True
except ImportError:
    HAS_VEC = False

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

DEFAULT_RAG_DB_PATH = DATA_DIR / "rag.db"

class RAGDatabase:
    def __init__(self, db_path: Path = DEFAULT_RAG_DB_PATH):
        self.db_path = db_path

        # Use check_same_thread=False for easy concurrent access
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        
        if HAS_VEC:
            self.db.enable_load_extension(True)
            sqlite_vec.load(self.db)
            self.db.enable_load_extension(False)
            
        self.db.row_factory = sqlite3.Row
        
        # Optimize performance
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA synchronous = NORMAL")
        self.db.execute("PRAGMA cache_size = -64000")
        
        self.init_schema()

    def init_schema(self):
        # Master chunks table
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS legal_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT,
                doc_num TEXT,
                chunk_index INTEGER,
                heading TEXT,
                content TEXT,
                char_count INTEGER,
                field_name TEXT,
                field_code INTEGER,
                industries TEXT,
                eff_status TEXT,
                issue_date TEXT,
                doc_type TEXT,
                agency_name TEXT,
                content_hash TEXT,
                usage_count INTEGER DEFAULT 0,
                last_used_date TEXT,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)

        # FTS5 table
        fts_check = self.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='legal_chunks_fts'"
        ).fetchone()
        
        if not fts_check:
            self.db.execute("""
                CREATE VIRTUAL TABLE legal_chunks_fts USING fts5(
                    doc_num, heading, content,
                    content='legal_chunks',
                    content_rowid='id',
                    tokenize='unicode61 remove_diacritics 2'
                )
            """)
            
            # Triggers for FTS
            self.db.execute("""
                CREATE TRIGGER chunks_ai AFTER INSERT ON legal_chunks BEGIN
                    INSERT INTO legal_chunks_fts(rowid, doc_num, heading, content)
                    VALUES (new.id, new.doc_num, new.heading, new.content);
                END
            """)
            self.db.execute("""
                CREATE TRIGGER chunks_ad AFTER DELETE ON legal_chunks BEGIN
                    INSERT INTO legal_chunks_fts(legal_chunks_fts, rowid, doc_num, heading, content)
                    VALUES ('delete', old.id, old.doc_num, old.heading, old.content);
                END
            """)
            self.db.execute("""
                CREATE TRIGGER chunks_au AFTER UPDATE ON legal_chunks BEGIN
                    INSERT INTO legal_chunks_fts(legal_chunks_fts, rowid, doc_num, heading, content)
                    VALUES ('delete', old.id, old.doc_num, old.heading, old.content);
                    INSERT INTO legal_chunks_fts(rowid, doc_num, heading, content)
                    VALUES (new.id, new.doc_num, new.heading, new.content);
                END
            """)

        # Vector table — số chiều lấy từ model đang dùng, không hardcode.
        # Bảng cũ khai float[768] còn model mặc định là 1536 chiều nên mọi lần
        # ghi vector đều fail; đó là lý do tầng vector chưa từng có dữ liệu.
        if HAS_VEC:
            from src.rag.embeddings_api import embedding_dimension

            dim = embedding_dimension()
            row = self.db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='legal_chunks_vec'"
            ).fetchone()
            if row is None:
                self.db.execute(
                    f"CREATE VIRTUAL TABLE legal_chunks_vec USING vec0(embedding float[{dim}])"
                )
            elif f"float[{dim}]" not in (row["sql"] or ""):
                logger.warning(
                    "legal_chunks_vec đang khai %s nhưng model hiện tại cần %d chiều — "
                    "dựng lại bảng, cần nhúng lại toàn bộ.",
                    (row["sql"] or "").split("vec0(")[-1].rstrip(")"), dim,
                )
                self.db.execute("DROP TABLE legal_chunks_vec")
                self.db.execute(
                    f"CREATE VIRTUAL TABLE legal_chunks_vec USING vec0(embedding float[{dim}])"
                )
        
        # Tra theo (doc_num, chunk_index) chạy ở mỗi lần upsert; thiếu index thì
        # mỗi đoạn là một lần quét toàn bảng 25.000 dòng.
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_chunks_docnum_idx "
            "ON legal_chunks(doc_num, chunk_index)"
        )

        # Graph table
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS legal_graph (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_doc_num TEXT,
                target_doc_num TEXT,
                relation_type TEXT,
                confidence REAL DEFAULT 1.0,
                UNIQUE(source_doc_num, target_doc_num, relation_type)
            )
        """)
        # Chỉ mục UNIQUE tự sinh chỉ phủ tiền tố source_doc_num, nên truy vết
        # chiều ngược ("văn bản này bị ai tác động") vẫn phải quét toàn bảng.
        # Phải đặt SAU khi bảng đã tồn tại.
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_graph_target ON legal_graph(target_doc_num)"
        )
        self.db.commit()

    def upsert_chunk(self, chunk_data: dict, commit: bool = True) -> int:
        """Ghi một đoạn. Đặt commit=False khi nạp hàng loạt.

        Commit từng đoạn biến mỗi chunk thành một transaction riêng — với 25.000
        đoạn thì phần lớn thời gian index là chờ fsync chứ không phải xử lý.
        """
        cursor = self.db.cursor()
        
        existing = cursor.execute(
            "SELECT id FROM legal_chunks WHERE doc_num = ? AND chunk_index = ?", 
            (chunk_data["doc_num"], chunk_data["chunk_index"])
        ).fetchone()

        industries = chunk_data.get("industries", [])
        if isinstance(industries, list):
            industries = json.dumps(industries, ensure_ascii=False)

        if existing:
            cursor.execute("""
                UPDATE legal_chunks 
                SET heading=?, content=?, char_count=?, field_name=?, field_code=?, 
                    industries=?, eff_status=?, issue_date=?, doc_type=?, agency_name=?, 
                    content_hash=?, updated_at=datetime('now')
                WHERE id=?
            """, (
                chunk_data.get("heading"), chunk_data.get("content"), chunk_data.get("char_count"),
                chunk_data.get("field_name"), chunk_data.get("field_code"), industries,
                chunk_data.get("eff_status"), chunk_data.get("issue_date"), chunk_data.get("doc_type"),
                chunk_data.get("agency_name"), chunk_data.get("content_hash"), existing["id"]
            ))
            if commit:
                self.db.commit()
            return existing["id"]
        else:
            cursor.execute("""
                INSERT INTO legal_chunks (
                    doc_id, doc_num, chunk_index, heading, content, char_count, 
                    field_name, field_code, industries, eff_status, issue_date, 
                    doc_type, agency_name, content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                chunk_data.get("doc_id"), chunk_data.get("doc_num"), chunk_data.get("chunk_index"),
                chunk_data.get("heading"), chunk_data.get("content"), chunk_data.get("char_count"),
                chunk_data.get("field_name"), chunk_data.get("field_code"), industries,
                chunk_data.get("eff_status"), chunk_data.get("issue_date"), chunk_data.get("doc_type"),
                chunk_data.get("agency_name"), chunk_data.get("content_hash")
            ))
            if commit:
                self.db.commit()
            return cursor.lastrowid

    def upsert_vector(self, chunk_id: int, embedding: List[float], commit: bool = True):
        if not HAS_VEC:
            return
        from src.rag.embeddings_api import embedding_dimension

        # Chặn ngay tại chỗ thay vì để sqlite-vec ném lỗi khó truy: lệch chiều là
        # dấu hiệu model nhúng đã đổi mà bảng chưa được dựng lại.
        expected = embedding_dimension()
        if len(embedding) != expected:
            raise ValueError(
                f"Vector {len(embedding)} chiều nhưng bảng cần {expected} — "
                f"model nhúng và schema không khớp."
            )

        # Pack float list into bytes required by sqlite-vec
        embedding_bytes = struct.pack(f"<{len(embedding)}f", *embedding)
        cursor = self.db.cursor()
        cursor.execute("DELETE FROM legal_chunks_vec WHERE rowid = ?", (chunk_id,))
        cursor.execute("INSERT INTO legal_chunks_vec (rowid, embedding) VALUES (?, ?)", (chunk_id, embedding_bytes))
        # Commit từng vector khiến mỗi chunk là một transaction riêng; cho phép
        # gộp khi nhúng hàng loạt.
        if commit:
            self.db.commit()

    def upsert_graph_edge(self, source_doc_num: str, target_doc_num: str, relation_type: str, confidence: float = 1.0):
        self.db.execute("""
            INSERT OR REPLACE INTO legal_graph (source_doc_num, target_doc_num, relation_type, confidence)
            VALUES (?, ?, ?, ?)
        """, (source_doc_num, target_doc_num, relation_type, confidence))
        self.db.commit()

    @staticmethod
    def build_fts_query(query: str, operator: str = "AND") -> str:
        """Chuyển câu người dùng thành biểu thức MATCH an toàn cho FTS5.

        Ký tự như '&', ':', '"', '*', '^' và các từ AND/OR/NOT/NEAR bị FTS5 hiểu
        là cú pháp. Trước đây câu 'Xây dựng & Bất động sản' ném syntax error rồi
        rơi vào nhánh dự phòng tìm CỤM TỪ CHÍNH XÁC — trả về 0 kết quả trong khi
        bỏ dấu '&' đi thì có 53. Ở đây mỗi token được bọc ngoặc kép nên mọi ký tự
        đều là dữ liệu, không còn là toán tử.
        """
        tokens = re.findall(r"\w+", query or "", flags=re.UNICODE)
        # Người dùng gõ "thuế OR lao động" là có ý dùng toán tử; giữ lại như một
        # token dữ liệu sẽ ra 0 kết quả vì không văn bản nào chứa chữ "OR".
        tokens = [t for t in tokens if t not in ("AND", "OR", "NOT", "NEAR")]
        if not tokens:
            return ""
        quoted = [f'"{t}"' for t in tokens]
        return f" {operator} ".join(quoted)

    def search_fts(self, query: str, limit: int = 100, operator: str = "AND") -> List[Dict]:
        match_expr = self.build_fts_query(query, operator=operator)
        if not match_expr:
            return []
        try:
            cursor = self.db.execute("""
                SELECT rowid as id, rank
                FROM legal_chunks_fts
                WHERE legal_chunks_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (match_expr, limit))
            return [dict(r) for r in cursor.fetchall()]
        except sqlite3.OperationalError as e:
            # Không nuốt im lặng: trả rỗng mà không log thì không phân biệt được
            # "không có kết quả" với "truy vấn hỏng".
            logger.warning("FTS lỗi với biểu thức %r: %s", match_expr, e)
            return []

    def search_vector(self, embedding: List[float], limit: int = 100) -> List[Dict]:
        if not HAS_VEC:
            return []
        embedding_bytes = struct.pack(f"<{len(embedding)}f", *embedding)
        cursor = self.db.execute("""
            SELECT rowid as id, distance 
            FROM legal_chunks_vec 
            WHERE embedding MATCH ? 
            ORDER BY distance 
            LIMIT ?
        """, (embedding_bytes, limit))
        return [dict(r) for r in cursor.fetchall()]

    def get_edges(self, doc_num: str) -> List[Dict]:
        cursor = self.db.execute("""
            SELECT * FROM legal_graph 
            WHERE source_doc_num = ? OR target_doc_num = ?
        """, (doc_num, doc_num))
        return [dict(r) for r in cursor.fetchall()]
        
    def get_chunk(self, chunk_id: int) -> Optional[Dict]:
        cursor = self.db.execute("SELECT * FROM legal_chunks WHERE id = ?", (chunk_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
        
    def get_max_usage_count(self) -> int:
        cursor = self.db.execute("SELECT MAX(usage_count) as m FROM legal_chunks")
        row = cursor.fetchone()
        return row['m'] if row and row['m'] else 1
        
    def track_usage(self, chunk_id: int):
        self.db.execute("""
            UPDATE legal_chunks 
            SET usage_count = usage_count + 1, last_used_date = datetime('now') 
            WHERE id = ?
        """, (chunk_id,))
        self.db.commit()

    def close(self):
        self.db.close()
