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
from src.rag.reports import figures as figures_mod
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


TIEU_DE = {
    "a": "Báo cáo tổng hợp pháp lý ngành",
    "b": "Báo cáo cập nhật văn bản mới",
    "c": "Báo cáo chuyên sâu cho doanh nghiệp",
}

THU_MUC = {"a": "nganh", "b": "van_ban_moi", "c": "doanh_nghiep"}


def _nhan_bia(job: dict, result: generators.ReportResult) -> str:
    """Dòng chủ đề in trên bìa: tên ngành với (a)/(c), số hiệu với (b)."""
    if job["kind"] == "b":
        nums = (result.sidecar or {}).get("doc_nums") or []
        return ", ".join(nums[:3]) + (" …" if len(nums) > 3 else "")
    ma, ten = job.get("vsic_code") or "", job.get("industry") or ""
    return f"{ma} · {ten}".strip(" ·") or "Chưa xác định"


def _khoa_hop_tac(brand: dict) -> dict:
    """Mọi khoá partner_* trong file thương hiệu, lấy theo TIỀN TỐ.

    Trước đây chỗ này liệt kê tay từng trường, và ba lần liên tiếp việc thêm một
    trường mới vào ReportMeta bị quên nối ở đây — hai cột giá trị không hiện,
    rồi tuỳ chọn tắt chấm đầu dòng không có tác dụng. Cả ba đều hỏng IM LẶNG:
    khối vẫn dựng, chỉ thiếu phần vừa thêm.

    Lọc theo tên trường có thật trên ReportMeta để một khoá lạ trong JSON không
    làm nổ TypeError — file cấu hình do người sửa tay, gõ nhầm là chuyện thường.
    """
    from dataclasses import fields

    from src.utils.report_pdf import ReportMeta

    hop_le = {f.name for f in fields(ReportMeta)}
    return {k: v for k, v in brand.items()
            if k.startswith("partner_") and k in hop_le}


def _build_pdf(job: dict, md_path: Path,
               result: generators.ReportResult) -> str | None:
    """Dựng PDF từ markdown đã qua cổng trích dẫn.

    Dùng chung build_report_pdf với scripts/generate_industry_reports.py: quy
    ước markdown ở mục 7 của prompt được viết cho đúng bộ dựng đó, nên bộ thứ
    hai sẽ lệch ngay lần đầu prompt đổi.

    Lỗi dựng PDF KHÔNG làm job thất bại — markdown đã có và đã qua cổng, mất
    PDF là mất một định dạng chứ không mất nội dung. Nhưng phải log, vì thiếu
    font là lỗi hay gặp nhất khi đổi máy (report_pdf.py hardcode đường dẫn font
    macOS) và im lặng thì không ai biết vì sao không có file.
    """
    from src.config import PROJECT_ROOT
    from src.utils.report_pdf import ReportMeta, build_report_pdf

    brand_path = PROJECT_ROOT / "report_branding.json"
    brand = (json.loads(brand_path.read_text(encoding="utf-8"))
             if brand_path.exists() else {})
    hom_nay = datetime.date.today()

    # Biểu đồ dựng từ chính khối dữ kiện mô hình đã nhận, nên hình và chữ không
    # thể nói hai chuyện khác nhau. Hỏng thì bỏ hình chứ không bỏ PDF.
    try:
        figures = figures_mod.build_figures(job["kind"], result.payload or {})
    except Exception as e:
        logger.warning("Job %d: không dựng được biểu đồ — %s: %s",
                       job["id"], type(e).__name__, e)
        figures = []

    chung = dict(
        figures=figures,
        industry=_nhan_bia(job, result),
        industry_code=job.get("vsic_code") or "",
        period=f"{TIEU_DE[job['kind']]} · {hom_nay:%m/%Y}",
        cutoff=f"{hom_nay:%d/%m/%Y}",
        scope=brand.get("scope", ""),
        company=brand.get("company", ""),
        contact=brand.get("footer", ""),
    )

    # HAI BẢN, KHÁC NHAU ĐÚNG MỘT THỨ: chân trang có hay không có lời ngỏ hợp
    # tác. Báo cáo gửi doanh nghiệp thì lời mời hợp tác với công ty luật là nói
    # với nhầm người; báo cáo dùng làm hồ sơ chào mời công ty luật thì cần nó.
    #
    # Dựng cả hai ngay tại đây thay vì thêm một cờ chọn: lúc gửi mới biết gửi
    # cho ai, mà lúc đó job đã chạy xong và không còn ngữ cảnh để dựng lại.
    ban = [("khach", {})]
    if (brand.get("partner_pitch") or "").strip():
        ban.append(("doitac", dict(
            **_khoa_hop_tac(brand),
        )))

    duong_dan: dict[str, str] = {}
    for ten, rieng in ban:
        out = md_path.with_name(f"{md_path.stem}_{ten}.pdf")
        try:
            build_report_pdf(result.markdown, out, ReportMeta(**chung, **rieng))
            duong_dan[ten] = str(out)
        except Exception as e:
            logger.warning("Job %d: không dựng được PDF bản %s — %s: %s",
                           job["id"], ten, type(e).__name__, e)

    # Trả bản gửi khách làm đường dẫn chính: đó là bản dùng nhiều hơn, và nếu
    # chỉ dựng được một bản thì phải là bản không có lời chào mời.
    return duong_dan.get("khach") or duong_dan.get("doitac")


def _write_outputs(job_id: int, kind: str, result: generators.ReportResult) -> dict:
    """Ghi markdown và sidecar.

    PDF dựng riêng SAU cổng trích dẫn, không ở đây: PDF là dạng gửi cho khách,
    còn markdown là bản để soi mô hình đã bịa số hiệu nào. Dựng cả hai cùng lúc
    thì bản bị chặn cũng có PDF, và sớm muộn có người gửi nhầm.
    """
    out_dir = REPORTS_DIR / THU_MUC[kind]
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
        if kind == "a":
            result = generators.generate_industry_report(
                session, rag, job["vsic_code"], scorer_version, embedder=embedder
            )
        elif kind == "b":
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

    # ── Cổng cứng: mọi số hiệu trong báo cáo phải CÓ THẬT ──
    # "Có thật" = trong kho, HOẶC có căn cứ trong nguồn mô hình đã đọc (toàn văn
    # văn bản nguồn + prompt). Nhóm sau là văn bản cũ bị bãi bỏ/dẫn chiếu mà kho
    # chưa có bản ghi — số thật, mô hình chép lại chứ không bịa.
    citation = check_citations(result.markdown, extra_allowed=result.allowed_doc_nums)
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

    # Qua cổng rồi mới dựng PDF — bản bị chặn chỉ có markdown.
    pdf = _build_pdf(job, Path(paths["output_md_path"]), result)
    if pdf:
        paths["output_pdf_path"] = pdf

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
