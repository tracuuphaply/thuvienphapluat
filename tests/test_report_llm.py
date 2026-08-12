"""Gọi mô hình sinh báo cáo — thử lại lỗi TẠM THỜI, không thử lại lỗi nội dung.

Nhà cung cấp LLM (reseller) hay chớp tắt: DNS không phân giải, đứt kết nối, 503,
429. Không thử lại thì một cái nấc mạng đánh hỏng cả báo cáo — với bot Telegram
tạo báo cáo thật, đó là hỏng nhìn thấy được. Nhưng thử lại 400/401 chỉ tốn thời
gian, nên phải phân biệt.
"""
from unittest.mock import patch

import httpx
import pytest

from src.rag.reports import llm
from src.rag.reports.llm import LLMUnavailable, call_report_llm


class FakeResp:
    def __init__(self, status=200, content="Báo cáo OK", finish="stop"):
        self.status_code = status
        self._content = content
        self._finish = finish

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("POST", "http://x"),
                response=self,
            )

    def json(self):
        return {"choices": [{"message": {"content": self._content},
                             "finish_reason": self._finish}]}


@pytest.fixture(autouse=True)
def _key_and_nosleep(monkeypatch):
    monkeypatch.setenv("V98_API_KEY", "test-key")
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)  # không chờ thật


def test_503_roi_thanh_cong_thi_thu_lai(monkeypatch):
    calls = [FakeResp(503), FakeResp(200, content="Xong")]
    with patch.object(llm.httpx, "post", side_effect=calls) as m:
        out = call_report_llm("sys", "user")
    assert m.call_count == 2
    assert out.text == "Xong"


def test_dns_dut_ket_noi_duoc_thu_lai(monkeypatch):
    # ConnectError phủ luôn "nodename nor servname" (DNS) — đúng lỗi đã gặp thật.
    seq = [httpx.ConnectError("nodename nor servname"), FakeResp(200)]
    with patch.object(llm.httpx, "post", side_effect=seq) as m:
        out = call_report_llm("sys", "user")
    assert m.call_count == 2
    assert out.text == "Báo cáo OK"


def test_het_luot_thi_nem_llm_unavailable(monkeypatch):
    with patch.object(llm.httpx, "post",
                      side_effect=httpx.ReadTimeout("quá lâu")) as m:
        with pytest.raises(LLMUnavailable):
            call_report_llm("sys", "user")
    assert m.call_count == llm.RETRY_ATTEMPTS  # đã thử đủ số lần


def test_400_khong_thu_lai(monkeypatch):
    """Lỗi nội dung (400) thử lại chỉ tốn thời gian — phải nổ ngay."""
    with patch.object(llm.httpx, "post", side_effect=[FakeResp(400)]) as m:
        with pytest.raises(LLMUnavailable):
            call_report_llm("sys", "user")
    assert m.call_count == 1


def test_thieu_khoa_nem_ngay(monkeypatch):
    monkeypatch.delenv("V98_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(LLMUnavailable):
        call_report_llm("sys", "user")
