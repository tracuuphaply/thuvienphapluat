"""
Điền dữ kiện pháp lý suy được cho văn bản đã có trong kho.

Ba nhóm, đều thuần suy diễn — không gọi mạng:

  1. Thứ bậc và loại chuẩn hoá (Điều 4 Luật BHVBQPPL 2025), suy từ số hiệu.
  2. Phạm vi lãnh thổ và mã tỉnh, suy từ cơ quan ban hành, có áp bản đồ sắp xếp
     đơn vị hành chính 2025 (Nghị quyết 202/2025/QH15).
  3. Cờ hiệu lực chuẩn hoá kèm mốc tính.

Chạy `--dry-run` trước: nó in bảng đối chiếu "hậu tố số hiệu → cấp suy ra" để
soi bằng mắt trước khi ghi. Gán sai một hậu tố là gán sai cả trăm văn bản.

    python -m scripts.backfill_legal_facts --dry-run
    python -m scripts.backfill_legal_facts
"""
from __future__ import annotations

import argparse
import logging
from collections import Counter, defaultdict
from datetime import date

from src.legal import effectivity
from src.legal.hierarchy import classify, resolve_province
from src.storage.database import get_session, init_db
from src.storage.models import Document

logger = logging.getLogger(__name__)


def _suffix_of(doc_num: str) -> str:
    """Phần đuôi số hiệu dùng để nhóm trong bảng đối chiếu."""
    text = (doc_num or "").strip()
    if "/" in text:
        return "/" + text.rsplit("/", 1)[-1]
    return text[:24]


def backfill(dry_run: bool, as_of: date) -> tuple[Counter, dict]:
    stats: Counter = Counter({
        "tong_van_ban": 0, "da_cap_nhat": 0, "khong_doi": 0,
        "vbqppl": 0, "khong_phai_vbqppl": 0,
        "co_ma_tinh": 0, "dia_phuong_khong_ro_tinh": 0,
        "eff_khong_ro": 0, "eff_suy_tu_ngay": 0,
    })
    # hậu tố → {cấp: số lượng}, để in bảng đối chiếu
    audit: dict[str, Counter] = defaultdict(Counter)

    with get_session() as session:
        docs = session.query(Document).order_by(Document.id).all()
        stats["tong_van_ban"] = len(docs)

        for doc in docs:
            facts = classify(doc.doc_num, doc.doc_type or "", doc.agency_name or "")
            raw_code, cur_code = resolve_province(doc.agency_name or "")
            eff = effectivity.resolve(doc.eff_status, doc.eff_from, doc.eff_to, as_of)

            audit[_suffix_of(doc.doc_num)][
                f"cấp {facts.hierarchy_level} · {facts.doc_type_norm}"
            ] += 1

            stats["vbqppl" if facts.is_vbqppl else "khong_phai_vbqppl"] += 1
            if cur_code:
                stats["co_ma_tinh"] += 1
            elif facts.territorial_scope == "tinh":
                stats["dia_phuong_khong_ro_tinh"] += 1
            if eff.state == effectivity.KHONG_RO:
                stats["eff_khong_ro"] += 1
            if eff.source == "ngay_thang":
                stats["eff_suy_tu_ngay"] += 1

            new_values = {
                "hierarchy_level": facts.hierarchy_level,
                "doc_type_norm": facts.doc_type_norm,
                "is_vbqppl": facts.is_vbqppl,
                "territorial_scope": facts.territorial_scope,
                "province_code_raw": raw_code,
                "province_code_current": cur_code,
                "eff_state": eff.state,
                "eff_state_as_of": eff.as_of,
                "eff_state_source": eff.source,
            }
            # Văn bản đã có trong kho trước khi có bao đóng dẫn chiếu đều là văn
            # bản đi qua bộ lọc lĩnh vực doanh nghiệp, không phải nút bao đóng.
            if doc.is_closure_node is None:
                new_values["is_closure_node"] = False

            changed = any(
                getattr(doc, key) != value for key, value in new_values.items()
            )
            if changed:
                stats["da_cap_nhat"] += 1
                if not dry_run:
                    for key, value in new_values.items():
                        setattr(doc, key, value)
            else:
                stats["khong_doi"] += 1

        if dry_run:
            session.rollback()

    return stats, audit


def print_audit(audit: dict) -> None:
    print("\n=== Bảng đối chiếu: hậu tố số hiệu → cấp suy ra ===")
    print("(soi kỹ dòng nào có nhiều hơn một cấp — đó là chỗ luật khớp chưa chặt)")
    rows = sorted(audit.items(), key=lambda kv: -sum(kv[1].values()))
    for suffix, levels in rows[:30]:
        total = sum(levels.values())
        detail = " | ".join(f"{k} ×{v}" for k, v in levels.most_common())
        flag = "  ⚠ NHIỀU CẤP" if len(levels) > 1 else ""
        print(f"  {suffix:<22} {total:>4}  {detail}{flag}")
    if len(rows) > 30:
        print(f"  … và {len(rows) - 30} hậu tố khác")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Chỉ đếm và in bảng đối chiếu, không ghi gì")
    parser.add_argument("--as-of", default="",
                        help="Mốc tính cờ hiệu lực (YYYY-MM-DD); mặc định hôm nay")
    args = parser.parse_args()

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()

    init_db()
    stats, audit = backfill(args.dry_run, as_of)

    if args.dry_run:
        print_audit(audit)

    print("\n=== Kết quả ===" + ("  (DRY RUN — chưa ghi gì)" if args.dry_run else ""))
    print(f"  mốc tính hiệu lực: {as_of}")
    for key in sorted(stats):
        print(f"  {key:34} {stats[key]:>6}")


if __name__ == "__main__":
    main()
