"""
Tải ruột biểu mẫu, tự thử lại quanh những lần Cloudflare chặn.

    python -m scripts.tiep_tai_ruot              # chạy tới khi xong hoặc hết vòng
    python -m scripts.tiep_tai_ruot --vong 40

VÌ SAO LÀ VÒNG LẶP. Bộ cào có cầu dao: 5 lần bị chặn liên tiếp thì dừng, thay vì
đốt hết hàng đợi để ghi hàng trăm dòng lỗi giống nhau. Cầu dao đó đúng, nhưng nó
biến mỗi lần chặn thành một lần phải gọi tay. Trong khi thứ chặn lại là thử thách
mà người vận hành sẽ giải trong Chrome của pipeline — giải xong thì lượt sau đi
tiếp được ngay. Vòng lặp này chỉ để không ai phải ngồi canh giữa hai lượt đó.

ĐO TIẾN TRIỂN TRÊN CÙNG MỘT TẬP. Số mẫu đã tải ruột đếm trên TOÀN hàng đợi, không
đếm trên phần "còn thiếu". Đếm trên phần còn thiếu thì tập co lại giữa hai lần
đo, và hiệu ra số âm ngay khi công việc chạy tốt — `tiep_liet_ke.py` đã vấp đúng
lỗi này và tự dừng đúng lúc nó đang chạy nhanh nhất.

KHÔNG DỪNG NGAY KHI MỘT VÒNG VỀ 0. Khác với pha liệt kê: ở đây số 0 thường có
nghĩa "thử thách chưa được giải xong", chứ không phải "chặn hẳn". Chờ qua vài
vòng rỗng liên tiếp rồi mới kết luận.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

from sqlalchemy import text

from src.storage.database import get_session, init_db

NGHI_SAU_KHI_CHAN = 120
NGHI_SAU_KHI_CHAY = 20
VONG_RONG_TOI_DA = 8


def da_tai() -> int:
    """Số mẫu đã có ruột, đếm trên TOÀN hàng đợi bieumau."""
    with get_session() as s:
        return s.execute(text(
            "SELECT COUNT(*) FROM legal_forms "
            "WHERE source='bieumau' AND crawl_status != 'PENDING'")).scalar() or 0


def con_lai() -> int:
    with get_session() as s:
        return s.execute(text(
            "SELECT COUNT(*) FROM legal_forms "
            "WHERE source='bieumau' AND crawl_status = 'PENDING'")).scalar() or 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vong", type=int, default=60)
    args = ap.parse_args()

    init_db()
    rong = 0
    for vong in range(1, args.vong + 1):
        truoc = da_tai()
        if not con_lai():
            print("\nHÀNG ĐỢI ĐÃ CẠN.")
            return

        # KHÔNG nuốt đầu ra của lượt cào. Bản đầu dùng capture_output=True, nên
        # suốt một vòng — có thể hàng giờ với 10.000 mẫu — màn hình không có một
        # dòng nào. Người vận hành nhìn vào chỉ thấy im lặng và kết luận nó đã
        # dừng, trong khi nó đang chạy bình thường. Một tiến trình dài mà không
        # nói gì thì không phân biệt được với một tiến trình đã chết.
        nhat_ky = []
        proc = subprocess.Popen(
            [sys.executable, "-m", "scripts.crawl_forms", "--source", "bieumau",
             "--tiep-tuc", "--loc-tieu-de"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        for dong in proc.stdout:
            nhat_ky.append(dong)
            print("   │ " + dong.rstrip(), flush=True)
        proc.wait()

        class _Kq:
            stdout = "".join(nhat_ky)
            stderr = ""
        kq = _Kq()
        them = da_tai() - truoc
        bi_chan = "Cloudflare" in (kq.stdout + kq.stderr)
        print(f"  vòng {vong:3}: +{them:4} mẫu · đã tải {da_tai():5,} · "
              f"còn {con_lai():5,}{'  [bị chặn]' if bi_chan else ''}", flush=True)

        if them <= 0:
            rong += 1
            if rong >= VONG_RONG_TOI_DA:
                print(f"\nDỪNG: {rong} vòng liên tiếp không tải thêm được mẫu nào.\n"
                      "Thử thách Cloudflare cần được giải trong Chrome của pipeline "
                      "(cổng CDP 9222) — cf_clearance gắn với IP và User-Agent nên "
                      "phải giải trong đúng profile đó.")
                return
        else:
            rong = 0
        time.sleep(NGHI_SAU_KHI_CHAN if bi_chan else NGHI_SAU_KHI_CHAY)

    print(f"\nHết {args.vong} vòng — đã tải {da_tai():,}, còn {con_lai():,}. "
          "Chạy lại lệnh này để đi tiếp.")


if __name__ == "__main__":
    main()
