"""Đề xuất #7 — bot phải xác thực người gửi và không được thiếu import.

Lỗi gốc:
  - Không có bất kỳ kiểm tra chat_id nào; TELEGRAM_ADMIN_CHAT_ID được import
    nhưng không dùng ở đâu. Ai tìm thấy bot cũng đọc được cả kho và chạy /sync.
  - Thiếu `import re` và `import datetime` → /report luôn ném NameError khi
    đính kèm PDF, nên file PDF chưa bao giờ gửi được.
"""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

SERVER = Path("src/notification/telegram_bot_server.py")


async def _async_noop(*args, **kwargs):
    """reply_text giả — phải là coroutine vì handler dùng await."""
    return None


class TestImportsDayDu:
    def test_moi_ten_module_dung_deu_da_duoc_import(self):
        tree = ast.parse(SERVER.read_text(encoding="utf-8"))
        imported = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    imported.add((a.asname or a.name).split(".")[0])
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    imported.add(a.asname or a.name)

        for mod in ("re", "datetime", "functools"):
            used = any(
                isinstance(n, ast.Name) and n.id == mod for n in ast.walk(tree)
            )
            if used:
                assert mod in imported, f"dùng {mod} nhưng chưa import"

    def test_module_import_duoc(self):
        import src.notification.telegram_bot_server as srv
        assert srv is not None


class TestAllowlist:
    def test_gom_nhieu_chat_id_ngan_bang_phay(self):
        from src.notification.telegram_bot_server import _parse_chat_ids
        assert _parse_chat_ids("111,222 , 333") == frozenset({"111", "222", "333"})

    def test_bo_qua_gia_tri_rong(self):
        from src.notification.telegram_bot_server import _parse_chat_ids
        assert _parse_chat_ids(None, "", "  ") == frozenset()

    def test_chat_id_ngoai_danh_sach_bi_tu_choi(self, monkeypatch):
        import src.notification.telegram_bot_server as srv

        monkeypatch.setattr(srv, "ALLOWED_CHAT_IDS", frozenset({"999"}))
        goi = []

        @srv.restricted()
        async def handler(update, context):
            goi.append(True)

        replies = []
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=12345),
            effective_message=SimpleNamespace(
                reply_text=lambda t, **k: asyncio.sleep(0, result=replies.append(t))
            ),
            callback_query=None,
        )
        asyncio.run(handler(update, None))

        assert goi == [], "handler vẫn chạy dù chat_id không được phép"
        assert replies and "không có quyền" in replies[0]

    def test_chat_id_hop_le_duoc_di_qua(self, monkeypatch):
        import src.notification.telegram_bot_server as srv

        monkeypatch.setattr(srv, "ALLOWED_CHAT_IDS", frozenset({"999"}))
        goi = []

        @srv.restricted()
        async def handler(update, context):
            goi.append(True)

        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=999),
            effective_message=SimpleNamespace(reply_text=_async_noop),
            callback_query=None,
        )
        asyncio.run(handler(update, None))
        assert goi == [True]

    def test_khong_co_allowlist_thi_tu_choi_tat_ca(self, monkeypatch):
        """Mặc định đóng: cấu hình trống không được biến bot thành công khai."""
        import src.notification.telegram_bot_server as srv

        monkeypatch.setattr(srv, "ALLOWED_CHAT_IDS", frozenset())
        goi = []

        @srv.restricted()
        async def handler(update, context):
            goi.append(True)

        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=1),
            effective_message=SimpleNamespace(reply_text=_async_noop),
            callback_query=None,
        )
        asyncio.run(handler(update, None))
        assert goi == []

    def test_sync_chi_danh_cho_admin(self, monkeypatch):
        import src.notification.telegram_bot_server as srv

        monkeypatch.setattr(srv, "ADMIN_CHAT_IDS", frozenset({"777"}))
        goi = []

        @srv.restricted(admin=True)
        async def handler(update, context):
            goi.append(True)

        # người dùng thường (không phải admin) bị chặn
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=111),
            effective_message=SimpleNamespace(reply_text=_async_noop),
            callback_query=None,
        )
        asyncio.run(handler(update, None))
        assert goi == []


class TestMoiHandlerDeuDuocBaoVe:
    def test_khong_handler_nao_bi_bo_sot(self):
        tree = ast.parse(SERVER.read_text(encoding="utf-8"))
        handlers = {
            "start_command", "industries_command", "search_command",
            "text_message_handler", "report_command", "impact_command",
            "sync_command", "callback_query_handler",
        }
        found = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in handlers:
                found[node.name] = [
                    d.func.id if isinstance(d, ast.Call) else getattr(d, "id", "")
                    for d in node.decorator_list
                ]
        assert set(found) == handlers, f"thiếu handler: {handlers - set(found)}"
        for name, decs in found.items():
            assert "restricted" in decs, f"{name} chưa được bảo vệ bằng @restricted"


class TestKhongRoRiLoiNoiBo:
    def test_khong_day_chi_tiet_exception_ra_chat(self):
        """Lỗi chi tiết lộ đường dẫn tuyệt đối và cấu trúc bảng cho người lạ."""
        src = SERVER.read_text(encoding="utf-8")
        assert 'reply_text(f"❌' not in src, "vẫn còn nội suy exception vào tin nhắn"


class TestGraphEdgeAttributes:
    def test_impact_dung_dung_ten_thuoc_tinh(self):
        """GraphEdge khai .source/.target/.relation — bản cũ đọc *_doc_num nên luôn crash."""
        from src.rag.graph_traversal import GraphEdge
        e = GraphEdge("A", "B", "Bãi bỏ", 1.0)
        assert (e.source, e.target, e.relation) == ("A", "B", "Bãi bỏ")

        src = SERVER.read_text(encoding="utf-8")
        assert "e.source_doc_num" not in src
        assert "e.source" in src
