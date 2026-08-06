"""
Dò nghĩa thật của mã `referenceType` do gateway Bộ Tư pháp trả về.

Bảng ánh xạ trong `moj_api.REFERENCE_TYPE_LABELS` vốn được đặt bằng suy đoán và
đã gán sai (mã 3 là "Căn cứ" nhưng bị ghi thành "Bãi bỏ"). Script này suy ra
nhãn từ bằng chứng: với mỗi cặp (văn bản nguồn, văn bản đích), tìm số hiệu đích
trong toàn văn nguồn rồi lấy động từ quan hệ đứng gần nhất phía trước.

Chạy:  python -m scripts.probe_reference_types [số_văn_bản]
Kết quả ghi ra data/reference_type_evidence.json
"""
import collections
import json
import re
import sys
import time
from pathlib import Path

from src.sources.moj_api import fetch_doc_detail
from src.storage.database import get_session
from src.storage.models import Document

# Động từ quan hệ trong văn bản QPPL, xếp theo mức cụ thể giảm dần: cụm dài
# phải đứng trước cụm ngắn để "sửa đổi, bổ sung" không bị "sửa đổi" nuốt mất.
RELATION_VERBS = [
    "căn cứ",
    "sửa đổi, bổ sung",
    "sửa đổi",
    "bãi bỏ",
    "hủy bỏ",
    "thay thế",
    "hết hiệu lực",
    "hợp nhất",
    "quy định chi tiết",
    "hướng dẫn",
    "đình chỉ",
    "ban hành kèm theo",
    "theo quy định tại",
]

CONTEXT_WINDOW = 140


def nearest_verb(text: str, pos: int) -> str | None:
    """Động từ quan hệ đứng gần nhất phía trước vị trí pos."""
    window = text[max(0, pos - CONTEXT_WINDOW):pos]
    best, best_pos = None, -1
    for verb in RELATION_VERBS:
        i = window.rfind(verb)
        if i > best_pos:
            best, best_pos = verb, i
    return best


def main(limit: int = 120) -> None:
    with get_session() as session:
        docs = [
            (d.moj_id, d.doc_num, d.clean_text_path)
            for d in session.query(Document)
            .filter(Document.moj_id.isnot(None), Document.clean_text_path.isnot(None))
            .limit(limit)
            .all()
        ]

    evidence: dict[int, collections.Counter] = collections.defaultdict(collections.Counter)
    samples: dict[int, list[str]] = collections.defaultdict(list)
    pair_count: dict[int, int] = collections.Counter()

    for moj_id, doc_num, clean_path in docs:
        path = Path(clean_path)
        if not path.exists():
            continue
        text = re.sub(r"\s+", " ", path.read_text(encoding="utf-8", errors="ignore")).lower()
        try:
            refs = (fetch_doc_detail(moj_id).get("data") or {}).get("references") or []
        except Exception as e:  # nguồn có thể chặn tạm thời; bỏ qua văn bản này
            print(f"  bỏ qua {doc_num}: {type(e).__name__}", file=sys.stderr)
            continue

        for ref in refs:
            code = ref.get("referenceType")
            target = ((ref.get("targetDocument") or {}).get("docNum") or "").strip()
            if not target:
                continue
            pair_count[code] += 1
            match = re.search(re.escape(target.lower()), text)
            if not match:
                continue
            verb = nearest_verb(text, match.start())
            if not verb:
                continue
            evidence[code][verb] += 1
            if len(samples[code]) < 3:
                start = max(0, match.start() - 90)
                samples[code].append(text[start:match.start() + len(target)])
        time.sleep(0.25)

    out = {}
    for code in sorted(evidence, key=lambda c: (c is None, c)):
        total = sum(evidence[code].values())
        top_verb, top_n = evidence[code].most_common(1)[0]
        out[str(code)] = {
            "tong_cap_quan_he": pair_count[code],
            "tong_co_bang_chung": total,
            "phan_bo_dong_tu": dict(evidence[code].most_common()),
            "dong_tu_ap_dao": top_verb,
            "ty_le": round(100 * top_n / total),
            "vi_du": samples[code],
        }

    dest = Path("data/reference_type_evidence.json")
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"=== BẰNG CHỨNG referenceType (mẫu {len(docs)} văn bản) ===")
    for code, info in out.items():
        print(
            f"\nmã {code}: {info['tong_cap_quan_he']} cặp, "
            f"{info['tong_co_bang_chung']} có bằng chứng"
        )
        for verb, n in list(info["phan_bo_dong_tu"].items())[:4]:
            pct = 100 * n // info["tong_co_bang_chung"]
            print(f"     {verb:<22} {n:>3}  ({pct}%)")
    print(f"\nĐã ghi {dest}")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 120)
