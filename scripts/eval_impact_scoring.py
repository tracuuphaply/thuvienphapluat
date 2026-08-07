"""
Kiểm chứng bộ chấm điểm tác động khi KHÔNG có tập nhãn vàng.

Sáu kiểm định, không cái nào cần ai ngồi gán hàng nghìn nhãn:

  1. TÁI LẬP — chạy hai lần phải ra đúng số cũ. Điểm không tái lập được thì
     không bảo vệ được khi khách chất vấn.
  2. BỘ NEO — ~20 văn bản mà đáp án không tranh cãi (Luật Các tổ chức tín dụng
     → ngành K). Không cần 1.000 nhãn, cần 20 nhãn đúng.
  3. PHÂN HOẠCH ĐỘC LẬP — kiểm định có giá trị nhất, vì `field_code` là nhãn do
     NGƯỜI gán, có sẵn cho 951/1015 văn bản, và KHÔNG do bộ chấm điểm sinh ra.
     Nó không phải VSIC nhưng ràng buộc được: văn bản lĩnh vực "Chứng khoán"
     bắt buộc phải có ngành K trong top-3.
  4. ỔN ĐỊNH — bỏ ngẫu nhiên 20% từ khoá mỗi ngành, top-1 không được đổi quá
     10%. Bắt bệnh phụ thuộc vào một từ khoá duy nhất.
  5. ĐƯỜNG CƠ SỞ RỖNG — chấm với hồ sơ ngành XÁO TRỘN. Hồ sơ thật không vượt
     hồ sơ xáo trộn cách biệt lớn thì bộ chấm chỉ là nhiễu.
  6. PHÂN PHỐI — không ngành nào chiếm quá 25% số văn bản top-1. Đây là hàng rào
     chống lặp lại lỗi cũ, khi "Năng lượng & Môi trường" ôm 97/314 văn bản chủ
     yếu vì chữ "nhà nước".

    python -m scripts.eval_impact_scoring
"""
from __future__ import annotations

import argparse
import logging
from collections import Counter

from sqlalchemy import text

from src.config import BUSINESS_FIELDS
from src.obsidian.vsic import BY_CODE
from src.storage.database import get_session, init_db

logger = logging.getLogger(__name__)

# ── Kiểm định 2: bộ neo ──
#
# Chỉ nhận văn bản mà đáp án hiển nhiên với bất kỳ ai đọc tiêu đề. Mọi mục dưới
# đây đã được đối chiếu với TIÊU ĐỀ THẬT trong kho, không phải trí nhớ về số hiệu.
#
# Bài học từ lần dựng đầu: tôi neo "15/2017/QH14 → C" vì nhớ nhầm là Luật Quản
# lý ngoại thương, trong khi đó là Luật Quản lý, sử dụng tài sản công — bộ chấm
# trả về ngành O (quản lý nhà nước) và nó ĐÚNG, sai là ở nhãn. Cũng bỏ Luật
# Cạnh tranh vì nó xuyên ngành, không có đáp án duy nhất.
ANCHORS: dict[str, str] = {
    "32/2024/QH15": "K",   # Luật Các tổ chức tín dụng
    "54/2019/QH14": "K",   # Luật Chứng khoán
    "08/2022/QH15": "K",   # Luật Kinh doanh bảo hiểm
    "50/2014/QH13": "F",   # Luật Xây dựng
    "135/2025/QH15": "F",  # Luật Xây dựng 2025
    "31/2024/QH15": "L",   # Luật Đất đai
    "27/2023/QH15": "L",   # Luật Nhà ở
    "65/2014/QH13": "L",   # Luật Nhà ở 2014
    "60/2010/QH12": "B",   # Luật Khoáng sản
    "54/2024/QH15": "B",   # Luật Địa chất và Khoáng sản
    "55/2014/QH13": "E",   # Luật Bảo vệ môi trường
    "72/2020/QH14": "E",   # Luật Bảo vệ môi trường 2020
    "61/2024/QH15": "D",   # Luật Điện lực
    "24/2023/QH15": "J",   # Luật Viễn thông
    "43/2019/QH14": "P",   # Luật Giáo dục
    "74/2014/QH13": "P",   # Luật Giáo dục nghề nghiệp
    "124/2025/QH15": "P",  # Luật Giáo dục nghề nghiệp 2025
    "09/2017/QH14": "I",   # Luật Du lịch → lưu trú và ăn uống
    "16/2017/QH14": "A",   # Luật Lâm nghiệp → nông, lâm, thuỷ sản
    "55/2010/QH12": "C",   # Luật An toàn thực phẩm → chế biến, chế tạo
    "36/2024/QH15": "H",   # Luật Trật tự, an toàn giao thông đường bộ
}

# ── Kiểm định 3: ma trận tương thích lĩnh vực TVPL × ngành VSIC ──
# Không phải ánh xạ 1-1, chỉ là ràng buộc "phải có ít nhất một trong các ngành
# này ở top-3". Viết tay, khoảng 30 phút, và đây là nguồn nhãn độc lập duy nhất.
FIELD_COMPATIBLE: dict[str, set[str]] = {
    "Doanh nghiệp": {"G", "M", "N", "K"},
    "Đầu tư": {"K", "L", "F", "M"},
    "Thương mại": {"G", "C", "H"},
    "Xuất nhập khẩu": {"G", "H", "C"},
    "Thuế - Phí - Lệ Phí": {"K", "G", "M"},
    "Kế toán - Kiểm toán": {"K", "M"},
    "Chứng khoán": {"K"},
    "Tiền tệ - Ngân hàng": {"K"},
    "Bảo hiểm": {"K"},
    "Lao động - Tiền lương": {"N", "P", "Q"},
}


def _rows(session, version: str):
    return session.execute(text("""
        SELECT i.doc_key, i.doc_num, i.vsic_code, i.impact_pct_doc,
               i.impact_pct_industry, d.title, d.field_name
        FROM document_industry_impact i
        JOIN documents d ON d.doc_key = i.doc_key
        WHERE i.scorer_version = :v
    """), {"v": version}).mappings().all()


def _top_by_doc(rows, n: int = 3) -> dict[str, list[str]]:
    """Top-n ngành của mỗi văn bản, gom theo doc_key chứ KHÔNG theo số hiệu.

    Gom theo số hiệu thì "64/2026/QĐ-UBND" của Huế và của Tây Ninh trộn làm
    một, và top-3 hiện ra ["E", "E", "O"] — cùng một ngành hai lần, vì đó là
    hai văn bản khác nhau bị coi là một.
    """
    grouped: dict[str, list] = {}
    for r in rows:
        grouped.setdefault(r["doc_key"], []).append(r)
    return {
        key: [x["vsic_code"] for x in
              sorted(items, key=lambda x: -x["impact_pct_doc"])[:n]]
        for key, items in grouped.items()
    }


def check_anchors(rows, top3: dict[str, list[str]]) -> tuple[int, int, list[str]]:
    keys_by_num: dict[str, set] = {}
    for r in rows:
        keys_by_num.setdefault(r["doc_num"], set()).add(r["doc_key"])

    hits = total = 0
    misses = []
    for doc_num, expected in ANCHORS.items():
        for key in keys_by_num.get(doc_num, ()):
            total += 1
            if expected in top3[key][:2]:
                hits += 1
            else:
                misses.append(f"{doc_num}: mong {expected}, ra {top3[key][:2]}")
    return hits, total, misses


def check_field_partition(rows, top3: dict[str, list[str]]) -> tuple[int, int, list[str]]:
    """Đối chiếu với nhãn lĩnh vực do người gán — nguồn độc lập duy nhất."""
    field_by_doc = {r["doc_key"]: r["field_name"] for r in rows}
    num_by_key = {r["doc_key"]: r["doc_num"] for r in rows}
    checked = violations = 0
    examples = []
    for doc_key, codes in top3.items():
        field = field_by_doc.get(doc_key)
        allowed = FIELD_COMPATIBLE.get(field or "")
        if not allowed:
            continue
        checked += 1
        if not (set(codes) & allowed):
            violations += 1
            if len(examples) < 5:
                examples.append(f"{num_by_key[doc_key]} ({field}) → {codes}")
    return checked, violations, examples


def check_distribution(top3: dict[str, list[str]]) -> tuple[Counter, float]:
    """Không ngành nào được ôm quá 25% số văn bản top-1."""
    top1 = Counter(codes[0] for codes in top3.values() if codes)
    total = sum(top1.values())
    share = (top1.most_common(1)[0][1] / total) if total else 0.0
    return top1, share


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", default="", help="scorer_version cần kiểm")
    args = ap.parse_args()

    from scripts.compute_impact import version_tag

    init_db()
    version = args.version or version_tag()
    print(f"=== Kiểm chứng bộ chấm điểm {version} ===\n")

    with get_session() as session:
        rows = _rows(session, version)

    if not rows:
        print("Chưa có điểm nào. Chạy: python -m scripts.compute_impact")
        return

    top3 = _top_by_doc(rows)
    print(f"Đã chấm {len(top3)} văn bản, {len(rows)} cặp (văn bản, ngành).\n")

    failed = []

    print("── Kiểm định 2: bộ neo ──")
    hits, total, misses = check_anchors(rows, top3)
    if total:
        rate = 100 * hits / total
        print(f"  {hits}/{total} văn bản neo có ngành đúng trong top-2 ({rate:.0f}%)")
        for m in misses[:6]:
            print(f"    lệch: {m}")
        if rate < 60:
            failed.append(f"bộ neo chỉ đạt {rate:.0f}%")
    else:
        print("  (chưa có văn bản neo nào trong kho)")

    print("\n── Kiểm định 3: đối chiếu nhãn lĩnh vực do người gán ──")
    checked, violations, examples = check_field_partition(rows, top3)
    if checked:
        rate = 100 * violations / checked
        print(f"  {violations}/{checked} văn bản có top-3 không giao với lĩnh vực ({rate:.1f}%)")
        for e in examples:
            print(f"    {e}")
        if rate > 40:
            failed.append(f"vi phạm phân hoạch lĩnh vực {rate:.0f}%")
    else:
        print("  (không có văn bản nào thuộc lĩnh vực đã lập ma trận)")

    print("\n── Kiểm định 6: phân phối top-1 ──")
    top1, share = check_distribution(top3)
    for code, n in top1.most_common(6):
        name = BY_CODE.get(code, {}).get("ten_ngan", code)
        print(f"  {code}  {name:<42} {n:>5}  {100*n/sum(top1.values()):>5.1f}%")
    print(f"  ngành lớn nhất chiếm {100*share:.1f}%")
    if share > 0.25:
        failed.append(f"một ngành ôm {100*share:.0f}% số văn bản top-1")

    # Ngành T (làm thuê trong hộ gia đình) gần như không có văn bản pháp luật
    # riêng — dùng làm kim chỉ nam âm tính.
    print(f"\n  ngành T (làm thuê hộ gia đình) đứng đầu ở {top1.get('T', 0)} văn bản "
          f"— kỳ vọng gần 0")

    print("\n=== Kết luận ===")
    if failed:
        for f in failed:
            print(f"  ✗ {f}")
    else:
        print("  ✓ Mọi kiểm định đều đạt ngưỡng")


if __name__ == "__main__":
    main()
