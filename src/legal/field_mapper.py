"""
Xếp một văn bản vào 1 trong 27 lĩnh vực của Thư viện Pháp luật.

BA TẦNG, theo thứ tự tin cậy giảm dần. Tầng nào quyết định được thì dừng, và
NGUỒN được trả về cùng kết quả — không trộn dữ kiện với suy đoán:

    tvpl      TVPL đã gán mã. Đây là dữ kiện, không phải suy luận.
    moj_map   Suy từ tên lĩnh vực của Bộ Tư pháp qua bảng dưới.
    tu_khoa   Suy từ tiêu đề văn bản. Yếu nhất.
    khac      Không xếp được → "27. Lĩnh vực khác", đúng nhãn TVPL dùng.

VÌ SAO PHẢI GHI NGUỒN. Kho có 1.448 văn bản mang mã TVPL thật và 3.018 văn bản
không. Nếu gộp cả hai thành một cột `field_code` thì về sau không ai phân biệt
được đâu là phân loại của TVPL, đâu là suy đoán của hệ thống — và một suy đoán
sai sẽ được đọc như dữ kiện.

VÌ SAO BẢNG ÁNH XẠ VIẾT TAY. 203 tên lĩnh vực của Bộ Tư pháp là văn bản tự do,
nhiều tên trùng nghĩa ("Quản lý ngân sách", "Ngân sách nhà nước", "Quản lý ngân
sách nhà nước") và nhiều tên ghép hai lĩnh vực bằng dấu chấm phẩy. Không có
thuật toán nào đoán đúng những cái đó; đọc và xếp tay một lần là xong.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from src.legal.tvpl_fields import MA_KHAC, TEN_THEO_MA

# ── Nguồn phân loại ──
NGUON_TVPL = "tvpl"
NGUON_MOJ = "moj_map"
NGUON_TU_KHOA = "tu_khoa"
NGUON_KHAC = "khac"


@dataclass(frozen=True)
class KetQua:
    ma: int
    ten: str
    nguon: str


def _chuan(text: str) -> str:
    """Bỏ dấu, hạ chữ thường, gom khoảng trắng — để so khớp không phụ thuộc gõ."""
    t = unicodedata.normalize("NFD", (text or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = t.replace("đ", "d")
    return re.sub(r"\s+", " ", t).strip()


# ── Tầng 2: tên lĩnh vực Bộ Tư pháp → mã TVPL ──
#
# Khoá đã chuẩn hoá (bỏ dấu, chữ thường). Chỉ liệt kê tên KHÁC với danh mục
# TVPL; tên trùng khớp được bắt tự động ở dưới.
_MOJ_SANG_TVPL: dict[str, int] = {
    # 19 · Tài chính nhà nước
    "quan ly ngan sach": 19, "ngan sach nha nuoc": 19,
    "quan ly ngan sach nha nuoc": 19, "tai chinh": 19, "tai chinh khac": 19,
    "tai chinh hanh chinh su nghiep": 19, "kho bac": 19, "du tru quoc gia": 19,
    "quan ly tai san cong": 19, "quan ly cong san": 19,
    "quan ly, su dung tai san cong": 19, "quan ly tai san nha nuoc": 19,
    "ke hoach - tai chinh": 19, "thanh tra, kiem tra tai chinh": 19,
    "quan ly no va tai chinh doi ngoai": 19, "tai chinh doi ngoai": 19,
    "quan ly quy ngan sach, quy du tru nha nuoc, va cac quy tai chinh khac cua nha nuoc": 19,
    "quan ly ngan sach; tai chinh khac": 19,
    "quan ly ngan sach; tai chinh doi ngoai": 19,
    "quan ly ngan sach; quan ly tai san cong": 19,
    "tai chinh doi ngoai; quan ly ngan sach": 19,
    "dau thau": 19,
    # 5 · Tiền tệ - Ngân hàng
    "tcnh va thi truong tc, trai phieu, khac": 5, "tin dung": 5,
    "quan ly ngoai hoi": 5, "ngan hang nha nuoc viet nam": 5,
    "thanh tra, giam sat ngan hang": 5, "ngan hang va to chuc tai chinh": 5,
    "cuc an toan he thong cac to chuc tin dung": 5, "phong, chong rua tien": 5,
    "quan ly dich vu tai chinh va cac quy tai chinh": 5,
    "quan ly tai chinh cac to chuc tai chinh va dich vu tai chinh": 5,
    "tcnh va thi truong tc, trai phieu, khac; quan ly dich vu tai chinh va cac quy tai chinh": 5,
    "quan ly dich vu tai chinh va cac quy tai chinh; tai chinh khac": 5,
    # 15 · Bộ máy hành chính
    "to chuc- bien che": 15, "chinh quyen dia phuong": 15, "cong chuc": 15,
    "cong chuc, vien chuc": 15, "to chuc can bo": 15, "vien chuc": 15,
    "thanh tra": 15, "co cau to chuc": 15, "noi vu": 15, "quan ly nha nuoc": 15,
    "cai cach hanh chinh": 15, "kiem soat thu tuc hanh chinh": 15,
    "to chuc chinh quyen dia phuong": 15, "phan cap, phan quyen": 15,
    "phan cap, phan quyen, phan dinh tham quyen va linh vuc": 15,
    "can bo, cong chuc": 15, "thi dua, khen thuong": 15,
    "dao tao boi duong can bo, cong chuc, vien chuc": 15,
    "to chuc phi chinh phu": 15, "van thu va luu tru nha nuoc": 15,
    "van thu - luu tru": 15, "luu tru": 15, "cong tac thanh nien": 15,
    "cong tac dan toc": 15, "co quan dai dien viet nam o nuoc ngoai": 15,
    "cong tac lanh su": 15, "chinh sach": 15,
    "cat giam thu tuc hanh chinh, dieu kien kinh doanh": 15,
    "ban hanh van ban quy pham phap luat": 15,
    "xay dung phap luat, phap che": 15,
    "kiem tra, ra soat, he thong hoa, hop nhat van ban quy pham phap luat, phap dien he thong quy pham phap luat": 15,
    # 13 · Dịch vụ pháp lý
    "bo tro tu phap": 13, "tro giup phap ly": 13, "luat su": 13,
    "giam dinh tu phap": 13, "thua phat lai": 13, "tu van phap luat": 13,
    "cong chung": 13, "dau gia tai san": 13,
    "quan tai vien va hanh nghe quan ly, thanh ly tai san": 13,
    # 25 · Quyền dân sự
    "ho tich, quoc tich, chung thuc": 25, "ho tich": 25, "quoc tich": 25,
    "nuoi con nuoi": 25, "boi thuong nha nuoc": 25, "ly lich tu phap": 25,
    "dang ky giao dich bao dam": 25, "dan su - kinh te": 25,
    "uu dai nguoi co cong voi cach mang": 25,
    "cap ban sao tu so goc, chung thuc ban sao tu ban chinh, chung thuc chu ky va chung thuc hop dong, giao dich": 25,
    "xuat canh, nhap canh cua cong dan viet nam": 25,
    # 18 · Thủ tục Tố tụng
    "thi hanh an dan su": 18, "tuong tro tu phap": 18, "phap luat quoc te": 18,
    # 16 · Vi phạm hành chính
    "xu ly vi pham hanh chinh": 16,
    "xu ly vi pham hanh chinh va theo doi thi hanh phap luat": 16,
    "handling of administrative violations": 16,
    # 17 · Trách nhiệm hình sự
    "hinh su - hanh chinh": 17,
    # 23 · Tài nguyên - Môi trường
    "dat dai": 23, "moi truong": 23, "bao ve moi truong": 23,
    "tai nguyen khoang san, dia chat": 23, "dia chat va khoang san": 23,
    "tai nguyen nuoc": 23, "tai nguyen va moi truong": 23,
    "khi tuong thuy van va bien doi khi hau": 23, "khi hau , thuy van": 23,
    "bien va hai dao": 23, "thuy loi": 23,
    "thuy loi, de dieu va phong chong bao lut": 23, "phong, chong thien tai": 23,
    "lam nghiep": 23, "nong nghiep": 23, "phat trien nong thon": 23,
    "thuy san": 23, "bao ve thuc vat": 23, "thu y": 23,
    "nong nghiep va moi truong": 23, "khoa hoc, cong nghe va moi truong": 23,
    # 20 · Xây dựng - Đô thị
    "xay dung": 20, "quy hoach": 20, "quy hoach - kien truc": 20,
    "phat trien do thi": 20, "quan ly hoat dong xay dung": 20,
    "kinh te xay dung": 20,
    "ha tang ky thuat do thi, khu cong nghiep, khu kinh te, khu cong nghe cao": 20,
    # 12 · Bất động sản
    "nha o va cong so": 12, "nha o": 12, "quan ly nha": 12,
    "quan ly nha va thi truong bat dong san": 12, "kinh doanh bat dong san": 12,
    # 21 · Giao thông - Vận tải
    "duong bo": 21, "duong sat": 21, "duong thuy noi dia": 21, "hang hai": 21,
    "hang khong": 21, "van tai": 21,
    # 22 · Giáo dục
    "giao duc mam non": 22, "giao duc": 22, "giao duc dai hoc": 22,
    "giao duc va dao tao": 22, "quy che thi, tuyen sinh": 22,
    "nha giao va can bo quan ly co so giao duc": 22, "dao tao voi nuoc ngoai": 22,
    "giao duc dao tao thuoc he thong giao duc quoc dan va cac co so khac": 22,
    "pho bien, giao duc phap luat": 22,
    "pho bien, giao duc phap luat, hoa giai o co so": 22,
    # 24 · Thể thao - Y tế
    "y te": 24, "kham chua benh": 24, "kham benh, chua benh": 24,
    "quan ly kham, chua benh": 24, "y te du phong": 24, "moi truong y te": 24,
    "trang thiet bi y te": 24, "trang thiet bi va cong trinh y te": 24,
    "an toan thuc pham": 24, "ve sinh an toan va dinh duong": 24,
    "phong, chong hiv/aids": 24, "the duc, the thao": 24,
    # 26 · Văn hóa - Xã hội
    "quang cao": 26, "dien anh": 26, "xuat ban, in, phat hanh": 26,
    "nghe thuat bieu dien": 26, "my thuat, nhiep anh va trien lam": 26,
    "van hoa co so": 26, "du lich": 26,
    "quyen tac gia, quyen lien quan doi voi tac pham van hoc, nghe thuat": 26,
    "chinh sach tro giup xa hoi doi voi doi tuong bao tro xa hoi": 26,
    # 11 · Công nghệ thông tin
    "cong nghe thong tin": 11, "cong nghe thong tin,dien tu": 11,
    "phat thanh truyen hinh va thong tin dien tu": 11, "buu chinh": 11,
    "vien thong va internet;": 11, "tan so-vo tuyen dien": 11,
    "chuyen doi so": 11,
    "hoat dong khoa hoc va cong nghe": 11,
    "khoa hoc, cong nghe va doi moi sang tao": 11,
    "cong nghe cao, chuyen giao cong nghe": 11,
    "danh gia, tham dinh va giam dinh cong nghe": 11,
    "nang luong nguyen tu, an toan buc xa va hat nhan": 11,
    "an toan buc xa va hat nhan": 11,
    # 3 · Thương mại
    "cong nghiep": 3, "nang luong": 3, "dau khi": 3, "hoa chat": 3,
    "tieu chuan do luong chat luong": 3, "chat luong san pham, hang hoa": 3,
    "linh vuc gia": 3, "gia": 3, "quan ly gia": 3,
    "quan ly gia; quan ly dich vu tai chinh va cac quy tai chinh": 3,
    # 15 · An ninh quốc phòng → Bộ máy hành chính (TVPL không tách riêng)
    "an ninh va trat tu, an toan xa hoi": 15, "an ninh quoc gia": 15,
    "quoc phong": 15, "si quan": 15, "dan quan tu ve": 15,
    "cong nghiep quoc phong": 15, "phong thu dan su": 15, "dong vien": 15,
    "bien phong": 15, "bien gioi quoc gia": 15, "quan ly bien gioi": 15,
    "cong trinh quoc phong, khu quan su": 15, "bao ve bi mat nha nuoc": 15,
    "chinh sach hau phuong quan doi": 15,
    "phong chay, chua chay": 15, "phong chay, chua chay va cuu nan, cuu ho": 15,
    "linh vuc quan ly vu khi – vat lieu no cong nghiep va cong cu ho tro.": 15,
    "dieu kien ve an ninh, trat tu doi voi mot so nganh, nghe kinh doanh co dieu kien": 15,
}

# ── Tầng 3: từ khoá trong tiêu đề → mã TVPL ──
#
# Chỉ dùng khi hai tầng trên bó tay. Xếp theo thứ tự ưu tiên: cụm đặc trưng
# trước, cụm chung sau — "tổ chức tín dụng" phải thắng "tổ chức".
#
# CỤM PHẢI ĐỦ DÀI ĐỂ PHÂN BIỆT. Bỏ dấu tiếng Việt tạo ra từ đồng âm, và token
# ngắn thì sai hàng loạt. Ba ca đo được trên chính kho này:
#
#   "thuoc"    → khớp "thuộc" (thuộc thẩm quyền, thuộc hệ thống), 68/68 sai.
#                Thuốc men nay bắt bằng "duoc pham", "dang ky thuoc".
#   "luat su"  → khớp "luật SỬA đổi, bổ sung", nên mọi luật sửa đổi bị xếp vào
#                Dịch vụ pháp lý. 39 văn bản.
#   "xay dung" → lẫn "Luật Xây dựng" với "xây dựng chương trình/kế hoạch".
#                Nay đòi cụm chỉ đúng hoạt động xây dựng.
_TU_KHOA: list[tuple[str, int]] = [
    ("so huu tri tue", 14), ("quyen tac gia", 14), ("sang che", 14),
    ("nhan hieu", 14), ("chi dan dia ly", 14),
    ("chung khoan", 7), ("thi truong chung khoan", 7),
    ("to chuc tin dung", 5), ("ngan hang", 5), ("ngoai hoi", 5),
    ("tien te", 5), ("lai suat", 5), ("tin dung", 5),
    ("bao hiem xa hoi", 8), ("bao hiem y te", 8), ("bao hiem", 8),
    ("ke toan", 9), ("kiem toan", 9),
    ("thue", 6), ("phi va le phi", 6), ("le phi", 6), ("hai quan", 4),
    ("xuat khau", 4), ("nhap khau", 4), ("xuat nhap khau", 4),
    ("lao dong", 10), ("tien luong", 10), ("cong doan", 10),
    ("an toan, ve sinh lao dong", 10), ("viec lam", 10),
    ("doanh nghiep", 1), ("dang ky kinh doanh", 1), ("pha san", 1),
    ("hop tac xa", 1), ("ho kinh doanh", 1),
    ("dau tu cong", 2), ("dau tu", 2), ("ppp", 2), ("dau tu nuoc ngoai", 2),
    ("dat dai", 23), ("khoang san", 23), ("moi truong", 23),
    ("tai nguyen nuoc", 23), ("lam nghiep", 23), ("thuy san", 23),
    ("nong nghiep", 23), ("thuy loi", 23), ("de dieu", 23),
    ("bat dong san", 12), ("nha o", 12), ("chung cu", 12),
    ("luat xay dung", 20), ("hoat dong xay dung", 20),
    ("cong trinh xay dung", 20), ("giay phep xay dung", 20),
    ("dau tu xay dung", 20), ("quy chuan xay dung", 20),
    ("quy hoach do thi", 20), ("do thi", 20),
    ("giao thong", 21), ("duong bo", 21), ("hang hai", 21),
    ("hang khong", 21), ("duong sat", 21), ("van tai", 21),
    ("giao duc", 22), ("dao tao", 22), ("hoc sinh", 22), ("sinh vien", 22),
    ("truong hoc", 22), ("giao vien", 22),
    ("kham benh", 24), ("chua benh", 24), ("duoc pham", 24),
    ("dang ky thuoc", 24), ("gia thuoc", 24), ("kinh doanh duoc", 24),
    ("y te", 24), ("an toan thuc pham", 24), ("the thao", 24),
    ("cong nghe thong tin", 11), ("vien thong", 11), ("giao dich dien tu", 11),
    ("chu ky so", 11), ("an toan thong tin", 11), ("du lieu", 11),
    ("dinh danh va xac thuc dien tu", 11), ("chuyen doi so", 11),
    ("khoa hoc va cong nghe", 11), ("khoa hoc, cong nghe", 11),
    ("van hoa", 26), ("du lich", 26), ("quang cao", 26), ("bao chi", 26),
    ("xuat ban", 26), ("nguoi khuyet tat", 26), ("tre em", 26),
    ("tro giup xa hoi", 26), ("casino", 26), ("xo so", 26),
    ("ngan sach", 19), ("tai san cong", 19), ("dau thau", 19),
    ("du tru quoc gia", 19), ("no cong", 19),
    ("hanh nghe luat su", 13), ("doan luat su", 13), ("cong chung", 13),
    ("trong tai thuong mai", 13),
    ("hoa giai", 13), ("giam dinh tu phap", 13),
    ("ho tich", 25), ("quoc tich", 25), ("nuoi con nuoi", 25),
    ("cu tru", 25), ("can cuoc", 25),
    ("to tung", 18), ("thi hanh an", 18),
    ("xu phat vi pham hanh chinh", 16), ("vi pham hanh chinh", 16),
    ("hinh su", 17),
    ("thuong mai", 3), ("canh tranh", 3), ("bao ve quyen loi nguoi tieu dung", 3),
    ("gia ca", 3), ("cong nghiep", 3), ("dien luc", 3), ("dau khi", 3),
    ("to chuc bo may", 15), ("can bo, cong chuc", 15), ("cong chuc", 15),
    ("vien chuc", 15), ("chinh quyen dia phuong", 15), ("quoc phong", 15),
    ("cong an", 15), ("thanh tra", 15), ("khen thuong", 15),
]


def _tu_ten_moj(field_name: str | None) -> int | None:
    if not field_name:
        return None
    khoa = _chuan(field_name)
    if khoa in _MOJ_SANG_TVPL:
        return _MOJ_SANG_TVPL[khoa]
    # Tên trùng thẳng với danh mục TVPL.
    for ma, ten in TEN_THEO_MA.items():
        if khoa == _chuan(ten):
            return ma
    return None


def _tu_tieu_de(title: str | None) -> int | None:
    if not title:
        return None
    t = _chuan(title)
    for cum, ma in _TU_KHOA:
        if cum in t:
            return ma
    return None


def phan_loai(field_code: int | None, field_name: str | None,
              title: str | None) -> KetQua:
    """Xếp một văn bản vào lĩnh vực TVPL, kèm nguồn của kết luận."""
    if field_code and field_code in TEN_THEO_MA:
        return KetQua(field_code, TEN_THEO_MA[field_code], NGUON_TVPL)

    ma = _tu_ten_moj(field_name)
    if ma:
        return KetQua(ma, TEN_THEO_MA[ma], NGUON_MOJ)

    ma = _tu_tieu_de(title)
    if ma:
        return KetQua(ma, TEN_THEO_MA[ma], NGUON_TU_KHOA)

    return KetQua(MA_KHAC, TEN_THEO_MA[MA_KHAC], NGUON_KHAC)
