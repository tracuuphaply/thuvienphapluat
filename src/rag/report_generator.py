"""
AI Legal Compliance Report Generator.
Uses the FPTS-style System Prompt template to generate comprehensive industry legal reports based on database context.
"""
import os
import json
import logging
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

import httpx

from src.config import (
    DATA_DIR,
    PROJECT_ROOT,
    llm_api_key,
    openai_api_base,
    report_max_tokens,
    report_model,
    report_prompt_path,
)
from src.legal import effectivity
from src.legal.hierarchy import LEVEL_NON_NORMATIVE
from src.legal.provinces import province_name
from src.obsidian.config_obsidian import HIERARCHY_LABELS
from src.obsidian.vsic import code_of
from src.rag.db_rag import RAGDatabase
from src.rag.hybrid_search import hybrid_search, industry_search, SearchResult
from src.rag.graph_traversal import cascade_retrieve, validate_results, impact_analysis
from src.storage.database import get_session
from src.storage.models import Document, DocumentReference

logger = logging.getLogger(__name__)

# Mẫu prompt nằm trong repo là bản chuẩn; cho phép trỏ ra ngoài bằng biến môi
# trường thay vì hardcode đường dẫn máy cá nhân (bản cũ trỏ tới ~/Downloads nên
# trên bất kỳ máy nào khác cũng rơi về fallback).
REPO_PROMPT_PATH = PROJECT_ROOT / "src" / "rag" / "prompts" / "prompt_bao_cao_v98.md"
LEGACY_PROMPT_PATH = PROJECT_ROOT / "src" / "rag" / "prompts" / "prompt_report.md"


class PromptTemplateMissing(RuntimeError):
    """Không đọc được mẫu prompt — không được sinh báo cáo bằng prompt rút gọn."""


def _default_embedder():
    """Embedder cho nhánh vector; None nếu chưa cấu hình khoá API.

    Trả None thay vì ném lỗi để báo cáo vẫn chạy được bằng BM25 khi chưa có khoá.
    """
    from src.rag.embeddings_api import EmbeddingAPI

    embedder = EmbeddingAPI()
    if not embedder.api_key:
        logger.warning("Không có khoá API nhúng — chỉ dùng BM25, không có tìm kiếm ngữ nghĩa.")
        return None
    return embedder


def load_system_prompt() -> str:
    """Load system prompt from template file.

    Trước đây khi thiếu file, hàm trả về một câu mô tả vai trò một dòng và báo
    cáo vẫn được sinh ra — mất toàn bộ cấu trúc bắt buộc, quy tắc trích dẫn và
    điều cấm, mà người dùng không hề biết. Giờ thiếu mẫu là lỗi cứng.
    """
    # Đường mới trước: nó nở {{include:_chung/...}}, còn nhánh đọc file thô bên
    # dưới thì không. Từ khi mục "ĐIỀU CẤM VÀ CHECKLIST" chuyển sang file dùng
    # chung, đọc thô sẽ đưa nguyên chuỗi "{{include:...}}" cho mô hình — tức
    # báo cáo (a) mất sạch quy tắc trích dẫn và điều cấm, im lặng.
    if not report_prompt_path():
        try:
            from src.rag.reports.prompts import load_prompt

            return load_prompt("a")
        except Exception as e:
            logger.warning("Không nạp được prompt qua reports.prompts: %s", e)

    override = report_prompt_path()
    candidates = [Path(override)] if override else []
    candidates.append(REPO_PROMPT_PATH)
    candidates.append(LEGACY_PROMPT_PATH)

    for path in candidates:
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        # Extract system prompt section (starting from ## 1. VAI TRÒ)
        # Cắt từ "## 1. VAI TRÒ" tới trước mục 9 (hợp đồng dữ liệu) — phần sau
        # là tài liệu cho người vận hành, không phải chỉ dẫn cho mô hình.
        if "## 1. VAI TRÒ" in content:
            body = content[content.find("## 1. VAI TRÒ"):]
            cut = body.find("## 9. HỢP ĐỒNG DỮ LIỆU")
            return body[:cut].rstrip() if cut > 0 else body
        return content

    raise PromptTemplateMissing(
        f"Không đọc được mẫu prompt báo cáo tại: {[str(p) for p in candidates]}"
    )


def generate_compliance_report(
    db: RAGDatabase,
    industry: str,
    days: int = 250,
    scope: str = "",
    target_audience: str = "",
    # Mục 4 của prompt quy định 4–6 trang và giải thích rõ lý do: "một bản 4
    # trang được đọc hết có giá trị hơn một bản 15 trang bị bỏ qua". Mặc định
    # cũ là 8–15 trang, mâu thuẫn ngay với prompt hệ thống — script sinh báo
    # cáo có ghi đè, còn Telegram và CLI thì không.
    desired_length: str = "Báo cáo chuyên đề (4–6 trang)",
    model: str = "",
    embedder=None,
    context_sink: dict | None = None,
) -> str:
    """
    Generate a full professional Legal Compliance Report for an industry following the system prompt template.
    """
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=days)
    cut_off_date_str = end_date.strftime("%d/%m/%Y")
    period_str = f"Tháng {start_date.strftime('%m/%Y')} – {end_date.strftime('%m/%Y')}"

    default_scope = "Khung pháp lý điều chỉnh hoạt động kinh doanh, đầu tư, nghĩa vụ tài chính, lao động và điều kiện kinh doanh"
    default_audience = "Ban Lãnh đạo doanh nghiệp và Trưởng bộ phận pháp chế"

    scope = scope.strip() if scope else default_scope
    target_audience = target_audience.strip() if target_audience else default_audience

    logger.info(f"Generating legal report for industry '{industry}' [Scope: {scope}, Model: {model}]")

    # 1. Truy xuất theo cả bộ từ khoá của ngành. Tìm bằng đúng tên ngành khiến
    #    FTS đòi mọi token cùng xuất hiện trong một đoạn — 4/10 ngành ra 0 kết quả.
    #    Không truyền embedder thì nhánh vector không bao giờ chạy, hybrid search
    #    thoái hoá thành BM25 thuần — đúng lỗi cũ.
    if embedder is None:
        embedder = _default_embedder()
    raw_results = industry_search(db, industry=industry, limit=60, embedder=embedder)

    # 2. Loại đoạn thuộc văn bản đã bị bãi bỏ/thay thế; văn bản bị sửa đổi được
    #    giữ lại kèm cảnh báo (phần chưa bị sửa vẫn là luật hiện hành).
    as_dicts = [
        {"id": r.id, "doc_num": r.doc_num, "doc_key": r.doc_key,
         "heading": r.heading, "content": r.content}
        for r in raw_results
    ]
    kept = validate_results(db, as_dicts)
    loai_do_het_hieu_luc = len(as_dicts) - len(kept)
    if loai_do_het_hieu_luc:
        logger.info(f"Đã loại {loai_do_het_hieu_luc} đoạn thuộc văn bản hết hiệu lực")

    # 3. Không có dữ liệu thì KHÔNG gọi LLM. Sinh báo cáo từ ngữ cảnh rỗng chỉ
    #    tạo ra một văn bản trông có thẩm quyền mà không dựa trên căn cứ nào.
    if not kept:
        logger.warning(f"Không truy xuất được điều khoản nào cho ngành '{industry}'")
        return _empty_retrieval_report(industry, period_str, cut_off_date_str, scope)

    retrieved_doc_nums = list({c["doc_num"] for c in kept if c.get("doc_num")})

    docs_metadata = []
    graph_edges = []
    chunks_detail = []
    thieu_trang_thai = []

    # Search SQLite master DB for full metadata
    try:
        with get_session() as session:
            db_docs = session.query(Document).filter(Document.doc_num.in_(retrieved_doc_nums)).all()
            for doc in db_docs:
                # Không mặc định "Còn hiệu lực" khi nguồn không nói gì: với báo
                # cáo tuân thủ, đó là bịa dữ kiện pháp lý.
                eff_status = doc.eff_status or "Chưa xác định"
                if not doc.eff_status:
                    thieu_trang_thai.append(doc.doc_num)

                # Cấp hiệu lực và phạm vi lãnh thổ là dữ kiện mô hình BẮT BUỘC
                # phải có: Mục 3 Bước 3 của prompt yêu cầu xử lý mâu thuẫn giữa
                # các văn bản theo thứ bậc, mà trước đây nó chỉ nhận được chuỗi
                # doc_type nên phải tự đoán cái nào cao hơn cái nào.
                level = doc.hierarchy_level
                level = LEVEL_NON_NORMATIVE if level is None else int(level)
                docs_metadata.append({
                    "doc_num": doc.doc_num,
                    "title": doc.title,
                    "doc_type": doc.doc_type,
                    "cap_hieu_luc_phap_ly": level,
                    "cap_hieu_luc_dien_giai": HIERARCHY_LABELS.get(
                        level, HIERARCHY_LABELS[LEVEL_NON_NORMATIVE]
                    ),
                    "la_van_ban_qppl": bool(doc.is_vbqppl),
                    "pham_vi_lanh_tho": doc.territorial_scope or "khong_xac_dinh",
                    "dia_ban_ap_dung": province_name(doc.province_code_current),
                    "issue_date": str(doc.issue_date) if doc.issue_date else "",
                    "eff_from": str(doc.eff_from) if doc.eff_from else "",
                    "eff_to": str(doc.eff_to) if doc.eff_to else "",
                    "eff_status": eff_status,
                    "tinh_trang_hieu_luc_chuan_hoa": doc.eff_state or effectivity.KHONG_RO,
                    "hieu_luc_tinh_den_ngay": (
                        str(doc.eff_state_as_of) if doc.eff_state_as_of else ""
                    ),
                    "agency_name": doc.agency_name or "",
                    "field_name": doc.field_name or "",
                    "industries": doc.industries or ""
                })

                # Lấy quan hệ theo CẢ HAI CHIỀU. Chỉ lấy chiều xuôi thì không bao
                # giờ biết được văn bản này đang bị ai sửa đổi hay bãi bỏ — đúng
                # câu hỏi quan trọng nhất khi thẩm định hiệu lực.
                out_refs = session.query(DocumentReference).filter(
                    DocumentReference.source_doc_id == doc.id
                ).all()
                for ref in out_refs:
                    graph_edges.append({
                        "source_doc_num": doc.doc_num,
                        "target_doc_num": ref.target_doc_num,
                        "relation_type": ref.relation_type,
                        "chieu": "văn bản này tác động lên",
                    })

                in_refs = session.query(DocumentReference).filter(
                    DocumentReference.target_doc_num == doc.doc_num
                ).all()
                for ref in in_refs:
                    src = session.query(Document).filter(
                        Document.id == ref.source_doc_id
                    ).first()
                    graph_edges.append({
                        "source_doc_num": src.doc_num if src else "",
                        "target_doc_num": doc.doc_num,
                        "relation_type": ref.relation_type,
                        "chieu": "văn bản này BỊ tác động bởi",
                    })
    except Exception as e:
        logger.warning(f"Error querying master DB for metadata: {e}")

    found_doc_nums = {d["doc_num"] for d in docs_metadata}
    thieu_metadata = sorted(set(retrieved_doc_nums) - found_doc_nums)

    # Chunks detail excerpt
    for c in kept[:30]:
        item = {
            "doc_num": c["doc_num"],
            "heading": c["heading"],
            "content_excerpt": (c["content"] or "")[:1200],
        }
        if c.get("canh_bao_hieu_luc"):
            item["canh_bao_hieu_luc"] = c["canh_bao_hieu_luc"]
        chunks_detail.append(item)

    # Prepare JSON Data Context for LLM
    data_payload = {
        "thong_tin_tra_cuu": {
            "nganh_tra_cuu": industry,
            "tong_so_van_ban_tim_thay": len(docs_metadata),
            "tong_so_doan_triet_xuat": len(chunks_detail),
            "tong_so_quan_he_dan_chieu": len(graph_edges)
        },
        # Khối này để agent buộc phải nêu rõ khoảng trống dữ liệu ở cuối báo cáo
        # theo Mục 6 và Mục 8 của prompt, thay vì im lặng lấp bằng kiến thức nền.
        "han_che_du_lieu": {
            "so_van_ban_khong_ro_trang_thai_hieu_luc": len(thieu_trang_thai),
            "danh_sach_khong_ro_trang_thai": thieu_trang_thai,
            "so_doan_bi_loai_vi_van_ban_het_hieu_luc": loai_do_het_hieu_luc,
            "so_van_ban_thieu_metadata": len(thieu_metadata),
            "danh_sach_thieu_metadata": thieu_metadata,
            "pham_vi_thoi_gian_thuc_te": (
                "Kho dữ liệu KHÔNG được lọc theo kỳ báo cáo. Danh sách văn bản dưới "
                "đây là toàn bộ kết quả truy xuất theo ngành, có thể nằm ngoài "
                f"{period_str}. Phải tự đối chiếu issue_date của từng văn bản trước "
                "khi khẳng định nó thuộc kỳ báo cáo."
            ),
        },
        "danh_sach_van_ban": docs_metadata,
        "chi_tiet_dieu_khoan_chunks": chunks_detail,
        "do_thi_quan_he_van_ban_edges": graph_edges
    }

    # Trả ngữ cảnh ra ngoài để dựng biểu đồ từ đúng bộ văn bản đã đưa vào báo
    # cáo, thay vì truy xuất lần hai (vừa tốn tiền nhúng vừa có thể lệch kết quả).
    if context_sink is not None:
        context_sink.update(data_payload)

    system_prompt = load_system_prompt()

    # Mục 2 và mục 9 của prompt tham chiếu {{MA_NGANH}}, nhưng bản cũ chỉ gửi
    # tên ngành — mã ngành CHƯA BAO GIỜ tới tay mô hình, trong khi đó chính là
    # mã ghi trên giấy đăng ký kinh doanh của doanh nghiệp.
    ma_nganh = code_of(industry)
    industry_label = (
        f"{industry} (VSIC cấp 1, mã {ma_nganh})" if ma_nganh else industry
    )

    user_prompt = f"""
Soạn Báo cáo pháp lý chuyên đề theo đúng mẫu hệ thống đã được quy định.

NGANH      : {industry_label}
PHAM_VI    : {scope}
KY_BAO_CAO : {period_str}
MOC_CAT    : {cut_off_date_str}
DOI_TUONG  : {target_audience}
DO_DAI     : {desired_length}

=== DỮ LIỆU THỰC TẾ TRÍCH XUẤT TỪ DATABASE PHÁP LUẬT ===
{json.dumps(data_payload, ensure_ascii=False, indent=2)}

LƯU Ý QUAN TRỌNG:
1. Áp dụng chuẩn xác 100% CẤU TRÚC BÁO CÁO BẮT BUỘC ở Mục 4 (Trang bìa -> Tóm tắt điều hành -> Chương I -> Chương II...N -> Khối Văn bản trọng tâm -> Chương cuối -> Phụ lục bắt buộc).
2. Áp dụng văn phong: Tiêu đề mục là luận điểm hoàn chỉnh, câu mở đoạn in đậm chứa kết luận, đánh số luận cứ (1)... (2)..., định lượng số liệu và dẫn chiếu điều khoản cụ thể.
3. Không tự bịa số hiệu văn bản nằm ngoài Database cung cấp.
4. Khối `han_che_du_lieu` là dữ kiện bắt buộc phải công bố: mọi văn bản có
   eff_status "Chưa xác định" phải được ghi rõ là CHƯA XÁC MINH ĐƯỢC HIỆU LỰC,
   không được trình bày như đang còn hiệu lực. Đưa toàn bộ khối này vào phần
   hạn chế dữ liệu ở cuối báo cáo theo Mục 6 và Mục 8.
5. Kho dữ liệu không lọc theo kỳ báo cáo — tự đối chiếu issue_date của từng văn
   bản trước khi khẳng định nó phát sinh trong kỳ.
6. Khi hai văn bản mâu thuẫn, dùng `cap_hieu_luc_phap_ly` để xử lý theo Mục 3
   Bước 3: SỐ NHỎ HƠN LÀ HIỆU LỰC CAO HƠN. Văn bản có `la_van_ban_qppl` = false
   KHÔNG được dùng làm căn cứ pháp lý, chỉ được nhắc như thông tin tham khảo.
7. Văn bản có `pham_vi_lanh_tho` = "tinh" chỉ áp dụng trong `dia_ban_ap_dung`.
   Không được trình bày như quy định áp dụng toàn quốc.
"""

    api_key = llm_api_key()
    api_base = openai_api_base()

    if not api_key:
        logger.warning("No API Key configured. Returning fallback report.")
        return _fallback_structured_report(industry, period_str, cut_off_date_str, docs_metadata, graph_edges)

    try:
        url = f"{api_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        # Danh sách model không còn hardcode: gpt-4o là mặc định cũ, nhưng khoá
        # cứng khiến không đổi được model qua cấu hình.
        model_name = model or report_model()
        # 8–15 trang tiếng Việt vượt xa 8000 token; mức cũ luôn cắt giữa chừng.
        max_tokens = report_max_tokens()

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.3,
            "max_tokens": max_tokens
        }

        logger.info(f"Calling LLM Chat Completions ({model_name})...")
        resp = httpx.post(url, headers=headers, json=payload, timeout=300.0)
        resp.raise_for_status()
        data = resp.json()

        if "choices" in data and len(data["choices"]) > 0:
            choice = data["choices"][0]
            report_text = choice["message"]["content"]
            # Báo cáo bị cắt giữa chừng mà im lặng thì người đọc tưởng là bản đầy đủ.
            if choice.get("finish_reason") == "length":
                logger.warning("Báo cáo bị cắt do chạm giới hạn token")
                report_text += (
                    "\n\n---\n"
                    f"> ⚠️ **Báo cáo bị cắt do chạm giới hạn {max_tokens} token.** "
                    "Nội dung phía trên chưa đầy đủ. Tăng `REPORT_MAX_TOKENS` hoặc "
                    "thu hẹp phạm vi chuyên đề rồi tạo lại."
                )
            logger.info("Successfully generated AI Legal Report!")
            return report_text
    except Exception as e:
        logger.error(f"Error executing LLM API call for report: {e}")

    return _fallback_structured_report(industry, period_str, cut_off_date_str, docs_metadata, graph_edges)


def _empty_retrieval_report(industry: str, period_str: str, cut_off_date_str: str, scope: str) -> str:
    """Báo cáo khi không truy xuất được điều khoản nào.

    Gọi LLM với ngữ cảnh rỗng sẽ cho ra một báo cáo trông chuyên nghiệp nhưng
    không dựa trên bất kỳ văn bản nào trong kho — đúng thứ Mục 8 của prompt cấm.
    """
    return f"""# BÁO CÁO PHÁP LÝ CHUYÊN ĐỀ — KHÔNG ĐỦ DỮ LIỆU
NGÀNH {industry.upper()}
{period_str} · Dữ liệu chốt đến ngày {cut_off_date_str}

## Không thể lập báo cáo

Truy xuất cơ sở dữ liệu **không trả về điều khoản nào** cho ngành `{industry}`
với phạm vi: {scope}

Báo cáo đã được dừng lại có chủ đích. Sinh nội dung phân tích khi không có căn
cứ nào trong kho sẽ tạo ra một tài liệu trông có thẩm quyền nhưng không dẫn
chiếu được tới văn bản thật.

## Cần kiểm tra

1. Kho văn bản đã có tài liệu thuộc ngành này chưa (`python -m src.rag.cli stats`).
2. Bộ từ khoá của ngành trong `INDUSTRY_MAP` đã đủ bao phủ chưa.
3. Toàn bộ văn bản truy xuất được có bị loại vì đã hết hiệu lực không.
"""


def _fallback_structured_report(industry: str, period_str: str, cut_off_date_str: str, docs_metadata: list, graph_edges: list) -> str:
    """Fallback structured report if LLM API is unavailable."""
    md = f"""# BÁO CÁO PHÁP LÝ CHUYÊN ĐỀ
NGÀNH {industry.upper()}
{period_str} · Dữ liệu chốt đến ngày {cut_off_date_str}

## Tóm tắt điều hành
- Đã tổng hợp {len(docs_metadata)} văn bản quy phạm pháp luật trong cơ sở dữ liệu.
- Phát hiện {len(graph_edges)} quan hệ sửa đổi, bãi bỏ, hướng dẫn.

## Danh mục văn bản ghi nhận
"""
    for d in docs_metadata:
        md += f"- **{d['doc_num']}**: {d['title']} (Cơ quan: {d['agency_name']}, Trạng thái: {d['eff_status']})\n"

    md += "\n> *Lưu ý: Không thể kết nối API AI để tạo toàn văn báo cáo phân tích theo mẫu FPTS.*"
    return md
