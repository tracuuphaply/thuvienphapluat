"""Cổng kiểm trích dẫn — chặn số hiệu BỊA, không chặn số hiệu có thật.

Bài học đắt: "không có trong kho" từng bị đánh đồng với "bịa". Nhưng một quyết
định mới bãi bỏ văn bản cũ PHẢI gọi tên văn bản cũ, mà kho chỉ có văn bản từ
cuối 2025 — số hiệu cũ có thật, nằm trong toàn văn nguồn, mô hình chép lại chứ
không bịa. `extra_allowed` mở đúng nhóm đó mà vẫn chặn số bịa thật sự.
"""
import sqlite3

import pytest

from src.rag.citation_check import check_citations, extract_doc_nums


@pytest.fixture
def docs_db(tmp_path):
    """DB tạm chỉ có bảng documents với vài số hiệu."""
    path = tmp_path / "legal_docs.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE documents (doc_num TEXT)")
    conn.executemany("INSERT INTO documents (doc_num) VALUES (?)",
                     [("301/2026/NĐ-CP",), ("47/2026/QĐ-UBND",)])
    conn.commit()
    conn.close()
    return path


class TestExtractDocNums:
    def test_bat_dung_dinh_dang_tinh(self):
        nums = extract_doc_nums("Bãi bỏ Quyết định 18/2016/QĐ-UBND và 12/2017/QĐ-UBND.")
        assert "18/2016/QĐ-UBND" in nums
        assert "12/2017/QĐ-UBND" in nums

    def test_khong_nuot_ngay_thang(self):
        assert extract_doc_nums("ban hành ngày 03/8") == []


class TestCitationGate:
    def test_so_hieu_trong_kho_thi_qua(self, docs_db):
        r = check_citations("Theo Nghị định 301/2026/NĐ-CP.", db_path=docs_db)
        assert r.ok and r.found == ["301/2026/NĐ-CP"]

    def test_so_hieu_la_bi_chan(self, docs_db):
        r = check_citations("Theo Nghị định 999/2099/NĐ-CP.", db_path=docs_db)
        assert not r.ok and "999/2099/NĐ-CP" in r.missing

    def test_extra_allowed_mo_cho_van_ban_cu(self, docs_db):
        """Số hiệu văn bản cũ bị bãi bỏ — có trong nguồn, không có trong kho."""
        r = check_citations(
            "Quyết định 47/2026/QĐ-UBND bãi bỏ Quyết định 18/2016/QĐ-UBND.",
            db_path=docs_db, extra_allowed={"18/2016/QĐ-UBND"})
        assert r.ok, r.missing
        assert "18/2016/QĐ-UBND" in r.found

    def test_extra_allowed_khong_cuu_so_bia(self, docs_db):
        """Nới cho văn bản cũ không được biến cổng thành vô dụng: số KHÔNG có

        trong nguồn vẫn bị chặn.
        """
        r = check_citations(
            "Bãi bỏ 18/2016/QĐ-UBND; và viện dẫn 66/2099/NQ-CP.",
            db_path=docs_db, extra_allowed={"18/2016/QĐ-UBND"})
        assert not r.ok
        assert "66/2099/NQ-CP" in r.missing
        assert "18/2016/QĐ-UBND" in r.found

    def test_extra_allowed_chuan_hoa_dau_phan_cach(self, docs_db):
        """"18-2016-QĐ-UBND" trong báo cáo khớp "18/2016/QĐ-UBND" trong allowlist."""
        r = check_citations(
            "Bãi bỏ 18-2016-QĐ-UBND.",
            db_path=docs_db, extra_allowed={"18/2016/QĐ-UBND"})
        assert r.ok, r.missing

    def test_bo_dau_D_khop_ND_voi_NghiDinh(self, tmp_path):
        """Mô hình rớt dấu Đ: "168/2025/ND-CP" phải khớp "168/2025/NĐ-CP" trong kho."""
        import sqlite3
        path = tmp_path / "d.db"
        conn = sqlite3.connect(str(path))
        conn.execute("CREATE TABLE documents (doc_num TEXT)")
        conn.execute("INSERT INTO documents VALUES ('168/2025/NĐ-CP')")
        conn.commit(); conn.close()

        r = check_citations("Theo Nghị định 168/2025/ND-CP.", db_path=path)
        assert r.ok, r.missing
        # chiều ngược cũng đúng: kho có bản không dấu, báo cáo viết có dấu
        assert check_citations("QĐ 40/2026/QD-UBND.",
                               db_path=path, extra_allowed={"40/2026/QĐ-UBND"}).ok
