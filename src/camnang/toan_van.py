"""
Tải toàn văn văn bản căn cứ từ Google Drive, có nhớ đệm.

VÌ SAO PHẢI TẢI: toàn văn cố ý KHÔNG nằm trong repo và cũng không nằm trong
`du-lieu.json` — trang công khai chỉ đăng dữ kiện, không đăng toàn văn. Nhưng
không có toàn văn thì bài Cẩm nang chỉ nói được về tờ giấy, không nói được về
nghĩa vụ mà văn bản đặt ra. Chỉ mục ship sẵn ID Drive ở trường `g` đúng để mở
đường này.

FILE TRÊN DRIVE LÀ HTML THÔ CỦA CỔNG BỘ TƯ PHÁP, không phải văn bản đọc được.
Phải đi qua `html_to_clean_text()`, không nhét thẳng vào prompt: HTML thô là
hàng chục nghìn ký tự thẻ và style, ăn hết cửa sổ ngữ cảnh mà không mang thông
tin nào.

NHỚ ĐỆM LÀ BẮT BUỘC, không phải tối ưu: một văn bản căn cứ được nhiều biểu mẫu
dùng chung, và chạy lại pipeline là việc bình thường. Không đệm thì mỗi lượt
chạy tải lại vài trăm file vài trăm KB từ Drive và bị chặn tốc độ.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx

from src.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

THU_MUC_DEM = PROJECT_ROOT / "data" / "cam-nang" / "toan-van"

#: Endpoint tải trực tiếp. Dùng `uc?export=download` chứ không `file/d/…/view`:
#: bản kia trả về trang xem của Drive, không trả nội dung file.
URL_TAI = "https://drive.google.com/uc?export=download&id={}"

THOI_GIAN_CHO = 60.0

#: Dưới ngưỡng này thì không phải toàn văn — thường là trang lỗi của Drive hoặc
#: một khung HTML rỗng. Ghi nó vào đệm rồi gọi là "toàn văn" thì bịt mất dấu
#: hiệu còn thiếu, đúng lỗi mà scripts/backfill_fulltext_gdrive.py đã chặn.
NGUONG_KY_TU = 200

_RE_CONFIRM = re.compile(r'name="confirm"\s+value="([^"]+)"')


class KhongTaiDuoc(RuntimeError):
    """Không lấy được toàn văn. Bài vẫn viết được, chỉ là nông hơn."""


def _tai_html_tho(drive_id: str) -> str:
    """Một lượt GET tới Drive, có xử lý trang xác nhận quét virus."""
    with httpx.Client(timeout=THOI_GIAN_CHO, follow_redirects=True) as client:
        resp = client.get(URL_TAI.format(drive_id))
        resp.raise_for_status()
        html = resp.text

        # File lớn: Drive không trả nội dung mà trả một trang "không quét virus
        # được, tải tiếp?". Trang đó cũng là HTML 200 OK nên không bắt được bằng
        # mã trạng thái — phải nhận ra bằng chính cái nút xác nhận trong nó.
        m = _RE_CONFIRM.search(html)
        if m and len(html) < 20_000:
            resp = client.get(
                URL_TAI.format(drive_id) + f"&confirm={m.group(1)}"
            )
            resp.raise_for_status()
            html = resp.text
    return html


def tai_toan_van(
    drive_id: str,
    thu_muc_dem: Path | None = None,
    tai_lai: bool = False,
) -> str:
    """Toàn văn đã làm sạch của một văn bản, theo ID file Drive.

    Ném `KhongTaiDuoc` khi không lấy được — bên gọi quyết định viết bài nông hơn
    hay bỏ qua biểu mẫu đó, nhưng KHÔNG được im lặng coi như đã có toàn văn.
    """
    if not drive_id:
        raise KhongTaiDuoc("thiếu ID file Drive")

    dem = Path(thu_muc_dem or THU_MUC_DEM)
    duong_dan = dem / f"{drive_id}.md"
    if duong_dan.exists() and not tai_lai:
        return duong_dan.read_text(encoding="utf-8")

    try:
        html = _tai_html_tho(drive_id)
    except Exception as e:                       # noqa: BLE001
        raise KhongTaiDuoc(f"tải Drive {drive_id} hỏng: {e}") from e

    from src.pipeline.text_processor import html_to_clean_text

    sach = html_to_clean_text(html).strip()
    if len(sach) < NGUONG_KY_TU:
        raise KhongTaiDuoc(
            f"toàn văn {drive_id} chỉ {len(sach)} ký tự — không phải văn bản thật"
        )

    dem.mkdir(parents=True, exist_ok=True)
    duong_dan.write_text(sach, encoding="utf-8")
    logger.info("Tải toàn văn %s: %d ký tự", drive_id, len(sach))
    return sach


def cat_gon(text: str, tran: int) -> str:
    """Cắt toàn văn về mức nhét vừa prompt, cắt ở ranh giới dòng.

    Cắt giữa câu làm mô hình đọc một quy định cụt và tưởng đó là toàn bộ quy
    định. Cắt ở dòng và ghi rõ đã cắt thì nó biết phần sau còn nữa.
    """
    if len(text) <= tran:
        return text
    cat = text[:tran]
    lui = cat.rfind("\n")
    if lui > tran // 2:
        cat = cat[:lui]
    return cat.rstrip() + "\n\n[… phần còn lại của toàn văn đã bị cắt cho vừa ngữ cảnh …]"


__all__ = ["THU_MUC_DEM", "NGUONG_KY_TU", "KhongTaiDuoc", "tai_toan_van", "cat_gon"]
