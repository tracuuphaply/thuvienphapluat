"""
Bộ điều phối nơi lưu trữ đám mây.

Trước đây `src/main.py` chọn đích lưu trữ bằng `if LARK_APP_ID:` — nghĩa là chỉ
cần ai đó điền khoá Lark vào .env là toàn bộ pipeline âm thầm đổi chỗ lưu file,
không có cách nào khai báo ý định. Nay chọn bằng CLOUD_DRIVE_PROVIDER.

Hai điều module này làm mà hai nhánh riêng lẻ không làm:

  1. Báo rõ file nào KHÔNG lên được. Nhánh Lark hiện `continue` lặng lẽ khi một
     file lỗi, nên bên gọi tưởng đã xong và xoá file local. Ở đây mọi thất bại
     đều được trả về để xếp vào hàng đợi thử lại.
  2. Quyết định "văn bản nào lên mây" đọc từ một nguồn cấu hình duy nhất
     (config.upload_closure_nodes). Bên gọi nào cần lọc sẵn ở tầng truy vấn thì
     phải hỏi cùng hàm đó — chép cứng điều kiện ra chỗ khác là cách nhánh
     --upload-only từng báo "0 văn bản chờ upload" trong khi kho có 3.443 văn
     bản chưa lên.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.config import CLOUD_DRIVE_PROVIDER, upload_closure_nodes

logger = logging.getLogger(__name__)

GDRIVE = "gdrive"
LARK = "lark"
BOTH = "both"


@dataclass
class UploadOutcome:
    provider: str
    links: dict[str, Any] = field(default_factory=dict)
    uploaded: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped_reason: str | None = None

    @property
    def ok(self) -> bool:
        """Đã lên được ít nhất một file và không file nào lỗi."""
        return bool(self.uploaded) and not self.failed

    @property
    def skipped(self) -> bool:
        return self.skipped_reason is not None


def active_provider() -> str:
    provider = (CLOUD_DRIVE_PROVIDER or "").strip().lower()
    if provider not in (GDRIVE, LARK, BOTH):
        logger.warning(
            "CLOUD_DRIVE_PROVIDER=%r không hợp lệ, dùng %r", provider, LARK
        )
        return LARK
    return provider


def _upload_gdrive(doc_data: dict[str, Any]) -> UploadOutcome:
    from src.storage.gdrive import upload_document_files

    raw = upload_document_files(doc_data)
    return UploadOutcome(
        provider=GDRIVE,
        links={
            "gdrive_docx_link": raw.get("gdrive_docx_link"),
            "gdrive_fulltext_link": raw.get("gdrive_fulltext_link"),
            "gdrive_folder_id": raw.get("gdrive_folder_id"),
        },
        uploaded=list(raw.get("uploaded") or []),
        failed=list(raw.get("failed") or []),
    )


def _upload_lark(doc_data: dict[str, Any]) -> UploadOutcome:
    from pathlib import Path

    from src.storage.lark_drive import upload_document_files_lark

    # Nhánh Lark không báo file nào hỏng, nên suy ngược: file có trên đĩa mà
    # không có link trả về nghĩa là chưa lên được.
    raw = upload_document_files_lark(doc_data)
    expected = [
        ("docx", doc_data.get("docx_path"), "lark_docx_link"),
        ("clean_text", doc_data.get("clean_text_path"), "lark_fulltext_link"),
    ]
    uploaded, failed = [], []
    for kind, local_path, link_key in expected:
        if not local_path or not Path(local_path).exists():
            continue
        (uploaded if raw.get(link_key) else failed).append(kind)

    if not raw.get("lark_folder_token"):
        failed.append("folder")

    return UploadOutcome(
        provider=LARK,
        links={
            "lark_docx_link": raw.get("lark_docx_link"),
            "lark_fulltext_link": raw.get("lark_fulltext_link"),
            "lark_folder_token": raw.get("lark_folder_token"),
        },
        uploaded=uploaded,
        failed=failed,
    )


def upload_document(doc_data: dict[str, Any]) -> UploadOutcome:
    """Đẩy hồ sơ một văn bản lên nơi lưu trữ đang cấu hình.

    Văn bản kéo về theo dẫn chiếu (`is_closure_node`) MẶC ĐỊNH vẫn lên Drive:
    yêu cầu vận hành nói rõ mọi văn bản tải về đều phải lưu Drive trước, và
    nhóm này được nêu đích danh trong yêu cầu đó — văn bản bị bãi bỏ chính là
    mắt xích giải thích vì sao quy định hiện hành ra đời, người đọc báo cáo cần
    mở được nó. Đặt UPLOAD_CLOSURE_NODES=false để loại nhóm này khỏi Drive.
    """
    if doc_data.get("is_closure_node") and not upload_closure_nodes():
        return UploadOutcome(
            provider=active_provider(),
            skipped_reason="van_ban_ngu_canh",
        )

    provider = active_provider()
    if provider == GDRIVE:
        return _upload_gdrive(doc_data)
    if provider == LARK:
        return _upload_lark(doc_data)

    # BOTH: Drive là đích chính nên quyết định thành/bại; Lark chỉ là bản sao,
    # hỏng thì ghi log chứ không kéo cả văn bản vào hàng đợi thử lại.
    primary = _upload_gdrive(doc_data)
    try:
        mirror = _upload_lark(doc_data)
        primary.links.update(mirror.links)
    except Exception as e:
        logger.warning("Bản sao Lark thất bại cho %s: %s", doc_data.get("doc_num"), e)
    primary.provider = BOTH
    return primary
