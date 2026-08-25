"""
Sổ ghi biểu mẫu nào đã sinh bài, theo vân tay nguồn.

VÌ SAO CẦN: chạy lại toàn bộ pipeline không làm hỏng gì bên xuất bản —
`import_key` = `form_key` nên bài cũ được ánh xạ lại đúng chỗ, bài đã xuất bản
không bị ghi đè, slug không đổi khi tiêu đề đổi. Nhưng SINH LẠI THÂN BÀI BẰNG
LLM THÌ TỐN TIỀN. Sổ này là thứ duy nhất đứng giữa "chạy lại được" và "chạy lại
miễn phí".

SO SÁNH THEO VÂN TAY NGUỒN, KHÔNG THEO NGÀY. Ngày sinh chỉ trả lời "bài này bao
lâu rồi", còn câu cần trả lời là "nguồn của bài này có đổi không". Vân tay gồm
tiêu đề + hiệu lực + căn cứ + ruột mẫu — xem `BieuMau.nguon_hash()`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

DUONG_DAN_MAC_DINH = PROJECT_ROOT / "cam-nang" / "da-sinh.json"


@dataclass
class BanGhiTrangThai:
    nguon_hash: str
    sinh_luc: str
    citation_ok: bool


class SoTrangThai:
    """Đọc/ghi `da-sinh.json`. Vắng file = chưa sinh bài nào, không phải lỗi."""

    def __init__(self, duong_dan: Path | None = None):
        self.duong_dan = Path(duong_dan or DUONG_DAN_MAC_DINH)
        self._ban_ghi: dict[str, BanGhiTrangThai] = {}
        self._nap()

    def _nap(self) -> None:
        try:
            goi = json.loads(self.duong_dan.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError) as e:
            # Sổ hỏng thì coi như chưa có: sinh lại tốn tiền nhưng đúng, còn tin
            # một sổ hỏng thì bỏ qua đúng những bài cần sinh lại.
            logger.warning("Sổ trạng thái %s không đọc được (%s) — coi như rỗng",
                           self.duong_dan, e)
            return

        for khoa, m in (goi or {}).items():
            if not isinstance(m, dict):
                continue
            self._ban_ghi[khoa] = BanGhiTrangThai(
                nguon_hash=m.get("nguon_hash") or "",
                sinh_luc=m.get("sinh_luc") or "",
                citation_ok=bool(m.get("citation_ok")),
            )

    def can_sinh_lai(self, form_key: str, nguon_hash: str) -> bool:
        """Biểu mẫu mới, nguồn đã đổi, hoặc lần trước trượt cổng trích dẫn.

        Trượt cổng CŨNG phải sinh lại: bài đó chưa bao giờ tới được bên xuất bản
        (`citation_ok: false` bị loại vĩnh viễn), nên coi nó là "đã có" thì
        biểu mẫu ấy vĩnh viễn không có bài mà không ai thấy.
        """
        cu = self._ban_ghi.get(form_key)
        if cu is None:
            return True
        if cu.nguon_hash != nguon_hash:
            return True
        return not cu.citation_ok

    def ghi_nhan(self, form_key: str, nguon_hash: str, citation_ok: bool) -> None:
        self._ban_ghi[form_key] = BanGhiTrangThai(
            nguon_hash=nguon_hash,
            sinh_luc=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            citation_ok=citation_ok,
        )

    def luu(self) -> Path:
        self.duong_dan.parent.mkdir(parents=True, exist_ok=True)
        goi = {k: asdict(v) for k, v in sorted(self._ban_ghi.items())}
        self.duong_dan.write_text(
            json.dumps(goi, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return self.duong_dan

    def __len__(self) -> int:
        return len(self._ban_ghi)

    def __contains__(self, form_key: str) -> bool:
        return form_key in self._ban_ghi


__all__ = ["DUONG_DAN_MAC_DINH", "BanGhiTrangThai", "SoTrangThai"]
