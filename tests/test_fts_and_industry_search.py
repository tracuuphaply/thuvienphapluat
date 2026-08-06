"""Đề xuất #5 — thoát ký tự FTS và truy xuất theo bộ từ khoá ngành.

Lỗi gốc: ký tự '&' trong tên ngành làm FTS5 ném syntax error, rơi vào nhánh dự
phòng tìm cụm từ chính xác và trả về 0 kết quả — 4/10 ngành không lấy được gì.
"""
from src.obsidian.config_obsidian import INDUSTRY_MAP
from src.rag.db_rag import RAGDatabase
from src.rag.hybrid_search import industry_search


class TestBuildFtsQuery:
    def test_ky_tu_dac_biet_khong_lam_vo_truy_van(self):
        q = RAGDatabase.build_fts_query("Xây dựng & Bất động sản")
        assert "&" not in q
        assert q == '"Xây" AND "dựng" AND "Bất" AND "động" AND "sản"'

    def test_dau_hai_cham_va_ngoac_kep_duoc_boc(self):
        for raw in ['doanh nghiệp: quy định', 'thuế "ưu đãi"', "điều 5 * khoản 2"]:
            q = RAGDatabase.build_fts_query(raw)
            assert q.count('"') % 2 == 0, f"ngoặc kép lẻ trong {q!r}"

    def test_tu_khoa_fts_khong_bi_hieu_thanh_du_lieu(self):
        """'OR' để nguyên sẽ ra 0 kết quả vì không văn bản nào chứa chữ OR."""
        assert RAGDatabase.build_fts_query("thuế OR lao động") == '"thuế" AND "lao" AND "động"'

    def test_truy_van_rong_tra_ve_chuoi_rong(self):
        for raw in ["", "   ", "&&&", "!!!"]:
            assert RAGDatabase.build_fts_query(raw) == ""

    def test_toan_tu_or_dung_duoc_khi_can_mo_rong(self):
        assert RAGDatabase.build_fts_query("thuế phí", operator="OR") == '"thuế" OR "phí"'


class TestSearchFts:
    def test_ky_tu_amp_khong_con_lam_rong_ket_qua(self, rag_db, chunk_factory):
        chunk_factory("01/2026/NĐ-CP", "Quy định về xây dựng nhà ở và bất động sản thương mại")
        co_amp = rag_db.search_fts("Xây dựng & Bất động sản")
        khong_amp = rag_db.search_fts("Xây dựng Bất động sản")
        assert len(co_amp) == len(khong_amp) == 1

    def test_truy_van_hong_khong_lam_sap_ma_tra_rong(self, rag_db, chunk_factory):
        chunk_factory("02/2026/TT-BTC", "Quy định về thuế thu nhập doanh nghiệp")
        assert rag_db.search_fts('doanh nghiệp: "quy định" * ^') is not None

    def test_truy_van_rong_khong_goi_xuong_sqlite(self, rag_db):
        assert rag_db.search_fts("   ") == []


class TestIndustrySearch:
    def test_ten_nganh_dai_van_ra_ket_qua(self, rag_db, chunk_factory):
        chunk_factory("03/2026/TT-BYT", "Quy định về khám bệnh, chữa bệnh tại bệnh viện")
        chunk_factory("04/2026/TT-BYT", "Quy định đăng ký lưu hành thuốc và dược phẩm", chunk_index=1)
        ket_qua = industry_search(rag_db, "Y tế và trợ giúp xã hội", limit=20)
        assert len(ket_qua) >= 2, "phải tìm được qua từ khoá ngành dù tên ngành có '&'"

    def test_mo_rong_bang_tu_khoa_chu_khong_chi_ten_nganh(self, rag_db, chunk_factory):
        # Không đoạn nào chứa đủ cụm "Nông nghiệp & Thủy sản", chỉ chứa từ khoá con.
        chunk_factory("05/2026/NĐ-CP", "Chính sách hỗ trợ hoạt động chăn nuôi quy mô trang trại")
        ket_qua = industry_search(rag_db, "Nông nghiệp, lâm nghiệp và thuỷ sản", limit=20)
        assert len(ket_qua) == 1

    def test_nganh_la_khong_lam_sap(self, rag_db, chunk_factory):
        chunk_factory("06/2026/QĐ-TTg", "Nội dung bất kỳ")
        assert industry_search(rag_db, "Ngành không tồn tại xyz", limit=5) is not None

    def test_khong_tra_ve_chunk_trung_lap(self, rag_db, chunk_factory):
        """Một đoạn khớp nhiều từ khoá vẫn chỉ được xuất hiện một lần."""
        chunk_factory("07/2026/NĐ-CP", "Quy định về y tế, dược, thuốc, bệnh viện, khám bệnh")
        ket_qua = industry_search(rag_db, "Y tế và trợ giúp xã hội", limit=20)
        assert len({r.id for r in ket_qua}) == len(ket_qua)


def test_moi_nganh_deu_co_tu_khoa():
    """industry_search dựa vào bộ từ khoá này; ngành nào rỗng là ngành đó mù."""
    for nganh, tu_khoa in INDUSTRY_MAP.items():
        assert tu_khoa, f"ngành {nganh} không có từ khoá nào"
