"""Nhóm — van an toàn của tầng truy xuất.

Đây là rủi ro nghiêm trọng nhất của giai đoạn bao đóng dẫn chiếu vì nó hỏng
trong im lặng: báo cáo vẫn ra, vẫn đúng định dạng, chỉ là dựa trên rất ít điều
khoản — và không có dấu hiệu nào cho thấy phần lớn dữ liệu đã bị bỏ lại.

Cơ chế cũ lấy 100 kết quả rồi mới lọc bằng Python. Khi kho đầy văn bản đã hết
hiệu lực (bao đóng kéo về hàng nghìn bản như vậy), 100 chỗ đó bị chiếm sạch.
Nay điều kiện nằm trong câu SQL nên `limit` áp lên phần ĐÃ lọc.
"""
import pytest

from src.legal.effectivity import CON_HIEU_LUC, HET_TOAN_BO
from src.rag.db_rag import HAS_VEC
from src.rag.hybrid_search import DEFAULT_FILTERS, hybrid_search, with_default_filters


@pytest.fixture
def kho_lan_lon(rag_db):
    """Kho mô phỏng sau bao đóng: văn bản chết áp đảo văn bản còn hiệu lực.

    50 đoạn hết hiệu lực toàn bộ, 3 đoạn còn hiệu lực — tỷ lệ này chính là thứ
    bao đóng dẫn chiếu tạo ra, vì phần lớn văn bản nền đã bị thay thế từ lâu.
    """
    def add(doc_num, idx, eff_state, closure=0):
        rag_db.upsert_chunk({
            "doc_num": doc_num, "chunk_index": idx,
            "heading": f"Điều {idx}",
            "content": "quy định về thuế giá trị gia tăng đối với doanh nghiệp",
            "char_count": 60, "content_hash": f"h{doc_num}{idx}",
            "eff_state": eff_state, "is_closure_node": closure,
            "industries": [],
        }, commit=False)

    for i in range(50):
        add(f"CHET-{i}/2015/NĐ-CP", i, HET_TOAN_BO)
    for i in range(3):
        add(f"SONG-{i}/2026/NĐ-CP", i, CON_HIEU_LUC)
    rag_db.db.commit()
    return rag_db


class TestLocNgayTrongSQL:
    def test_van_ban_chet_khong_chiem_cho_van_ban_song(self, kho_lan_lon):
        """Lấy 10 kết quả từ kho 50 chết / 3 sống phải ra đủ 3 bản sống.

        Cơ chế cũ: 10 chỗ đầu gần như chắc chắn toàn văn bản chết, lọc xong còn 0.
        """
        results = hybrid_search(kho_lan_lon, "thuế giá trị gia tăng", limit=10)
        doc_nums = {r.doc_num for r in results}
        assert len(doc_nums) == 3, f"chỉ lấy được {doc_nums}"
        assert all(d.startswith("SONG-") for d in doc_nums)

    def test_khong_lot_van_ban_het_hieu_luc_nao(self, kho_lan_lon):
        results = hybrid_search(kho_lan_lon, "thuế giá trị gia tăng", limit=60)
        assert not [r for r in results if r.doc_num.startswith("CHET-")]

    def test_van_ban_ngu_canh_bi_loai_mac_dinh(self, rag_db):
        """Văn bản kéo về do bị dẫn chiếu chỉ để hiểu bối cảnh, không phải căn cứ."""
        rag_db.upsert_chunk({
            "doc_num": "NEN/2010/NĐ-CP", "chunk_index": 0, "heading": "Điều 1",
            "content": "quy định về đăng ký kinh doanh", "char_count": 30,
            "content_hash": "h1", "eff_state": CON_HIEU_LUC,
            "is_closure_node": 1, "industries": [],
        })
        assert hybrid_search(rag_db, "đăng ký kinh doanh", limit=10) == []

    def test_van_co_the_tra_cuu_lich_su_khi_yeu_cau_ro(self, kho_lan_lon):
        """Bỏ lọc phải là hành động có ý thức, không phải mặc định."""
        results = hybrid_search(
            kho_lan_lon, "thuế giá trị gia tăng", limit=60,
            filters={"exclude_eff_states": []},
        )
        assert [r for r in results if r.doc_num.startswith("CHET-")]

    def test_chunk_chua_gan_co_thi_giu_lai_chu_khong_loai(self, rag_db):
        """eff_state NULL = chưa reindex sau khi nâng cấp, không phải đã chết.

        Loại chúng sẽ làm kho rỗng ngay sau khi nâng cấp mà chưa kịp chạy lại
        index — mất dữ liệu vì một bước vận hành chưa làm, không phải vì dữ liệu.
        """
        rag_db.upsert_chunk({
            "doc_num": "CU/2020/NĐ-CP", "chunk_index": 0, "heading": "Điều 1",
            "content": "quy định về hóa đơn điện tử", "char_count": 30,
            "content_hash": "h2", "industries": [],
        })
        assert len(hybrid_search(rag_db, "hóa đơn điện tử", limit=10)) == 1


class TestBoLocMacDinh:
    def test_mac_dinh_loai_van_ban_het_hieu_luc_toan_bo(self):
        assert HET_TOAN_BO in DEFAULT_FILTERS["exclude_eff_states"]

    def test_mac_dinh_khong_loai_van_ban_het_hieu_luc_mot_phan(self):
        """Phần chưa bị sửa của văn bản sửa đổi một phần vẫn là luật hiện hành."""
        from src.legal.effectivity import HET_MOT_PHAN
        assert HET_MOT_PHAN not in DEFAULT_FILTERS["exclude_eff_states"]

    def test_nguoi_goi_ghi_de_duoc_tung_khoa(self):
        merged = with_default_filters({"exclude_closure": False})
        assert merged["exclude_closure"] is False
        assert merged["exclude_eff_states"] == [HET_TOAN_BO]

    def test_khong_sua_bo_mac_dinh_goc(self):
        """Trả về bản sao, nếu không một lần gọi làm hỏng mọi lần gọi sau."""
        with_default_filters({"exclude_closure": False})
        assert DEFAULT_FILTERS["exclude_closure"] is True


class TestSqlDungCu:
    def test_menh_de_rong_khi_khong_co_dieu_kien(self, rag_db):
        clause, params = rag_db.build_chunk_filter(None)
        assert clause == "" and params == []

    def test_ghep_duoc_nhieu_dieu_kien(self, rag_db):
        clause, params = rag_db.build_chunk_filter({
            "exclude_eff_states": [HET_TOAN_BO],
            "exclude_closure": True,
            "max_hierarchy_level": 7,
        })
        assert clause.startswith(" AND ")
        assert "eff_state" in clause and "is_closure_node" in clause
        assert "hierarchy_level" in clause
        assert params == [HET_TOAN_BO, 7]

    @pytest.mark.skipif(not HAS_VEC, reason="cần sqlite-vec")
    def test_nhanh_vector_lay_du_de_bu_phan_bi_loc(self, rag_db):
        """vec0 phải trả k láng giềng rồi mới lọc được, nên phải lấy dư."""
        assert rag_db.VECTOR_OVERFETCH > 1
