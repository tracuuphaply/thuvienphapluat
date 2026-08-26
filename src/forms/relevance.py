"""
Phễu lọc "biểu mẫu phục vụ hoạt động kinh doanh" — hai tầng quy tắc.

VÌ SAO LỌC THEO LĨNH VỰC LÀ KHÔNG ĐỦ. Cộng cả 21 lĩnh vực nghi là liên quan doanh
nghiệp được 17.385 mẫu trên tổng 33.820 — quá nửa kho. Mà lĩnh vực "Kế toán –
Kiểm toán" (1.220 mẫu) chứa cả biểu quyết toán ngân sách của Kho bạc Nhà nước lẫn
báo cáo tài chính doanh nghiệp. Hai thứ đó cùng lĩnh vực, cùng loại mẫu, cùng cơ
quan ban hành — không dấu hiệu phân loại nào tách được chúng.

THỨ PHÂN BIỆT LÀ AI CẦM BÚT ĐIỀN. Biểu mẫu nào cũng tự khai điều đó ngay ở khối
đầu ("Đơn vị báo cáo: Kho bạc Nhà nước", "Tên doanh nghiệp: …"). Phễu vì vậy chạy
trên tiêu đề + khối đầu ruột mẫu, không chạy trên metadata.

BA TẦNG, MỖI TẦNG ĐẮT HƠN TẦNG TRƯỚC:

    1. whitelist lĩnh vực     ~17.385 / 33.820   miễn phí, ở module này
    2. quy tắc từ khoá        cắt phần chắc chắn  miễn phí, ở module này
    3. mô hình ngôn ngữ       phần còn lại        một lượt gọi/mẫu, ở classifier.py

Tầng 2 chỉ được kết luận khi CHẮC — chắc giữ hoặc chắc loại. Mọi trường hợp lửng
lơ phải đẩy lên tầng 3 chứ không đoán: quy tắc đoán sai thì không ai biết, còn
đẩy lên tầng 3 chỉ tốn thêm ít tiền.

Bộ đếm dùng `count_matches()` của src/analysis/lexicon.py chứ không dùng
`if tu_khoa in van_ban`. Module đó ra đời từ đúng lỗi này: "nước" khớp cả "nhà
nước" khiến một ngành ôm 97/314 văn bản. Ở đây hậu quả còn trực tiếp hơn — dấu
hiệu LOẠI mà khớp nhầm là biểu mẫu doanh nghiệp bị vứt đi.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from src.analysis.lexicon import count_matches
from src.legal.form_taxonomy import CA_NHAN, CO_QUAN_NHA_NUOC, DOANH_NGHIEP

# ──────────────────────────────────────────────
# Tầng 1 — whitelist lĩnh vực /bieumau
# ──────────────────────────────────────────────
#: 21 mã lĩnh vực của trang /bieumau (danh mục 47 nhóm, KHÔNG phải danh mục 27
#: nhóm của trang văn bản). Số mẫu đo ngày 18/08/2026, tổng 17.385.
#:
#: LOẠI RA có chủ đích: 3 (bộ máy hành chính), 4 (bổ trợ tư pháp), 6 (cán bộ -
#: công chức - viên chức), 12 (Đảng), 18 (giáo dục), 20 (hôn nhân - gia đình),
#: 28 (quốc phòng - an ninh), 32 (thủ tục tố tụng), 34 (thi đua khen thưởng),
#: 38 (trách nhiệm hình sự), 39 (tư pháp - hộ tịch), 40 (văn hoá - thể thao),
#: 41 (văn thư lưu trữ), 45 (xuất nhập cảnh), 47 (y tế) — chủ doanh nghiệp không
#: điền chúng để phục vụ kinh doanh.
BIEU_MAU_BUSINESS_FIELDS: tuple[int, ...] = (
    1,   # An toàn thực phẩm        248
    2,   # Bảo hiểm                 635
    7,   # Công nghệ thông tin    1.221
    9,   # Chứng khoán            1.016
    11,  # Doanh nghiệp             875
    13,  # Đất đai – Nhà ở          592
    14,  # Đấu thầu                 297
    15,  # Đầu tư                   961
    21,  # Kế toán – Kiểm toán    1.220
    24,  # Lao động – Tiền lương  1.113
    27,  # Phòng cháy chữa cháy      53
    29,  # Sở hữu trí tuệ           265
    30,  # Tài chính              1.599
    31,  # Tài nguyên – Môi trường 1.647
    33,  # Thủ tục hành chính       150
    35,  # Thuế - Phí – Lệ phí    1.260
    36,  # Thương mại             1.291
    37,  # Tiền tệ - Ngân hàng    1.420
    42,  # Vi phạm hành chính       269
    44,  # Xây dựng - Đô thị        379
    46,  # Xuất nhập khẩu           874
)


def linh_vuc_bieu_mau_kinh_doanh() -> frozenset[int]:
    """Whitelist lĩnh vực, sau khi áp biến môi trường.

    Dùng chung biến `BUSINESS_FIELD_CODES` với bộ lọc văn bản là SAI: hai bên
    đánh mã khác nhau hoàn toàn. Biến riêng `FORM_FIELD_CODES` để người vận hành
    đổi định nghĩa mà không vô tình đổi luôn phạm vi báo cáo.
    """
    raw = (os.getenv("FORM_FIELD_CODES", "") or "").strip()
    if not raw:
        return frozenset(BIEU_MAU_BUSINESS_FIELDS)
    try:
        codes = {int(x) for x in raw.replace(";", ",").split(",") if x.strip()}
    except ValueError:
        return frozenset(BIEU_MAU_BUSINESS_FIELDS)
    return frozenset(codes) or frozenset(BIEU_MAU_BUSINESS_FIELDS)


def la_linh_vuc_kinh_doanh(ma: int | None) -> bool:
    return ma in linh_vuc_bieu_mau_kinh_doanh()


# ──────────────────────────────────────────────
# Tầng 2 — quy tắc từ khoá
# ──────────────────────────────────────────────
# Dấu hiệu LOẠI: mẫu do cơ quan nhà nước tự điền cho nội bộ bộ máy.
#
# Cố ý dùng CỤM ĐẦY ĐỦ chứ không dùng từ lẻ. "nhà nước" trần sẽ khớp cả "doanh
# nghiệp nhà nước" — mà doanh nghiệp nhà nước chính là đối tượng phải điền biểu
# mẫu kinh doanh. Một từ khoá quá rộng ở đây quét sạch cả nhóm mẫu hợp lệ.
DAU_HIEU_LOAI: tuple[str, ...] = (
    "kho bạc nhà nước",
    "vụ ngân sách nhà nước",
    "cơ quan nhà nước",
    "ngân sách nhà nước",
    "ngân sách trung ương",
    "ngân sách địa phương",
    "dự toán ngân sách",
    "quyết toán ngân sách",
    "đơn vị sự nghiệp công lập",
    "công chức",
    "viên chức",
    "đảng viên",
    "chi bộ",
    "cấp uỷ",
    "cấp ủy",
    "ủy ban nhân dân",
    "uỷ ban nhân dân",
    "hội đồng nhân dân",
    "quân nhân",
    "quốc phòng",
    "công an nhân dân",
    "thi đua khen thưởng",
    "cơ sở giáo dục",
    # TÊN LOẠI CƠ QUAN, không phải tên đối tượng phục vụ. Đây là chỗ phân biệt
    # "cá nhân điền" với "cơ quan phục vụ cá nhân điền": mẫu nhắc "học sinh" có
    # thể do phụ huynh điền, nhưng mẫu mà một BÊN KÝ là "Trường THCS Đồng Tiến"
    # thì bên đó là nhà trường.
    # Đo được: bỏ bốn từ "học sinh/sinh viên/hộ nghèo/người có công" khỏi danh
    # sách này làm "HỢP ĐỒNG SỬA CHỮA BÀN GHẾ HỌC SINH" — hợp đồng giữa trường
    # và nhà thầu — bị xếp thành mẫu cá nhân.
    "nhà trường",
    "trường thcs",
    "trường thpt",
    "trường tiểu học",
    "trường trung học",
    "trường mầm non",
    "phòng giáo dục",
    "sở giáo dục",
    "bệnh viện",
    "trạm y tế",
)

#: BỐN TỪ ĐÃ RỜI KHỎI DANH SÁCH TRÊN, và đây là thay đổi đáng kể nhất của đợt mở
#: sang cá nhân: "học sinh", "sinh viên", "hộ nghèo", "người có công".
#:
#: Chúng từng là dấu hiệu LOẠI vì mẫu nhắc tới học sinh thì không phải mẫu doanh
#: nghiệp điền — đúng với câu hỏi cũ. Nhưng câu hỏi cũ là "có phải doanh nghiệp
#: không", còn câu hỏi mới là "AI điền", và với câu hỏi mới thì chính bốn từ đó
#: là chỉ dấu MẠNH NHẤT rằng người điền là một cá nhân.
#:
#: Giữ chúng ở danh sách loại là tự tay vứt đúng phần kho định đi tìm.
DAU_HIEU_CA_NHAN: tuple[str, ...] = (
    "cá nhân",
    "công dân",
    "người dân",
    "hộ gia đình",
    "chủ hộ",
    "học sinh",
    "sinh viên",
    "phụ huynh",
    "hộ nghèo",
    "hộ cận nghèo",
    "người có công",
    "thương binh",
    "người khuyết tật",
    "người cao tuổi",
    "trẻ em",
    "vợ chồng",
    "cha mẹ",
    "con đẻ",
    "con nuôi",
    "kết hôn",
    "ly hôn",
    "khai sinh",
    "khai tử",
    "hộ tịch",
    "hộ khẩu",
    "thường trú",
    "tạm trú",
    "căn cước công dân",
    "chứng minh nhân dân",
    "hộ chiếu",
    "di chúc",
    "thừa kế",
    "di sản",
    "cấp dưỡng",
    "trợ cấp",
    "lương hưu",
    "thai sản",
    "bảo hiểm y tế",
    "khám chữa bệnh",
    "học phí",
    "học bổng",
    "nguyên đơn",
    "bị đơn",
    "người khởi kiện",
)

# Dấu hiệu GIỮ: chỉ dấu doanh nghiệp là bên điền.
DAU_HIEU_GIU: tuple[str, ...] = (
    "doanh nghiệp",
    "công ty cổ phần",
    "công ty trách nhiệm hữu hạn",
    "hộ kinh doanh",
    "hợp tác xã",
    "người sử dụng lao động",
    "người lao động",
    "hợp đồng lao động",
    "đăng ký doanh nghiệp",
    "đăng ký kinh doanh",
    "giấy chứng nhận đăng ký",
    "chi nhánh",
    "văn phòng đại diện",
    "địa điểm kinh doanh",
    "mã số thuế",
    "hoá đơn",
    "hóa đơn",
    "tờ khai thuế",
    "báo cáo tài chính",
    "vốn điều lệ",
    "cổ đông",
    "thành viên góp vốn",
    "tờ khai hải quan",
    "xuất khẩu",
    "nhập khẩu",
    "nhãn hiệu",
    "kinh doanh",
)

#: LOẠI VĂN BẢN Ở ĐẦU TIÊU ĐỀ — tầng phủ quyết, mạnh hơn mọi từ khoá chủ đề.
#:
#: Hiệu chuẩn 201 mẫu ngẫu nhiên trên 18 lĩnh vực liên quan cá nhân (26/08/2026)
#: cho thấy từ khoá CHỦ ĐỀ không phân biệt được ai điền, vì văn bản do cơ quan
#: phát hành cũng nói về đúng chủ đề đó:
#:     "MẪU BÁO CÁO HOẠT ĐỘNG BẢO HIỂM Y TẾ"        ← không phải mẫu của người bệnh
#:     "MẪU QUYẾT ĐỊNH VỀ VIỆC HƯỞNG TRỢ CẤP"       ← không phải mẫu của người hưởng
#:     "MẪU BÁO CÁO TUỔI LY HÔN TRUNG BÌNH CỦA TAND"← không phải mẫu của người ly hôn
#: Cả 17 ca dương tính giả của nhãn "cá nhân" đều đúng dạng này.
#:
#: Nhưng LOẠI VĂN BẢN thì phân biệt được, và phân biệt gần như tuyệt đối. Đo trên
#: cùng 201 mẫu, tỉ lệ phục vụ cá nhân theo loại:
#:     BÁO CÁO 0/37 · QUYẾT ĐỊNH 0/21 · THÔNG BÁO 0/17 · BIÊN BẢN 0/13 ·
#:     CÔNG VĂN 0/5 · PHIẾU KIỂM SÁT 0/4 · TRÍCH LỤC 0/3 · SỔ THEO DÕI 0/3
#: Tổng 93 mẫu thuộc các loại này, KHÔNG MỘT MẪU NÀO do cá nhân điền.
#:
#: Lý do bản chất: đây là công cụ một tổ chức PHÁT HÀNH, không phải giấy tờ một
#: người NỘP VÀO. Doanh nghiệp vẫn nộp báo cáo, nên đây chỉ phủ quyết cờ cá nhân
#: chứ không phủ quyết cờ doanh nghiệp.
LOAI_KHONG_PHAI_CA_NHAN: tuple[str, ...] = (
    "báo cáo", "quyết định", "thông báo", "biên bản", "công văn",
    "phiếu kiểm sát", "sổ theo dõi", "trích lục", "danh sách", "bảng tổng hợp",
    "kế hoạch", "đề án", "quy chế", "lời chứng", "phát biểu", "kiến nghị",
    "giấy phép", "giấy chứng nhận", "giấy biên nhận", "giấy đăng ký",
    "chứng chỉ", "yêu cầu", "phương án", "biểu tổng hợp",
)

#: Loại giấy tờ mà một NGƯỜI nộp vào cho cơ quan. Đo trên 201 mẫu: BẢN KHAI 5/5,
#: ĐƠN XIN 3/3, TỜ KHAI 2/2, PHIẾU KHAI BÁO 1/1, BẢN TƯỜNG TRÌNH 1/1 — 12/12 đều
#: phục vụ cá nhân. Cỡ mẫu nhỏ nên đây là BẰNG CHỨNG CỘNG THÊM, không phải kết
#: luận: "đơn đề nghị" cũng hay do doanh nghiệp nộp (5/12 trong mẫu).
LOAI_GIAY_TO_CA_NHAN: tuple[str, ...] = (
    "bản khai", "đơn xin", "tờ khai", "phiếu khai báo", "bản tường trình",
)

#: Tiêu đề nói lên chủ đề rõ hơn nhiều so với một lần xuất hiện đâu đó trong
#: ruột mẫu — cùng tỉ lệ trọng số mà industry_classifier.py đã dùng.
TRONG_SO_TIEU_DE = 3
TRONG_SO_RUOT = 1

#: Điểm tối thiểu để tầng 2 dám kết luận. Bằng đúng một lần khớp ở TIÊU ĐỀ, hoặc
#: ba lần khớp trong ruột mẫu.
NGUONG_CHAC = 3

#: Chỉ đọc phần đầu ruột mẫu. Khối tự khai ("Đơn vị báo cáo: …") luôn nằm ở đây,
#: còn phần thân đầy chỗ điền trống không nói lên ai điền.
KY_TU_DAU_RUOT = 1500

QUY_TAC = "quy_tac"
CAN_HOI_LLM = "can_hoi_llm"


@dataclass
class KetQuaQuyTac:
    """Kết luận của tầng 2. `audience` rỗng nghĩa là phải hỏi tầng 3.

    `audience` là phân loại CHÍNH, còn `cho_doanh_nghiep` / `cho_ca_nhan` là hai
    cờ độc lập — một biểu mẫu phục vụ được cả hai bên. Hợp đồng thuê nhà, hợp
    đồng vay, giấy uỷ quyền: doanh nghiệp dùng, cá nhân cũng dùng. Ép chọn một
    phía là mất mẫu ở phía kia.
    """

    audience: str | None = None
    diem_giu: int = 0
    diem_loai: int = 0
    diem_ca_nhan: int = 0
    loai_van_ban: str = ""
    dau_hieu_giu: list[str] = field(default_factory=list)
    dau_hieu_loai: list[str] = field(default_factory=list)
    dau_hieu_ca_nhan: list[str] = field(default_factory=list)
    cho_doanh_nghiep: bool = False
    cho_ca_nhan: bool = False

    @property
    def chac_chan(self) -> bool:
        return self.audience is not None

    def ly_do(self) -> str:
        if self.audience == DOANH_NGHIEP:
            return "quy tắc — dấu hiệu doanh nghiệp: " + ", ".join(self.dau_hieu_giu[:4])
        if self.audience == CO_QUAN_NHA_NUOC:
            return "quy tắc — dấu hiệu cơ quan nhà nước: " + ", ".join(
                self.dau_hieu_loai[:4])
        if self.audience == CA_NHAN:
            if self.cho_doanh_nghiep:
                return ("quy tắc — phục vụ cả hai bên: "
                        + ", ".join((self.dau_hieu_ca_nhan + self.dau_hieu_giu)[:4]))
            return "quy tắc — dấu hiệu cá nhân: " + ", ".join(
                self.dau_hieu_ca_nhan[:4])
        return (
            f"quy tắc không chắc (doanh nghiệp {self.diem_giu} / cá nhân "
            f"{self.diem_ca_nhan} / nhà nước {self.diem_loai}) — chuyển sang mô hình"
        )


def _cham_diem(tu_khoa: tuple[str, ...], tieu_de: str,
               ruot: str) -> tuple[int, list[str]]:
    diem = 0
    trung: list[str] = []
    for kw in tu_khoa:
        o_tieu_de = count_matches(kw, tieu_de)
        o_ruot = count_matches(kw, ruot)
        if not (o_tieu_de or o_ruot):
            continue
        # Ruột mẫu chỉ tính MỘT lần cho mỗi từ khoá: một biểu mẫu nhắc "doanh
        # nghiệp" 50 lần không vì thế mà thuộc về doanh nghiệp hơn.
        diem += o_tieu_de * TRONG_SO_TIEU_DE + min(1, o_ruot) * TRONG_SO_RUOT
        trung.append(kw)
    return diem, trung


def loai_van_ban(tieu_de: str) -> str:
    """Loại văn bản đứng đầu tiêu đề, đã bỏ tiền tố "MẪU".

    Xét ĐẦU tiêu đề chứ không tìm từ khoá ở bất kỳ đâu: "Đơn đề nghị cấp bản sao
    QUYẾT ĐỊNH ly hôn" là đơn của người dân, không phải quyết định của toà. Chữ
    quyết định ở đó là tân ngữ, không phải loại của chính tờ giấy này.
    """
    t = (tieu_de or "").strip().lower()
    for tien_to in ("mẫu ", "mẫu:"):
        if t.startswith(tien_to):
            t = t[len(tien_to):].lstrip()
    for loai in sorted(LOAI_KHONG_PHAI_CA_NHAN + LOAI_GIAY_TO_CA_NHAN,
                       key=len, reverse=True):
        if t.startswith(loai):
            return loai
    return ""


def quyet_dinh_quy_tac(tieu_de: str, ruot_text: str = "") -> KetQuaQuyTac:
    """Tầng 2, ba bộ dấu hiệu: doanh nghiệp · cá nhân · cơ quan nhà nước.

    ĐIỀU KIỆN VẪN LÀ "PHÍA KIA BẰNG 0", giữ nguyên từ bản hai bộ. Đó là điều kiện
    khắt khe có chủ đích: mẫu vừa nhắc "doanh nghiệp" vừa nhắc "cơ quan nhà nước"
    là mẫu thật sự nhập nhằng — ví dụ mẫu báo cáo mà cơ quan gửi VỀ doanh nghiệp.
    Đoán ở đó là đoán sai, phải để mô hình đọc.

    KHÁC BIỆT DUY NHẤT khi thêm bộ thứ ba: doanh nghiệp và cá nhân KHÔNG loại trừ
    nhau. Hai bên cùng có điểm là chuyện bình thường và có nghĩa rõ ràng — mẫu
    phục vụ cả hai — chứ không phải nhập nhằng. Chỉ dấu hiệu NHÀ NƯỚC mới làm cả
    hai bên kia mất hiệu lực, vì "cơ quan điền" và "dân điền" thì đúng là loại
    trừ nhau.

    `audience` ghi phía NẶNG hơn để giữ một phân loại chính đọc được; hai cờ mới
    mang thông tin đầy đủ.
    """
    td = (tieu_de or "").lower()
    ruot = (ruot_text or "")[:KY_TU_DAU_RUOT].lower()

    diem_loai, dh_loai = _cham_diem(DAU_HIEU_LOAI, td, ruot)
    diem_giu, dh_giu = _cham_diem(DAU_HIEU_GIU, td, ruot)
    diem_cn, dh_cn = _cham_diem(DAU_HIEU_CA_NHAN, td, ruot)

    kq = KetQuaQuyTac(diem_giu=diem_giu, diem_loai=diem_loai, diem_ca_nhan=diem_cn,
                      dau_hieu_giu=dh_giu, dau_hieu_loai=dh_loai,
                      dau_hieu_ca_nhan=dh_cn)

    if diem_loai >= NGUONG_CHAC and diem_giu == 0 and diem_cn == 0:
        kq.audience = CO_QUAN_NHA_NUOC
        return kq
    if diem_loai:
        return kq          # có mùi nhà nước mà không sạch → để mô hình đọc

    lvb = loai_van_ban(tieu_de)
    kq.loai_van_ban = lvb
    kq.cho_doanh_nghiep = diem_giu >= NGUONG_CHAC
    # PHỦ QUYẾT, không phải trừ điểm. Một công cụ do tổ chức phát hành thì không
    # có mức chủ đề nào làm nó thành giấy tờ của người dân được.
    kq.cho_ca_nhan = (diem_cn >= NGUONG_CHAC
                      and lvb not in LOAI_KHONG_PHAI_CA_NHAN)
    # LOẠI GIẤY TỜ TỰ NÓ ĐÃ ĐỦ, không cần thêm từ khoá chủ đề. Hiệu chuẩn cho
    # thấy 22/23 ca bỏ sót đều có điểm chủ đề BẰNG 0: "Bản khai để giải quyết chế
    # độ Bà mẹ Việt Nam anh hùng", "Phiếu khai báo tạm vắng", "Bản tường trình" —
    # không tiêu đề nào chứa từ khoá nào, mà cả ba đều rõ ràng do một người điền.
    # Đòi thêm bằng chứng chủ đề ở đây là đòi thứ mà chính loại giấy tờ đã nói.
    #
    # Nhưng CHỈ KHI KHÔNG CÓ dấu hiệu doanh nghiệp: "tờ khai thuế GTGT" và "tờ
    # khai hải quan" cũng là "tờ khai", và chúng là giấy tờ doanh nghiệp nộp hằng
    # kỳ. Mẫu 201 mẫu có TỜ KHAI 2/2 cá nhân, nhưng cỡ mẫu đó không đủ để bỏ qua
    # điều đã biết chắc từ kho doanh nghiệp.
    if lvb in LOAI_GIAY_TO_CA_NHAN and diem_giu == 0:
        kq.cho_ca_nhan = True
    if kq.cho_doanh_nghiep or kq.cho_ca_nhan:
        kq.audience = DOANH_NGHIEP if diem_giu >= diem_cn else CA_NHAN
    return kq


__all__ = [
    "BIEU_MAU_BUSINESS_FIELDS", "DAU_HIEU_LOAI", "DAU_HIEU_GIU",
    "DAU_HIEU_CA_NHAN", "LOAI_KHONG_PHAI_CA_NHAN", "LOAI_GIAY_TO_CA_NHAN",
    "loai_van_ban",
    "NGUONG_CHAC", "KY_TU_DAU_RUOT", "QUY_TAC", "CAN_HOI_LLM",
    "KetQuaQuyTac", "linh_vuc_bieu_mau_kinh_doanh", "la_linh_vuc_kinh_doanh",
    "quyet_dinh_quy_tac",
]
