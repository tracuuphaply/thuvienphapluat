"""
Dựng nội dung cho trang tra cứu công khai.

    python -m scripts.publish_site --dry-run
    python -m scripts.publish_site                    # ghi vào build/public-vault
    python -m scripts.publish_site --out ../legal-vault-public/content

Script này CHỈ SINH NỘI DUNG, không tự push. Việc tạo repo công khai và đẩy lên
là hành động ra bên ngoài, thuộc quyền quyết định của người vận hành.

VÌ SAO PHẢI LÀ REPO RIÊNG, không bật Pages trên repo này: repo làm việc chứa
`.env` với khoá API thật, thư mục `credentials/`, và `data/chrome_profile/` có
cookie đăng nhập TVPL. Công khai repo đồng nghĩa công khai toàn bộ LỊCH SỬ git —
và commit a3dd597 đã từng phải gỡ một profile Chrome 160 MiB kèm Cookies khỏi
lịch sử nhánh. Repo riêng chỉ chứa nội dung sinh ra thì không có gì để rò.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.config import PROJECT_ROOT
from src.publish import moc_static, site_exporter
from src.storage.database import get_session, init_db

logger = logging.getLogger(__name__)

DEFAULT_OUT = PROJECT_ROOT / "build" / "public-vault" / "content"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="Thư mục nội dung Quartz")
    ap.add_argument("--dry-run", action="store_true",
                    help="Đếm và in mẫu, không ghi file")
    ap.add_argument("--all", action="store_true",
                    help="Đăng cả văn bản không phải QPPL (mặc định: chỉ QPPL)")
    args = ap.parse_args()

    from scripts.compute_impact import version_tag

    init_db()
    out_dir = Path(args.out)
    version = version_tag()

    with get_session() as session:
        if args.dry_run:
            from src.storage.models import Document

            q = session.query(Document).filter(Document.public_slug.isnot(None))
            if not args.all:
                q = q.filter(Document.is_vbqppl == True)  # noqa: E712
            docs = q.all()
            print(f"=== Sẽ đăng {len(docs)} văn bản ===")
            print(f"  thư mục đích : {out_dir}")
            print(f"  scorer       : {version}")

            sample = docs[0] if docs else None
            if sample:
                impacts = site_exporter.impacts_by_doc(session, version)
                page = site_exporter.render_page(
                    session, sample, impacts.get(sample.doc_key, []),
                    site_exporter.build_slug_index(session),
                )
                print(f"\n=== Trang mẫu ({sample.public_slug}.md, "
                      f"{len(page)} ký tự) ===\n")
                print(page[:1600])
            session.rollback()
            return

        out_dir.mkdir(parents=True, exist_ok=True)
        stats = site_exporter.export_documents(
            session, out_dir, version, only_vbqppl=not args.all
        )
        stats.mocs = moc_static.export_indexes(session, out_dir, version)
        session.commit()

    print("\n=== Kết quả ===")
    for k, v in stats.as_dict().items():
        print(f"  {k:16} {v}")
    print(f"\nNội dung đã sẵn ở: {out_dir}")
    print("Bước tiếp theo (người vận hành làm):")
    print("  1. Tạo repo CÔNG KHAI riêng, ví dụ legal-vault-public")
    print("  2. Cài Quartz v4 vào repo đó, chép thư mục content/ này vào")
    print("  3. Bật GitHub Pages, đặt PUBLIC_VAULT_BASE_URL trong .env")


if __name__ == "__main__":
    main()
