"""Nhóm #2 — độ phủ kho văn bản.

Lỗi gốc: kho chỉ có 314 văn bản, sớm nhất 2025-11-29, không có Luật Doanh
nghiệp / Luật Đầu tư hay bất kỳ nghị định nền tảng nào — trong khi hàng trăm
văn bản trong kho đang "Căn cứ" vào chúng.

Nguyên nhân kỹ thuật: `scan_incremental` chỉ quét cửa sổ issueDate gần nhất, và
`search_by_doc_num` không dùng được vì endpoint /doc/all bỏ qua mọi tham số lọc.
"""
from datetime import date
from pathlib import Path

import pytest

from scripts.backfill_historical import _issue_date
from src.storage.database import get_session, insert_references, upsert_document


class TestSearchByDocNumDaDuocCanhBao:
    def test_docstring_ghi_ro_endpoint_bo_qua_bo_loc(self):
        """Hàm này luôn trả None; phải cảnh báo để người sau không tin nhầm."""
        from src.sources.moj_api import search_by_doc_num
        doc = search_by_doc_num.__doc__ or ""
        assert "CẢNH BÁO" in doc
        assert "bỏ qua" in doc and "tham số lọc" in doc

    def test_co_chi_duong_thay_the(self):
        from src.sources.moj_api import search_by_doc_num
        assert "targetDocument.id" in (search_by_doc_num.__doc__ or "")


class TestMissingTargets:
    def test_liet_ke_dung_van_ban_duoc_dan_ma_thieu(self, master_session, monkeypatch):
        from contextlib import contextmanager

        import scripts.backfill_cited_documents as bf

        src, _ = upsert_document(master_session, {
            "doc_num": "01/2026/QĐ-UBND", "title": "Nguồn", "agency_name": "UBND A",
        })
        master_session.commit()
        insert_references(master_session, src.id, [
            {"target_doc_num": "72/2025/QH15", "relation_type": "Căn cứ"},
            {"target_doc_num": "72/2025/QH15", "relation_type": "Dẫn chiếu"},
            {"target_doc_num": "99/2020/NĐ-CP", "relation_type": "Căn cứ"},
        ])
        master_session.commit()

        @contextmanager
        def fake_session():
            yield master_session

        monkeypatch.setattr(bf, "get_session", fake_session)
        missing = bf.missing_targets()

        assert missing["72/2025/QH15"] == 2, "phải đếm theo số lần được dẫn"
        assert "99/2020/NĐ-CP" in missing
        assert "01/2026/QĐ-UBND" not in missing, "văn bản đã có trong kho không phải là thiếu"

    def test_van_ban_da_co_thi_khong_liet_ke(self, master_session, monkeypatch):
        from contextlib import contextmanager

        import scripts.backfill_cited_documents as bf

        src, _ = upsert_document(master_session, {
            "doc_num": "02/2026/QĐ-UBND", "title": "Nguồn", "agency_name": "UBND B",
        })
        upsert_document(master_session, {
            "doc_num": "50/2025/QH15", "title": "Luật đã có", "agency_name": "Quốc hội",
        })
        master_session.commit()
        insert_references(master_session, src.id, [
            {"target_doc_num": "50/2025/QH15", "relation_type": "Căn cứ"},
        ])
        master_session.commit()

        @contextmanager
        def fake_session():
            yield master_session

        monkeypatch.setattr(bf, "get_session", fake_session)
        assert "50/2025/QH15" not in bf.missing_targets()


class TestHistoricalPaging:
    def test_doc_ngay_ban_hanh(self):
        assert _issue_date({"issueDate": "2025-06-16T00:00:00"}) == date(2025, 6, 16)
        assert _issue_date({"issueDate": ""}) is None
        assert _issue_date({}) is None

    def test_dung_khi_vuot_moc_thoi_gian(self, monkeypatch):
        """Không được lật trang vô hạn khi đã qua mốc cần lấy."""
        import scripts.backfill_historical as bh

        pages = {
            1: [{"id": "a", "docNum": "1/2026/NĐ-CP", "issueDate": "2026-08-01T00:00:00",
                 "title": "Nghị định về đầu tư kinh doanh"}],
            2: [{"id": "b", "docNum": "2/2020/NĐ-CP", "issueDate": "2020-01-01T00:00:00",
                 "title": "Nghị định về đầu tư kinh doanh"}],
        }
        goi = []

        def fake_list(page=1, page_size=50, keyword=""):
            goi.append(page)
            return {"data": {"items": pages.get(page, [])}}

        monkeypatch.setattr(bh, "fetch_doc_list", fake_list)
        monkeypatch.setattr(bh, "_extract_items", lambda r: r["data"]["items"])
        monkeypatch.setattr(bh, "tieu_de_dang_theo_doi", lambda item: True)

        got = bh.collect_candidates(date(2026, 1, 1), max_pages=50, sleep=0)
        assert goi == [1, 2], f"phải dừng ngay sau trang vượt mốc, đã lật {goi}"
        assert [c["id"] for c in got] == ["a"], "văn bản cũ hơn mốc không được nhận"

    def test_khong_lay_trung_id(self, monkeypatch):
        import scripts.backfill_historical as bh

        item = {"id": "x", "docNum": "1/2026/NĐ-CP", "issueDate": "2026-08-01T00:00:00",
                "title": "Nghị định"}

        def fake_list(page=1, page_size=50, keyword=""):
            return {"items": [item] if page <= 2 else []}

        monkeypatch.setattr(bh, "fetch_doc_list", fake_list)
        monkeypatch.setattr(bh, "_extract_items", lambda r: r["items"])
        monkeypatch.setattr(bh, "tieu_de_dang_theo_doi", lambda i: True)

        got = bh.collect_candidates(date(2026, 1, 1), max_pages=3, sleep=0)
        assert len(got) == 1, "phân trang không ổn định có thể trả lặp, phải khử trùng"

    def test_ton_trong_max_pages(self, monkeypatch):
        import scripts.backfill_historical as bh

        goi = []

        def fake_list(page=1, page_size=50, keyword=""):
            goi.append(page)
            return {"items": [{"id": f"i{page}", "docNum": "1/2026/NĐ-CP",
                               "issueDate": "2026-08-01T00:00:00", "title": "x"}]}

        monkeypatch.setattr(bh, "fetch_doc_list", fake_list)
        monkeypatch.setattr(bh, "_extract_items", lambda r: r["items"])
        monkeypatch.setattr(bh, "tieu_de_dang_theo_doi", lambda i: True)

        bh.collect_candidates(date(2020, 1, 1), max_pages=5, sleep=0)
        assert len(goi) == 5


class TestScriptsTonTai:
    @pytest.mark.parametrize("name", [
        "backfill_cited_documents.py",
        "backfill_historical.py",
        "rebuild_reference_graph.py",
        "probe_reference_types.py",
        "migrate_doc_key.py",
        "install_scheduler.sh",
    ])
    def test_script_co_mat(self, name):
        assert (Path("scripts") / name).exists()
