"""
Liệt kê tiếp các lĩnh vực còn thiếu, tự tính trang bắt đầu từ những gì đã có.

    python -m scripts.tiep_liet_ke            # đi tới khi xong hoặc hết kiên nhẫn
    python -m scripts.tiep_liet_ke --vong 3

VÌ SAO CÓ SCRIPT NÀY. Cloudflare chặn giữa chừng ở lĩnh vực lớn, và mỗi lần chặn
thì lượt chạy phải bắt đầu lại từ đúng chỗ dừng chứ không phải từ trang 1 — lật
lại 44 trang đã có là 44 lượt tải đốt thêm hạn mức để lấy về đúng thứ đã nằm
trong kho.

Trang bắt đầu suy từ SỐ MẪU ĐÃ CÓ chứ không lưu con trỏ riêng: TVPL trả 20 mẫu
mỗi trang, nên `số_mẫu // 20 + 1` là trang kế tiếp. Không có con trỏ thì không có
gì để lệch với thực tế — con trỏ lưu riêng mà sai thì nó âm thầm bỏ qua cả một
đoạn kho.

DỪNG KHI MỘT VÒNG KHÔNG THÊM ĐƯỢC GÌ. Chặn tạm thời thì vòng sau đi tiếp được;
chặn hẳn thì mọi vòng đều về 0 và chạy thêm chỉ tốn thời gian. Phân biệt hai thứ
đó bằng "có tiến triển không", không bằng đếm số lần thử.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

from sqlalchemy import text

from scripts.hieu_chuan_ca_nhan import LINH_VUC_CA_NHAN
from src.storage.database import get_session, init_db

MOI_TRANG = 20
NGHI_GIUA_LINH_VUC = 12
NGHI_GIUA_VONG = 90


def _dem_theo_linh_vuc() -> dict[int, int]:
    with get_session() as s:
        return dict(s.execute(text("""SELECT field_code, COUNT(*) FROM legal_forms
            WHERE source='bieumau' GROUP BY 1""")).fetchall())


def con_thieu() -> list[tuple[int, str, int, int]]:
    """(mã, tên, đã có, tổng) cho các lĩnh vực chưa đủ mẫu."""
    rows = _dem_theo_linh_vuc()
    return [(ma, ten, rows.get(ma, 0), n)
            for ma, (ten, n) in LINH_VUC_CA_NHAN.items()
            if rows.get(ma, 0) < n]


def tong_da_co() -> int:
    """Tổng mẫu đã có trên CẢ 18 lĩnh vực.

    Đếm trên cả 18 chứ không chỉ các lĩnh vực còn thiếu. Bản đầu cộng tổng trên
    tập "còn thiếu" ở cả hai đầu, mà tập đó CO LẠI khi một lĩnh vực cào xong —
    lĩnh vực 32 hoàn tất giữa vòng thì 1.520 mẫu của nó rời khỏi số sau, và hiệu
    ra −20 trong khi vòng đó thật sự thêm 3.374 mẫu. Script tự dừng vì tưởng bị
    chặn hẳn, đúng lúc nó đang chạy tốt nhất.

    So hai tổng thì phải so trên cùng một tập. Đây là lỗi im lặng vì con số vẫn
    trông hợp lý — chỉ mang dấu âm.
    """
    rows = _dem_theo_linh_vuc()
    return sum(rows.get(ma, 0) for ma in LINH_VUC_CA_NHAN)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vong", type=int, default=6, help="Số vòng tối đa")
    args = ap.parse_args()

    init_db()
    for vong in range(1, args.vong + 1):
        thieu = con_thieu()
        if not thieu:
            print("\nĐỦ CẢ 18 LĨNH VỰC.")
            return
        truoc = tong_da_co()
        print(f"\n═══ vòng {vong}: {len(thieu)} lĩnh vực còn thiếu "
              f"{sum(n - co for _, _, co, n in thieu):,} mẫu ═══", flush=True)

        for ma, ten, co, n in thieu:
            tu_trang = co // MOI_TRANG + 1
            print(f"  {ma:2} {ten:30} {co:5,}/{n:5,} → tiếp từ trang {tu_trang}",
                  flush=True)
            subprocess.run(
                [sys.executable, "-m", "scripts.crawl_forms", "--source", "bieumau",
                 "--field", str(ma), "--chi-hang-doi", "--tu-trang", str(tu_trang)],
                capture_output=True, text=True,
            )
            time.sleep(NGHI_GIUA_LINH_VUC)

        them = tong_da_co() - truoc
        print(f"  vòng {vong}: thêm {them:,} mẫu", flush=True)
        if them <= 0:
            print("\nDỪNG: một vòng trọn vẹn không thêm được mẫu nào — Cloudflare "
                  "đang chặn hẳn chứ không phải chặn tạm. Giải thử thách bằng tay "
                  "trong Chrome của pipeline rồi chạy lại.")
            return
        time.sleep(NGHI_GIUA_VONG)

    print(f"\nHết {args.vong} vòng. Chạy lại lệnh này để đi tiếp.")


if __name__ == "__main__":
    main()
