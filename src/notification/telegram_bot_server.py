"""
Interactive Telegram Bot Server for Legal Document System.

Usage:
  python -m src.notification.telegram_bot_server
"""
import os
import re
import sys
import json
import datetime
import logging
import asyncio
import functools
from pathlib import Path
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from src.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_ADMIN_CHAT_ID,
    DATA_DIR,
)
from src.notification import report_commands
from src.storage.database import get_session
from src.rag.db_rag import RAGDatabase
from src.rag.hybrid_search import hybrid_search
from src.rag.graph_traversal import cascade_retrieve, validate_results
from src.rag.rag_indexer import index_from_phase1
from src.obsidian.vault_syncer import sync as sync_obsidian_vault

logger = logging.getLogger(__name__)

# Initialize RAG Database
rag_db = RAGDatabase()


def _parse_chat_ids(*raw_values: Optional[str]) -> frozenset[str]:
    """Gom các chat_id được phép từ config; hỗ trợ danh sách ngăn bằng dấu phẩy."""
    ids: set[str] = set()
    for raw in raw_values:
        if not raw:
            continue
        for part in str(raw).replace(";", ",").split(","):
            part = part.strip()
            if part:
                ids.add(part)
    return frozenset(ids)


ALLOWED_CHAT_IDS = _parse_chat_ids(TELEGRAM_CHAT_ID, TELEGRAM_ADMIN_CHAT_ID)
ADMIN_CHAT_IDS = _parse_chat_ids(TELEGRAM_ADMIN_CHAT_ID) or ALLOWED_CHAT_IDS

if not ALLOWED_CHAT_IDS:
    logger.warning(
        "TELEGRAM_CHAT_ID và TELEGRAM_ADMIN_CHAT_ID đều trống — bot sẽ TỪ CHỐI mọi "
        "lệnh. Điền ít nhất một chat_id vào .env để dùng được."
    )


def _chat_id_of(update: Update) -> Optional[str]:
    chat = update.effective_chat
    return str(chat.id) if chat else None


async def _deny(update: Update) -> None:
    """Trả lời gọn cho người không có quyền, không lộ cấu trúc nội bộ."""
    target = update.effective_message or (
        update.callback_query.message if update.callback_query else None
    )
    if target:
        await target.reply_text("⛔ Bạn không có quyền sử dụng bot này.")


def restricted(admin: bool = False):
    """Chỉ cho phép các chat_id trong allowlist gọi handler.

    Không có allowlist thì từ chối tất cả — mặc định đóng, vì kho văn bản và
    lệnh /sync đều không nên mở cho người lạ.
    """
    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            # Đọc allowlist tại thời điểm gọi, không chốt cứng lúc import: handler
            # được decorate ngay khi nạp module nên chốt cứng sẽ khiến mọi thay
            # đổi cấu hình sau đó không có tác dụng.
            allowed = ADMIN_CHAT_IDS if admin else ALLOWED_CHAT_IDS
            chat_id = _chat_id_of(update)
            if chat_id not in allowed:
                logger.warning(
                    "Từ chối %s từ chat_id=%s (admin=%s)", handler.__name__, chat_id, admin
                )
                await _deny(update)
                return
            return await handler(update, context)

        return wrapper

    return decorator

@restricted()
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start and /help commands."""
    msg = (
        "🤖 *BỘ NÃO PHÁP LUẬT — TELEGRAM BOT*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Chào mừng bạn! Tôi là trợ lý AI tìm kiếm và tạo báo cáo tuân thủ pháp luật doanh nghiệp.\n\n"
        "📌 *Các Lệnh Khả Dụng:*\n"
        "*Báo cáo*\n"
        "📊 `/baocao` — Điều khiển báo cáo (đặt, xem, huỷ)\n"
        "🏢 `/nganh` — 21 mã ngành VSIC\n"
        "📋 `/hangdoi` — Báo cáo đang chờ và đã xong\n"
        "📄 `/xem <id>` — Chi tiết một báo cáo, tải PDF\n"
        "🗑️ `/huy <id>` — Huỷ báo cáo đang chờ\n"
        "⚙️ `/chay` — Chạy hàng đợi ngay\n\n"
        "*Tra cứu*\n"
        "🔍 `/search <từ khóa>` — Tìm văn bản (vector + BM25)\n"
        "🔗 `/impact <số hiệu>` — Quan hệ dẫn chiếu của một văn bản\n"
        "🔄 `/sync` — Đồng bộ vault và RAG\n"
        "❓ `/help` — Hướng dẫn này\n\n"
        "💡 *Mẹo:* Bạn cũng có thể **gõ trực tiếp câu hỏi** vào ô chat (không cần gõ `/search`), bot sẽ tự tìm kiếm cho bạn!"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("📊 Tạo Báo Cáo Ngành", callback_data="menu_report"),
            InlineKeyboardButton("🏢 Các Ngành Nghề", callback_data="menu_industries"),
        ],
        [
            InlineKeyboardButton("🔄 Đồng bộ Dữ liệu", callback_data="menu_sync"),
            InlineKeyboardButton("🔍 Tìm kiếm Mẫu", callback_data="menu_search_sample"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)

@restricted()
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search command or text search.

    Không dùng parse_mode="Markdown": nội dung do người dùng gõ và số hiệu văn
    bản chứa ký tự đặc biệt của Markdown (*, _, `, [) làm Telegram trả 400 và câu
    trả lời rơi mất. Lấy `msg` từ cả message lẫn callback: nút "Tìm kiếm Mẫu" gọi
    hàm này với update.message = None. Chạy truy xuất trong executor để không
    treo vòng lặp sự kiện (mọi tin nhắn thường đều đổ vào đây).
    """
    msg = update.message or (update.callback_query and update.callback_query.message)
    if msg is None:
        return
    query = " ".join(context.args) if context.args else ""
    if not query:
        await msg.reply_text("⚠️ Vui lòng nhập từ khóa tìm kiếm. Ví dụ: /search kế toán trưởng")
        return

    await msg.reply_text(f"🔍 Đang tìm kiếm: {query}…")
    try:
        # Không truyền embedder thì /search chỉ chạy BM25, mất hẳn tìm kiếm ngữ nghĩa.
        from src.rag.report_generator import _default_embedder
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None,
            lambda: hybrid_search(rag_db, query=query, limit=5,
                                  embedder=_default_embedder()),
        )
        if not results:
            await msg.reply_text("❌ Không tìm thấy văn bản pháp luật phù hợp.")
            return

        lines = [f"🔎 KẾT QUẢ TÌM KIẾM cho “{query}”:", "━" * 18, ""]
        for r in results:
            lines.append(f"📜 {r.doc_num} (điểm {r.final_score:.2f})")
            lines.append(f"📌 {r.heading}")
            lines.append(r.content[:250].replace("\n", " "))
            lines.append("")
        await msg.reply_text("\n".join(lines))
    except Exception as e:
        logger.error(f"Search error: {e}")
        await msg.reply_text("❌ Có lỗi khi tìm kiếm. Vui lòng thử lại sau.")

@restricted()
async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Default handler for non-command text messages — treats text as RAG search query."""
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if text.startswith("/"):
        return
    context.args = text.split()
    await search_command(update, context)

@restricted()
async def baocao_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/baocao [a|b] [mã ngành] — xếp báo cáo vào hàng đợi."""
    args = context.args or []
    with get_session() as session:
        if not args:
            kq = report_commands.huong_dan(session)
        else:
            kq = report_commands.xep_bao_cao(
                session, args[0], args[1] if len(args) > 1 else "")
            session.commit()
    await _tra_loi(update, kq)


@restricted()
async def nganh_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/nganh — 21 ngành VSIC."""
    await _tra_loi(update, report_commands.danh_sach_nganh())


@restricted()
async def hangdoi_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/hangdoi — báo cáo đang chờ, đang chạy, vừa xong."""
    with get_session() as session:
        kq = report_commands.danh_sach_hang_doi(session)
    await _tra_loi(update, kq)


@restricted()
async def xem_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/xem <id> — chi tiết một báo cáo, kèm PDF nếu có."""
    job_id = _so_nguyen(context.args)
    if job_id is None:
        await update.message.reply_text(
            "⚠️ Thiếu số hiệu báo cáo.\nVí dụ: `/xem 12`", parse_mode="Markdown")
        return
    with get_session() as session:
        kq = report_commands.chi_tiet_job(session, job_id)
    await _tra_loi(update, kq)


@restricted()
async def huy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/huy <id> — huỷ báo cáo đang chờ."""
    job_id = _so_nguyen(context.args)
    if job_id is None:
        await update.message.reply_text(
            "⚠️ Thiếu số hiệu báo cáo.\nVí dụ: `/huy 12`", parse_mode="Markdown")
        return
    with get_session() as session:
        kq = report_commands.huy_job(session, job_id)
    await _tra_loi(update, kq)


@restricted(admin=True)
async def chay_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/chay — rút hàng đợi ngay, không đợi lịch.

    Chạy trong executor: một job gọi mô hình mất tới 300 giây, làm trong vòng
    lặp sự kiện thì bot đứng im, không nhận được cả lệnh /hangdoi.
    """
    await update.message.reply_text("⚙️ Đang chạy hàng đợi báo cáo…")

    def _chay():
        from src.config import impact_scorer_version
        from src.rag.reports import worker
        with get_session() as session:
            return worker.drain(session, rag_db, impact_scorer_version())

    loop = asyncio.get_running_loop()
    try:
        stats = await loop.run_in_executor(None, _chay)
        d = stats.as_dict() if hasattr(stats, "as_dict") else dict(stats)
        await update.message.reply_text(
            "✅ *Chạy xong hàng đợi*\n\n"
            f"Lấy ra: {d.get('picked', 0)} · Xong: {d.get('done', 0)} · "
            f"Lỗi: {d.get('failed', 0)} · Bị chặn: {d.get('blocked', 0)}\n\n"
            "Gõ `/hangdoi` để xem kết quả.",
            parse_mode="Markdown")
    except Exception:
        # Chi tiết vào log, KHÔNG vào chat: exception của SQLAlchemy và httpx
        # mang theo đường dẫn tuyệt đối, tên bảng và đôi khi cả URL kèm khoá.
        logger.exception("Lỗi chạy hàng đợi báo cáo")
        await update.message.reply_text(
            "❌ Hàng đợi chạy lỗi. Chi tiết đã ghi vào log của máy chủ.")


def _so_nguyen(args) -> int | None:
    try:
        return int((args or [""])[0])
    except (ValueError, IndexError):
        return None


async def _tra_loi(update: Update, kq) -> None:
    """Gửi kết quả một lệnh: chuỗi, rồi file đính kèm nếu có."""
    msg = update.message or (update.callback_query and update.callback_query.message)
    if msg is None:
        return
    try:
        await msg.reply_text(kq.van_ban, parse_mode="Markdown")
    except Exception:
        # Markdown hỏng không được nuốt mất nội dung — gửi lại dạng thô.
        await msg.reply_text(kq.van_ban)

    for duong_dan in [kq.file_dinh_kem, *getattr(kq, "file_bo_sung", [])]:
        if not duong_dan:
            continue
        p = Path(duong_dan)
        with open(p, "rb") as f:
            await msg.reply_document(document=f, filename=p.name)


@restricted()
async def impact_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /impact <doc_num> command."""
    doc_num = " ".join(context.args) if context.args else ""
    if not doc_num:
        await update.message.reply_text("⚠️ Vui lòng nhập số hiệu văn bản. Ví dụ: /impact 101/2026/TT-BTC")
        return

    await update.message.reply_text(f"🔗 Đang phân tích quan hệ dẫn chiếu cho: {doc_num}…")
    try:
        # Chạy trong executor: cascade_retrieve truy vấn đồ thị, không được treo
        # vòng lặp sự kiện. Không dùng Markdown: số hiệu chứa ký tự đặc biệt.
        loop = asyncio.get_running_loop()
        edges = await loop.run_in_executor(
            None, lambda: cascade_retrieve(rag_db, doc_num, max_depth=2))
        if not edges:
            await update.message.reply_text(
                f"ℹ️ Không thấy quan hệ dẫn chiếu nào cho văn bản {doc_num} trong đồ thị.")
            return

        lines = [f"🕸️ QUAN HỆ DẪN CHIẾU của {doc_num}:", "━" * 18, ""]
        for e in edges:
            lines.append(f"• {e.source} [{e.relation}] → {e.target}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        logger.error(f"Impact analysis error: {e}")
        await update.message.reply_text("❌ Lỗi khi phân tích tác động. Vui lòng thử lại sau.")

@restricted(admin=True)
async def sync_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /sync command — runs vault sync and RAG indexing in background thread."""
    await update.message.reply_text("🔄 Bắt đầu đồng bộ Obsidian Vault và RAG Database...", parse_mode="Markdown")
    
    def _run_sync_task():
        try:
            sync_obsidian_vault()
            index_from_phase1(None, rag_db)
            return True, "✅ Đồng bộ hoàn tất thành công!"
        except Exception as e:
            return False, f"❌ Lỗi đồng bộ: {e}"
            
    loop = asyncio.get_running_loop()
    success, msg = await loop.run_in_executor(None, _run_sync_task)
    await update.message.reply_text(msg, parse_mode="Markdown")

@restricted()
async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button callback queries."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if data == "menu_report" or data == "menu_industries":
        await nganh_command(update, context)
    elif data == "menu_sync":
        await query.message.reply_text("🔄 Bắt đầu đồng bộ dữ liệu...")
        def _run_sync():
            sync_obsidian_vault()
            index_from_phase1(None, rag_db)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _run_sync)
        await query.message.reply_text("✅ Đồng bộ hoàn tất!")
    elif data == "menu_search_sample":
        context.args = ["quy định", "xử", "phạt"]
        await search_command(update, context)
    elif data.startswith("rpt_"):
        # Nút mang MÃ ngành VSIC (một chữ cái), không phải tên ngành của bộ 10
        # ngành cũ. Và nó XẾP HÀNG chứ không sinh tại chỗ — xem report_commands.
        with get_session() as session:
            kq = report_commands.xep_bao_cao(session, "a", data.replace("rpt_", ""))
            session.commit()
        await _tra_loi(update, kq)

def main() -> None:
    """Start the interactive Telegram Bot server."""
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not configured in .env!")
        sys.exit(1)
        
    print("=" * 60)
    print("🚀 Khởi chạy Interactive Telegram Bot Server...")
    print(f"Token: {TELEGRAM_BOT_TOKEN[:10]}...")
    print("=" * 60)
    
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Handlers
    app.add_handler(CommandHandler(["start", "help"], start_command))
    app.add_handler(CommandHandler("search", search_command))
    # /report và /industries giữ làm bí danh: người dùng đã quen gõ chúng, và
    # lệnh cũ im lặng biến mất thì trông như bot hỏng.
    app.add_handler(CommandHandler(["baocao", "report"], baocao_command))
    app.add_handler(CommandHandler(["nganh", "industries"], nganh_command))
    app.add_handler(CommandHandler("hangdoi", hangdoi_command))
    app.add_handler(CommandHandler("xem", xem_command))
    app.add_handler(CommandHandler("huy", huy_command))
    app.add_handler(CommandHandler("chay", chay_command))
    app.add_handler(CommandHandler("impact", impact_command))
    app.add_handler(CommandHandler(["sync", "run"], sync_command))
    
    # Callback queries (inline buttons)
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    
    # Text message fallback (search query)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    
    print("✅ Bot server đã sẵn sàng nhận tin nhắn trên Telegram!")
    app.run_polling()

if __name__ == "__main__":
    main()
