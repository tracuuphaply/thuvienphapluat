"""
Slug công khai của một văn bản — dùng cho tên file vault và đường dẫn URL.

Số hiệu trần không đủ làm định danh: 63 tỉnh đánh số độc lập nên
"40/2026/QĐ-UBND" tồn tại ở nhiều tỉnh. Vault hiện đặt tên note theo
sanitize_filename(doc_num), nên note của tỉnh thứ hai ghi đè note của tỉnh thứ
nhất mà không báo gì.

Yêu cầu của slug, theo thứ tự quan trọng:
  1. Ổn định vĩnh viễn. URL công khai đã phát ra trong báo cáo PDF không được
     đổi khi kho lớn lên. Vì vậy slug chỉ được suy từ chính văn bản đó
     (số hiệu + cơ quan), tuyệt đối không từ trạng thái toàn kho như
     "hiện có trùng hay không".
  2. Duy nhất.
  3. Đọc được. Văn bản trung ương giữ slug trần vì số hiệu của chúng vốn đã
     duy nhất toàn quốc; chỉ văn bản địa phương mới cần phần phân biệt.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

# Hậu tố số hiệu của văn bản do chính quyền địa phương ban hành. Đây là nhóm
# duy nhất có thể trùng số hiệu giữa các địa phương, nên cũng là nhóm duy nhất
# cần phần phân biệt.
_LOCAL_SUFFIX = re.compile(r"-(UBND|HĐND|HDND)\s*$", re.IGNORECASE)

# Số hiệu không parse được đều rơi về cùng một giá trị ("Không số"), nên chúng
# luôn đụng nhau và luôn cần phân biệt.
_DEGENERATE = {"", "khong-so", "khong-xac-dinh"}

# Đ → DD, KHÔNG phải D. Thư viện Pháp luật đăng bản dịch tiếng Anh của cùng một
# văn bản dưới số hiệu ASCII, nên "296/2026/NĐ-CP" và "296/2026/ND-CP" cùng tồn
# tại trong kho. Bỏ dấu thành "D" khiến hai bản ghi khác nhau ra cùng một slug và
# vi phạm ràng buộc duy nhất — đã gặp thật, làm gãy cả một lượt cào.
#
# Mã hoá thành "DD" giữ cho phép tạo slug KHÔNG MẤT THÔNG TIN ở đúng chỗ nguy
# hiểm nhất: Đ xuất hiện 617 lần trong số hiệu, mọi ký tự có dấu khác cộng lại
# chỉ 7 lần.
_DIACRITIC_MAP = str.maketrans({"Đ": "DD", "đ": "dd"})


def slugify_doc_num(doc_num: str) -> str:
    """Số hiệu → dạng an toàn cho tên file và URL.

    Bỏ dấu tiếng Việt thay vì giữ nguyên như sanitize_filename() của vault: URL
    có dấu bị mã hoá percent thành chuỗi không đọc nổi khi dán vào báo cáo.

    CHỮ THƯỜNG, vì Quartz hạ chữ thường mọi đường dẫn nó phát ra còn GitHub
    Pages thì phân biệt hoa/thường. Giữ slug dạng hoa nghĩa là mọi link trong
    phụ lục PDF trỏ tới 404 — đúng thứ file này nói là tệ hơn không có link.
    Hạ ở đây chứ không ở public_url() để slug BẰNG ĐÚNG đường dẫn URL: khi đó
    ràng buộc duy nhất trên cột public_slug chính là bảo đảm URL không đụng
    nhau, thay vì phải hy vọng hai slug khác nhau không cùng ra một URL.

    Hạ chữ thường không phá phép mã hoá Đ → DD ở trên: "NĐ-CP" ra "ndd-cp" còn
    "ND-CP" ra "nd-cp", vẫn phân biệt được vì khác nhau ở độ dài, không ở kiểu
    chữ. Đã kiểm trên 4.467 slug thật: 0 va chạm sau khi hạ.
    """
    text = (doc_num or "").strip().translate(_DIACRITIC_MAP)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^A-Za-z0-9]+", "-", text)
    return text.strip("-").lower()


# Dạng chuẩn của số hiệu Việt Nam: "292/2026/NĐ-CP", "47/2013/TT-BNNPTNT".
# Hai dấu gạch chéo đầu, phần còn lại nối bằng gạch ngang đơn.
#
# Ý nghĩa của việc khoanh dạng chuẩn: TRONG dạng này, vị trí của "/" và "-" là
# cố định, nên bỏ dấu rồi thay hết bằng "-" vẫn suy ngược lại được — hai số
# hiệu chuẩn khác nhau không thể ra cùng một slug. Ngoài dạng này thì không có
# bảo đảm nào, nên gắn phần phân biệt.
#
# Lý do phải chặt tới mức này: hai lần trước tôi chỉ vá đúng ca vừa gặp và lần
# nào cũng có ca mới. "05/2000/QĐ--BVHTT" đụng "05/2000/QĐ-BVHTT" (gạch đôi),
# rồi "85/2005/TTLT/BTC-BCA" đụng "85/2005/TTLT-BTC-BCA" (gạch chéo thay gạch
# ngang) — ca thứ hai là thứ tôi từng ghi trong chính file này là "số hiệu Việt
# Nam không có dạng đó".
_DANG_CHUAN = re.compile(r"^\d+/\d{4}/[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$")


def _is_lossy(doc_num: str) -> bool:
    """Việc tạo slug có làm mất thông tin phân biệt không?

    Trả về False chỉ khi số hiệu ở dạng chuẩn — nơi phép tạo slug suy ngược
    được. Mọi dạng khác coi là có thể mất thông tin.
    """
    text = (doc_num or "").strip().translate(_DIACRITIC_MAP)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return not _DANG_CHUAN.match(text)


def _discriminator(doc_key: str) -> str:
    """4 ký tự suy từ doc_key — ổn định vì doc_key là định danh thật."""
    return hashlib.sha256(doc_key.encode("utf-8")).hexdigest()[:4]


def needs_discriminator(doc_num: str, base: str) -> bool:
    """Có cần thêm phần phân biệt vào slug không?

    Ba trường hợp: văn bản địa phương (số hiệu trùng giữa các tỉnh), số hiệu
    rác, và số hiệu mà việc bỏ dấu làm mất thông tin phân biệt.
    """
    return (
        bool(_LOCAL_SUFFIX.search((doc_num or "").strip()))
        or base.lower() in _DEGENERATE
        or _is_lossy(doc_num)
    )


def make_public_slug(doc_num: str, doc_key: str) -> str:
    """Slug công khai của một văn bản.

    Chỉ phụ thuộc vào chính văn bản, nên chạy lại lúc nào cũng ra cùng kết quả
    và không đổi khi kho có thêm văn bản mới.
    """
    base = slugify_doc_num(doc_num)
    if needs_discriminator(doc_num, base):
        return f"{base or 'khong-so'}--{_discriminator(doc_key or doc_num)}"
    return base
