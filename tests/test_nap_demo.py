"""Bộ nạp kho demo — phần dựng lại QUAN HỆ DẪN CHIẾU.

VÌ SAO CÓ FILE NÀY. Bản đầu của `nap_demo.py` bỏ qua khối `do_thi` trong
`du-lieu.json`, và cái giá không phải là "mục Văn bản liên quan trống" như
docstring khi đó ghi. Sơ đồ liên kết ở chế độ toàn kho chỉ nhận nút có ít nhất
một cạnh, nên kho 0 cạnh vẽ ra ĐÚNG MỘT NÚT và ô chú thích ghi "Toàn kho · 1
văn bản" — đo được trên trình duyệt thật. Người dùng đọc câu đó ra "bộ não liên
kết đã bị lỗi", và đúng là không có cách nào đọc khác.

Nên mấu chốt cần khoá lại là: cạnh nạp vào phải nối đúng cặp mà
`assistant_export._do_thi()` join lại lúc xuất — `source_doc_id` là khoá ngoại,
`target_doc_num` là SỐ HIỆU. Lệch một trong hai đầu thì cạnh im lặng biến mất
lúc xuất, và triệu chứng lại đúng là cái màn hình một nút ấy.
"""
import pytest

from src.storage.models import Document, DocumentReference
from scripts.nap_demo import _nap_quan_he


def _van_ban(*so_hieu):
    return [{"n": s, "t": f"Tiêu đề {s}"} for s in so_hieu]


@pytest.fixture
def kho_ba_van_ban(master_session):
    for i, so in enumerate(["01/2020/QH14", "02/2021/NĐ-CP", "03/2022/TT-BTC"]):
        master_session.add(Document(doc_num=so, doc_key=f"{so}::x", title=so, moj_id=f"m{i}"))
    master_session.commit()
    return master_session


def test_canh_noi_dung_cap_ma_luc_xuat_join_lai(kho_ba_van_ban):
    """source_doc_id là id, target_doc_num là số hiệu — không được đổi chỗ."""
    goi = {"do_thi": {"quan_he": ["Căn cứ", "Thay thế"], "canh": [[0, 1, 1]]}}
    n = _nap_quan_he(kho_ba_van_ban, goi,
                     _van_ban("01/2020/QH14", "02/2021/NĐ-CP", "03/2022/TT-BTC"),
                     DocumentReference)
    assert n == 1
    r = kho_ba_van_ban.query(DocumentReference).one()
    nguon = kho_ba_van_ban.query(Document).filter_by(doc_num="01/2020/QH14").one()
    assert r.source_doc_id == nguon.id
    assert r.target_doc_num == "02/2021/NĐ-CP"   # SỐ HIỆU, không phải id
    assert r.relation_type == "Thay thế"          # tra đúng bảng quan_he


def test_cat_bot_van_ban_thi_bo_canh_tro_ra_ngoai(kho_ba_van_ban):
    """`--gioi-han` cắt mảng van_ban; cạnh trỏ ra ngoài phần đã cắt phải bị bỏ.

    Giữ lại thì chỉ số soi vào mảng đã cắt sẽ trỏ sang một văn bản KHÁC — sai âm
    thầm, vì đồ thị vẫn vẽ ra được nên không có gì báo.
    """
    goi = {"do_thi": {"quan_he": ["Căn cứ"], "canh": [[0, 1, 0], [0, 2, 0], [2, 1, 0]]}}
    n = _nap_quan_he(kho_ba_van_ban, goi,
                     _van_ban("01/2020/QH14", "02/2021/NĐ-CP"),   # đã cắt còn 2
                     DocumentReference)
    assert n == 1
    assert kho_ba_van_ban.query(DocumentReference).one().target_doc_num == "02/2021/NĐ-CP"


def test_hai_muc_trung_so_hieu_khong_sinh_canh_lap(kho_ba_van_ban):
    """Số hiệu KHÔNG duy nhất: 300 mục đầu của file thật gộp lại còn 297 văn bản."""
    goi = {"do_thi": {"quan_he": ["Căn cứ"], "canh": [[0, 1, 0], [2, 1, 0]]}}
    n = _nap_quan_he(kho_ba_van_ban, goi,
                     # mục 0 và mục 2 cùng số hiệu → cùng một cạnh
                     _van_ban("01/2020/QH14", "02/2021/NĐ-CP", "01/2020/QH14"),
                     DocumentReference)
    assert n == 1


def test_bo_canh_tro_toi_van_ban_kho_khong_co(kho_ba_van_ban):
    """Nửa cạnh không vẽ được, và `_do_thi()` cũng bỏ nó lúc xuất."""
    goi = {"do_thi": {"quan_he": ["Căn cứ"], "canh": [[0, 1, 0]]}}
    n = _nap_quan_he(kho_ba_van_ban, goi,
                     _van_ban("01/2020/QH14", "99/9999/XX-YY"),
                     DocumentReference)
    assert n == 0


def test_bo_tu_tro_va_loai_quan_he_ngoai_bang(kho_ba_van_ban):
    goi = {"do_thi": {"quan_he": ["Căn cứ"], "canh": [[0, 0, 0], [0, 1, 77]]}}
    n = _nap_quan_he(kho_ba_van_ban, goi,
                     _van_ban("01/2020/QH14", "02/2021/NĐ-CP"), DocumentReference)
    assert n == 1
    assert kho_ba_van_ban.query(DocumentReference).one().relation_type == "Chưa xác định"


def test_khong_co_khoi_do_thi_thi_khong_no(kho_ba_van_ban):
    """File cũ không có `do_thi` vẫn phải nạp được, chỉ là 0 cạnh."""
    assert _nap_quan_he(kho_ba_van_ban, {}, _van_ban("01/2020/QH14"),
                        DocumentReference) == 0


def test_canh_di_duoc_qua_bo_xuat(kho_ba_van_ban):
    """Kiểm tận đầu ra: cạnh nạp vào phải hiện lên trong du-lieu.json.

    Đây là phép kiểm duy nhất bắt được lỗi ở chỗ giáp ranh — nạp đúng mà xuất ra
    0 cạnh thì màn hình vẫn là "Toàn kho · 1 văn bản".
    """
    from src.publish import assistant_export
    for i, d in enumerate(kho_ba_van_ban.query(Document).all()):
        d.public_slug = f"vb-{i}"
    kho_ba_van_ban.commit()

    goi = {"do_thi": {"quan_he": ["Căn cứ"], "canh": [[0, 1, 0]]}}
    _nap_quan_he(kho_ba_van_ban, goi,
                 _van_ban("01/2020/QH14", "02/2021/NĐ-CP", "03/2022/TT-BTC"),
                 DocumentReference)

    chi_so = {d.public_slug: i for i, d in
              enumerate(kho_ba_van_ban.query(Document).order_by(Document.id).all())}
    do_thi = assistant_export._do_thi(kho_ba_van_ban, chi_so)
    assert len(do_thi["canh"]) == 1
    assert do_thi["quan_he"] == ["Căn cứ"]
