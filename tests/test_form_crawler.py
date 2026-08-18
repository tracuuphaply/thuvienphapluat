"""Bộ cào biểu mẫu — dựng URL và lật trang, không mở trình duyệt.

Phần chạm mạng (`start`/`stop`/`_goto`) không test ở đây: nó phải qua Chrome thật
vì Cloudflare chặn mọi thứ khác. Cái test được và cũng là cái từng sai — dựng URL
và lật trang — thì tách hẳn ra để chạy khô.
"""
import asyncio
import gzip
from pathlib import Path

import pytest

from src.legal.form_taxonomy import HOP_DONG_CRAWL_CODES
from src.sources.tvpl_forms import (
    TVPLFormCrawler,
    duong_dan_html,
    url_bieu_mau,
    url_hop_dong,
)
from src.sources.tvpl_forms_parse import SOURCE_BIEU_MAU, SOURCE_HOP_DONG

FIXTURES = Path(__file__).parent / "fixtures" / "forms"


def doc(ten: str) -> str:
    return gzip.decompress((FIXTURES / f"{ten}.html.gz").read_bytes()).decode("utf-8")


class TestDungURL:
    def test_field_va_organ_la_hai_tham_so_rieng(self):
        """CẠM BẪY ĐÃ ĐO NGÀY 18/08/2026.

        Thanh phân trang của chính TVPL phát ra `?q=&type=0&field=11,organ0&page=1`.
        Dạng đó KHÔNG áp bộ lọc: trang trả về đủ 33.820 mẫu chứ không phải 875 mẫu
        lĩnh vực Doanh nghiệp, và ô chọn lĩnh vực vẫn hiện "Tất cả". Chép lại dạng
        đó là cào nhầm toàn kho mà không có dấu hiệu nào báo sai.
        """
        u = url_bieu_mau(field=11, page=1)
        assert "field=11&organ=0" in u
        assert "field=11%2Corgan0" not in u and "field=11,organ0" not in u

    def test_giu_du_bon_tham_so_bat_buoc(self):
        u = url_bieu_mau(field=11, page=3)
        for phan in ("type=0", "field=11", "organ=0", "q=", "page=3"):
            assert phan in u

    def test_hop_dong_bo_type_khi_xem_tat_ca(self):
        """`type=0` không phải "tất cả" ở /hopdong — nó là nhóm không tồn tại."""
        assert "type=" not in url_hop_dong(loai=0, page=1)
        assert "type=6" in url_hop_dong(loai=6, page=1)

    def test_duong_dan_html_gom_ca_ten_kho(self):
        """/bieumau/46696 và /hopdong/46696 là hai mẫu khác nhau.

        Đặt tên file theo id trần thì mẫu sau ghi đè mẫu trước.
        """
        assert duong_dan_html("bieumau-46696") != duong_dan_html("hopdong-46696")


class _CrawlerGia(TVPLFormCrawler):
    """Cào trên fixture: thay `lay_html` bằng HTML lưu sẵn, không mở Chrome."""

    def __init__(self, trang_theo_url):
        super().__init__()
        self.trang_theo_url = trang_theo_url
        self.da_goi: list[str] = []

    async def lay_html(self, url: str) -> str:
        self.da_goi.append(url)
        for khoa, html in self.trang_theo_url.items():
            if khoa in url:
                return html
        return "<html><body>Không tìm thấy</body></html>"


def chay(coro):
    return asyncio.run(coro)


class TestLatTrang:
    def test_dung_khi_trang_khong_con_muc_moi(self):
        """TVPL trả lặp trang cuối khi `page` vượt số trang có thật.

        Chỉ dựa vào nút "Trang sau" là lật vô hạn — nút đó luôn được vẽ.
        """
        html = doc("bieumau_list_field11_p1")
        c = _CrawlerGia({"/bieumau": html})
        muc = chay(c.duyet_danh_sach(SOURCE_BIEU_MAU, field=11))
        assert len(muc) == 20            # 20 mẫu của trang 1, không nhân đôi
        assert len(c.da_goi) == 2        # trang 2 lặp lại → dừng ngay

    def test_dien_ma_linh_vuc_tu_bo_loc_da_dung(self):
        """Trang liệt kê KHÔNG hiện lĩnh vực — nó đến từ chính bộ lọc đã mở."""
        c = _CrawlerGia({"/bieumau": doc("bieumau_list_field11_p1")})
        muc = chay(c.duyet_danh_sach(SOURCE_BIEU_MAU, field=11))
        assert {m.field_code for m in muc} == {11}

    def test_gioi_han_cat_dung_so_luong(self):
        c = _CrawlerGia({"/bieumau": doc("bieumau_list_field11_p1")})
        assert len(chay(c.duyet_danh_sach(SOURCE_BIEU_MAU, field=11, gioi_han=7))) == 7

    def test_hop_dong_di_het_ca_22_nhom(self):
        """Đi theo 10 nhóm gốc là thiếu 137 mẫu — xem test_form_taxonomy.py."""
        c = _CrawlerGia({"/hopdong": doc("hopdong_list_p1")})
        muc = chay(c.duyet_hop_dong())
        khoa = [m.form_key for m in muc]
        assert len(khoa) == len(set(khoa))
        ma_da_goi = {int(u.split("type=")[1].split("&")[0])
                     for u in c.da_goi if "type=" in u}
        assert ma_da_goi == set(HOP_DONG_CRAWL_CODES)

    def test_hop_dong_giu_nhom_gap_dau_tien(self):
        """Mẫu gặp lại ở nhóm sau thì giữ nhãn của nhóm cụ thể gặp trước.

        Thứ tự HOP_DONG_CRAWL_CODES đặt nhóm con trước nhóm cha, nên ghi đè bằng
        lần gặp sau sẽ đẩy mẫu lên nhãn chung chung hơn.
        """
        c = _CrawlerGia({"/hopdong": doc("hopdong_list_p1")})
        muc = chay(c.duyet_hop_dong())
        assert muc[0].form_type_code == HOP_DONG_CRAWL_CODES[0]

    def test_trang_rong_khong_lam_vo(self):
        c = _CrawlerGia({})
        assert chay(c.duyet_danh_sach(SOURCE_HOP_DONG, loai=6)) == []


class TestDemDoiChieu:
    def test_canh_bao_khi_lay_thieu_so_voi_con_so_tvpl_bao(self, caplog):
        """Lấy 20/875 phải NÓI ra.

        Im lặng ở đây nghĩa là kho thiếu mà trông như đã cào xong — không ai
        phát hiện cho tới khi khách hỏi vì sao thiếu mẫu.
        """
        c = _CrawlerGia({"/bieumau": doc("bieumau_list_field11_p1")})
        with caplog.at_level("WARNING"):
            chay(c.duyet_danh_sach(SOURCE_BIEU_MAU, field=11))
        assert any("20/875" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("ma", HOP_DONG_CRAWL_CODES)
def test_moi_nhom_goc_deu_dung_duoc_url(ma):
    assert f"type={ma}" in url_hop_dong(loai=ma, page=1)
