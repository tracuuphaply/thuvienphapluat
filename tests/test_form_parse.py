"""Bóc HTML biểu mẫu TVPL — chạy trên trang thật đã lưu, không chạm mạng.

Fixture là bản sao NGUYÊN VẸN của bốn trang tải ngày 18/08/2026 (nén gzip), chứ
không phải HTML rút gọn viết tay. Rút gọn thì test chỉ còn kiểm tra chính cái
mình vừa bịa ra, và TVPL đổi markup ở phần bị cắt sẽ không ai biết.

  bieumau_list_field11_p1        lĩnh vực Doanh nghiệp, trang 1 — 875 mẫu
  bieumau_detail_47156_khobac    mẫu báo cáo ngân sách của Kho bạc Nhà nước
  hopdong_list_p1                mẫu hợp đồng, trang 1 — 662 mẫu
  hopdong_detail_46696_khoanviec Hợp đồng khoán việc
"""
import gzip
from pathlib import Path

import pytest

from src.sources.tvpl_forms_parse import (
    MIN_BODY_CHARS,
    REF_TRONG_RUOT_MAU,
    REF_TRUONG_CAN_CU,
    FormParseError,
    chuan_hoa_so_hieu,
    co_trang_sau,
    tach_can_cu_trong_ruot,
    tach_chi_tiet,
    tach_danh_sach,
    tach_so_luong,
)

FIXTURES = Path(__file__).parent / "fixtures" / "forms"


def doc(ten: str) -> str:
    return gzip.decompress((FIXTURES / f"{ten}.html.gz").read_bytes()).decode("utf-8")


@pytest.fixture(scope="module")
def bm_list():
    return doc("bieumau_list_field11_p1")


@pytest.fixture(scope="module")
def hd_list():
    return doc("hopdong_list_p1")


@pytest.fixture(scope="module")
def bm_detail():
    return doc("bieumau_detail_47156_khobac")


@pytest.fixture(scope="module")
def hd_detail():
    return doc("hopdong_detail_46696_khoanviec")


class TestTrangLietKe:
    def test_lay_du_20_muc_khong_phai_10(self, bm_list, hd_list):
        """LỖI ĐÃ XẢY RA THẬT, ĐO ĐƯỢC: bản đầu lấy đúng một nửa.

        Bộ chọn cũ là `div.content-1 p.nqTitle > a`. TVPL vẽ các dòng đan xen hai
        lớp sọc `content-1` và `content-0`, nên mỗi trang 20 mẫu chỉ ra 10 — và
        không có lỗi nào nổi lên, kho chỉ đơn giản thiếu một nửa. Trên kho hợp
        đồng 662 mẫu thì mất 331 mẫu.
        """
        assert len(tach_danh_sach(bm_list)) == 20
        assert len(tach_danh_sach(hd_list)) == 20

    def test_so_luong_tim_thay(self, bm_list, hd_list):
        """Khoá lại con số của bộ lọc field=11: 875, không phải 33.820.

        Nếu dựng URL sai dạng (`field=11,organ0`) thì trang trả về TOÀN KHO và
        con số này thành 33820 — đó là dấu hiệu duy nhất báo cào nhầm.
        """
        assert tach_so_luong(bm_list) == 875
        assert tach_so_luong(hd_list) == 662

    def test_khoa_gom_ca_ten_kho(self, bm_list, hd_list):
        """id TVPL chỉ duy nhất TRONG một kho, không duy nhất giữa hai kho."""
        assert all(i.form_key.startswith("bieumau-") for i in tach_danh_sach(bm_list))
        assert all(i.form_key.startswith("hopdong-") for i in tach_danh_sach(hd_list))

    def test_khong_lan_muc_tu_khoi_xem_nhieu_nhat(self, bm_list):
        """Cột phải có khối "XEM NHIỀU NHẤT" cũng là link biểu mẫu.

        Chúng không phải kết quả của bộ lọc; lọt vào là kho có mẫu ngoài lĩnh vực
        mà không ai giải thích được vì sao.
        """
        assert len(tach_danh_sach(bm_list)) == 20

    def test_lay_duoc_tu_khoa_va_ngay_cap_nhat(self, bm_list):
        dau = tach_danh_sach(bm_list)[0]
        assert dau.form_key == "bieumau-47131"
        assert dau.keywords
        assert dau.updated_on is not None and dau.updated_on.year == 2026

    def test_nhan_ra_con_trang_sau(self, bm_list, hd_list):
        assert co_trang_sau(bm_list)
        assert co_trang_sau(hd_list)


class TestTrangChiTietBieuMau:
    def test_lay_duoc_ruot_mau(self, bm_detail):
        d = tach_chi_tiet(bm_detail, "bieumau", "47156")
        assert len(d.body_html) > 10_000
        assert "0124.N.KBNN" in d.body_html

    def test_tieu_de_tu_breadcrumb(self, bm_detail):
        d = tach_chi_tiet(bm_detail, "bieumau", "47156")
        assert d.title.startswith("MẪU BÁO CÁO TÌNH HÌNH THỰC HIỆN NGÂN SÁCH")

    def test_can_cu_tach_so_hieu_khoi_nhan(self, bm_detail):
        """TVPL viết "Thông tư 131/2025/TT-BTC"; documents.doc_num là số hiệu trần.

        Đem cả nhãn đi khớp thì không văn bản nào khớp, và biểu mẫu vĩnh viễn
        không nối được với kho.
        """
        (ref,) = tach_chi_tiet(bm_detail, "bieumau", "47156").refs
        assert ref.doc_num == "131/2025/TT-BTC"
        assert ref.nhan == "Thông tư 131/2025/TT-BTC"
        assert ref.source == REF_TRUONG_CAN_CU

    def test_can_cu_giu_lai_id_tvpl(self, bm_detail):
        """Link căn cứ mang sẵn id TVPL — khớp chắc hơn dò theo số hiệu.

        Số hiệu KHÔNG duy nhất toàn quốc (63 tỉnh đánh số độc lập), id TVPL thì
        duy nhất. Vứt id đi là tự bỏ đường khớp tốt nhất.
        """
        (ref,) = tach_chi_tiet(bm_detail, "bieumau", "47156").refs
        assert ref.tvpl_doc_id == "686963"
        assert ref.url and "/van-ban/" in ref.url


class TestTrangChiTietHopDong:
    def test_ruot_mau_khong_nam_trong_divNoiDungBM(self, hd_detail):
        """/hopdong KHÔNG có `.divNoiDungBM` — phải có nhánh dự phòng.

        Chỉ tìm `.divNoiDungBM` thì cả 662 mẫu hợp đồng đều ra rỗng.
        """
        assert "divNoiDungBM" not in hd_detail
        d = tach_chi_tiet(hd_detail, "hopdong", "46696")
        assert len(d.body_html) > 5_000
        assert "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM" in d.body_html

    def test_can_cu_boc_tu_loi_van(self, hd_detail):
        """/hopdong không có trường "Căn cứ" — căn cứ nằm trong lời văn."""
        d = tach_chi_tiet(hd_detail, "hopdong", "46696")
        assert d.refs
        assert d.refs[0].doc_num == "91/2015/QH13"
        assert all(r.source == REF_TRONG_RUOT_MAU for r in d.refs)

    def test_khong_nuot_thanh_chia_se_va_quang_cao(self, hd_detail):
        """Lấy cả `.divTNPL` sẽ kéo theo "In / Zing Me / Yahoo / Facebook"."""
        d = tach_chi_tiet(hd_detail, "hopdong", "46696")
        assert "Zing Me" not in d.body_html


class TestChotChanRong:
    def test_ruot_rong_thi_nem_loi_chu_khong_luu_cam(self):
        """Biểu mẫu không có ruột là vô dụng, mà lưu im lặng thì kho TRÔNG như đã
        cào xong. TVPL đổi tên class là hỏng hàng loạt — phải nổ ngay.
        """
        with pytest.raises(FormParseError, match="Ruột biểu mẫu"):
            tach_chi_tiet(
                '<html><body><div class="divNoiDungBM"></div></body></html>',
                "bieumau", "1",
            )

    def test_ruot_qua_ngan_cung_bi_chan(self):
        ngan = "<p>" + "x" * (MIN_BODY_CHARS - 50) + "</p>"
        with pytest.raises(FormParseError):
            tach_chi_tiet(
                f'<html><body><div class="divNoiDungBM">{ngan}</div></body></html>',
                "bieumau", "1",
            )

    def test_trang_khong_co_khoi_noi_dung_cung_bi_chan(self):
        with pytest.raises(FormParseError):
            tach_chi_tiet("<html><body><p>Không tìm thấy</p></body></html>",
                          "hopdong", "1")


class TestChuanHoaSoHieu:
    @pytest.mark.parametrize("nhan,mong_doi", [
        ("Thông tư 131/2025/TT-BTC", "131/2025/TT-BTC"),
        ("Nghị định 187/2026/NĐ-CP", "187/2026/NĐ-CP"),
        ("Công văn 4204/BCT-TTNN", "4204/BCT-TTNN"),
        ("Thông tư liên tịch 01/2016/TTLT-BYT", "01/2016/TTLT-BYT"),
    ])
    def test_cat_tien_to_loai_van_ban(self, nhan, mong_doi):
        assert chuan_hoa_so_hieu(nhan) == mong_doi

    @pytest.mark.parametrize("nhan", ["Bộ luật Dân sự", "Luật Doanh nghiệp 2020"])
    def test_nhan_thuan_chu_giu_nguyen(self, nhan):
        """Cắt "Bộ luật Dân sự" thành "Dân sự" rồi đem khớp kho là vô nghĩa.

        Không có dấu "/" thì phần còn lại không phải số hiệu — giữ nguyên.
        """
        assert chuan_hoa_so_hieu(nhan) == nhan


class TestBocCanCuTrongLoiVan:
    def test_bo_qua_so_khong_phai_so_hieu(self):
        """Thân hợp đồng đầy chỗ điền dạng số: mã số thuế, số tài khoản, điện thoại.

        Bộ nhận dạng ở đây hẹp hơn của citation_check có chủ đích — bắt buộc phải
        có phần "/NĂM/" ở giữa.
        """
        loi_van = (
            "Mã số thuế: 0315459414 Điện thoại: 028/3930/3279 "
            "Số tài khoản: 1234/5678 Căn cứ Bộ luật Dân sự năm 2015 số 91/2015/QH13"
        )
        assert [r.doc_num for r in tach_can_cu_trong_ruot(loi_van)] == ["91/2015/QH13"]

    def test_khu_trung_va_chan_tran(self):
        loi_van = " ".join(f"{i}/2020/NĐ-CP" for i in range(1, 20))
        refs = tach_can_cu_trong_ruot(loi_van, gioi_han=3)
        assert len(refs) == 3
        assert len({r.doc_num for r in refs}) == 3


class TestGhepChuTuNhieuThe:
    """LỖI ĐÃ XẢY RA THẬT: `get_text(" ")` chèn dấu cách vào GIỮA TỪ.

    Aspose xuất từ Word cắt chữ thành nhiều `<span>` liền nhau, có chỗ cắt giữa
    từ. Ghép bằng dấu cách cho ra "Độc lậ p - Tự do", "Bộ l uật D ân sự",
    "T h ời hạn báo cáo". Hậu quả kép: bộ đếm từ khoá của phễu trượt hết (cụm
    "bộ luật dân sự" không còn khớp), và bản DOCX dựng lại không đọc được.
    """

    def test_khong_chen_dau_cach_giua_tu(self, hd_detail):
        from src.sources.tvpl_forms_parse import chu_trong_ruot, tach_chi_tiet

        ruot = chu_trong_ruot(tach_chi_tiet(hd_detail, "hopdong", "46696").body_html)
        assert "Độc lập - Tự do - Hạnh phúc" in ruot
        assert "Bộ luật Dân sự" in ruot
        assert "Độc lậ p" not in ruot
        assert "l uật" not in ruot

    def test_van_ngat_giua_hai_khoi(self):
        """Ghép trắng trơn thì sai theo chiều ngược lại: hai đoạn dính vào nhau."""
        from src.sources.tvpl_forms_parse import chu_trong_ruot

        ruot = chu_trong_ruot("<p><span>VIỆT </span><span>NAM</span></p><p>Độc lập</p>")
        assert ruot == "VIỆT NAM Độc lập"

    def test_bao_cao_khobac_giu_nguyen_cum_dinh_danh(self, bm_detail):
        from src.sources.tvpl_forms_parse import chu_trong_ruot, tach_chi_tiet

        ruot = chu_trong_ruot(tach_chi_tiet(bm_detail, "bieumau", "47156").body_html)
        assert "Thời hạn báo cáo" in ruot
        assert "T h ời" not in ruot
