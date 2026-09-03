"""Nạp kho DEMO từ `du-lieu.json` của trang công khai.

DÙNG ĐỂ LÀM GÌ. Cơ sở dữ liệu thật (`data/legal_docs.db`) không nằm trong repo —
nó bị .gitignore loại ra vì chứa toàn văn và nặng hàng trăm MB. Ai clone repo về
mà chưa có kho thì `publish_site --html` chạy đúng nhưng dựng ra một trang rỗng:
giao diện lên, danh sách trống, và trông y hệt như code hỏng.

Script này lấp đúng khoảng đó. Nó đọc `tro-ly/du-lieu.json` — bộ metadata đã
đăng công khai — rồi dựng một SQLite đủ để `publish_site --html` chạy ra trang
thật, xem được bằng mắt.

    python -m scripts.nap_demo --tu ../legal-vault-public/tro-ly/du-lieu.json
    python -m scripts.nap_demo --tu du-lieu.json --gioi-han 200

RUỘT BIỂU MẪU lấy được, ruột văn bản thì không. `--noi-dung` trỏ vào thư mục
`content/` của repo trang công khai: 653/653 trang biểu mẫu ở đó có sẵn mục
"## Nội dung biểu mẫu" với đủ ruột mẫu, vì ruột mẫu VỐN đã được đăng.

    python -m scripts.nap_demo --tu ../legal-vault-public/tro-ly/du-lieu.json \
                               --noi-dung ../legal-vault-public/content

Văn bản thì 0/4.168 trang có toàn văn, và đó là CHỦ Ý chứ không phải thiếu sót:
mỗi trang văn bản đều ghi "Trang này không đăng toàn văn". Toàn văn chỉ nằm ở
`data/clean_text/*.md` trên máy đã chạy pipeline. Nên trên kho demo, mục nội dung
của VĂN BẢN sẽ luôn trống — muốn xem thì phải dựng từ kho thật.

GIỚI HẠN, PHẢI NÓI RÕ. Bộ này CHỈ có những gì `du-lieu.json` mang theo. Nó có
metadata và có QUAN HỆ DẪN CHIẾU (dựng lại từ khối `do_thi`), nhưng KHÔNG có:
  · điểm tác động 21 ngành  → mọi trang sẽ ghi "Chưa chấm điểm tác động"
  · toàn văn văn bản        → mục "Nội dung" của văn bản trống, kể cả khi có --noi-dung
  · thân biểu mẫu           → trừ khi truyền --noi-dung
Nên đây là bản để KIỂM GIAO DIỆN VÀ ĐƯỜNG DẪN, không phải bản để đăng.

VÌ SAO PHẢI NẠP CẢ QUAN HỆ. Bản đầu bỏ qua khối `do_thi`, và hệ quả không dừng ở
"mục Văn bản liên quan trống" như đã ghi ở đây. Sơ đồ quan hệ ở chế độ toàn kho
chỉ nhận nút CÓ ÍT NHẤT MỘT CẠNH (`S.ke.has(i)` trong tro_ly/index.html), nên kho
0 cạnh cho ra đúng MỘT nút — chính văn bản đang mở. Trên màn hình nó hiện ra là
"Toàn kho · 1 văn bản", trông y như bộ đồ thị hỏng chứ không như dữ liệu thiếu.
Mà 23.801 cạnh ấy nằm sẵn trong file nguồn, chỉ là chưa ai đọc.
"""
from __future__ import annotations

import argparse
import datetime
import json
import logging
import re
import time
from pathlib import Path

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Cờ phạm vi trong du-lieu.json được nén còn "tw"/"tinh"; DB dùng tên đầy đủ.
_PHAM_VI = {"tw": "trung_uong", "tinh": "tinh"}


def _ngay(s: str) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(s) if s else None
    except ValueError:
        return None


_RE_KHOA = re.compile(r'^form_key:\s*"?([^"\n]+)"?\s*$', re.M)


def _ruot_tu_trang(thu_muc_content: Path, kho_ruot: Path) -> dict[str, str]:
    """Rút ruột biểu mẫu từ các trang đã đăng. Trả về {form_key: đường dẫn .md}.

    Trang biểu mẫu công khai có cấu trúc cố định — bốn mục `## Tải về`,
    `## Căn cứ pháp lý`, `## Nội dung biểu mẫu`, `## Nguồn` — và cả 653 trang đều
    có đủ bốn. Cắt đúng mục thứ ba.

    CẮT Ở MỤC KẾ TIẾP, không lấy tới hết file: sau ruột còn `## Nguồn` mang URL
    Thư viện Pháp luật. Lấy tràn là dán địa chỉ nguồn vào giữa thân mẫu — đúng
    thứ mà chính trang tĩnh cũng cắt bỏ.
    """
    ra: dict[str, str] = {}
    d = Path(thu_muc_content) / "bieu-mau"
    if not d.is_dir():
        logger.warning("Không thấy %s — bỏ qua phần ruột biểu mẫu.", d)
        return ra
    kho_ruot.mkdir(parents=True, exist_ok=True)
    for f in sorted(d.glob("*.md")):
        try:
            noi = f.read_text(encoding="utf-8")
        except OSError:
            continue
        m = _RE_KHOA.search(noi)
        dau = noi.find("\n## Nội dung biểu mẫu")
        if not m or dau < 0:
            continue
        than = noi[noi.index("\n", dau + 1) + 1:]
        ket = than.find("\n## ")
        than = (than[:ket] if ket >= 0 else than).strip()
        if not than:
            continue
        khoa = m.group(1).strip()
        p_ra = kho_ruot / f"{khoa}.md"
        p_ra.write_text(than, encoding="utf-8")
        ra[khoa] = str(p_ra)
    logger.info("Rút được ruột của %d biểu mẫu từ %s", len(ra), d)
    return ra


def _toan_van_tu_drive(goi: dict, van_ban: list, kho: Path,
                       nghi: float = 0.0) -> dict[str, str]:
    """Tải toàn văn từng văn bản từ Google Drive, làm sạch, ghi ra .md.

    Trả về {số hiệu: đường dẫn .md}.

    VÌ SAO TẢI ĐƯỢC MÀ KHÔNG CẦN KHOÁ. `upload_file()` đặt quyền
    `{"type": "anyone", "role": "reader"}` cho mọi file nó đẩy lên, nên bản toàn
    văn đã công khai theo đường liên kết — chính là đường mà nút "↗ Toàn văn"
    trên trang vẫn mở. Tải bằng HTTP thường, ai cũng chạy được, không cần
    `credentials/`.

    File trên Drive là HTML THÔ của Bộ Tư pháp, không phải bản đã sạch. Nên phải
    đi qua `html_to_clean_text()` ở đây — đúng hàm mà pipeline dùng — chứ không
    ghi thẳng: ghi thẳng là đưa nguyên style, thẻ và bố cục trang nguồn vào kho.

    BỎ QUA FILE ĐÃ CÓ. 4.169 lượt tải là việc dài; chạy lại phải tiếp được chỗ
    dở chứ không bắt tải lại từ đầu.
    """
    import urllib.request

    from src.pipeline.text_processor import html_to_clean_text

    ra: dict[str, str] = {}
    kho.mkdir(parents=True, exist_ok=True)
    co_id = [v for v in van_ban if v.get("g")]
    logger.info("Tải toàn văn từ Drive: %d/%d văn bản có bản trên Drive",
                len(co_id), len(van_ban))
    loi = 0
    for k, v in enumerate(co_id, 1):
        so = (v.get("n") or "").strip()
        if not so:
            continue
        dich = kho / (v["s"] + ".md")
        if dich.is_file() and dich.stat().st_size:
            ra[so] = str(dich)
            continue
        url = f"https://drive.google.com/uc?export=download&id={v['g']}"
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                tho = r.read().decode("utf-8", errors="replace")
        except Exception as e:                       # noqa: BLE001
            loi += 1
            logger.warning("Không tải được %s: %s", so, e)
            continue
        sach = html_to_clean_text(tho)
        if not sach.strip():
            loi += 1
            continue
        dich.write_text(sach, encoding="utf-8")
        ra[so] = str(dich)
        if k % 100 == 0:
            logger.info("  … %d/%d", k, len(co_id))
        if nghi:
            time.sleep(nghi)
    if loi:
        logger.warning("%d văn bản tải hỏng — chạy lại sẽ thử tiếp.", loi)
    return ra


def nap(duong_json: Path, gioi_han: int | None = None,
        thu_muc_content: Path | None = None,
        tai_toan_van: bool = False) -> tuple[int, int, int, int, int, int]:
    """Đổ metadata, quan hệ và (nếu có) ruột biểu mẫu vào kho.

    Trả về (số văn bản, số biểu mẫu, số cạnh, số ruột BM, số toàn văn VB).
    """
    from src.storage.database import get_session, init_db, upsert_document
    from src.storage.models import DocumentReference, LegalForm

    goi = json.loads(duong_json.read_text(encoding="utf-8"))
    # `eff_state` KHÔNG ghi thẳng được: apply_derived_facts() tự tính lại nó từ
    # `eff_status` ở mọi đường ghi. Truyền eff_state vào thì nó bị đè, cả kho
    # thành "khong_ro", và bộ lọc mặc định của trang trợ lý ("Còn hiệu lực")
    # giấu sạch — trang lên nhưng danh sách trống, trông y hệt kho rỗng.
    # du-lieu.json có sẵn bảng tra mã → nhãn, dùng đúng nó.
    nhan_hl = goi.get("hieu_luc_vb", {})
    van_ban = goi.get("van_ban", [])
    bieu_mau = goi.get("bieu_mau", [])
    if gioi_han:
        # Cạnh trong `do_thi` là CHỈ SỐ vào mảng van_ban ĐẦY ĐỦ. Cắt mảng rồi mới
        # soi chỉ số thì cạnh trỏ lệch sang văn bản khác — sai âm thầm, đồ thị
        # vẫn vẽ ra được nên không ai biết. Cắt xong thì chỉ giữ cạnh có CẢ HAI
        # đầu còn nằm trong phần đã cắt.
        van_ban = van_ban[:gioi_han]
        bieu_mau = bieu_mau[:gioi_han]

    init_db()
    ruot = (_ruot_tu_trang(thu_muc_content, Path("data") / "demo_ruot")
            if thu_muc_content else {})
    toan_van = (_toan_van_tu_drive(goi, van_ban, Path("data") / "demo_toan_van")
                if tai_toan_van else {})
    n_vb = n_bm = n_ruot = 0
    with get_session() as s:
        for v in van_ban:
            so = (v.get("n") or "").strip()
            if not so:
                continue
            upsert_document(s, {
                "doc_num": so,
                "title": v.get("t") or so,
                "doc_type": v.get("l") or "",
                # ĐỊNH DANH THEO SLUG, KHÔNG THEO CHỈ SỐ MẢNG. Bản trước ghi
                # `f"demo-{i}"` với `i` là vị trí trong mảng, mà
                # `resolve_existing_document()` tra `moj_id` TRƯỚC TIÊN. Mảng
                # `van_ban` sắp theo `public_slug`, nên chỉ cần bản du-lieu.json
                # mới chèn thêm một văn bản sắp trước là mọi chỉ số phía sau dịch
                # một — và nạp lại lên kho cũ thì từng hàng bị ghi đè bằng dữ
                # liệu của văn bản KẾ BÊN.
                # Dựng lại được: nạp 6 văn bản, thêm một mục vào đầu rồi nạp lại
                # → hàng doc_num 01/1997/QH10 (một Luật) mang tiêu đề và
                # doc_type của một Quyết định, nên apply_derived_facts() tính lại
                # hierarchy_level/is_vbqppl/territorial_scope theo loại SAI. Văn
                # bản mới không bao giờ được thêm, mà script vẫn in "văn bản 7".
                # Không ngoại lệ, không log, trang dựng ra vẫn hợp lệ.
                # `s` là slug đã đăng công khai — ổn định giữa các bản dữ liệu.
                "moj_id": f"demo-{v.get('s') or so}",
                # Slug lấy THẲNG từ nguồn, không sinh lại. make_public_slug()
                # gắn 4 ký tự băm của doc_key = "{số hiệu}::{cơ quan}"; kho demo
                # đoán lại băm đó sẽ ra khác, nên 663/4.201 văn bản địa phương có
                # URL lệch bản đã đăng — trong khi script tự khai mục đích là
                # "kiểm đường dẫn".
                "public_slug": v.get("s") or None,
                # Cơ quan ban hành: thiếu nó thì doc_key rụng mất nửa sau, và hai
                # văn bản khác nhau trùng số hiệu (26 cặp trong kho, hầu hết là
                # QĐ-UBND/NQ-HĐND của các tỉnh khác nhau) bị gộp làm MỘT hàng
                # trộn dữ liệu của cả hai.
                "agency_name": v.get("a") or None,
                "hierarchy_level": v.get("c"),
                "eff_status": nhan_hl.get(v.get("e"), ""),
                "issue_date": _ngay(v.get("d", "")),
                "territorial_scope": _PHAM_VI.get(v.get("p"), "trung_uong"),
                "tvpl_field_code": v.get("f"),
                # Toàn văn tải từ Drive về, đã làm sạch. `upsert_document` bỏ qua
                # khoá có giá trị None nên không truyền khi chưa tải là đúng —
                # không xoá mất đường dẫn của lần chạy trước.
                **({"clean_text_path": toan_van[so]} if toan_van.get(so) else {}),
                "gdrive_fulltext_link": (
                    f"https://drive.google.com/file/d/{v['g']}/view"
                    if v.get("g") else None),
            })
            n_vb += 1
        s.commit()
        # ĐẾM HÀNG THẬT, không đếm mục JSON. Hai con số lệch nhau khi số hiệu
        # trùng bị gộp, và người vận hành đọc "văn bản 400" ở bước nạp rồi
        # "van_ban 396" ở bước dựng ngay sau đó mà không có gì giải thích.
        n_doc_vao = n_vb
        n_vb = s.execute(text("SELECT COUNT(*) FROM documents")).scalar() or 0

        for b in bieu_mau:
            khoa = (b.get("k") or "").strip()
            if not khoa:
                continue
            cu_co = s.query(LegalForm).filter_by(form_key=khoa).first()
            if cu_co:
                # Chạy lại trên kho đã có: vẫn phải gắn ruột. Bỏ qua thẳng như
                # bản trước là chạy lại với --noi-dung không có tác dụng gì, mà
                # người dùng thì không thấy lý do — kho vẫn đủ biểu mẫu.
                if ruot.get(khoa) and not cu_co.body_md_path:
                    cu_co.body_md_path = ruot[khoa]
                    n_ruot += 1
                continue
            if ruot.get(khoa):
                n_ruot += 1
            s.add(LegalForm(
                body_md_path=ruot.get(khoa),
                form_key=khoa,
                source=khoa.split("-")[0] or "hopdong",
                external_id=khoa.split("-")[-1],
                title=b.get("t") or khoa,
                is_business=True,
                crawl_status="OK",
                nghiep_vu=json.dumps(b.get("v") or [], ensure_ascii=False),
                eff_state=b.get("e"),
                gdrive_docx_link=(
                    f"https://drive.google.com/file/d/{b['g']}/view"
                    if isinstance(b.get("g"), str) else None),
            ))
            n_bm += 1
        s.commit()
        # Cùng lý do với n_vb: đếm theo KHO. Chạy lại thì mọi biểu mẫu đã có nên
        # vòng lặp `continue` hết, n_bm cục bộ bằng 0 và bản in ra thành "biểu
        # mẫu 0" trong khi kho vẫn đủ.
        n_bm = s.execute(text("SELECT COUNT(*) FROM legal_forms")).scalar() or 0

        n_canh = _nap_quan_he(s, goi, van_ban, DocumentReference)
        # Cũng đếm theo KHO: chạy lần hai thì `n_ruot` cục bộ bằng 0 (mọi biểu
        # mẫu đã có body_md_path nên nhánh gắn ruột không chạy), và bản trước in
        # cảnh báo sai "Không có ruột biểu mẫu — popup sẽ không hiện nội dung"
        # trong khi ruột vẫn còn nguyên trong kho. `n_tv` cũng vậy.
        n_ruot = s.execute(text(
            "SELECT COUNT(*) FROM legal_forms WHERE body_md_path IS NOT NULL")).scalar() or 0
        n_tv = s.execute(text(
            "SELECT COUNT(*) FROM documents WHERE clean_text_path IS NOT NULL")).scalar() or 0
    return n_vb, n_bm, n_canh, n_ruot, n_tv, n_doc_vao


def _nap_quan_he(s, goi: dict, van_ban: list, DocumentReference) -> int:
    """Dựng lại `document_references` từ khối `do_thi`. Trả về số cạnh đã ghi.

    Cạnh trong file là bộ ba chỉ số `[nguồn, đích, loại]`; kho thì nối bằng
    `source_doc_id` (khoá ngoại) và `target_doc_num` (SỐ HIỆU, không phải id) —
    đúng cặp mà `assistant_export._do_thi()` join lại khi xuất. Ghi sai một
    trong hai đầu là cạnh biến mất lúc xuất chứ không báo lỗi lúc nạp.
    """
    do_thi = goi.get("do_thi") or {}
    canh = do_thi.get("canh") or []
    ten_quan_he = do_thi.get("quan_he") or []
    if not canh:
        return 0

    n = len(van_ban)
    # Tra id theo số hiệu, MỘT LẦN. Hỏi kho từng cạnh là 23.801 lượt truy vấn.
    id_theo_so = dict(
        s.execute(text("SELECT doc_num, id FROM documents")).fetchall())

    hang, da_co = [], set()
    for c in canh:
        if len(c) < 2:
            continue
        i, j = c[0], c[1]
        # Cả hai đầu phải nằm trong phần đã nạp. Nửa cạnh không vẽ được, và
        # `_do_thi()` cũng bỏ nó lúc xuất — giữ lại chỉ tổ phình kho.
        if not (0 <= i < n and 0 <= j < n) or i == j:
            continue
        so_nguon = (van_ban[i].get("n") or "").strip()
        so_dich = (van_ban[j].get("n") or "").strip()
        id_nguon = id_theo_so.get(so_nguon)
        if not id_nguon or not so_dich or so_dich not in id_theo_so:
            continue
        loai = c[2] if len(c) > 2 else None
        ten = ten_quan_he[loai] if isinstance(loai, int) and loai < len(ten_quan_he) \
            else "Chưa xác định"
        # Số hiệu KHÔNG duy nhất trong kho: 300 mục đầu của file gộp lại còn 297
        # văn bản. Hai mục trùng số hiệu cho ra cùng một cặp cạnh, nên phải khử
        # trùng ở đây — không thì kho có cạnh lặp còn đồ thị thì không đổi.
        khoa = (id_nguon, so_dich, ten)
        if khoa in da_co:
            continue
        da_co.add(khoa)
        hang.append({
            "source_doc_id": id_nguon,
            "target_doc_num": so_dich,
            "relation_type": ten,
            "target_doc_id": id_theo_so.get(so_dich),
        })

    if not hang:
        return 0

    # KHỬ TRÙNG VỚI KHO ĐÃ CÓ, không chỉ trong một lần chạy. `da_co` ở trên chỉ
    # lọc trong lô này; `bulk_insert_mappings` thì ghi thẳng, mà bảng
    # `document_references` KHÔNG có ràng buộc UNIQUE và `init_db()` chỉ
    # `create_all` chứ không xoá bảng. Nên chạy lại script trên cùng kho là cộng
    # dồn — đo được: hai lần nạp 300 mục cho 188 hàng trên 94 cạnh phân biệt, mà
    # cả hai lần đều in "quan hệ 94" vì hàm trả về số hàng chèn LẦN NÀY.
    #
    # Sơ đồ trợ lý che mất lỗi này (`_do_thi()` gom cạnh vào một `set`), nhưng
    # trang tĩnh thì lộ: `html_site._lien_quan()` duyệt từng hàng nên mỗi quan hệ
    # hiện hai lần. Đo trên bản dựng sau hai lần nạp: 133 khối danh sách bị lặp.
    #
    # Chạy lại là thao tác ĐƯỢC KỲ VỌNG — docstring nêu hai lệnh mẫu khác nhau,
    # và đường "chạy lại để gắn ruột biểu mẫu" cũng đi qua đây.
    cu_co = {
        (r[0], r[1], r[2])
        for r in s.execute(text(
            "SELECT source_doc_id, target_doc_num, relation_type "
            "FROM document_references")).fetchall()
    }
    moi = [h for h in hang
           if (h["source_doc_id"], h["target_doc_num"], h["relation_type"]) not in cu_co]
    if moi:
        s.bulk_insert_mappings(DocumentReference, moi)
        s.commit()
    # Trả về số cạnh CÓ TRONG KHO, không phải số vừa chèn: chạy lại lần hai mà
    # in "quan hệ 0" thì người vận hành tưởng hỏng.
    return len(cu_co | {(h["source_doc_id"], h["target_doc_num"], h["relation_type"])
                        for h in hang})


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tu", required=True, help="Đường dẫn tới du-lieu.json")
    ap.add_argument("--gioi-han", type=int, default=None,
                    help="Chỉ nạp N mục đầu, cho nhanh")
    ap.add_argument("--toan-van", action="store_true",
                    help="Tải toàn văn văn bản từ Google Drive (bản đã công khai "
                         "theo liên kết). Lâu — 4.169 lượt tải; chạy lại tiếp được.")
    ap.add_argument("--noi-dung", type=Path, default=None, metavar="THU_MUC",
                    help="Thư mục content/ của repo trang công khai — rút ruột "
                         "biểu mẫu từ đó (văn bản KHÔNG có toàn văn ở đó)")
    a = ap.parse_args()

    p = Path(a.tu)
    if not p.is_file():
        raise SystemExit(f"Không thấy file: {p}")

    if a.noi_dung and not a.noi_dung.is_dir():
        raise SystemExit(f"Không thấy thư mục: {a.noi_dung}")
    n_vb, n_bm, n_canh, n_ruot, n_tv, n_vao = nap(
        p, a.gioi_han, a.noi_dung, a.toan_van)
    print(f"\n=== Đã nạp kho DEMO ===")
    print(f"  văn bản  {n_vb}")
    if n_vao > n_vb:
        print(f"    ({n_vao} mục đọc vào — {n_vao - n_vb} bị gộp vì trùng số hiệu")
        print(f"     mà nguồn không ghi cơ quan ban hành để phân biệt)")
    print(f"  biểu mẫu {n_bm}")
    print(f"  quan hệ  {n_canh}")
    print(f"  ruột BM  {n_ruot}")
    if not n_ruot:
        # Nói ngay ở đây, vì triệu chứng phía sau chỉ là "ruot.bieu_mau 0" giữa
        # một bảng số toàn số dương, rồi popup không hiện phần nội dung nào.
        print("  ⚠ Không có ruột biểu mẫu — popup sẽ không hiện phần Nội dung.")
        print("    Thêm: --noi-dung <đường dẫn>/legal-vault-public/content")
    print(f"  toàn văn {n_tv}")
    if not n_tv:
        print("  ⚠ Không có toàn văn văn bản — popup văn bản sẽ không có phần")
        print("    Nội dung. Thêm cờ --toan-van để tải từ Drive (lâu, nhưng")
        print("    chạy lại tiếp được và không cần khoá).")
    if not n_canh:
        # Nói thẳng ra, vì triệu chứng của nó trên giao diện là "Toàn kho · 1
        # văn bản" — trông như đồ thị hỏng chứ không như kho thiếu quan hệ.
        print("  ⚠ Không có quan hệ nào — sơ đồ liên kết sẽ chỉ hiện MỘT nút.")
        print("    Kiểm lại: du-lieu.json nguồn có khối \"do_thi\" với cạnh không?")
    # Câu chốt phải theo ĐÚNG thứ vừa nạp. Viết cứng "KHÔNG có toàn văn" thì
    # chạy với --toan-van xong vẫn đọc được một câu sai ngay dưới dòng báo đã
    # tải về 25 bản.
    thieu = ["điểm tác động"]
    if not n_tv:
        thieu.append("toàn văn văn bản")
    if not n_ruot:
        thieu.append("ruột biểu mẫu")
    print(f"\nĐây là bản KHÔNG có {', '.join(thieu)}.")
    print("Dùng để xem giao diện và kiểm đường dẫn, KHÔNG dùng để đăng.")
    print("\nDựng trang:")
    print("  python -m scripts.publish_site --html --out build/site")


if __name__ == "__main__":
    main()
