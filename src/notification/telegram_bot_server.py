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
from src.obsidian.config_obsidian import INDUSTRY_MAP
from src.rag.db_rag import RAGDatabase
from src.rag.hybrid_search import hybrid_search
from src.rag.graph_traversal import cascade_retrieve, validate_results
from src.rag.report_generator import generate_compliance_report
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
        "🔍 `/search <từ khóa>` — Tìm kiếm văn bản bằng Hybrid RAG (Vector + BM25)\n"
        "📊 `/report` — Tạo báo cáo tuân thủ AI theo ngành nghề\n"
        "🔗 `/impact <số hiệu>` — Phân tích tác động đồ thị luật (GraphRAG)\n"
        "🔄 `/sync` — Chạy đồng bộ cào luật 2026 + Obsidian Vault + RAG DB\n"
        "🏢 `/industries` — Xem danh sách 10 ngành nghề kinh doanh\n"
        "❓ `/help` — Hiển thị hướng dẫn này\n\n"
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
async def industries_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List available industries with inline buttons."""
    msg = "🏢 *DANH SÁCH 10 NGÀNH NGHỀ KINH DOANH*\n\nBấm vào ngành bên dưới để tạo báo cáo tuân thủ AI ngay lập tức:\n\n"
    
    keyboard = []
    for idx, ind_name in enumerate(INDUSTRY_MAP.keys()):
        msg += f"{idx+1}. `{ind_name}`\n"
        keyboard.append([InlineKeyboardButton(f"📊 Báo cáo: {ind_name}", callback_data=f"rpt_{ind_name}")])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    if update.message:
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.reply_text(msg, parse_mode="Markdown", reply_markup=reply_markup)

@restricted()
async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search command or text search."""
    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.message.reply_text("⚠️ Vui lòng nhập từ khóa tìm kiếm.\nVí dụ: `/search kế toán trưởng`", parse_mode="Markdown")
        return
        
    await update.message.reply_text(f"🔍 Đang tìm kiếm thông tin cho: *{query}*...", parse_mode="Markdown")
    
    try:
        # Không truyền embedder thì /search chỉ chạy BM25, mất hẳn tìm kiếm ngữ nghĩa.
        from src.rag.report_generator import _default_embedder
        results = hybrid_search(rag_db, query=query, limit=5, embedder=_default_embedder())
        if not results:
            await update.message.reply_text("❌ Không tìm thấy văn bản pháp luật phù hợp.")
            return
            
        msg = f"🔎 *KẾT QUẢ TÌM KIẾM cho '{query}':*\n━━━━━━━━━━━━━━━━━━━━━\n\n"
        for r in results:
            score_fmt = f"{r.final_score:.2f}"
            msg += f"📜 *{r.doc_num}* (Điểm: `{score_fmt}`)\n"
            msg += f"📌 *{r.heading}*\n"
            content_snippet = r.content[:250].replace('\n', ' ')
            msg += f"_{content_snippet}_\n\n"
            
        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Search error: {e}")
        await update.message.reply_text("❌ Có lỗi khi tìm kiếm. Vui lòng thử lại sau.")

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
async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /report command."""
    industry = " ".join(context.args) if context.args else ""
    if not industry:
        # Show industry selection menu
        await industries_command(update, context)
        return
        
    await _generate_and_send_report(update.message, industry)

@restricted()
async def impact_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /impact <doc_num> command."""
    doc_num = " ".join(context.args) if context.args else ""
    if not doc_num:
        await update.message.reply_text("⚠️ Vui lòng nhập số hiệu văn bản.\nVí dụ: `/impact 101/2026/TT-BTC`", parse_mode="Markdown")
        return
        
    await update.message.reply_text(f"🔗 Đang phân tích tác động đồ thị luật GraphRAG cho: *{doc_num}*...", parse_mode="Markdown")
    
    try:
        edges = cascade_retrieve(rag_db, doc_num, max_depth=2)
        if not edges:
            await update.message.reply_text(f"ℹ️ Không thấy quan hệ tác động trực tiếp nào cho văn bản `{doc_num}` trong đồ thị.", parse_mode="Markdown")
            return
            
        msg = f"🕸️ *TÁC ĐỘNG ĐỒ THỊ LUẬT (GraphRAG) cho {doc_num}:*\n━━━━━━━━━━━━━━━━━━━━━\n\n"
        for e in edges:
            msg += f"• *{e.source}* `[{e.relation}]` → *{e.target}*\n"
            
        await update.message.reply_text(msg, parse_mode="Markdown")
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
    
    data = query.data
    if data == "menu_report" or data == "menu_industries":
        await industries_command(update, context)
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
        industry_name = data.replace("rpt_", "")
        await _generate_and_send_report(query.message, industry_name)

async def _generate_and_send_report(message_obj, industry_name: str) -> None:
    """Helper to generate AI compliance report, convert to PDF, and send both text summary and PDF file to Telegram chat."""
    await message_obj.reply_text(f"📊 Đang tạo báo cáo tuân thủ AI & file PDF cho ngành *{industry_name}* (vui lòng đợi 10-15s)...", parse_mode="Markdown")
    
    from src.utils.pdf_exporter import convert_md_to_pdf

    def _make_report_and_pdf():
        report_md = generate_compliance_report(rag_db, industry=industry_name, days=250)
        pdf_path = convert_md_to_pdf(report_md, report_title=f"BÁO CÁO PHÁP LÝ CHUYÊN ĐỀ — NGÀNH {industry_name.upper()}")
        return report_md, pdf_path
        
    loop = asyncio.get_running_loop()
    try:
        report_md, pdf_path = await loop.run_in_executor(None, _make_report_and_pdf)
        
        # 1. Send text preview / chunks
        from src.notification.telegram_bot import _split_message
        chunks = _split_message(report_md, max_len=3800)
        for chunk in chunks:
            try:
                await message_obj.reply_text(chunk, parse_mode="Markdown")
            except Exception:
                await message_obj.reply_text(chunk)

        # 2. Send attached PDF file
        if pdf_path and pdf_path.exists():
            clean_ind_filename = re.sub(r"[^\w\-_]", "_", industry_name)
            pdf_filename = f"Bao_Cao_Phap_Ly_{clean_ind_filename}_{datetime.date.today().strftime('%Y%m%d')}.pdf"
            with open(pdf_path, "rb") as f:
                await message_obj.reply_document(
                    document=f,
                    filename=pdf_filename,
                    caption=f"📄 *File PDF Báo cáo Pháp lý Chuyên đề Ngành {industry_name}*"
                )
    except Exception as e:
        logger.error(f"Error generating report or PDF: {e}")
        await message_obj.reply_text("❌ Lỗi khi tạo báo cáo. Vui lòng thử lại sau.")


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
    app.add_handler(CommandHandler("industries", industries_command))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("report", report_command))
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
