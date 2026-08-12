"""Bộ lọc "văn bản liên quan doanh nghiệp".

Báo cáo cho chủ doanh nghiệp không được lẫn văn bản y tế, giáo dục, văn hoá-xã
hội, hay quyết định cấp tỉnh. Lỗi thật đã gặp: báo cáo (b) "văn bản mới" hoá ra
là quyết định bãi bỏ hỗ trợ khám chữa bệnh của tỉnh Sơn La — đúng thể loại, sai
người đọc.
"""
from sqlalchemy import text

from src.legal.business_relevance import (
    filter_business_docs,
    filter_business_doc_keys,
    is_business_document,
    is_business_field,
    reason_excluded,
)


class TestPureRules:
    def test_linh_vuc_doanh_nghiep(self):
        assert is_business_field(6)      # Thuế - Phí - Lệ phí
        assert is_business_field(1)      # Doanh nghiệp
        assert not is_business_field(24)  # Thể thao - Y tế
        assert not is_business_field(22)  # Giáo dục
        assert not is_business_field(27)  # Lĩnh vực khác

    def test_bon_nhom_ranh_gioi_da_chon(self):
        for code in (13, 16, 19, 25):  # dịch vụ pháp lý, vi phạm HC, TCNN, quyền dân sự
            assert is_business_field(code), code

    def test_phai_thoa_ca_hai_tieu_chi(self):
        assert is_business_document(6, "trung_uong")        # OK
        assert not is_business_document(24, "trung_uong")   # sai lĩnh vực
        assert not is_business_document(6, "tinh")          # cấp tỉnh
        assert not is_business_document(24, "tinh")         # sai cả hai

    def test_ly_do_loai_noi_ro_nguyen_nhan(self):
        assert reason_excluded(24, "trung_uong").startswith("ngoai_linh_vuc")
        assert reason_excluded(6, "tinh").startswith("khong_phai_trung_uong")
        assert reason_excluded(6, "trung_uong") == ""  # không bị loại

    def test_hai_van_ban_trong_bao_cao_hong_deu_bi_loai(self):
        """47/2026 (y tế) loại vì lĩnh vực; 65/2026 (doanh nghiệp nhưng cấp tỉnh)

        loại vì phạm vi. Cả hai đều không được vào báo cáo.
        """
        assert not is_business_document(24, "tinh")  # 47/2026/QĐ-UBND
        assert not is_business_document(1, "tinh")   # 65/2026/QĐ-UBND


class TestEnvOverride:
    def test_doi_bo_linh_vuc(self, monkeypatch):
        monkeypatch.setenv("BUSINESS_FIELD_CODES", "6,10")
        assert is_business_field(6) and is_business_field(10)
        assert not is_business_field(1)  # ngoài override

    def test_tat_loc_cap_tinh(self, monkeypatch):
        monkeypatch.setenv("REPORT_CENTRAL_ONLY", "false")
        assert is_business_document(6, "tinh")   # cấp tỉnh nay được nhận
        assert not is_business_document(24, "tinh")  # vẫn phải đúng lĩnh vực


class _Doc:
    def __init__(self, field, scope):
        self.tvpl_field_code = field
        self.territorial_scope = scope


class TestFilterHelpers:
    def test_filter_business_docs_giu_thu_tu(self):
        docs = [_Doc(6, "trung_uong"), _Doc(24, "trung_uong"),
                _Doc(1, "tinh"), _Doc(10, "trung_uong")]
        kept = filter_business_docs(docs)
        assert [d.tvpl_field_code for d in kept] == [6, 10]

    def test_filter_doc_keys_tu_db(self, master_session):
        # Đặt thẳng tvpl_field_code + territorial_scope bằng UPDATE để tách khỏi
        # bộ phân loại — upsert_document nay tự suy hai cột này (apply_derived_facts).
        from src.storage.database import make_doc_key, upsert_document

        specs = [
            ("10/2026/NĐ-CP", "Chính phủ", 6, "trung_uong"),      # giữ
            ("47/2026/QĐ-UBND", "UBND Sơn La", 24, "tinh"),       # loại (lĩnh vực)
            ("65/2026/QĐ-UBND", "UBND Lai Châu", 1, "tinh"),      # loại (cấp tỉnh)
        ]
        keys = []
        for num, agency, field, scope in specs:
            upsert_document(master_session, {
                "doc_num": num, "title": num, "agency_name": agency})
            master_session.execute(text(
                "UPDATE documents SET tvpl_field_code=:f, territorial_scope=:s "
                "WHERE doc_num=:n"), {"f": field, "s": scope, "n": num})
            keys.append(make_doc_key(num, agency))
        master_session.commit()

        kept = filter_business_doc_keys(master_session, keys)
        assert kept == [keys[0]]


class TestEnqueueLoc:
    def test_van_ban_ngoai_pham_vi_bi_skip_khong_thanh_bao_cao(self, master_session):
        """Chốt chặn: enqueue (b) tự động phải bỏ văn bản y tế và cấp tỉnh."""
        from src.rag.reports.jobs import enqueue_update_reports
        from src.storage.database import make_doc_key, upsert_document

        specs = [
            ("10/2026/NĐ-CP", "Chính phủ", 6, "trung_uong", 2),   # queued
            ("47/2026/QĐ-UBND", "UBND Sơn La", 24, "tinh", 7),    # skip: lĩnh vực
            ("65/2026/QĐ-UBND", "UBND Lai Châu", 1, "tinh", 7),   # skip: cấp tỉnh
        ]
        saved = []
        for num, agency, field, scope, level in specs:
            upsert_document(master_session, {
                "doc_num": num, "title": num, "agency_name": agency})
            master_session.execute(text(
                "UPDATE documents SET tvpl_field_code=:f, territorial_scope=:s "
                "WHERE doc_num=:n"), {"f": field, "s": scope, "n": num})
            # hierarchy_level đi qua saved_docs dict (materiality đọc từ đó), nên
            # không bị apply_derived_facts ghi đè trong luồng enqueue.
            saved.append({"doc_key": make_doc_key(num, agency),
                          "hierarchy_level": level, "event_type": "A",
                          "is_closure_node": False})
        master_session.commit()

        enqueue_update_reports(master_session, saved)
        master_session.commit()

        queued = master_session.execute(text(
            "SELECT subject_keys FROM report_jobs WHERE status='QUEUED'"
        )).scalars().all()
        assert len(queued) == 1
        assert make_doc_key("10/2026/NĐ-CP", "Chính phủ") in queued[0]
        assert "47/2026" not in queued[0] and "65/2026" not in queued[0]

        skips = master_session.execute(text(
            "SELECT trigger_reason FROM report_jobs WHERE status='SKIPPED'"
        )).scalars().all()
        assert any("ngoai_linh_vuc" in r for r in skips)
        assert any("khong_phai_trung_uong" in r for r in skips)
