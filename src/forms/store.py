"""
Ghi biểu mẫu và căn cứ của chúng xuống cơ sở dữ liệu.

Tách khỏi bộ cào để phần này test được bằng dữ liệu dựng tay, không cần trình
duyệt: mọi hàm ở đây nhận `FormListItem` / `FormDetail` chứ không nhận HTML.

NỐI CĂN CỨ VỀ KHO VĂN BẢN — HAI ĐƯỜNG, KHÁC ĐỘ CHẮC CHẮN:

  1. `documents.tvpl_id` — link căn cứ trên /bieumau mang sẵn id TVPL của văn bản
     (…-686963.aspx). Id duy nhất, khớp một-một.
  2. `documents.doc_num` — dò theo số hiệu. Số hiệu KHÔNG duy nhất toàn quốc: 63
     tỉnh đánh số độc lập nên "67/2026/QĐ-UBND" tồn tại ở 18 tỉnh. Khớp ra nhiều
     bản thì để TRỐNG chứ không chọn bừa một cái — sai ở đây là gắn biểu mẫu vào
     văn bản của tỉnh khác, còn tệ hơn không gắn gì.

Không khớp được là chuyện BÌNH THƯỜNG: kho mới có 4.467 văn bản còn biểu mẫu dẫn
tới cả những văn bản chưa cào (đo trên mẫu thử: 2/2 căn cứ đều chưa có trong kho).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_, text

from src.legal.form_taxonomy import (
    sang_ma_van_ban,
    ten_linh_vuc_bieu_mau,
    ten_loai_mau,
    ten_nhom_hop_dong,
)
from src.sources.tvpl_forms_parse import (
    SOURCE_BIEU_MAU,
    FormDetail,
    FormListItem,
)
from src.storage.models import LegalForm, LegalFormRef

logger = logging.getLogger(__name__)


@dataclass
class KetQuaLuu:
    them_moi: int = 0
    cap_nhat: int = 0
    khong_doi: int = 0
    can_cu_noi_duoc: int = 0
    can_cu_chua_co_trong_kho: int = 0

    def tom_tat(self) -> str:
        return (
            f"{self.them_moi} mới, {self.cap_nhat} cập nhật, "
            f"{self.khong_doi} không đổi; căn cứ: "
            f"{self.can_cu_noi_duoc} nối được / "
            f"{self.can_cu_chua_co_trong_kho} chưa có trong kho"
        )


def loc_dang_cong_khai(q):
    """Lọc biểu mẫu ĐỦ ĐIỀU KIỆN LÊN TRANG CÔNG KHAI: doanh nghiệp HOẶC cá nhân.

    MỘT hàm cho mọi bên tiêu thụ, không phải mỗi bên tự viết `is_business == 1`.
    Trước đây điều kiện đó nằm rải ở sáu chỗ — trang công khai, bộ dữ liệu trợ lý,
    chỉ mục tìm kiếm, lệnh Telegram — và mở sang cá nhân nghĩa là sửa đúng sáu
    chỗ. Sót một chỗ thì mẫu cá nhân có trong kho, có trang, mà tìm không ra;
    không có gì hỏng, không có gì báo.

    KHÔNG dùng cho Telegram: bot `/bieumau` là công cụ của chủ doanh nghiệp, đổ
    thêm mẫu cá nhân vào là làm hỏng cái đang dùng được. Nó lọc `is_business`
    thẳng, có chủ đích.
    """
    return q.filter(or_(LegalForm.is_business.is_(True),
                        LegalForm.is_individual.is_(True)))


def _ten_loai(source: str, ma: int | None) -> str | None:
    if ma is None:
        return None
    return ten_loai_mau(ma) if source == SOURCE_BIEU_MAU else ten_nhom_hop_dong(ma)


def tim_doc_key(session, doc_num: str, tvpl_doc_id: str | None) -> str | None:
    """doc_key của văn bản căn cứ, hoặc None khi chưa có / không chắc.

    Trả None trong hai trường hợp khác hẳn nhau — kho chưa có văn bản, và số hiệu
    khớp nhiều văn bản. Cả hai đều KHÔNG được đoán bừa; bên gọi phân biệt bằng
    log chứ không bằng giá trị trả về, vì với người đọc thì hệ quả như nhau:
    biểu mẫu chưa nối được vào kho.
    """
    if tvpl_doc_id:
        row = session.execute(
            text("SELECT doc_key FROM documents WHERE tvpl_id = :i LIMIT 2"),
            {"i": str(tvpl_doc_id)},
        ).fetchall()
        if len(row) == 1:
            return row[0][0]

    if not doc_num or "/" not in doc_num:
        return None

    rows = session.execute(
        text("SELECT doc_key, territorial_scope FROM documents WHERE doc_num = :n"),
        {"n": doc_num},
    ).fetchall()
    if len(rows) == 1:
        return rows[0][0]
    if len(rows) > 1:
        # Nhiều tỉnh trùng số hiệu. Chỉ chốt được khi đúng MỘT bản là trung ương
        # — biểu mẫu kèm theo văn bản trung ương là trường hợp áp đảo.
        tw = [r[0] for r in rows if r[1] == "trung_uong"]
        if len(tw) == 1:
            return tw[0]
        logger.info(
            "Số hiệu %s khớp %d văn bản, không chốt được — để trống doc_key",
            doc_num, len(rows),
        )
    return None


def luu_bieu_mau(
    session,
    item: FormListItem,
    detail: FormDetail | None = None,
    body_hash: str | None = None,
    body_chars: int | None = None,
    body_html_path: str | None = None,
    crawl_status: str = "OK",
    crawl_error: str | None = None,
    ket_qua: KetQuaLuu | None = None,
) -> LegalForm:
    """Thêm mới hoặc cập nhật một biểu mẫu, theo `form_key`.

    Giữ nguyên kết quả phễu lọc đã có (`audience`, `nghiep_vu`, …) khi ruột mẫu
    KHÔNG đổi: phân loại lại tốn một lượt gọi mô hình cho mỗi mẫu, mà nội dung
    không đổi thì kết luận cũng không đổi. `body_hash` là thứ quyết định.
    """
    kq = ket_qua or KetQuaLuu()
    form = session.query(LegalForm).filter_by(form_key=item.form_key).one_or_none()
    la_moi = form is None
    if la_moi:
        form = LegalForm(form_key=item.form_key)
        session.add(form)

    noi_dung_doi = bool(body_hash) and form.body_hash != body_hash

    form.source = item.source
    form.external_id = item.external_id
    form.slug = item.slug
    form.title = item.title
    form.url = item.url
    form.keywords = json.dumps(item.keywords, ensure_ascii=False)
    form.updated_on = item.updated_on
    form.crawl_status = crawl_status
    form.crawl_error = crawl_error

    if item.form_type_code is not None:
        form.form_type_code = item.form_type_code
        form.form_type_name = _ten_loai(item.source, item.form_type_code)
    if item.field_code is not None:
        form.field_code = item.field_code
        form.field_name = ten_linh_vuc_bieu_mau(item.field_code)
        ma_vb, nguon = sang_ma_van_ban(item.field_code)
        form.tvpl_field_code = ma_vb
        form.tvpl_field_source = nguon

    if body_hash is not None:
        form.body_hash = body_hash
    if body_chars is not None:
        form.body_chars = body_chars
    if body_html_path is not None:
        form.body_html_path = body_html_path

    if noi_dung_doi and not la_moi:
        # Ruột đổi thì kết luận phễu cũ không còn bảo chứng gì. Xoá để lượt phân
        # loại sau chạy lại, thay vì giữ một nhãn đã lỗi thời mà trông vẫn đúng.
        form.audience = None
        form.audience_source = None
        form.audience_confidence = None
        form.audience_reason = None
        form.is_business = None
        form.excluded_reason = None
        form.published_hash = None

    if detail is not None:
        _luu_can_cu(session, item.form_key, detail, kq)

    if la_moi:
        kq.them_moi += 1
    elif noi_dung_doi:
        kq.cap_nhat += 1
    else:
        kq.khong_doi += 1
    return form


def _luu_can_cu(session, form_key: str, detail: FormDetail, kq: KetQuaLuu) -> None:
    """Ghi lại căn cứ. Xoá hết rồi ghi lại chứ không vá từng dòng.

    Căn cứ của một biểu mẫu là một tập nhỏ (1–8 dòng) và TVPL có sửa: vá từng
    dòng sẽ để lại căn cứ cũ đã bị gỡ nằm lại vĩnh viễn.
    """
    session.query(LegalFormRef).filter_by(form_key=form_key).delete()
    for ref in detail.refs:
        doc_key = tim_doc_key(session, ref.doc_num, ref.tvpl_doc_id)
        if doc_key:
            kq.can_cu_noi_duoc += 1
        else:
            kq.can_cu_chua_co_trong_kho += 1
        session.add(LegalFormRef(
            form_key=form_key,
            doc_num=ref.doc_num,
            doc_key=doc_key,
            source=ref.source,
        ))


TRANG_THAI_CHO = "PENDING"


def ghi_hang_doi(session, items) -> int:
    """Ghi mọi mục vừa liệt kê vào DB với trạng thái PENDING. Trả về số dòng mới.

    HÀNG ĐỢI PHẢI NẰM TRONG DB, KHÔNG PHẢI TRONG BỘ NHỚ — đúng lý do
    `crawl_frontier` tồn tại. Bản đầu chỉ ghi dòng khi ĐÃ THỬ tải trang chi tiết,
    nên đứt giữa chừng là mất danh sách: đo ngày 18/08/2026, kho có 76 dòng cho
    662 mẫu đã liệt kê, và mỗi lần chạy lại phải lật 22 nhóm × ~40 lượt tải mất
    5,5 phút chỉ để dựng lại đúng cái danh sách vừa mất.

    Tệ hơn con số: 40 lượt tải đó chạy TRƯỚC việc cần làm, nên khi bộ cào chạm
    tới trang chi tiết đầu tiên thì Cloudflare đã dựng lại thử thách.

    KHÔNG hạ cấp dòng đã OK: hàm chỉ chèn dòng còn thiếu.
    """
    hom_nay = date.today()
    da_co = {
        k for (k,) in session.query(LegalForm.form_key).filter(
            LegalForm.form_key.in_([it.form_key for it in items])
        ).all()
    }
    them = 0
    for it in items:
        if it.form_key in da_co:
            continue
        luu_bieu_mau(session, it, crawl_status=TRANG_THAI_CHO)
        them += 1

    # Đóng mốc "còn thấy trên nguồn" cho MỌI mục vừa liệt kê, kể cả mục đã có.
    # Đây là nửa còn lại của cơ chế phát hiện mẫu bị gỡ: không đóng mốc thì không
    # phân biệt được "TVPL vẫn còn mẫu này" với "lượt cào chưa tới nó".
    session.query(LegalForm).filter(
        LegalForm.form_key.in_([it.form_key for it in items])
    ).update({"last_seen_at": hom_nay, "delisted_at": None},
             synchronize_session=False)

    if them:
        logger.info("Ghi %d mục mới vào hàng đợi biểu mẫu", them)
    return them


def danh_dau_bi_go(session, source: str, moc: date | None = None) -> list[str]:
    """Đánh dấu biểu mẫu không còn xuất hiện trên trang liệt kê TVPL.

    MẤT KHỎI NGUỒN LÀ TÍN HIỆU PHÁP LÝ, KHÔNG PHẢI LỖI CÀO. Biểu mẫu biến mất
    thường vì văn bản mẹ đã bị thay thế và TVPL gỡ luôn phụ lục cũ. Không ghi lại
    thì kho giữ mãi một biểu mẫu mà chính nguồn đã bỏ, và người dùng tải về một tờ
    giấy không còn tồn tại ở đâu.

    KHÔNG XOÁ bản ghi: bản đã tải vẫn là bằng chứng về thứ từng có hiệu lực, và
    báo cáo cũ có thể đã dẫn tới nó. Chỉ gắn `delisted_at`.

    Chỉ chạy được sau một lượt liệt kê ĐẦY ĐỦ (không có --limit): lượt cào cắt
    ngang sẽ làm mọi mẫu chưa tới lượt trông như đã bị gỡ.
    """
    hom_nay = moc or date.today()
    rows = (
        session.query(LegalForm)
        .filter(LegalForm.source == source)
        .filter(LegalForm.delisted_at.is_(None))
        .filter((LegalForm.last_seen_at.is_(None)) | (LegalForm.last_seen_at < hom_nay))
        .all()
    )
    for f in rows:
        f.delisted_at = hom_nay
        # Trang công khai phải đăng lại để hiện cảnh báo đã bị gỡ.
        f.published_hash = None
    if rows:
        logger.warning("%d biểu mẫu %s không còn trên TVPL — đã gắn delisted_at",
                       len(rows), source)
    return [f.form_key for f in rows]


def hang_doi_con_lai(session, source: str) -> list[FormListItem]:
    """Các mục còn phải tải trang chi tiết, dựng lại từ DB.

    Cho phép chạy tiếp mà KHÔNG lật lại trang liệt kê — vào thẳng việc cần làm
    trong lúc `cf_clearance` còn tươi nhất.
    """
    rows = (
        session.query(LegalForm)
        .filter(LegalForm.source == source)
        .filter(LegalForm.crawl_status != "OK")
        .order_by(LegalForm.form_key)
        .all()
    )
    ra: list[FormListItem] = []
    for f in rows:
        ra.append(FormListItem(
            source=f.source, external_id=f.external_id, slug=f.slug or "",
            title=f.title or "", url=f.url or "",
            keywords=json.loads(f.keywords or "[]"),
            updated_on=f.updated_on,
            field_code=f.field_code, form_type_code=f.form_type_code,
        ))
    return ra


def so_hieu_can_cu_chua_co(session, gioi_han: int = 500) -> list[str]:
    """Số hiệu văn bản mà biểu mẫu dẫn tới nhưng kho chưa có.

    Đây là danh sách việc cho bộ cào văn bản: mỗi số hiệu ở đây là một chỗ mà
    người đọc bấm vào biểu mẫu rồi không đi tiếp được sang căn cứ.
    """
    rows = session.execute(text("""
        SELECT DISTINCT doc_num FROM legal_form_refs
        WHERE doc_key IS NULL AND doc_num LIKE '%/%'
        ORDER BY doc_num LIMIT :n
    """), {"n": gioi_han}).fetchall()
    return [r[0] for r in rows]


def noi_lai_can_cu(session) -> int:
    """Thử nối lại các căn cứ còn trống sau khi kho văn bản lớn thêm.

    Chạy sau mỗi lần cào văn bản: biểu mẫu cào từ tháng trước có thể nối được
    hôm nay mà không phải cào lại TVPL.
    """
    refs = session.query(LegalFormRef).filter(LegalFormRef.doc_key.is_(None)).all()
    noi_them = 0
    for ref in refs:
        doc_key = tim_doc_key(session, ref.doc_num, None)
        if doc_key:
            ref.doc_key = doc_key
            noi_them += 1
    if noi_them:
        logger.info("Nối thêm %d căn cứ biểu mẫu vào kho văn bản", noi_them)
    return noi_them


__all__ = [
    "loc_dang_cong_khai",
    "KetQuaLuu", "TRANG_THAI_CHO", "tim_doc_key", "luu_bieu_mau",
    "ghi_hang_doi", "hang_doi_con_lai", "danh_dau_bi_go",
    "so_hieu_can_cu_chua_co", "noi_lai_can_cu",
]
