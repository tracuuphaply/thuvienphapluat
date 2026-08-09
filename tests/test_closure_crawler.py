"""Nhóm — crawler bao đóng dẫn chiếu.

Ba thứ phải đúng, vì sai là hỏng cả kho:
  - văn bản kéo về phải được đánh dấu là NGỮ CẢNH, nếu không bản tin hằng ngày
    ngập vài nghìn văn bản không liên quan và Drive bị đốt hết quota
  - KHÔNG được lọc theo hiệu lực: văn bản bị bãi bỏ là mắt xích giải thích quy
    định hiện hành thay thế cái gì
  - các van chặn phải dừng được vòng lặp, vì người dùng đã chọn đệ quy không
    giới hạn nên không có gì khác giữ nó hội tụ
"""
import pytest
from sqlalchemy import text

from src.pipeline import closure
from src.storage.database import insert_references, upsert_document
from src.utils import disk_guard


@pytest.fixture
def kho(master_session):
    """Một văn bản nguồn dẫn chiếu tới ba văn bản chưa có trong kho."""
    doc, _ = upsert_document(master_session, {
        "doc_num": "292/2026/NĐ-CP", "title": "Nghị định nguồn",
        "agency_name": "Chính phủ", "moj_id": "1000",
    })
    master_session.flush()
    insert_references(master_session, doc.id, [
        {"target_doc_num": "83/2015/QH13", "relation_type": "Căn cứ",
         "target_moj_id": "2001"},
        {"target_doc_num": "72/2010/QĐ-TTg", "relation_type": "Thay thế",
         "target_moj_id": "2002"},
        {"target_doc_num": "Không số", "relation_type": "Căn cứ",
         "target_moj_id": "2003"},
        {"target_doc_num": "99/2019/TT-BTC", "relation_type": "Căn cứ",
         "target_moj_id": None},
    ])
    master_session.commit()
    return master_session


class TestNapHangDoi:
    def test_chi_nap_dich_chua_co_trong_kho(self, kho):
        assert closure.seed_frontier(kho) == 2
        kho.commit()
        rows = kho.execute(text("SELECT doc_num FROM crawl_frontier")).scalars().all()
        assert set(rows) == {"83/2015/QH13", "72/2010/QĐ-TTg"}

    def test_loai_so_hieu_rac(self, kho):
        """165 cạnh trỏ tới "Không số" — đó là thùng rác số hiệu không parse được.

        Đưa vào hàng đợi là tự tạo một nút khổng lồ vô nghĩa giữa sơ đồ tư duy.
        """
        closure.seed_frontier(kho)
        kho.commit()
        rows = kho.execute(text("SELECT doc_num FROM crawl_frontier")).scalars().all()
        assert "Không số" not in rows

    def test_dich_khong_co_id_duoc_dem_chu_khong_nuot(self, kho):
        """Không tra được id thì phải hiện ra ở khối hạn chế dữ liệu của báo cáo."""
        assert closure.unresolvable_targets(kho) == 1

    def test_nap_lai_khong_tao_ban_trung(self, kho):
        closure.seed_frontier(kho)
        kho.commit()
        assert closure.seed_frontier(kho) == 0

    def test_khong_nap_van_ban_da_co_trong_kho(self, kho):
        upsert_document(kho, {
            "doc_num": "83/2015/QH13", "title": "Luật Kế toán",
            "agency_name": "Quốc hội", "moj_id": "2001",
        })
        kho.commit()
        closure.seed_frontier(kho)
        kho.commit()
        rows = kho.execute(text("SELECT doc_num FROM crawl_frontier")).scalars().all()
        assert "83/2015/QH13" not in rows


class TestUuTien:
    def test_sua_doi_uu_tien_hon_can_cu(self):
        assert closure.priority_of("Thay thế", 1, 1) > closure.priority_of("Căn cứ", 1, 1)

    def test_duoc_dan_nhieu_thi_uu_tien_hon(self):
        assert closure.priority_of("Căn cứ", 100, 1) > closure.priority_of("Căn cứ", 1, 1)

    def test_cang_sau_cang_it_uu_tien(self):
        assert closure.priority_of("Căn cứ", 10, 1) > closure.priority_of("Căn cứ", 10, 3)

    def test_quan_he_chua_xac_dinh_bi_ha_uu_tien(self):
        """Mã quan hệ chưa kiểm chứng không được đối xử như quan hệ đã biết."""
        assert (closure.priority_of("Chưa xác định (mã 4)", 5, 1)
                < closure.priority_of("Căn cứ", 5, 1))


class TestVanChan:
    def _fake_moj(self, monkeypatch, calls: list):
        import src.sources.moj_api as moj

        def fake_fetch(moj_id):
            calls.append(moj_id)
            return {"data": {"id": moj_id, "docNum": f"DOC-{moj_id}",
                             "title": "x", "references": []}}
        monkeypatch.setattr(moj, "fetch_doc_detail", fake_fetch)
        monkeypatch.setattr(closure, "MOJ_RATE_LIMIT_SECONDS", 0)

    def test_ngan_sach_moi_lan_chay_duoc_ton_trong(self, kho, monkeypatch):
        calls: list = []
        self._fake_moj(monkeypatch, calls)
        closure.seed_frontier(kho)
        kho.commit()
        stats = closure.run_closure(kho, max_fetch=1, on_document=lambda d, p: None)
        assert stats.fetched == 1 and len(calls) == 1
        # Hàng đợi trong DB nên phần còn lại vẫn chờ, không mất.
        assert stats.pending_after == 1

    def test_het_hang_doi_thi_dung(self, kho, monkeypatch):
        self._fake_moj(monkeypatch, [])
        closure.seed_frontier(kho)
        kho.commit()
        stats = closure.run_closure(kho, max_fetch=100, on_document=lambda d, p: None)
        assert stats.stopped_reason == "het_hang_doi"

    def test_cham_tran_so_van_ban_thi_dung(self, kho, monkeypatch):
        self._fake_moj(monkeypatch, [])
        monkeypatch.setattr(closure, "CLOSURE_MAX_NODES", 1)
        closure.seed_frontier(kho)
        kho.commit()
        stats = closure.run_closure(kho, max_fetch=100, on_document=lambda d, p: None)
        assert "cham_tran" in stats.stopped_reason and stats.fetched == 0

    def test_het_dung_luong_dia_thi_dung_co_trat_tu(self, kho, monkeypatch):
        """Đĩa đầy giữa lúc SQLite đang ghi có thể làm hỏng cơ sở dữ liệu."""
        self._fake_moj(monkeypatch, [])

        def het_cho(*a, **kw):
            raise disk_guard.DiskSpaceExhausted("còn 0.1 GB")
        monkeypatch.setattr(disk_guard, "ensure_space", het_cho)

        closure.seed_frontier(kho)
        kho.commit()
        stats = closure.run_closure(kho, max_fetch=100, on_document=lambda d, p: None)
        assert "het_dung_luong_dia" in stats.stopped_reason
        assert stats.fetched == 0

    def test_hub_van_tai_ve_nhung_khong_gian_no(self, kho, monkeypatch):
        """72/2025/QH15 bị dẫn 204 lần — giãn nở từ nó kéo về cả hệ thống pháp luật.

        Vẫn phải TẢI VỀ vì báo cáo cần trích dẫn nó; chỉ không đi tiếp từ nó.
        """
        self._fake_moj(monkeypatch, [])
        monkeypatch.setattr(closure, "CLOSURE_HUB_INDEGREE", 0)
        closure.seed_frontier(kho)
        kho.commit()
        stats = closure.run_closure(kho, max_fetch=10, on_document=lambda d, p: None)
        assert stats.fetched == 2, "hub vẫn phải được tải về"
        assert stats.hubs_skipped == 2
        states = kho.execute(text("SELECT state FROM crawl_frontier")).scalars().all()
        assert set(states) == {closure.HUB_NOT_EXPANDED}

    def test_loi_mang_khong_lam_dung_ca_dot(self, kho, monkeypatch):
        import src.sources.moj_api as moj

        def fetch_hong(moj_id):
            if moj_id == "2001":
                raise RuntimeError("mat mang")
            return {"data": {"id": moj_id, "docNum": "X", "title": "x", "references": []}}
        monkeypatch.setattr(moj, "fetch_doc_detail", fetch_hong)
        monkeypatch.setattr(closure, "MOJ_RATE_LIMIT_SECONDS", 0)

        closure.seed_frontier(kho)
        kho.commit()
        stats = closure.run_closure(kho, max_fetch=10, on_document=lambda d, p: None)
        assert stats.failed == 1 and stats.fetched == 1
        row = kho.execute(text(
            "SELECT state, attempts, last_error FROM crawl_frontier WHERE moj_id='2001'"
        )).mappings().first()
        assert row["state"] == closure.FAILED
        assert row["attempts"] == 1 and "mat mang" in row["last_error"]


    def test_loi_ghi_kho_khong_lam_dung_ca_dot(self, kho, monkeypatch):
        """Lỗi lúc GHI khác lỗi lúc TẢI, và nguy hiểm hơn hẳn.

        Sau một lỗi flush, SQLAlchemy từ chối mọi lệnh tiếp theo trên session
        đó — kể cả lệnh đánh dấu FAILED. Bản trước gọi _mark ngay, nên chính bộ
        bắt lỗi ném tiếp và giết vòng lặp: một văn bản hỏng làm mất cả lô 300.
        Đã xảy ra thật với "05/2000/QĐ--BVHTT" đụng ràng buộc public_slug.
        """
        import src.sources.moj_api as moj

        monkeypatch.setattr(moj, "fetch_doc_detail", lambda i: {
            "data": {"id": i, "docNum": f"X{i}", "title": "x", "references": []}})
        monkeypatch.setattr(closure, "MOJ_RATE_LIMIT_SECONDS", 0)

        def ghi(detail, depth):
            if detail.get("moj_id") == "2001":
                # Ép session vào trạng thái hỏng đúng như một vi phạm ràng buộc.
                kho.execute(text("INSERT INTO documents (doc_num) VALUES (NULL)"))
                kho.flush()

        closure.seed_frontier(kho)
        kho.commit()
        stats = closure.run_closure(kho, max_fetch=10, on_document=ghi)

        assert stats.failed == 1
        assert stats.saved == 1, "văn bản còn lại vẫn phải được ghi"
        states = dict(kho.execute(text(
            "SELECT moj_id, state FROM crawl_frontier")).all())
        assert states["2001"] == closure.FAILED
        assert states["2002"] == closure.DONE


class TestDoSauBaoDong:
    """Độ sâu suy từ văn bản phát hiện ra đích, không gán cứng.

    Bản trước ghi depth = 1 cho mọi mục, nên `first_seen_depth` là dữ kiện sai
    trên toàn bộ văn bản nền, và số hạng −1,5·depth trong công thức ưu tiên trở
    thành hằng số — xếp hạng mất hẳn phần phạt theo khoảng cách.
    """

    def test_dich_cua_hat_giong_o_do_sau_1(self, kho):
        closure.seed_frontier(kho)
        kho.commit()
        depths = kho.execute(text(
            "SELECT DISTINCT depth FROM crawl_frontier")).scalars().all()
        assert depths == [1]

    def test_dich_cua_van_ban_nen_sau_hon_mot_bac(self, kho):
        nen, _ = upsert_document(kho, {
            "doc_num": "83/2015/QH13", "title": "Luật nền", "moj_id": "2001",
            "agency_name": "Quốc hội", "is_closure_node": True,
            "first_seen_depth": 1,
        })
        kho.flush()
        insert_references(kho, nen.id, [
            {"target_doc_num": "45/2013/QH13", "relation_type": "Căn cứ",
             "target_moj_id": "3001"},
        ])
        kho.commit()

        closure.seed_frontier(kho)
        kho.commit()
        assert kho.execute(text(
            "SELECT depth FROM crawl_frontier WHERE moj_id='3001'"
        )).scalar() == 2

    def test_duong_ngan_nhat_moi_la_khoang_cach_that(self, kho):
        """Một đích bị nhiều văn bản ở nhiều tầng dẫn tới."""
        sau, _ = upsert_document(kho, {
            "doc_num": "70/2020/NĐ-CP", "title": "Sâu", "moj_id": "2002",
            "agency_name": "Chính phủ", "is_closure_node": True,
            "first_seen_depth": 4,
        })
        kho.flush()
        insert_references(kho, sau.id, [
            {"target_doc_num": "83/2015/QH13", "relation_type": "Căn cứ",
             "target_moj_id": "2001"},
        ])
        kho.commit()
        closure.seed_frontier(kho)
        kho.commit()
        # Hạt giống (depth 0) cũng dẫn tới 2001, nên khoảng cách là 1 chứ không phải 5.
        assert kho.execute(text(
            "SELECT depth FROM crawl_frontier WHERE moj_id='2001'")).scalar() == 1

    def test_tran_do_sau_chan_duoc_duoi_dai(self, kho, monkeypatch):
        monkeypatch.setattr(closure, "CLOSURE_MAX_DEPTH", 1)
        nen, _ = upsert_document(kho, {
            "doc_num": "83/2015/QH13", "title": "Luật nền", "moj_id": "2001",
            "agency_name": "Quốc hội", "is_closure_node": True,
            "first_seen_depth": 1,
        })
        kho.flush()
        insert_references(kho, nen.id, [
            {"target_doc_num": "45/2013/QH13", "relation_type": "Căn cứ",
             "target_moj_id": "3001"},
        ])
        kho.commit()

        closure.seed_frontier(kho)
        kho.commit()
        assert kho.execute(text(
            "SELECT COUNT(*) FROM crawl_frontier WHERE moj_id='3001'")).scalar() == 0

    def test_khong_dat_tran_thi_khong_gioi_han(self, kho, monkeypatch):
        monkeypatch.setattr(closure, "CLOSURE_MAX_DEPTH", 0)
        nen, _ = upsert_document(kho, {
            "doc_num": "83/2015/QH13", "title": "Luật nền", "moj_id": "2001",
            "agency_name": "Quốc hội", "is_closure_node": True,
            "first_seen_depth": 9,
        })
        kho.flush()
        insert_references(kho, nen.id, [
            {"target_doc_num": "45/2013/QH13", "relation_type": "Căn cứ",
             "target_moj_id": "3001"},
        ])
        kho.commit()
        closure.seed_frontier(kho)
        kho.commit()
        assert kho.execute(text(
            "SELECT depth FROM crawl_frontier WHERE moj_id='3001'")).scalar() == 10


class TestWatermark:
    """Mốc quét bền vững thay cửa sổ trượt.

    Cửa sổ trượt `today - 30 ngày` quét lại toàn bộ cửa sổ ở mỗi lần chạy
    (6.906 văn bản để tìm 50 bản mới), và máy tắt lâu hơn cửa sổ là mất hẳn phần
    ở giữa mà không có dấu hiệu nào.
    """

    def test_lan_dau_quet_ve_san_co_dinh(self, master_session):
        from datetime import date

        from src.config import CLOSURE_SEED_FLOOR
        from src.storage.database import get_crawl_cutoff

        cutoff, ly_do = get_crawl_cutoff(master_session, "moj")
        assert cutoff == date.fromisoformat(CLOSURE_SEED_FLOOR)
        assert ly_do == "lan_dau_quet_ve_san"

    def test_lan_sau_quet_lui_qua_watermark(self, master_session):
        """Không cắt đúng watermark: văn bản được ĐĂNG muộn hơn ngày ban hành,

        nên cắt sát sẽ bỏ sót vĩnh viễn mọi văn bản đăng chậm.
        """
        from datetime import date, timedelta

        from src.config import CRAWL_OVERLAP_DAYS
        from src.storage.database import get_crawl_cutoff, update_crawl_watermark

        high = date.today() - timedelta(days=5)
        update_crawl_watermark(master_session, "moj", high)
        master_session.commit()

        cutoff, ly_do = get_crawl_cutoff(master_session, "moj")
        assert cutoff == high - timedelta(days=CRAWL_OVERLAP_DAYS)
        assert "watermark" in ly_do

    def test_khong_bao_gio_quet_duoi_san(self, master_session):
        """Sàn 01/01/2026 là cố định, không trôi."""
        from datetime import date

        from src.config import CLOSURE_SEED_FLOOR
        from src.storage.database import get_crawl_cutoff, update_crawl_watermark

        update_crawl_watermark(master_session, "moj", date(2026, 1, 10))
        master_session.commit()
        cutoff, _ = get_crawl_cutoff(master_session, "moj")
        assert cutoff == date.fromisoformat(CLOSURE_SEED_FLOOR)

    def test_watermark_khong_bi_lui(self, master_session):
        """Lần quét sau chỉ thấy văn bản cũ thì watermark phải giữ nguyên."""
        from datetime import date

        from src.storage.database import get_crawl_cutoff, update_crawl_watermark

        update_crawl_watermark(master_session, "moj", date(2026, 8, 1))
        master_session.commit()
        update_crawl_watermark(master_session, "moj", date(2026, 3, 1))
        master_session.commit()

        cutoff, ly_do = get_crawl_cutoff(master_session, "moj")
        assert "2026-08-01" in ly_do

    def test_khong_co_moc_moi_thi_khong_ghi(self, master_session):
        """Lượt quét rỗng không được làm mất watermark đang có."""
        from datetime import date

        from src.storage.database import get_crawl_cutoff, update_crawl_watermark

        update_crawl_watermark(master_session, "moj", date(2026, 8, 1))
        master_session.commit()
        update_crawl_watermark(master_session, "moj", None)
        master_session.commit()
        _, ly_do = get_crawl_cutoff(master_session, "moj")
        assert "2026-08-01" in ly_do
