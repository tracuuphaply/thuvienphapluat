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


class TestRuotTuTrangCongKhai:
    """Rút ruột biểu mẫu từ các trang đã đăng.

    Ruột biểu mẫu VỐN đã công khai — 653/653 trang `content/bieu-mau/*.md` có
    sẵn mục "## Nội dung biểu mẫu". Toàn văn VĂN BẢN thì không, và đó là chủ ý:
    mỗi trang văn bản đều ghi "Trang này không đăng toàn văn". Nên kho demo lấy
    được ruột biểu mẫu mà không bao giờ lấy được toàn văn văn bản.
    """

    def _trang(self, tmp_path, ten="bm-hopdong-1.md", khoa="hopdong-1", than=None):
        d = tmp_path / "content" / "bieu-mau"
        d.mkdir(parents=True, exist_ok=True)
        (d / ten).write_text(
            f'---\ntitle: "X"\nform_key: "{khoa}"\n---\n\n'
            "# X\n\n## Tải về\n\n- [docx](./x.docx)\n\n"
            "## Căn cứ pháp lý\n\n*Không có.*\n\n"
            "## Nội dung biểu mẫu\n\n" + (than or "HỢP ĐỒNG\n\nKính gửi: .....") + "\n\n"
            "## Nguồn\n\n- https://thuvienphapluat.vn/hopdong/1\n",
            encoding="utf-8")
        return tmp_path / "content"

    def test_cat_dung_muc_noi_dung(self, tmp_path):
        from scripts.nap_demo import _ruot_tu_trang
        ra = _ruot_tu_trang(self._trang(tmp_path), tmp_path / "ruot")
        assert set(ra) == {"hopdong-1"}
        than = (tmp_path / "ruot" / "hopdong-1.md").read_text(encoding="utf-8")
        assert than.startswith("HỢP ĐỒNG") and "Kính gửi" in than

    def test_khong_nuot_sang_muc_nguon(self, tmp_path):
        """Sau ruột còn `## Nguồn` mang URL Thư viện Pháp luật.

        Lấy tới hết file là dán địa chỉ nguồn vào giữa thân mẫu — đúng thứ mà
        trang tĩnh cũng cắt bỏ.
        """
        from scripts.nap_demo import _ruot_tu_trang
        _ruot_tu_trang(self._trang(tmp_path), tmp_path / "ruot")
        than = (tmp_path / "ruot" / "hopdong-1.md").read_text(encoding="utf-8")
        assert "thuvienphapluat" not in than
        assert "## Nguồn" not in than

    def test_bo_qua_trang_thieu_khoa_hoac_thieu_muc(self, tmp_path):
        from scripts.nap_demo import _ruot_tu_trang
        d = tmp_path / "content" / "bieu-mau"
        d.mkdir(parents=True)
        (d / "a.md").write_text("---\ntitle: X\n---\n\n## Nội dung biểu mẫu\n\nRuột\n",
                                encoding="utf-8")   # thiếu form_key
        (d / "b.md").write_text('---\nform_key: "k-b"\n---\n\n## Tải về\n\nx\n',
                                encoding="utf-8")   # thiếu mục nội dung
        assert _ruot_tu_trang(tmp_path / "content", tmp_path / "ruot") == {}

    def test_ruot_rong_thi_khong_tinh(self, tmp_path):
        from scripts.nap_demo import _ruot_tu_trang
        assert _ruot_tu_trang(self._trang(tmp_path, than="   "), tmp_path / "ruot") == {}

    def test_khong_co_thu_muc_thi_tra_rong_chu_khong_no(self, tmp_path):
        """Chạy không có repo trang công khai bên cạnh là ca bình thường."""
        from scripts.nap_demo import _ruot_tu_trang
        assert _ruot_tu_trang(tmp_path / "khong-ton-tai", tmp_path / "ruot") == {}


class TestChayLaiKhongHongDuLieu:
    """Bộ nạp phải CHẠY LẠI ĐƯỢC — docstring nêu hai lệnh mẫu, và đường "chạy
    lại để gắn ruột biểu mẫu" cũng đi qua đây. Ba lỗi từng có, đều im lặng."""

    def test_dinh_danh_khong_lay_theo_chi_so_mang(self, master_session, kho_ba_van_ban):
        """`moj_id` phải ổn định theo VĂN BẢN, không theo vị trí trong mảng.

        `resolve_existing_document()` tra `moj_id` TRƯỚC TIÊN. Mảng `van_ban` sắp
        theo `public_slug`, nên bản dữ liệu mới chèn thêm một văn bản sắp trước
        là mọi chỉ số phía sau dịch một — nạp lại lên kho cũ thì từng hàng bị ghi
        đè bằng dữ liệu của văn bản KẾ BÊN. Dựng lại được: hàng doc_num
        01/1997/QH10 (một Luật) mang tiêu đề và doc_type của một Quyết định.
        """
        import inspect
        from scripts import nap_demo
        ma = inspect.getsource(nap_demo.nap)
        ma = "\n".join(d.split("#")[0] for d in ma.split("\n"))
        assert 'f"demo-{i}"' not in ma, "định danh lại lấy theo chỉ số mảng"
        assert "enumerate(van_ban)" not in ma, "vòng lặp văn bản không được dùng chỉ số"

    def test_nap_quan_he_chay_lai_khong_nhan_doi(self, kho_ba_van_ban):
        """`document_references` không có ràng buộc UNIQUE và `init_db()` không
        xoá bảng, nên chèn thẳng là cộng dồn qua mỗi lần chạy.

        Đo trước khi sửa: hai lần nạp 300 mục cho 188 hàng trên 94 cạnh phân
        biệt, mà cả hai lần đều in "quan hệ 94". Sơ đồ trợ lý che mất (`_do_thi()`
        gom vào `set`), nhưng trang tĩnh thì lộ — 133 khối danh sách bị lặp.
        """
        from scripts.nap_demo import _nap_quan_he
        goi = {"do_thi": {"quan_he": ["Căn cứ"], "canh": [[0, 1, 0], [1, 2, 0]]}}
        vb = _van_ban("01/2020/QH14", "02/2021/NĐ-CP", "03/2022/TT-BTC")
        n1 = _nap_quan_he(kho_ba_van_ban, goi, vb, DocumentReference)
        n2 = _nap_quan_he(kho_ba_van_ban, goi, vb, DocumentReference)
        n3 = _nap_quan_he(kho_ba_van_ban, goi, vb, DocumentReference)
        assert (n1, n2, n3) == (2, 2, 2), "số báo phải là số cạnh TRONG KHO"
        assert kho_ba_van_ban.query(DocumentReference).count() == 2, "đã nhân đôi"

    def test_slug_lay_thang_tu_nguon(self):
        """`make_public_slug()` gắn 4 ký tự băm của doc_key = "{số hiệu}::{cơ quan}".

        Kho demo không biết cơ quan nên băm ra khác, và 663/4.201 văn bản địa
        phương có URL lệch bản đã đăng — trong khi script tự khai mục đích là
        "kiểm đường dẫn".
        """
        import inspect
        from scripts import nap_demo
        assert '"public_slug"' in inspect.getsource(nap_demo.nap)
