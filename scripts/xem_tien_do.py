"""
Xem tiến độ cào biểu mẫu mà KHÔNG tranh khoá ghi với bộ cào.

    python -m scripts.xem_tien_do            # in một lần
    python -m scripts.xem_tien_do --lap 300  # in lại mỗi 5 phút

VÌ SAO KHÔNG ĐỌC THẲNG KHO. Kho chạy ở chế độ rollback journal (mặc định của
SQLite), nên trong lúc bộ cào mở giao dịch ghi thì MỌI người đọc đều bị chặn —
kể cả `sqlite3 file:...?mode=ro`. Thực đo: hỏi mỗi giây suốt 2 phút không chen
được một lần nào. Nghĩa là đúng lúc cần theo dõi nhất thì không theo dõi được.

Cách vòng qua: chép kho sang một bản tạm bằng `sqlite3 .backup`, vốn chịu được
việc đọc song song, rồi đếm trên bản chép. Số có thể trễ vài giây so với thực tế
— chấp nhận được, vì thứ cần biết là xu hướng chứ không phải con số tức thời.

(Cách sửa gốc là bật WAL: người đọc không còn bị người ghi chặn. Nhưng đổi chế độ
cần lúc không có giao dịch nào đang mở, nên phải chờ cào xong.)
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
import json
from pathlib import Path

DB = Path("data/legal_docs.db")


def _ban_chep() -> Path | None:
    """Bản chép nhất quán của kho, hoặc None nếu không chép được."""
    tmp = Path(tempfile.gettempdir()) / "tien_do_bieumau.db"
    r = subprocess.run(["sqlite3", str(DB), f".backup '{tmp}'"],
                       capture_output=True, text=True, timeout=120)
    return tmp if r.returncode == 0 and tmp.exists() else None


def trang_dang_mo(cong: int = 9222) -> str:
    """Trang bộ cào đang mở, hỏi thẳng trình duyệt — không đụng kho."""
    try:
        d = json.load(urllib.request.urlopen(
            f"http://localhost:{cong}/json/list", timeout=4))
        for t in d:
            if t.get("type") == "page" and "thuvienphapluat" in t.get("url", ""):
                return t.get("url", "").rsplit("/", 1)[-1][:58]
    except Exception:                                    # noqa: BLE001
        pass
    return "(không hỏi được trình duyệt)"


def in_mot_lan() -> None:
    p = _ban_chep()
    if not p:
        print(f"{time.strftime('%H:%M:%S')}  chưa chép được kho (bộ cào đang ghi dồn)")
        return
    c = sqlite3.connect(p)
    dem = dict(c.execute("SELECT crawl_status, COUNT(*) FROM legal_forms "
                         "WHERE source='bieumau' GROUP BY 1").fetchall())
    c.close()

    ok = dem.get("OK", 0)
    hong = dem.get("FAILED", 0)
    rong = dem.get("EMPTY_BODY", 0)
    cho = dem.get("PENDING", 0)
    # Phần việc thật = những mẫu qua được bộ lọc tiêu đề. PENDING là phần bộ lọc
    # loại bỏ, KHÔNG phải việc còn tồn — đọc nhầm chỗ này là tưởng còn 5.373 mẫu
    # phải cào trong khi chúng đã được quyết định là không cào.
    viec = ok + hong + rong
    print(f"{time.strftime('%H:%M:%S')}  "
          f"xong {ok:5,}/{viec:5,} ({ok/max(viec,1)*100:4.1f}%) · "
          f"chờ thử lại {hong + rong:5,} · "
          f"lọc bỏ {cho:5,} · {trang_dang_mo()}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lap", type=int, help="Giây giữa hai lần in")
    args = ap.parse_args()
    while True:
        in_mot_lan()
        if not args.lap:
            return
        time.sleep(args.lap)


if __name__ == "__main__":
    main()
