"""
Biểu đồ báo cáo.

Trọng tâm: biểu đồ vắng mặt là lỗi IM LẶNG. Payload vẫn hợp lệ, PDF vẫn dựng,
báo cáo vẫn gửi đi — chỉ thiếu hình mà không ai biết vì sao. Nên phần lớn test
ở đây kiểm rằng biểu đồ CÓ xuất hiện khi dữ liệu đủ.
"""
from __future__ import annotations

import inspect
from datetime import date, timedelta

from src.rag.reports import context as report_context
from src.rag.reports import figures


def _vb(**kw) -> dict:
    nen = {"doc_num": "01/2026/NĐ-CP", "doc_type": "Nghị định",
           "tinh_trang_hieu_luc_chuan_hoa": "Còn hiệu lực", "eff_from": "2026-01-01"}
    nen.update(kw)
    return nen


class TestChonBieuDo:
    def test_du_lieu_day_du_thi_co_ba_bieu_do(self):
        mai = date.today() + timedelta(days=40)
        ds = [
            _vb(doc_type="Nghị định", eff_from=str(mai)),
            _vb(doc_type="Thông tư", eff_from=str(mai.replace(day=1) + timedelta(days=40))),
            _vb(doc_type="Luật", eff_from=str(mai.replace(day=1) + timedelta(days=80))),
            _vb(doc_type="Quyết định", tinh_trang_hieu_luc_chuan_hoa="Hết hiệu lực toàn bộ",
                eff_from=str(mai.replace(day=1) + timedelta(days=120))),
        ]
        figs = figures.build_figures("a", {"danh_sach_van_ban": ds})
        assert len(figs) == 3
        assert all(f.png for f in figs)

    def test_khong_co_van_ban_thi_khong_co_bieu_do(self):
        assert figures.build_figures("a", {"danh_sach_van_ban": []}) == []
        assert figures.build_figures("a", {}) == []

    def test_qua_it_nhom_thi_bo_bieu_do_thay_vi_ve_hai_cot(self):
        """Biểu đồ hai cột trông như lỗi in và hạ uy tín cả bản báo cáo."""
        ds = [_vb(doc_type="Nghị định"), _vb(doc_type="Nghị định")]
        titles = [f.title for f in figures.build_figures("a", {"danh_sach_van_ban": ds})]
        assert not any("thuộc loại gì" in t for t in titles)

    def test_so_thu_tu_lien_tuc_khi_co_bieu_do_bi_bo(self):
        """Bộ dựng PDF in "BIỂU ĐỒ {number}" nguyên văn, số nhảy cóc lộ ra bản in."""
        ds = [_vb(doc_type=t) for t in ("Nghị định", "Thông tư", "Luật", "Quyết định")]
        figs = figures.build_figures("a", {"danh_sach_van_ban": ds})
        assert [f.number for f in figs] == list(range(1, len(figs) + 1))

    def test_moc_da_qua_khong_vao_bieu_do_moc_sap_toi(self):
        cu = [_vb(doc_type=t, eff_from="2019-0%d-01" % i)
              for i, t in enumerate(("Nghị định", "Thông tư", "Luật"), 1)]
        titles = [f.title for f in figures.build_figures("a", {"danh_sach_van_ban": cu})]
        assert not any("mốc bạn cần chuẩn bị" in t for t in titles)


class TestBieuDoNganhCuaBaoCaoB:
    def _payload(self):
        return {
            "danh_sach_van_ban": [_vb(doc_type=t) for t in
                                  ("Nghị định", "Thông tư", "Luật")],
            "diem_tac_dong_nganh": [
                {"doc_num": "01/2026/NĐ-CP", "ma_nganh": "K",
                 "ten_nganh": "Tài chính, ngân hàng và bảo hiểm",
                 "ty_trong_tac_dong": 42.0, "cuong_do_tac_dong": 91.0},
                {"doc_num": "01/2026/NĐ-CP", "ma_nganh": "F",
                 "ten_nganh": "Xây dựng",
                 "ty_trong_tac_dong": 31.0, "cuong_do_tac_dong": 77.0},
                {"doc_num": "01/2026/NĐ-CP", "ma_nganh": "G",
                 "ten_nganh": "Bán buôn, bán lẻ",
                 "ty_trong_tac_dong": 12.0, "cuong_do_tac_dong": 40.0},
            ],
        }

    def test_bao_cao_b_co_them_bieu_do_nganh(self):
        """(b) gom văn bản của nhiều ngành nên "ngành nào lãnh nhiều nhất" là

        câu hỏi thật. (a) và (c) vốn chỉ nói về một ngành.
        """
        titles = [f.title for f in figures.build_figures("b", self._payload())]
        assert any("Ngành nào chịu ảnh hưởng" in t for t in titles)

    def test_bao_cao_a_va_c_khong_ve_bieu_do_nganh(self):
        for kind in ("a", "c"):
            titles = [f.title for f in figures.build_figures(kind, self._payload())]
            assert not any("Ngành nào chịu ảnh hưởng" in t for t in titles), kind

    def test_moi_khoa_figures_doc_deu_co_trong_document_facts(self):
        """Chốt hợp đồng khoá giữa figures.py và context.document_facts().

        Hai lần trong cùng một file tôi đoán tên khoá và đoán sai —
        "impact_pct_doc" (tên cột SQL, không phải tên khoá trả ra) và
        "tinh_trang_hieu_luc_chuan_hoa" (không tồn tại). Cả hai đều hỏng IM LẶNG: biểu đồ
        hoặc biến mất, hoặc vẫn vẽ nhưng nhóm theo trường sai. Test này so
        thẳng vào mã nguồn hàm kia.
        """
        src = inspect.getsource(report_context.document_facts)
        for khoa in ("doc_type", "eff_from", "tinh_trang_hieu_luc_chuan_hoa"):
            assert f'"{khoa}"' in src, (
                f"figures.py đọc khoá {khoa!r} mà document_facts() không trả ra"
            )

    def test_ten_truong_khop_voi_industry_impact(self):
        """Chốt hợp đồng giữa figures.py và context.industry_impact().

        Bản đầu tôi đọc tên cột trong câu SQL ("impact_pct_doc") thay vì tên
        khoá lúc trả ra ("ty_trong_tac_dong"), nên biểu đồ này không bao giờ
        hiện và không có gì báo lỗi. Test so thẳng vào mã nguồn của hàm kia để
        lần đổi tên sau làm đỏ test chứ không làm biến mất một biểu đồ.
        """
        src = inspect.getsource(report_context.industry_impact)
        for khoa in ("ten_nganh", "ma_nganh", "ty_trong_tac_dong"):
            assert f'"{khoa}"' in src, (
                f"figures.py đọc khoá {khoa!r} mà industry_impact() không còn trả ra"
            )
