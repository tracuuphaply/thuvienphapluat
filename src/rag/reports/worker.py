"""
Rút hàng đợi báo cáo.

Chạy TÁCH KHỎI pipeline cào dữ liệu. Gọi mô hình mất tới 300 giây, và trước đây
lời gọi đó nằm trong khối try bao trọn pipeline — nghĩa là một lỗi LLM đánh dấu
cả lần cào là FAILED, và run_daily.sh khi đó bỏ luôn hai bước đồng bộ vault và
RAG. Một báo cáo hỏng không được phép làm hỏng ngày cào dữ liệu.

KIỂM TRA TRÍCH DẪN LÀ CỔNG CỨNG cho cả ba loại. Trước đây chỉ nhánh
scripts/generate_industry_reports.py có kiểm; đường Telegram và CLI xuất PDF
thẳng, nên lời hứa "báo cáo có số hiệu lạ sẽ KHÔNG được xuất" chỉ đúng ở một
trong ba đường.
"""
from __future__ import annotations

import datetime
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from src.config import DATA_DIR
from src.rag.citation_check import check_citations
from src.rag.db_rag import RAGDatabase
from src.rag.reports import generators, jobs
from src.rag.reports.llm import LLMUnavailable
from src.storage.models import Document

logger = logging.getLogger(__name__)

REPORTS_DIR = DATA_DIR / "reports"


@dataclass
class WorkerStats:
    picked: int = 0
    done: int = 0
    failed: int = 0
    blocked: int = 0
    chained: int = 0

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _write_outputs(job_id: int, kind: str, result: generators.ReportResult) -> dict:
    """Ghi markdown và sidecar. PDF do bước xuất bản lo, sau khi qua cổng trích dẫn."""
    out_dir = REPORTS_DIR / {"a": "nganh", "b": "van_ban_moi", "c": "doanh_nghiep"}[kind]
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"job{job_id:05d}_{datetime.date.today().isoformat()}"

    md_path = out_dir / f"{stem}.md"
    md_path.write_text(result.markdown, encoding="utf-8")
    paths = {"output_md_path": str(md_path)}

    if result.sidecar:
        # Hợp đồng máy đọc được để báo cáo (c) tiêu thụ. Bắt (c) parse markdown
        # do mô hình sinh là mời lỗi vào giữa dây chuyền.
        json_path = out_dir / f"{stem}.json"
        json_path.write_text(
            json.dumps(result.sidecar, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        paths["output_json_path"] = str(json_path)

    return paths


def run_job(session, rag: RAGDatabase, job: dict, scorer_version: str,
            embedder=None) -> str:
    """Chạy một job. Trả về trạng thái cuối."""
    job_id, kind = job["id"], job["kind"]
    jobs.mark(session, job_id, jobs.RUNNING)
    session.commit()

    try:
        if kind == "b":
            keys = json.loads(job["subject_keys"] or "[]")
            result = generators.generate_update_report(
                session, rag, keys, scorer_version
            )
        elif kind == "c":
            parent = session.execute(
                text("SELECT output_md_path, output_json_path FROM report_jobs WHERE id = :i"), {"i": job["parent_job_id"]}
            ).mappings().first()
            if not parent or not parent["output_md_path"]:
                raise LLMUnavailable("Báo cáo gốc (b) chưa có đầu ra để dựa vào.")
            result = generators.generate_business_report(
                session, rag, job["vsic_code"],
                Path(parent["output_md_path"]).read_text(encoding="utf-8"),
                json.loads(Path(parent["output_json_path"]).read_text(encoding="utf-8")),
                scorer_version, embedder=embedder,
            )
        else:
            raise LLMUnavailable(f"Loại báo cáo {kind!r} chưa có bộ sinh riêng.")
    except Exception as e:
        logger.error("Job %d thất bại: %s", job_id, e)
        jobs.mark(session, job_id, jobs.FAILED, error=str(e)[:500])
        session.commit()
        return jobs.FAILED

    # ── Cổng cứng: mọi số hiệu trong báo cáo phải có thật trong kho ──
    citation = check_citations(result.markdown)
    paths = _write_outputs(job_id, kind, result)

    if not citation.ok:
        logger.warning(
            "Job %d bị chặn: %d số hiệu không có trong kho — %s",
            job_id, len(citation.missing), citation.missing[:5],
        )
        jobs.mark(session, job_id, jobs.BLOCKED_CITATION,
                  citation_total=citation.total,
                  citation_missing=len(citation.missing),
                  model=result.model,
                  error=f"so hieu la: {citation.missing[:10]}",
                  **paths)
        session.commit()
        return jobs.BLOCKED_CITATION

    jobs.mark(session, job_id, jobs.DONE,
              citation_total=citation.total, citation_missing=0,
              model=result.model, **paths)
    session.commit()
    return jobs.DONE


def chain_business_reports(session, job: dict, sidecar_path: str) -> int:
    """Sau khi (b) xong, xếp hàng (c) cho từng ngành vượt ngưỡng cường độ."""
    try:
        sidecar = json.loads(Path(sidecar_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Không đọc được sidecar %s: %s", sidecar_path, e)
        return 0

    added = 0
    for row in sidecar.get("industries_affected", []):
        if jobs.enqueue(
            session, "c", f"{row['ma_nganh']}-{job['id']}",
            vsic_code=row["ma_nganh"], industry=row["ten_nganh"],
            parent_job_id=job["id"],
            trigger_reason=f"bao_cao_b_{job['id']}_cuong_do_{row['cuong_do_tac_dong']:.0f}",
            priority=row["cuong_do_tac_dong"],
        ):
            added += 1
    return added


def drain(session, rag: RAGDatabase, scorer_version: str, max_jobs: int = 5,
          embedder=None) -> WorkerStats:
    stats = WorkerStats()

    while stats.picked < max_jobs:
        job = jobs.next_job(session)
        if not job:
            break
        stats.picked += 1

        status = run_job(session, rag, job, scorer_version, embedder=embedder)
        if status == jobs.DONE:
            stats.done += 1
            if job["kind"] == "b":
                row = session.execute(
                    text("SELECT output_json_path FROM report_jobs WHERE id = :i"), {"i": job["id"]}
                ).mappings().first()
                if row and row["output_json_path"]:
                    stats.chained += chain_business_reports(
                        session, job, row["output_json_path"]
                    )
                    session.commit()
        elif status == jobs.BLOCKED_CITATION:
            stats.blocked += 1
        else:
            stats.failed += 1

    return stats
