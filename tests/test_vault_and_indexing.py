"""Đề xuất #4 — ghép đường dẫn UUID ↔ số hiệu.

Lỗi gốc: data/metadata/ đặt tên theo số hiệu, data/clean_text/ và data/chunks/
đặt tên theo UUID. Code ghép đường dẫn từ tên file metadata nên luôn trượt:
314/314 file vault rỗng nội dung, 6124/6124 chunk mất sạch metadata.
"""
import json
from pathlib import Path

from src.obsidian.vault_exporter import export_document_to_md, load_clean_text, sanitize_filename


class TestLoadCleanText:
    def test_dung_clean_text_path_trong_metadata(self, tmp_path):
        clean_dir = tmp_path / "clean_text"
        clean_dir.mkdir()
        uuid_file = clean_dir / "0034b890-7637-11f1-bf90-3df95518d6f5.md"
        uuid_file.write_text("Điều 1. Nội dung thật của văn bản", encoding="utf-8")

        doc_data = {"doc_num": "04/2026/NQ-HĐND", "clean_text_path": str(uuid_file)}
        assert "Nội dung thật" in load_clean_text(doc_data, clean_dir)

    def test_duong_dan_tuong_doi_van_doc_duoc(self, tmp_path, monkeypatch):
        clean_dir = tmp_path / "clean_text"
        clean_dir.mkdir()
        (clean_dir / "abc.md").write_text("Nội dung tương đối", encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        doc_data = {"doc_num": "X", "clean_text_path": "clean_text/abc.md"}
        assert "Nội dung tương đối" in load_clean_text(doc_data, clean_dir)

    def test_ten_file_doi_cho_van_tim_duoc_qua_thu_muc(self, tmp_path):
        """clean_text_path trỏ sai thư mục nhưng tên file đúng — vẫn phải tìm ra."""
        clean_dir = tmp_path / "clean_text"
        clean_dir.mkdir()
        (clean_dir / "xyz.md").write_text("Nội dung", encoding="utf-8")
        doc_data = {"doc_num": "X", "clean_text_path": "/duong/dan/cu/xyz.md"}
        assert "Nội dung" in load_clean_text(doc_data, clean_dir)

    def test_du_phong_theo_moj_id(self, tmp_path):
        clean_dir = tmp_path / "clean_text"
        clean_dir.mkdir()
        (clean_dir / "uuid-123.md").write_text("Qua moj_id", encoding="utf-8")
        assert "Qua moj_id" in load_clean_text({"moj_id": "uuid-123"}, clean_dir)

    def test_khong_co_thi_tra_rong_chu_khong_no(self, tmp_path):
        clean_dir = tmp_path / "clean_text"
        clean_dir.mkdir()
        assert load_clean_text({"doc_num": "99/2026/NĐ-CP"}, clean_dir) == ""

    def test_KHONG_doan_duong_dan_tu_ten_file_metadata(self, tmp_path):
        """Chính là lỗi cũ: suy tên file clean_text từ tên file metadata."""
        clean_dir = tmp_path / "clean_text"
        clean_dir.mkdir()
        (clean_dir / "04_2026_NQ-HĐND.md").write_text("KHÔNG ĐƯỢC LẤY FILE NÀY", encoding="utf-8")
        (clean_dir / "uuid-that.md").write_text("nội dung đúng", encoding="utf-8")
        doc_data = {
            "doc_num": "04/2026/NQ-HĐND",
            "clean_text_path": str(clean_dir / "uuid-that.md"),
        }
        assert load_clean_text(doc_data, clean_dir) == "nội dung đúng"


class TestExportDocumentToMd:
    def _doc(self, **kw):
        d = {
            "doc_num": "04/2026/NQ-HĐND",
            "title": "Nghị quyết thử nghiệm",
            "doc_type": "Nghị quyết",
            "field_name": "Thương mại",
        }
        d.update(kw)
        return d

    def test_noi_dung_van_ban_co_trong_file(self):
        md = export_document_to_md(self._doc(), "Điều 1. Phạm vi điều chỉnh", [])
        assert "Điều 1. Phạm vi điều chỉnh" in md

    def test_danh_sach_lien_quan_xuong_dong_that(self):
        """Bản cũ dùng "\\\\n" nên 235/314 file hiện ký tự \\n nguyên văn."""
        refs = [
            {"relation_type": "Căn cứ", "target_doc_num": "72/2025/QH15"},
            {"relation_type": "Bãi bỏ", "target_doc_num": "88/2015/QH13"},
        ]
        md = export_document_to_md(self._doc(), "nội dung", refs)
        assert "\\n" not in md, "vẫn còn ký tự xuống dòng bị escape"
        assert "- Căn cứ: [[72-2025-QH15]]\n- Bãi bỏ: [[88-2015-QH13]]" in md

    def test_tag_khong_con_khoang_trang(self):
        """re.sub(r'\\\\s+') khớp 'gạch chéo + s', không phải khoảng trắng."""
        md = export_document_to_md(self._doc(doc_type="Nghị quyết"), "x", [])
        assert '"Nghị_quyết"' in md
        assert '"Nghị quyết"' not in md.split("tags:")[1].split("\n")[0]

    def test_so_hieu_co_dau_gach_cheo_thanh_ten_file_hop_le(self):
        assert sanitize_filename("89/2025/QH15") == "89-2025-QH15"
        assert "/" not in sanitize_filename("23/2026/VBHN-TT-BTC")

    def test_frontmatter_yaml_hop_le(self):
        import yaml
        md = export_document_to_md(self._doc(title='Nghị quyết có "dấu ngoặc kép"'), "x", [])
        fm = md.split("---")[1]
        data = yaml.safe_load(fm)
        assert data["doc_num"] == "04/2026/NQ-HĐND"


class TestRagIndexerMetadataMapping:
    def test_khop_metadata_bang_doc_num_khong_phai_ten_file(self, tmp_path, rag_db, monkeypatch):
        """Chunk đặt tên UUID, metadata đặt tên số hiệu — phải khớp qua doc_num."""
        data_dir = tmp_path
        (data_dir / "chunks").mkdir()
        (data_dir / "metadata").mkdir()

        (data_dir / "chunks" / "0034b890-uuid_chunks.json").write_text(
            json.dumps([{
                "doc_num": "04/2026/NQ-HĐND", "chunk_index": 0,
                "heading": "Điều 1", "content": "Nội dung điều 1",
            }], ensure_ascii=False), encoding="utf-8")

        (data_dir / "metadata" / "04_2026_NQ-HĐND.json").write_text(
            json.dumps({
                "doc_num": "04/2026/NQ-HĐND", "title": "NQ thử",
                "eff_status": "Còn hiệu lực", "issue_date": "2026-01-15",
                "doc_type": "Nghị quyết", "agency_name": "HĐND tỉnh",
            }, ensure_ascii=False), encoding="utf-8")

        import src.rag.rag_indexer as ri
        monkeypatch.setattr(ri, "DATA_DIR", data_dir)
        ri.index_from_phase1(None, rag_db)

        row = rag_db.db.execute(
            "SELECT eff_status, issue_date, doc_type, agency_name FROM legal_chunks WHERE doc_num=?",
            ("04/2026/NQ-HĐND",),
        ).fetchone()
        assert row["eff_status"] == "Còn hiệu lực", "metadata vẫn NULL — mapping còn hỏng"
        assert row["issue_date"] == "2026-01-15"
        assert row["doc_type"] == "Nghị quyết"

    def test_metadata_duoc_lam_moi_du_noi_dung_khong_doi(self, tmp_path, rag_db, monkeypatch):
        """Trạng thái hiệu lực đổi mà điều khoản giữ nguyên là ca phổ biến nhất."""
        data_dir = tmp_path
        (data_dir / "chunks").mkdir()
        (data_dir / "metadata").mkdir()
        chunk_file = data_dir / "chunks" / "uuid_chunks.json"
        meta_file = data_dir / "metadata" / "m.json"

        chunk_file.write_text(json.dumps([{
            "doc_num": "05/2026/NĐ-CP", "chunk_index": 0,
            "heading": "Điều 1", "content": "Nội dung không đổi",
        }], ensure_ascii=False), encoding="utf-8")

        import src.rag.rag_indexer as ri
        monkeypatch.setattr(ri, "DATA_DIR", data_dir)

        meta_file.write_text(json.dumps({
            "doc_num": "05/2026/NĐ-CP", "eff_status": "Còn hiệu lực",
        }, ensure_ascii=False), encoding="utf-8")
        ri.index_from_phase1(None, rag_db)

        meta_file.write_text(json.dumps({
            "doc_num": "05/2026/NĐ-CP", "eff_status": "Hết hiệu lực toàn bộ",
        }, ensure_ascii=False), encoding="utf-8")
        ri.index_from_phase1(None, rag_db)

        row = rag_db.db.execute(
            "SELECT eff_status FROM legal_chunks WHERE doc_num=?", ("05/2026/NĐ-CP",)
        ).fetchone()
        assert row["eff_status"] == "Hết hiệu lực toàn bộ", "metadata bị kẹt ở giá trị cũ"
