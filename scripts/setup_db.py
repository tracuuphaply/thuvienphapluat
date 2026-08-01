"""
Database setup script — initializes schema and verifies connection.

Usage:
  python scripts/setup_db.py
"""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage.database import init_db, get_session, engine
from src.storage.models import Document, CrawlRun


import argparse

def main():
    parser = argparse.ArgumentParser(description="Database Setup & Reset Utility")
    parser.add_argument("--reset", action="store_true", help="Reset database (delete data/legal_docs.db and recreate schema)")
    args = parser.parse_args()

    print("=" * 50)
    print("Database Setup — Legal Document System")
    print("=" * 50)

    db_file = Path(__file__).resolve().parent.parent / "data" / "legal_docs.db"
    if args.reset:
        if db_file.exists():
            db_file.unlink()
            print("🗑️ Resetting database: deleted existing legal_docs.db")

    # Show connection info
    print(f"\nDatabase URL: {engine.url}")
    print(f"Driver: {engine.url.drivername}")

    # Create tables
    print("\nCreating tables...")
    init_db()
    print("✅ Tables created successfully.")

    # Verify by counting
    with get_session() as session:
        doc_count = session.query(Document).count()
        run_count = session.query(CrawlRun).count()
        print(f"\nCurrent data:")
        print(f"  documents:  {doc_count} rows")
        print(f"  crawl_runs: {run_count} rows")

    print("\n✅ Database setup complete!")
    print(f"   Location: {engine.url}\n")


if __name__ == "__main__":
    main()

