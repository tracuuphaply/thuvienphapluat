"""
Backup utility — daily DB + file backup with history retention.

Usage:
  python -m src.utils.backup
"""
from __future__ import annotations

import gzip
import json
import logging
import shutil
import subprocess
from datetime import date, timedelta
from pathlib import Path

from src.config import BACKUPS_DIR, DATA_DIR, DATABASE_URL

logger = logging.getLogger(__name__)

RETENTION_DAYS = 30  # Keep 30 days of backups


def backup_database() -> str | None:
    """
    Backup the database.
    - SQLite: copy the .db file
    - PostgreSQL: run pg_dump
    """
    today = date.today().isoformat()

    if "sqlite" in DATABASE_URL:
        # Extract SQLite file path
        db_path = DATABASE_URL.split("///")[-1]
        db_file = Path(db_path)
        if not db_file.exists():
            logger.warning("SQLite file not found: %s", db_file)
            return None

        backup_path = BACKUPS_DIR / f"db_{today}.sqlite.gz"
        with open(db_file, "rb") as f_in:
            with gzip.open(backup_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

        logger.info("SQLite backup saved: %s", backup_path)
        return str(backup_path)

    elif "postgresql" in DATABASE_URL:
        backup_path = BACKUPS_DIR / f"db_{today}.sql.gz"
        try:
            result = subprocess.run(
                ["pg_dump", DATABASE_URL],
                capture_output=True,
                text=True,
                check=True,
            )
            with gzip.open(backup_path, "wt", encoding="utf-8") as f:
                f.write(result.stdout)
            logger.info("PostgreSQL backup saved: %s", backup_path)
            return str(backup_path)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error("pg_dump failed: %s", e)
            return None

    return None


def backup_files() -> str | None:
    """Backup data/tvpl and data/moj directories."""
    today = date.today().isoformat()
    backup_path = BACKUPS_DIR / f"files_{today}.tar.gz"

    tvpl_dir = DATA_DIR / "tvpl"
    moj_dir = DATA_DIR / "moj"

    dirs_to_backup = []
    if tvpl_dir.exists() and any(tvpl_dir.iterdir()):
        dirs_to_backup.append(str(tvpl_dir))
    if moj_dir.exists() and any(moj_dir.iterdir()):
        dirs_to_backup.append(str(moj_dir))

    if not dirs_to_backup:
        logger.info("No files to backup.")
        return None

    try:
        subprocess.run(
            ["tar", "-czf", str(backup_path)] + dirs_to_backup,
            check=True,
            capture_output=True,
        )
        logger.info("File backup saved: %s", backup_path)
        return str(backup_path)
    except subprocess.CalledProcessError as e:
        logger.error("File backup failed: %s", e)
        return None


def cleanup_old_backups(retention_days: int = RETENTION_DAYS) -> int:
    """Remove backups older than retention_days. Returns count removed."""
    cutoff = date.today() - timedelta(days=retention_days)
    removed = 0

    for f in BACKUPS_DIR.glob("*"):
        if f.is_file():
            # Extract date from filename (e.g., db_2026-07-25.sqlite.gz)
            try:
                date_str = f.stem.split("_", 1)[1][:10]
                file_date = date.fromisoformat(date_str)
                if file_date < cutoff:
                    f.unlink()
                    removed += 1
            except (IndexError, ValueError):
                continue

    if removed:
        logger.info("Cleaned up %d old backups (> %d days)", removed, retention_days)
    return removed


def run_backup() -> None:
    """Run full backup routine."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting daily backup...")

    db_backup = backup_database()
    file_backup = backup_files()
    cleaned = cleanup_old_backups()

    logger.info(
        "Backup complete: DB=%s, Files=%s, Cleaned=%d",
        "OK" if db_backup else "SKIP",
        "OK" if file_backup else "SKIP",
        cleaned,
    )


if __name__ == "__main__":
    run_backup()
