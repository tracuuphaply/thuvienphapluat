"""Bước ĐỌC — tóm tắt insight từng văn bản trước khi tổng hợp báo cáo.

Lỗi gốc mà bước này chữa: báo cáo chỉ trình bày metadata (số hiệu, cơ quan,
ngày) rồi để người đọc tự mở từng văn bản ra hiểu thêm. Bước này đọc HẾT toàn
văn từng văn bản, chắt ra insight neo vào Điều/Khoản, và cache lại để không
tóm tắt lại cùng một văn bản ở hàng chục báo cáo.
"""
import json
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from src.rag.reports import summarizer as sm
from src.rag.reports.llm import LLMResult, LLMUnavailable


# ── Một insight hợp lệ, dùng lại nhiều nơi ──
GOOD_INSIGHT = {
    "mot_cau": "Quy định điều kiện kinh doanh vận tải.",
    "pham_vi_dieu_chinh": "Doanh nghiệp vận tải hành khách.",
    "noi_dung_chinh": [
        {"dieu_khoan": "Điều 12 khoản 3",
         "quy_dinh": "Vốn tối thiểu 10 tỷ đồng.",
         "y_nghia": "Doanh nghiệp phải bổ sung vốn."},
    ],
    "nghia_vu_moi": ["Nộp báo cáo trước 15/01 (Điều 20)"],
    "moc_thoi_gian": ["01/07/2026 — bắt đầu áp dụng (Điều 45)"],
    "che_tai": [],
    "diem_dang_chu_y": ["Ngưỡng vốn tăng từ 3 tỷ lên 10 tỷ"],
}


def _resp(obj, truncated=False):
    return LLMResult(text=json.dumps(obj, ensure_ascii=False),
                     truncated=truncated, model="test-model")


@dataclass
class FakeDoc:
    doc_key: str
    doc_num: str
    title: str = "Nghị định thử nghiệm"


# ──────────────────────────────────────────────
# Hàm thuần — không gọi mô hình
# ──────────────────────────────────────────────
class TestPureHelpers:
    def test_content_hash_on_dinh_theo_noi_dung(self):
        a = [{"heading": "Điều 1", "content": "abc"}]
        b = [{"heading": "Điều 1", "content": "abc"}]
        c = [{"heading": "Điều 1", "content": "abcd"}]
        assert sm.content_hash(a) == sm.content_hash(b)
        assert sm.content_hash(a) != sm.content_hash(c)

    def test_batches_gom_theo_ngan_sach(self):
        chunks = [{"heading": f"Đ{i}", "content": "x" * 100} for i in range(10)]
        batches = sm._batches(chunks, budget=250)
        assert len(batches) > 1
        assert sum(len(b) for b in batches) == 10  # không mất đoạn nào

    def test_batches_doan_khong_lo_dung_rieng(self):
        chunks = [{"heading": "Đ1", "content": "y" * 1000}]
        assert sm._batches(chunks, budget=100) == [chunks]

    def test_parse_insight_chiu_rac_quanh_json(self):
        raw = "Đây là kết quả:\n```json\n" + json.dumps(GOOD_INSIGHT) + "\n```"
        got = sm.parse_insight(raw)
        assert got["mot_cau"] == GOOD_INSIGHT["mot_cau"]

    def test_parse_insight_bo_khoa_ngoai_schema(self):
        obj = {**GOOD_INSIGHT, "khoa_la": "phải bị loại"}
        got = sm.parse_insight(json.dumps(obj))
        assert "khoa_la" not in got

    def test_parse_insight_khong_co_json_thi_nem(self):
        with pytest.raises(ValueError):
            sm.parse_insight("hoàn toàn không có JSON ở đây")

    def test_clean_ep_truong_mang(self):
        got = sm._clean({"nghia_vu_moi": "một chuỗi", "noi_dung_chinh": []})
        assert got["nghia_vu_moi"] == ["một chuỗi"]

    def test_is_thin_khi_khong_co_noi_dung_chinh(self):
        assert sm._is_thin({"mot_cau": "x", "noi_dung_chinh": []})
        assert not sm._is_thin(GOOD_INSIGHT)


# ──────────────────────────────────────────────
# Tóm tắt một văn bản — có gọi mô hình (đã mock)
# ──────────────────────────────────────────────
class TestSummarizeChunks:
    def test_van_ban_ngan_goi_mot_lan(self):
        chunks = [{"heading": "Điều 1", "content": "Nội dung ngắn."}]
        with patch.object(sm, "call_report_llm", return_value=_resp(GOOD_INSIGHT)) as m:
            got = sm.summarize_chunks(chunks, "10/2026/NĐ-CP", "ND thử")
        assert m.call_count == 1
        assert got["noi_dung_chinh"]

    def test_van_ban_dai_map_reduce(self, monkeypatch):
        # Ép ngân sách nhỏ để buộc cắt thành nhiều mẻ + một lượt hợp nhất.
        monkeypatch.setattr(sm, "CHAR_BUDGET", 150)
        chunks = [{"heading": f"Điều {i}", "content": "z" * 100} for i in range(4)]
        with patch.object(sm, "call_report_llm", return_value=_resp(GOOD_INSIGHT)) as m:
            got = sm.summarize_chunks(chunks, "11/2026/NĐ-CP", "ND dài")
        # nhiều mẻ + 1 lần hợp nhất → gọi nhiều hơn 1 lần
        assert m.call_count >= 3
        assert got["mot_cau"]

    def test_bi_cat_token_coi_la_loi(self):
        chunks = [{"heading": "Điều 1", "content": "x"}]
        with patch.object(sm, "call_report_llm",
                          return_value=_resp(GOOD_INSIGHT, truncated=True)):
            with pytest.raises(LLMUnavailable):
                sm.summarize_chunks(chunks, "12/2026/NĐ-CP", "ND")


# ──────────────────────────────────────────────
# Cache theo doc_key trong rag.db
# ──────────────────────────────────────────────
class TestCache:
    def test_lan_hai_dung_cache_khong_goi_lai(self, rag_db, chunk_factory):
        chunk_factory("20/2026/NĐ-CP", "Điều 1. Nội dung.", chunk_index=0)
        with patch.object(sm, "call_report_llm", return_value=_resp(GOOD_INSIGHT)) as m:
            a = sm.insight_for_document(rag_db, "20/2026/NĐ-CP", "20/2026/NĐ-CP", "ND")
            b = sm.insight_for_document(rag_db, "20/2026/NĐ-CP", "20/2026/NĐ-CP", "ND")
        assert a == b
        assert m.call_count == 1, "lần hai phải lấy từ cache, không gọi mô hình"

    def test_noi_dung_doi_thi_tom_tat_lai(self, rag_db, chunk_factory):
        chunk_factory("21/2026/NĐ-CP", "Điều 1. Bản gốc.", chunk_index=0)
        with patch.object(sm, "call_report_llm", return_value=_resp(GOOD_INSIGHT)) as m:
            sm.insight_for_document(rag_db, "21/2026/NĐ-CP", "21/2026/NĐ-CP", "ND")
            # Ghi đè nội dung đoạn → content_hash đổi → phải gọi lại
            chunk_factory("21/2026/NĐ-CP", "Điều 1. Đã sửa.", chunk_index=0)
            sm.insight_for_document(rag_db, "21/2026/NĐ-CP", "21/2026/NĐ-CP", "ND")
        assert m.call_count == 2

    def test_khong_co_toan_van_tra_none(self, rag_db):
        got = sm.insight_for_document(rag_db, "khong-ton-tai::", "99/2026/NĐ-CP", "X")
        assert got is None


# ──────────────────────────────────────────────
# build_insights — điểm vào cho generators
# ──────────────────────────────────────────────
class TestBuildInsights:
    def test_phan_loai_ba_nhom(self, rag_db, chunk_factory):
        chunk_factory("30/2026/NĐ-CP", "Điều 1. Có nội dung.", chunk_index=0)
        docs = [
            FakeDoc("30/2026/NĐ-CP", "30/2026/NĐ-CP"),   # tóm tắt tốt
            FakeDoc("31/2026/NĐ-CP", "31/2026/NĐ-CP"),   # không có toàn văn
        ]
        with patch.object(sm, "call_report_llm", return_value=_resp(GOOD_INSIGHT)):
            bundle = sm.build_insights(rag_db, docs)
        assert [i["doc_num"] for i in bundle.items] == ["30/2026/NĐ-CP"]
        assert bundle.khong_co_toan_van == ["31/2026/NĐ-CP"]
        assert bundle.loi_tom_tat == []

    def test_loi_tom_tat_khong_lam_hong_ca_lo(self, rag_db, chunk_factory):
        chunk_factory("32/2026/NĐ-CP", "Điều 1. A.", chunk_index=0)
        chunk_factory("33/2026/NĐ-CP", "Điều 1. B.", chunk_index=0)
        docs = [FakeDoc("32/2026/NĐ-CP", "32/2026/NĐ-CP"),
                FakeDoc("33/2026/NĐ-CP", "33/2026/NĐ-CP")]

        def flaky(system, user, **kw):
            # Văn bản 32 hỏng, 33 chạy được.
            if "32/2026" in user:
                raise LLMUnavailable("giả lập lỗi mô hình")
            return _resp(GOOD_INSIGHT)

        with patch.object(sm, "call_report_llm", side_effect=flaky):
            bundle = sm.build_insights(rag_db, docs)
        assert bundle.loi_tom_tat == ["32/2026/NĐ-CP"]
        assert [i["doc_num"] for i in bundle.items] == ["33/2026/NĐ-CP"]

    def test_insight_rong_ruot_vao_loi_tom_tat(self, rag_db, chunk_factory):
        chunk_factory("34/2026/NĐ-CP", "Điều 1. C.", chunk_index=0)
        thin = {"mot_cau": "x", "noi_dung_chinh": []}
        with patch.object(sm, "call_report_llm", return_value=_resp(thin)):
            bundle = sm.build_insights(rag_db, [FakeDoc("34/2026/NĐ-CP", "34/2026/NĐ-CP")])
        assert bundle.items == []
        assert bundle.loi_tom_tat == ["34/2026/NĐ-CP"]

    def test_source_doc_nums_lay_tu_toan_van(self, rag_db, chunk_factory):
        """Số hiệu văn bản cũ bị bãi bỏ nằm trong toàn văn phải được thu về —

        đây là nguồn để cổng trích dẫn không chặn nhầm.
        """
        chunk_factory("35/2026/QĐ-UBND",
                      "Điều 1. Bãi bỏ Quyết định 18/2016/QĐ-UBND và 12/2017/QĐ-UBND.",
                      chunk_index=0)
        with patch.object(sm, "call_report_llm", return_value=_resp(GOOD_INSIGHT)):
            bundle = sm.build_insights(rag_db, [FakeDoc("35/2026/QĐ-UBND", "35/2026/QĐ-UBND")])
        assert "18/2016/QĐ-UBND" in bundle.source_doc_nums
        assert "12/2017/QĐ-UBND" in bundle.source_doc_nums

    def test_source_doc_nums_thu_ca_khi_tom_tat_hong(self, rag_db, chunk_factory):
        """Tóm tắt hỏng vẫn phải thu số hiệu nguồn: số cũ vẫn có thật."""
        chunk_factory("36/2026/QĐ-UBND",
                      "Điều 1. Bãi bỏ Quyết định 09/2015/QĐ-UBND.", chunk_index=0)
        with patch.object(sm, "call_report_llm",
                          side_effect=LLMUnavailable("lỗi")):
            bundle = sm.build_insights(rag_db, [FakeDoc("36/2026/QĐ-UBND", "36/2026/QĐ-UBND")])
        assert bundle.loi_tom_tat == ["36/2026/QĐ-UBND"]
        assert "09/2015/QĐ-UBND" in bundle.source_doc_nums


# ──────────────────────────────────────────────
# Tầng DB
# ──────────────────────────────────────────────
class TestDBLayer:
    def test_full_document_dung_thu_tu(self, rag_db, chunk_factory):
        chunk_factory("40/2026/NĐ-CP", "Điều 2 nội dung", heading="Điều 2", chunk_index=1)
        chunk_factory("40/2026/NĐ-CP", "Điều 1 nội dung", heading="Điều 1", chunk_index=0)
        rows = rag_db.full_document("40/2026/NĐ-CP")
        assert [r["heading"] for r in rows] == ["Điều 1", "Điều 2"]

    def test_luu_va_doc_insight(self, rag_db):
        rag_db.save_document_insight(
            "41/2026/NĐ-CP", "41/2026/NĐ-CP", "hash1", "v1", "m",
            json.dumps(GOOD_INSIGHT, ensure_ascii=False), 500)
        row = rag_db.get_document_insight("41/2026/NĐ-CP")
        assert row["content_hash"] == "hash1"
        assert json.loads(row["insight_json"])["mot_cau"] == GOOD_INSIGHT["mot_cau"]


# ──────────────────────────────────────────────
# Nối vào generators — payload báo cáo phải mang insight
# ──────────────────────────────────────────────
class TestGeneratorWiring:
    """Bằng chứng bước ĐỌC thật sự tới được payload mô hình nhận, không chỉ

    sống trong summarizer. Đây là điều người dùng phàn nàn: báo cáo trước đây
    chỉ có metadata.
    """

    def test_update_context_co_insight_tung_van_ban(
            self, rag_db, master_session):
        from sqlalchemy import text as _text

        from src.rag.reports import generators
        from src.storage.database import make_doc_key, upsert_document

        # van_ban_dan_chieu_khong_lay_duoc() đọc crawl_frontier; bảng này do
        # migration dựng, test master_session chưa có nên tạo rỗng ở đây.
        master_session.execute(_text("CREATE TABLE IF NOT EXISTS crawl_frontier (state TEXT)"))

        upsert_document(master_session, {
            "doc_num": "50/2026/NĐ-CP", "title": "Nghị định điều kiện kinh doanh",
            "agency_name": "Chính phủ", "eff_status": "Còn hiệu lực",
        })
        master_session.commit()
        doc_key = make_doc_key("50/2026/NĐ-CP", "Chính phủ")
        # Chèn đoạn có doc_key khớp — full_document/_dieu_khoan_van_ban tra theo
        # COALESCE(doc_key, doc_num), nên doc_key phải trùng khoá đã chuẩn hoá.
        rag_db.upsert_chunk({
            "doc_num": "50/2026/NĐ-CP", "doc_key": doc_key, "chunk_index": 0,
            "heading": "Điều 12", "content": "Điều 12. Vốn tối thiểu 10 tỷ.",
            "char_count": 30, "content_hash": "h-50-0",
        })

        with patch.object(sm, "call_report_llm", return_value=_resp(GOOD_INSIGHT)):
            report_ctx = generators.build_update_context(
                master_session, rag_db, [doc_key], scorer_version="test")

        payload = report_ctx.payload
        assert "insight_tung_van_ban" in payload
        items = payload["insight_tung_van_ban"]
        assert [i["doc_num"] for i in items] == ["50/2026/NĐ-CP"]
        assert items[0]["noi_dung_chinh"], "insight phải mang nội dung thực chất"
        assert payload["thong_tin_tra_cuu"]["so_van_ban_da_doc_sau"] == 1

    def test_source_citations_gop_ba_nguon(self):
        from src.rag.reports import generators
        payload = {
            "chi_tiet_dieu_khoan_chunks": [
                {"content_excerpt": "Sửa đổi Thông tư 05/2019/TT-BTC."}],
            "van_ban_bi_tac_dong": [
                {"dieu_khoan_cu": [{"content_excerpt": "theo Nghị định 88/2018/NĐ-CP"}]}],
            "bao_cao_goc": "Báo cáo gốc dẫn 22/2023/QH15.",
        }
        allowed = generators._source_citations(
            "Theo Quyết định 27/2018/QĐ-TTg về VSIC.",  # prompt scaffolding
            payload,
            {"18/2016/QĐ-UBND"},                        # source_doc_nums từ toàn văn
        )
        # đủ cả bốn nguồn
        for n in ("27/2018/QĐ-TTg", "05/2019/TT-BTC", "88/2018/NĐ-CP",
                  "22/2023/QH15", "18/2016/QĐ-UBND"):
            assert n in allowed, n
