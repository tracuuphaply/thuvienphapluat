"""Đề xuất #2 và #6 — báo cáo không được bịa hiệu lực, không được sinh từ ngữ cảnh rỗng.

Lỗi gốc:
  - `doc.eff_status or "Còn hiệu lực"` khiến 80/314 văn bản (25%) không rõ trạng
    thái bị khẳng định là còn hiệu lực trong báo cáo gửi khách.
  - Không có chốt chặn khi truy xuất rỗng: 4/10 ngành ra 0 chunk mà vẫn gọi LLM.
  - Thiếu mẫu prompt thì im lặng dùng prompt một dòng, mất toàn bộ cấu trúc bắt buộc.
"""
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.rag import report_generator as rg
from src.storage.database import upsert_document


class TestLoadSystemPrompt:
    def test_doc_duoc_mau_trong_repo(self):
        prompt = rg.load_system_prompt()
        assert "VAI TRÒ" in prompt
        assert len(prompt) > 5000, "mẫu prompt bị cắt cụt"

    def test_mau_prompt_co_du_cac_muc_bat_buoc(self):
        prompt = rg.load_system_prompt()
        for muc in ("CẤU TRÚC BẮT BUỘC", "QUY ƯỚC MARKDOWN", "ĐIỀU CẤM"):
            assert muc in prompt, f"thiếu mục {muc}"

    def test_thieu_mau_thi_bao_loi_chu_khong_im_lang(self, tmp_path, monkeypatch):
        """Sinh báo cáo bằng prompt rút gọn mà không báo gì là tệ hơn thất bại."""
        monkeypatch.setenv("REPORT_PROMPT_PATH", str(tmp_path / "khong-ton-tai.md"))
        monkeypatch.setattr(rg, "REPO_PROMPT_PATH", tmp_path / "cung-khong-co.md")
        with pytest.raises(rg.PromptTemplateMissing):
            rg.load_system_prompt()

    def test_khong_hardcode_duong_dan_ca_nhan(self):
        src = Path("src/rag/report_generator.py").read_text(encoding="utf-8")
        assert "/Users/lenhatminh/Downloads/prompt" not in src


class TestEmptyRetrievalGuard:
    def test_khong_goi_LLM_khi_khong_co_du_lieu(self, rag_db):
        """Ngữ cảnh rỗng + LLM = báo cáo trông có thẩm quyền mà không có căn cứ.

        Chỉ xét endpoint sinh báo cáo: nhánh nhúng câu truy vấn cũng dùng
        httpx.post nên không thể assert_not_called() trên toàn bộ.
        """
        with patch("httpx.post") as mock_post:
            out = rg.generate_compliance_report(rag_db, industry="Ngành trống rỗng xyz")

        goi_llm = [
            c for c in mock_post.call_args_list
            if "chat/completions" in str(c.args[0] if c.args else c.kwargs.get("url", ""))
        ]
        assert not goi_llm, "vẫn gọi LLM dù không truy xuất được gì"
        assert "KHÔNG ĐỦ DỮ LIỆU" in out

    def test_bao_cao_rong_noi_ro_ly_do(self, rag_db):
        out = rg.generate_compliance_report(rag_db, industry="Ngành trống rỗng xyz")
        assert "không trả về điều khoản nào" in out.lower()
        assert "Cần kiểm tra" in out


class TestEffStatusKhongBiBia:
    def test_khong_mac_dinh_con_hieu_luc(self, rag_db, chunk_factory, master_session, monkeypatch):
        """Thiếu trạng thái phải hiện là 'Chưa xác định', không phải 'Còn hiệu lực'."""
        chunk_factory("77/2026/NĐ-CP", "Quy định về khám bệnh chữa bệnh và thuốc dược phẩm")
        upsert_document(master_session, {
            "doc_num": "77/2026/NĐ-CP", "title": "Nghị định không rõ hiệu lực",
            "eff_status": None,
        })
        master_session.commit()

        from contextlib import contextmanager

        @contextmanager
        def fake_session():
            yield master_session

        monkeypatch.setattr(rg, "get_session", fake_session)

        captured = {}

        class FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["payload"] = json
            return FakeResp()

        monkeypatch.setenv("V98_API_KEY", "test-key")
        with patch("httpx.post", side_effect=fake_post):
            rg.generate_compliance_report(rag_db, industry="Y tế và trợ giúp xã hội")

        user_msg = captured["payload"]["messages"][1]["content"]
        assert '"eff_status": "Chưa xác định"' in user_msg
        assert '"eff_status": "Còn hiệu lực"' not in user_msg

    def test_khoi_han_che_du_lieu_duoc_gui_kem(self, rag_db, chunk_factory, master_session, monkeypatch):
        chunk_factory("78/2026/NĐ-CP", "Quy định về khám bệnh chữa bệnh và thuốc dược phẩm")
        upsert_document(master_session, {
            "doc_num": "78/2026/NĐ-CP", "title": "ND", "eff_status": None,
        })
        master_session.commit()

        from contextlib import contextmanager

        @contextmanager
        def fake_session():
            yield master_session

        monkeypatch.setattr(rg, "get_session", fake_session)
        captured = {}

        class FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]}

        monkeypatch.setenv("V98_API_KEY", "test-key")
        with patch("httpx.post", side_effect=lambda url, headers=None, json=None, timeout=None: (
            captured.update(payload=json), FakeResp())[1]):
            rg.generate_compliance_report(rag_db, industry="Y tế và trợ giúp xã hội")

        user_msg = captured["payload"]["messages"][1]["content"]
        assert "han_che_du_lieu" in user_msg
        assert "so_van_ban_khong_ro_trang_thai_hieu_luc" in user_msg
        assert "pham_vi_thoi_gian_thuc_te" in user_msg


class TestTruncationDetection:
    def test_bao_cao_bi_cat_duoc_canh_bao(self, rag_db, chunk_factory, monkeypatch):
        chunk_factory("79/2026/NĐ-CP", "Quy định về khám bệnh chữa bệnh và thuốc dược phẩm")

        class FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{
                    "message": {"content": "# Báo cáo dở dang"},
                    "finish_reason": "length",
                }]}

        monkeypatch.setenv("V98_API_KEY", "test-key")
        with patch("httpx.post", return_value=FakeResp()):
            out = rg.generate_compliance_report(rag_db, industry="Y tế và trợ giúp xã hội")
        assert "bị cắt" in out.lower()

    def test_bao_cao_du_thi_khong_them_canh_bao(self, rag_db, chunk_factory, monkeypatch):
        chunk_factory("80/2026/NĐ-CP", "Quy định về khám bệnh chữa bệnh và thuốc dược phẩm")

        class FakeResp:
            def raise_for_status(self): pass
            def json(self):
                return {"choices": [{
                    "message": {"content": "# Báo cáo đầy đủ"},
                    "finish_reason": "stop",
                }]}

        monkeypatch.setenv("V98_API_KEY", "test-key")
        with patch("httpx.post", return_value=FakeResp()):
            out = rg.generate_compliance_report(rag_db, industry="Y tế và trợ giúp xã hội")
        assert "bị cắt" not in out.lower()


class TestGraphDuocDungThatSu:
    def test_report_generator_co_goi_validate_results(self):
        """Bản cũ import validate_results rồi không gọi — lưới an toàn là code chết."""
        src = Path("src/rag/report_generator.py").read_text(encoding="utf-8")
        assert "validate_results(db" in src, "validate_results vẫn chưa được gọi"

    def test_lay_quan_he_ca_hai_chieu(self):
        src = Path("src/rag/report_generator.py").read_text(encoding="utf-8")
        assert "DocumentReference.target_doc_num == doc.doc_num" in src, \
            "thiếu truy vấn chiều ngược: không biết văn bản bị ai tác động"


class TestKhongConCTA:
    """CTA đã được gỡ khỏi mẫu báo cáo pháp lý theo yêu cầu.

    Báo cáo giữ đúng vai trò tài liệu pháp lý; phần mời gọi chuyển sang nội dung
    email chứ không nằm trong file PDF.
    """

    def test_bo_render_khong_con_ham_cta(self):
        import src.utils.report_pdf as rp
        assert not hasattr(rp, "_cta")

    def test_script_khong_con_cta_block(self):
        import scripts.generate_industry_reports as g
        assert not hasattr(g, "cta_block")

    def test_ReportMeta_khong_con_truong_cta(self):
        from dataclasses import fields
        from src.utils.report_pdf import ReportMeta
        ten = {f.name for f in fields(ReportMeta)}
        assert not (ten & {"cta_title", "cta_body", "website", "email", "phone"})

    def test_thong_tin_lien_he_van_o_chan_trang(self):
        """Gỡ CTA không được làm mất luôn thông tin liên hệ ở chân trang."""
        from dataclasses import fields
        from src.utils.report_pdf import ReportMeta
        assert "contact" in {f.name for f in fields(ReportMeta)}

    def test_prompt_cam_mo_hinh_tu_viet_khoi_moi_goi(self):
        """Gỡ CTA ở tầng dựng PDF là chưa đủ — mô hình vẫn có thể tự viết ra."""
        prompt = rg.load_system_prompt()
        assert "Không viết khối kêu gọi liên hệ" in prompt
