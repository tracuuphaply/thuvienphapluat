"""
Sinh thân bài Cẩm nang cho một biểu mẫu: dựng ngữ cảnh → gọi mô hình → qua cổng.

TÁI DÙNG, KHÔNG VIẾT LẠI. `call_report_llm()` đã có phần xử lý
`finish_reason == "length"` và ba lượt thử lại lỗi mạng — bài bị cắt giữa chừng
mà im lặng là lỗi nặng, và viết lại logic đó ở đây là bảo đảm hai bản sẽ trôi
khác nhau. Prompt đi qua `load_cam_nang_prompt()` để dùng chung phần giọng văn
và phần điều cấm với ba loại báo cáo.

MỘT LƯỢT SINH LẠI KHI TRƯỢT CỔNG TIÊU ĐỀ, không nhiều hơn. Cổng tiêu đề trượt là
lỗi làm theo chỉ dẫn, thường sửa được ngay khi chỉ mặt lỗi; trượt lần hai nghĩa
là mô hình không có tiêu đề nào khác để đưa, và thử tiếp chỉ đốt tiền.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.camnang import cong
from src.camnang.kho import Kho, UngVien
from src.camnang.toan_van import KhongTaiDuoc, cat_gon, tai_toan_van
from src.rag.reports.llm import LLMResult, call_report_llm, strip_code_fence
from src.rag.reports.prompts import load_cam_nang_prompt

logger = logging.getLogger(__name__)

#: Trần ký tự toàn văn nhét vào một prompt. Một biểu mẫu có tới 4 căn cứ; nhét
#: cả bốn toàn văn đầy đủ là vài trăm nghìn ký tự, vượt cửa sổ ngữ cảnh và làm
#: mô hình lạc khỏi chính tờ mẫu — thứ bài này nói về.
TRAN_TOAN_VAN_MOI_VB = 30_000

#: Trần ruột tờ mẫu đưa vào prompt. Mô hình cần ĐỌC tờ mẫu để chỉ chỗ điền, chứ
#: không cần chép nó — ruột mẫu đã có chỗ riêng cuối bài.
TRAN_RUOT_MAU = 20_000


def _cat_mo_ta(mo_ta: str) -> str:
    """Đưa mô tả về trong trần, cắt ở RANH GIỚI TỪ.

    Khác THAN_BAI_MAX (chạm trần thì LOẠI, vì đó là dấu hiệu mô hình đang chép
    tờ mẫu): mô tả dài 520 ký tự chỉ là hơi dài lời, và nó là meta description —
    cắt gọn ở đó là việc bình thường, vứt cả bài thì không. Nhưng cắt cứng bằng
    slice thì đứt giữa từ ("…trong 10 ngày làm vi"), và đó là thứ hiện nguyên
    văn trên kết quả tìm kiếm.
    """
    if len(mo_ta) <= cong.MO_TA_MAX:
        return mo_ta
    cat = mo_ta[:cong.MO_TA_MAX]
    lui = cat.rfind(" ")
    if lui > cong.MO_TA_MAX // 2:
        cat = cat[:lui]
    return cat.rstrip(" ,;:-–—") + "…"


class SinhThatBai(RuntimeError):
    """Không sinh được bài cho biểu mẫu này. Bỏ qua nó, không dừng cả lượt."""


@dataclass
class BaiSinhRa:
    """Một bản ghi đúng §1 hợp đồng, cộng phần chẩn đoán không đem giao."""

    form_key: str
    tieu_de: str
    mo_ta: str
    than_bai: str
    citation_ok: bool
    #: Chẩn đoán — KHÔNG ghi vào bai.json, chỉ để in ra và ghi log.
    so_hieu_la: list[str] = field(default_factory=list)
    so_hieu_dat: int = 0
    model: str = ""
    bi_cat: bool = False
    sinh_lai: bool = False

    def ban_ghi(self) -> dict:
        """Đúng bốn trường của hợp đồng, cộng cờ cổng. Không thừa một khoá."""
        return {
            "form_key": self.form_key,
            "tieu_de": self.tieu_de,
            "mo_ta": self.mo_ta,
            "than_bai": self.than_bai,
            "citation_ok": self.citation_ok,
        }


def _doc_json(text: str) -> dict:
    """Bóc khối JSON khỏi đầu ra mô hình.

    Mẫu prompt cấm viết chữ nào ngoài JSON, nhưng cấm không phải là bảo đảm —
    cùng lý do tồn tại của cổng trích dẫn. Gỡ hàng rào mã trước, rồi bóc từ dấu
    `{` đầu tới `}` cuối; hỏng thật thì ném lỗi, KHÔNG đoán mò một bài rỗng.
    """
    raw = strip_code_fence(text or "").strip()
    try:
        goi = json.loads(raw)
    except json.JSONDecodeError:
        i, j = raw.find("{"), raw.rfind("}")
        if i < 0 or j <= i:
            raise SinhThatBai(f"đầu ra không có JSON: {raw[:200]!r}")
        try:
            goi = json.loads(raw[i:j + 1])
        except json.JSONDecodeError as e:
            raise SinhThatBai(f"JSON hỏng: {e}") from e

    if not isinstance(goi, dict):
        raise SinhThatBai(f"đầu ra không phải đối tượng JSON: {type(goi).__name__}")
    return goi


def _nhan_hieu_luc(kho: Kho, ma: str) -> str:
    return kho.hieu_luc_bm.get(ma, ma or "không rõ")


def dung_ngu_canh(
    ung_vien: UngVien,
    kho: Kho,
    tai_toan_van_ve: bool = True,
    thu_muc_dem: Path | None = None,
) -> tuple[str, cong.NguonTrichDan]:
    """Dựng phần người-dùng của prompt, và nhóm số hiệu được nguồn bảo chứng.

    HAI THỨ NÀY PHẢI SINH RA CÙNG MỘT CHỖ. Nhóm bảo chứng chỉ đúng khi nó gồm
    đúng những số hiệu có trong thứ mô hình ĐƯỢC ĐỌC. Tách ra hai hàm thì sớm
    muộn một bên thêm nguồn mà bên kia không biết, và cổng trích dẫn chặn oan —
    hoặc tệ hơn, cho qua oan.
    """
    bm = ung_vien.bieu_mau
    nguon = cong.NguonTrichDan()

    ruot = bm.ruot_mau[:TRAN_RUOT_MAU]
    nguon.them_van_ban(ruot)
    nguon.them_so_hieu(bm.can_cu)

    khoi_can_cu: list[str] = []
    for vb in ung_vien.can_cu_khop:
        dong = [
            f"### Căn cứ: {vb.so_hieu} — {vb.tieu_de}",
            f"Tình trạng hiệu lực: {vb.hieu_luc}",
        ]
        if tai_toan_van_ve and vb.co_toan_van:
            try:
                text = tai_toan_van(vb.drive_toan_van, thu_muc_dem=thu_muc_dem)
            except KhongTaiDuoc as e:
                logger.warning("Không lấy được toàn văn %s: %s", vb.so_hieu, e)
            else:
                # CẮT TRƯỚC, BẢO CHỨNG SAU — thứ tự này là toàn bộ ý nghĩa của
                # nhóm bảo chứng. Nạp bản đầy đủ rồi mới cắt cho prompt nghĩa là
                # cổng bảo chứng cho những số hiệu nằm sau mốc cắt, tức những số
                # mô hình CHƯA TỪNG ĐỌC — mà "mô hình chưa từng đọc mà vẫn viết
                # ra" chính là định nghĩa của bịa.
                text_cat = cat_gon(text, TRAN_TOAN_VAN_MOI_VB)
                nguon.them_van_ban(text_cat)
                dong.append("")
                dong.append("Toàn văn:")
                dong.append(text_cat)
        khoi_can_cu.append("\n".join(dong))

    thieu_can_cu = not ung_vien.can_cu_khop
    phan = [
        "## BIỂU MẪU CẦN VIẾT BÀI",
        "",
        f"- Tên biểu mẫu (nguyên văn từ kho): {bm.tieu_de}",
        "- Nhóm nghiệp vụ: "
        + (", ".join(kho.nghiep_vu.get(v, v) for v in bm.nghiep_vu) or "chưa phân nhóm"),
        f"- Tình trạng hiệu lực: {_nhan_hieu_luc(kho, bm.hieu_luc)}",
        "- Số hiệu căn cứ ghi nhận được: "
        + (", ".join(bm.can_cu) if bm.can_cu else "KHÔNG CÓ"),
        "",
    ]

    if thieu_can_cu:
        phan += [
            "> ⚠ Kho KHÔNG ghi nhận văn bản căn cứ nào khớp cho biểu mẫu này.",
            "> Viết theo §4 của mẫu: thừa nhận thẳng bằng một câu lời thường,",
            "> KHÔNG trích Điều/khoản/số hiệu nào, và soi chính tờ mẫu.",
            "",
        ]

    phan += ["## RUỘT TỜ MẪU (để bạn ĐỌC — không chép lại vào bài)", "", ruot, ""]
    if khoi_can_cu:
        phan += ["## VĂN BẢN CĂN CỨ", ""] + khoi_can_cu
    phan += [
        "",
        "---",
        "",
        "Trả về đúng một đối tượng JSON với ba khoá `tieu_de`, `mo_ta`, "
        "`than_bai`. Không viết chữ nào ngoài JSON.",
    ]
    return "\n".join(phan), nguon


_NHAC_TIEU_DE = (
    "\n\nLƯU Ý SỬA LỖI — lượt trước bị cổng chặn tiêu đề loại, lý do: {ly_do}.\n"
    "Viết lại tiêu đề theo §5: lấy tên biểu mẫu, chuyển về chữ thường có dấu như "
    "một câu tiếng Việt bình thường, rồi thêm phần nói rõ bài trả lời câu hỏi gì. "
    "Không có quốc hiệu, tiêu ngữ, 'Mẫu số', 'Phụ lục', 'Biểu mẫu số', 'Đơn vị:', "
    "'Tên cơ quan'. Thân bài giữ nguyên chất lượng, không rút ngắn."
)


def sinh_bai(
    ung_vien: UngVien,
    kho: Kho,
    tai_toan_van_ve: bool = True,
    thu_muc_dem: Path | None = None,
    db_path: Path | None = None,
    model: str = "",
    max_tokens: int = 0,
    goi_llm=call_report_llm,
) -> BaiSinhRa:
    """Sinh một bài, chạy đủ ba cổng, trả về bản ghi đã có `citation_ok` thật.

    `goi_llm` tiêm được để test chạy không cần mạng — cùng cách
    src/rag/report_generator.py làm.
    """
    bm = ung_vien.bieu_mau
    he_thong = load_cam_nang_prompt()
    nguoi_dung, nguon = dung_ngu_canh(
        ung_vien, kho, tai_toan_van_ve=tai_toan_van_ve, thu_muc_dem=thu_muc_dem
    )

    ket_qua: LLMResult | None = None
    goi: dict = {}
    kq_tieu_de = cong.KetQuaCong(False, "chưa chạy")
    sinh_lai = False

    for lan in (1, 2):
        them = "" if lan == 1 else _NHAC_TIEU_DE.format(ly_do=kq_tieu_de.ly_do)
        ket_qua = goi_llm(he_thong, nguoi_dung + them, model=model,
                          max_tokens=max_tokens)
        # Kiểm "bị cắt" TRƯỚC khi bóc JSON: khi chạm trần token,
        # `call_report_llm` nối một khối cảnh báo vào cuối văn bản, mà khối đó
        # phá luôn cú pháp JSON. Bóc trước thì lỗi hiện ra là "JSON hỏng" và
        # người vận hành đi sửa nhầm chỗ.
        if ket_qua.truncated:
            raise SinhThatBai(
                f"bài bị cắt do chạm trần token — tăng CAM_NANG_MAX_TOKENS "
                f"(hiện {max_tokens or 'mặc định'})"
            )
        goi = _doc_json(ket_qua.text)
        kq_tieu_de = cong.cong_tieu_de(goi.get("tieu_de") or "")
        if kq_tieu_de:
            break
        logger.warning("[%s] cổng tiêu đề loại (%s) — sinh lại lần %d",
                       bm.form_key, kq_tieu_de.ly_do, lan + 1)
        sinh_lai = True
    if not kq_tieu_de:
        raise SinhThatBai(f"cổng tiêu đề loại sau 2 lượt: {kq_tieu_de.ly_do}")

    tb = cong.chuoi_hop_le(goi.get("than_bai"))
    if tb is None:
        raise SinhThatBai(
            f"than_bai không phải chuỗi ({type(goi.get('than_bai')).__name__})")
    than_bai = tb.strip()
    if not than_bai:
        raise SinhThatBai("mô hình trả thân bài rỗng")

    mt = cong.chuoi_hop_le(goi.get("mo_ta"))
    if mt is None:
        raise SinhThatBai(
            f"mo_ta không phải chuỗi ({type(goi.get('mo_ta')).__name__})")
    mo_ta = _cat_mo_ta(re.sub(r"\s+", " ", mt.strip()))

    # Đối chiếu TOÀN BỘ phần chữ, không riêng thân bài: tiêu đề thành <title> và
    # mô tả thành meta description — số hiệu bịa nằm đó còn hiện ra trên trang
    # kết quả Google, dễ thấy hơn nằm giữa bài.
    tieu_de = (cong.chuoi_hop_le(goi.get("tieu_de")) or "").strip()
    dat, bao_cao = cong.cong_trich_dan(
        cong.van_ban_doi_chieu(tieu_de, mo_ta, than_bai), nguon, db_path=db_path)
    if not dat:
        logger.warning("[%s] cổng trích dẫn: %s", bm.form_key, bao_cao.summary())

    return BaiSinhRa(
        form_key=bm.form_key,
        tieu_de=tieu_de,
        mo_ta=mo_ta,
        than_bai=than_bai,
        citation_ok=dat,
        so_hieu_la=list(bao_cao.missing),
        so_hieu_dat=len(bao_cao.found),
        model=ket_qua.model,
        bi_cat=ket_qua.truncated,
        sinh_lai=sinh_lai,
    )


__all__ = [
    "TRAN_TOAN_VAN_MOI_VB", "TRAN_RUOT_MAU",
    "SinhThatBai", "BaiSinhRa", "dung_ngu_canh", "sinh_bai",
]
