"""
Chốt chặn dung lượng đĩa.

Bao đóng dẫn chiếu chạy đệ quy không giới hạn, mà đo thực tế mỗi văn bản chiếm
~346 KB (HTML 179 KB + toàn văn sạch 77 KB + chunk 90 KB) chưa kể rag.db phình
theo. Đĩa đầy giữa lúc SQLite đang ghi có thể làm hỏng cơ sở dữ liệu, nên phải
dừng có trật tự khi còn chỗ, thay vì chạy tới lúc hết.

Frontier nằm trong cơ sở dữ liệu nên dừng ở đâu chạy tiếp ở đó — không mất gì.
"""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from src.config import DATA_DIR

logger = logging.getLogger(__name__)

# Dừng khi phần trống tụt xuống dưới mức này. 5 GB đủ chỗ cho một lần VACUUM
# rag.db và một bản sao lưu, tức là vẫn còn xoay xở được sau khi dừng.
DEFAULT_MIN_FREE_GB = 5.0

_GB = 1024 ** 3


@dataclass(frozen=True)
class DiskStatus:
    free_gb: float
    total_gb: float
    min_free_gb: float

    @property
    def ok(self) -> bool:
        return self.free_gb >= self.min_free_gb

    def message(self) -> str:
        return (
            f"đĩa còn {self.free_gb:.1f} GB / {self.total_gb:.0f} GB "
            f"(ngưỡng dừng {self.min_free_gb:.1f} GB)"
        )


class DiskSpaceExhausted(RuntimeError):
    """Đã chạm ngưỡng dung lượng — dừng có trật tự."""


def check(min_free_gb: float = DEFAULT_MIN_FREE_GB, path: Path | None = None) -> DiskStatus:
    usage = shutil.disk_usage(path or DATA_DIR)
    return DiskStatus(
        free_gb=usage.free / _GB,
        total_gb=usage.total / _GB,
        min_free_gb=min_free_gb,
    )


def ensure_space(
    min_free_gb: float = DEFAULT_MIN_FREE_GB, path: Path | None = None
) -> DiskStatus:
    """Ném DiskSpaceExhausted nếu đã chạm ngưỡng.

    Gọi trước mỗi lô crawl chứ không phải mỗi văn bản: gọi quá dày thì mỗi lần
    tải là một lần hỏi hệ điều hành, mà dung lượng không đổi nhanh tới vậy.
    """
    status = check(min_free_gb, path)
    if not status.ok:
        raise DiskSpaceExhausted(status.message())
    return status
