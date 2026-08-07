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

        # Cột lọc: phải nằm ngay trong legal_chunks để điều kiện đi vào câu SQL.
        # Lọc sau khi đã lấy 100 kết quả về Python nghĩa là 100 chỗ đó có thể bị
        # văn bản đã hết hiệu lực chiếm sạch, lọc xong còn vài đoạn — và sau bao
        # đóng dẫn chiếu thì đó là tình huống mặc định chứ không phải ngoại lệ.
        self._add_chunk_columns([
            ("eff_state", "TEXT"),
            ("is_closure_node", "INTEGER"),
            ("hierarchy_level", "INTEGER"),
            ("is_vbqppl", "INTEGER"),
        ])

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
        # Điều kiện lọc mặc định của mọi truy xuất phục vụ báo cáo.
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_chunks_eff_state "
            "ON legal_chunks(eff_state, is_closure_node)"
        )

        # Graph table
        #
        # Khoá theo doc_key chứ KHÔNG theo số hiệu. Số hiệu chỉ duy nhất trong
        # phạm vi một cơ quan, nên khoá theo số hiệu làm hai văn bản của hai
        # tỉnh khác nhau gộp thành một cạnh — đã gặp thật với "64/2026/QĐ-UBND"
        # của Huế và của Tây Ninh cùng "Căn cứ" 72/2025/QH15.
        #
        # target_doc_key NULL khi đích chưa có trong kho, nên target_doc_num
        # cũng phải nằm trong khoá duy nhất; thiếu nó thì mọi cạnh treo của cùng
        # một nguồn sẽ gộp làm một.
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS legal_graph (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_doc_key TEXT NOT NULL,
                source_doc_num TEXT NOT NULL,
                target_doc_key TEXT,
                target_doc_num TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                confidence REAL DEFAULT 1.0
            )
        """)
        # Khoá duy nhất phải là CHỈ MỤC BIỂU THỨC, không phải ràng buộc UNIQUE
        # thường: SQL coi mỗi NULL là một giá trị khác nhau, nên UNIQUE(...,
        # target_doc_key, ...) hoàn toàn không có tác dụng với cạnh treo. Mà
        # cạnh treo chiếm 2.963/7.926 cạnh — mỗi lần đồng bộ lại chèn thêm một
        # bản sao, chạy hằng ngày thì đồ thị phình vô hạn. Đã xảy ra thật: một
        # lượt đồng bộ đẩy 7.926 cạnh thành 10.889.
        self.db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_canh ON legal_graph(
                source_doc_key, COALESCE(target_doc_key, ''),
                target_doc_num, relation_type
            )
        """)
        # Truy vết chiều ngược ("văn bản này bị ai tác động") là câu hỏi quan
        # trọng nhất khi thẩm định hiệu lực, và chỉ mục duy nhất không phủ nó.
        for col in ("target_doc_num", "source_doc_num", "target_doc_key"):
            self.db.execute(
                f"CREATE INDEX IF NOT EXISTS idx_graph_{col} ON legal_graph({col})"
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
                    eff_state=?, is_closure_node=?, hierarchy_level=?, is_vbqppl=?,
                    content_hash=?, updated_at=datetime('now')
                WHERE id=?
            """, (
                chunk_data.get("heading"), chunk_data.get("content"), chunk_data.get("char_count"),
                chunk_data.get("field_name"), chunk_data.get("field_code"), industries,
                chunk_data.get("eff_status"), chunk_data.get("issue_date"), chunk_data.get("doc_type"),
                chunk_data.get("agency_name"),
                chunk_data.get("eff_state"), chunk_data.get("is_closure_node"),
                chunk_data.get("hierarchy_level"), chunk_data.get("is_vbqppl"),
                chunk_data.get("content_hash"), existing["id"]
            ))
            if commit:
                self.db.commit()
            return existing["id"]
        else:
            cursor.execute("""
                INSERT INTO legal_chunks (
                    doc_id, doc_num, chunk_index, heading, content, char_count,
                    field_name, field_code, industries, eff_status, issue_date,
                    doc_type, agency_name,
                    eff_state, is_closure_node, hierarchy_level, is_vbqppl,
                    content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                chunk_data.get("doc_id"), chunk_data.get("doc_num"), chunk_data.get("chunk_index"),
                chunk_data.get("heading"), chunk_data.get("content"), chunk_data.get("char_count"),
                chunk_data.get("field_name"), chunk_data.get("field_code"), industries,
                chunk_data.get("eff_status"), chunk_data.get("issue_date"), chunk_data.get("doc_type"),
                chunk_data.get("agency_name"),
                chunk_data.get("eff_state"), chunk_data.get("is_closure_node"),
                chunk_data.get("hierarchy_level"), chunk_data.get("is_vbqppl"),
                chunk_data.get("content_hash")
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

    def upsert_graph_edge(self, source_doc_key: str, source_doc_num: str,
                          target_doc_num: str, relation_type: str,
                          target_doc_key: str | None = None,
                          confidence: float = 1.0, commit: bool = True):
        """Ghi một cạnh quan hệ, định danh hai đầu bằng doc_key.

        `source_doc_key` bắt buộc: đó là thứ phân biệt "64/2026/QĐ-UBND" của Huế
        với bản cùng số hiệu của Tây Ninh. `target_doc_key` được phép NULL vì
        văn bản đích có thể chưa có trong kho.
        """
        self.db.execute("""
            INSERT OR REPLACE INTO legal_graph
                (source_doc_key, source_doc_num, target_doc_key, target_doc_num,
                 relation_type, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (source_doc_key, source_doc_num, target_doc_key, target_doc_num,
              relation_type, confidence))
        if commit:
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

    def _add_chunk_columns(self, columns: List[tuple]) -> None:
        """Thêm cột vào legal_chunks nếu chưa có."""
        existing = {
            r[1] for r in self.db.execute("PRAGMA table_info(legal_chunks)")
        }
        for name, ddl in columns:
            if name not in existing:
                self.db.execute(f"ALTER TABLE legal_chunks ADD COLUMN {name} {ddl}")
                logger.info("legal_chunks: thêm cột %s", name)

    def build_chunk_filter(self, filters: Optional[Dict[str, Any]]) -> tuple:
        """(mệnh đề SQL, tham số) để lọc ngay trong câu truy vấn.

        Trả về chuỗi rỗng khi không có điều kiện nào, để bên gọi ghép thẳng vào
        câu SQL mà không phải xử lý trường hợp đặc biệt.
        """
        if not filters:
            return "", []

        clauses: List[str] = []
        params: List[Any] = []

        dead = filters.get("exclude_eff_states")
        if dead:
            # eff_state NULL nghĩa là chunk chưa được đánh dấu lại sau khi thêm
            # cột — giữ lại thay vì loại, vì loại sẽ làm rỗng kho ngay sau khi
            # nâng cấp mà chưa kịp reindex.
            placeholders = ",".join("?" * len(dead))
            clauses.append(
                f"(c.eff_state IS NULL OR c.eff_state NOT IN ({placeholders}))"
            )
            params.extend(dead)

        if filters.get("exclude_closure"):
            clauses.append("(c.is_closure_node IS NULL OR c.is_closure_node = 0)")

        if filters.get("only_vbqppl"):
            clauses.append("(c.is_vbqppl IS NULL OR c.is_vbqppl = 1)")

        max_level = filters.get("max_hierarchy_level")
        if max_level is not None:
            clauses.append("(c.hierarchy_level IS NULL OR c.hierarchy_level <= ?)")
            params.append(max_level)

        if filters.get("field_name"):
            clauses.append("c.field_name = ?")
            params.append(filters["field_name"])

        date_range = filters.get("date_range")
        if date_range:
            clauses.append("(c.issue_date IS NULL OR (c.issue_date >= ? AND c.issue_date <= ?))")
            params.extend(date_range)

        return (" AND " + " AND ".join(clauses)) if clauses else "", params

    def search_fts(
        self,
        query: str,
        limit: int = 100,
        operator: str = "AND",
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict]:
        """Tìm toàn văn, có lọc NGAY trong câu SQL.

        Lọc sau khi đã lấy `limit` kết quả về Python là sai về bản chất: `limit`
        chỗ đó bị văn bản không đủ điều kiện chiếm trước, lọc xong còn rất ít.
        Ghép điều kiện vào SQL thì `limit` áp dụng lên phần ĐÃ lọc.
        """
        match_expr = self.build_fts_query(query, operator=operator)
        if not match_expr:
            return []
        where_extra, params = self.build_chunk_filter(filters)
        try:
            cursor = self.db.execute(f"""
                SELECT f.rowid as id, f.rank
                FROM legal_chunks_fts f
                JOIN legal_chunks c ON c.id = f.rowid
                WHERE legal_chunks_fts MATCH ?{where_extra}
                ORDER BY f.rank
                LIMIT ?
            """, (match_expr, *params, limit))
            return [dict(r) for r in cursor.fetchall()]
        except sqlite3.OperationalError as e:
            # Không nuốt im lặng: trả rỗng mà không log thì không phân biệt được
            # "không có kết quả" với "truy vấn hỏng".
            logger.warning("FTS lỗi với biểu thức %r: %s", match_expr, e)
            return []

    # Nhánh vector không lọc trước được: vec0 phải trả đúng k láng giềng gần
    # nhất rồi mới join lọc. Lấy dư rồi cắt là cách duy nhất để sau khi lọc vẫn
    # còn đủ kết quả.
    VECTOR_OVERFETCH = 4

    def search_vector(
        self,
        embedding: List[float],
        limit: int = 100,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict]:
        if not HAS_VEC:
            return []
        embedding_bytes = struct.pack(f"<{len(embedding)}f", *embedding)
        where_extra, params = self.build_chunk_filter(filters)
        fetch = limit * self.VECTOR_OVERFETCH if where_extra else limit
        cursor = self.db.execute(f"""
            SELECT v.id AS id, v.distance AS distance FROM (
                SELECT rowid AS id, distance
                FROM legal_chunks_vec
                WHERE embedding MATCH ?
                ORDER BY distance
                LIMIT ?
            ) v
            JOIN legal_chunks c ON c.id = v.id
            WHERE 1=1{where_extra}
            ORDER BY v.distance
            LIMIT ?
        """, (embedding_bytes, fetch, *params, limit))
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
