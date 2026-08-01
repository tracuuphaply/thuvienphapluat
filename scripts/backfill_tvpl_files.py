"""
Tải bù file .docx/.pdf từ TVPL cho các văn bản đã có trong database.

Dùng khi những lần chạy trước không tải được file (bị Cloudflare chặn, chưa cấu
hình Chrome, mất mạng…) nhưng metadata và toàn văn đã có sẵn.

Chạy:
    python scripts/backfill_tvpl_files.py            # tất cả văn bản còn thiếu
    python scripts/backfill_tvpl_files.py --limit 10 # chạy thử 10 văn bản

File tải xong được đẩy thẳng vào đúng thư mục Lark Drive của văn bản đó.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import AUTO_CLEANUP_LOCAL_FILES, LARK_APP_ID  # noqa: E402
from src.sources.tvpl_downloader import download_documents_sync  # noqa: E402
from src.storage.database import get_session, init_db  # noqa: E402
from src.storage.file_store import save_document_metadata  # noqa: E402
from src.storage.lark_drive import (  # noqa: E402
    get_lark_client,
    upload_document_files_lark,
)
from src.storage.models import Document  # noqa: E402

logger = logging.getLogger("backfill")


def main() -> int:
    parser = argparse.ArgumentParser(description="Tải bù file TVPL cho văn bản đã có")
    parser.add_argument("--limit", type=int, default=0, help="Chỉ xử lý N văn bản đầu")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    init_db()

    with get_session() as session:
        pending = (
            session.query(Document)
            .filter(Document.docx_path.is_(None))
            .filter(Document.tvpl_url.isnot(None))
            .filter(Document.tvpl_id.isnot(None))
            .all()
        )
        if args.limit:
            pending = pending[: args.limit]

        if not pending:
            logger.info("Không có văn bản nào cần tải bù.")
            return 0

        logger.info("Cần tải bù %d văn bản.", len(pending))

        targets = [
            {"tvpl_url": doc.tvpl_url, "tvpl_id": doc.tvpl_id} for doc in pending
        ]
        results = {
            str(r.get("tvpl_id")): r for r in download_documents_sync(targets)
        }

        client = get_lark_client() if LARK_APP_ID else None
        downloaded = uploaded = 0

        for doc in pending:
            result = results.get(str(doc.tvpl_id))
            if not result or not result.get("success"):
                continue

            if result.get("docx_path"):
                doc.docx_path = result["docx_path"]
                doc.has_docx = True
            if result.get("pdf_path"):
                doc.pdf_path = result["pdf_path"]
                doc.has_pdf = True
            downloaded += 1
            session.commit()

            if not client:
                continue

            doc_data = {
                col.name: getattr(doc, col.name) for col in Document.__table__.columns
            }
            doc_data["metadata_path"] = save_document_metadata(doc_data)

            try:
                if doc.lark_folder_token:
                    # Văn bản đã có thư mục trên Drive — chỉ bổ sung file mới vào
                    # đúng thư mục đó, không tạo lại cây thư mục.
                    base = str(doc.doc_num).replace("/", "_")
                    for path, name in [
                        (doc.docx_path, f"{base}.docx"),
                        (doc.pdf_path, f"{base}.pdf"),
                    ]:
                        if path and Path(path).exists():
                            link = client.upload_file(path, doc.lark_folder_token, name)
                            if name.endswith(".docx"):
                                doc.lark_docx_link = link["view_link"]
                                doc.gdrive_docx_link = link["view_link"]
                            else:
                                doc.lark_pdf_link = link["view_link"]
                                doc.gdrive_pdf_link = link["view_link"]
                else:
                    res = upload_document_files_lark(doc_data)
                    doc.lark_folder_token = res.get("lark_folder_token")
                    doc.lark_docx_link = res.get("lark_docx_link")
                    doc.lark_pdf_link = res.get("lark_pdf_link")

                uploaded += 1
                session.commit()

                if AUTO_CLEANUP_LOCAL_FILES:
                    for path in (doc.docx_path, doc.pdf_path):
                        if path and Path(path).exists():
                            Path(path).unlink()
            except Exception as e:
                logger.warning("Upload hỏng cho %s: %s", doc.doc_num, e)

        logger.info("Xong: tải %d, upload %d / %d văn bản.", downloaded, uploaded, len(pending))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
