"""Phễu lọc biểu mẫu doanh nghiệp — ba tầng.

HAI MẪU MỐC, LẤY TỪ TRANG THẬT, ĐỐI NHAU HOÀN TOÀN VỀ MẶT METADATA:

  /bieumau/47156  Mẫu báo cáo tình hình thực hiện ngân sách trung ương của KHO
                  BẠC NHÀ NƯỚC — PHẢI BỊ LOẠI
  /bieumau/47131  Mẫu giấy đề nghị đăng ký thay đổi người đại diện theo pháp
                  luật — PHẢI ĐƯỢC GIỮ

Cả hai đều là "Mẫu văn bản", đều do cơ quan trung ương ban hành, đều kèm theo một
văn bản quy phạm. Không dấu hiệu phân loại nào của TVPL tách được chúng — chỉ
"ai cầm bút điền" mới tách được. Đó là toàn bộ lý do phễu tồn tại.
"""
import gzip
import json
from pathlib import Path

import pytest

from src.forms import pheu
from src.forms.classifier import KetQuaPhanLoai, dung_prompt, phan_loai
from src.forms.relevance import (
    BIEU_MAU_BUSINESS_FIELDS,
    NGUONG_CHAC,
    la_linh_vuc_kinh_doanh,
    quyet_dinh_quy_tac,
)
from src.legal.form_taxonomy import CO_QUAN_NHA_NUOC, DOANH_NGHIEP, KHAC, NGHIEP_VU
from src.rag.reports.llm import LLMResult
from src.sources.tvpl_forms_parse import chu_trong_ruot, tach_chi_tiet
from src.storage.models import LegalForm

FIXTURES = Path(__file__).parent / "fixtures" / "forms"


def doc(ten: str) -> str:
    return gzip.decompress((FIXTURES / f"{ten}.html.gz").read_bytes()).decode("utf-8")


def ruot_va_tieu_de(ten: str, source: str, eid: str) -> tuple[str, str]:
    d = tach_chi_tiet(doc(ten), source, eid)
    return d.title, chu_trong_ruot(d.body_html)


# ──────────────────────────────────────────────
# Tầng 1
# ──────────────────────────────────────────────
class TestTang1LinhVuc:
    def test_giu_dung_21_linh_vuc_da_do(self):
        assert len(BIEU_MAU_BUSINESS_FIELDS) == 21
        assert len(set(BIEU_MAU_BUSINESS_FIELDS)) == 21

    @pytest.mark.parametrize("ma,ten", [(11, "Doanh nghiệp"), (24, "Lao động"),
                                        (35, "Thuế"), (46, "Xuất nhập khẩu")])
    def test_linh_vuc_lo_i_kinh_doanh_duoc_giu(self, ma, ten):
        assert la_linh_vuc_kinh_doanh(ma), ten

    @pytest.mark.parametrize("ma,ten", [(3, "Bộ máy hành chính"), (12, "Đảng"),
                                        (18, "Giáo dục"), (28, "Quốc phòng"),
                                        (47, "Y tế")])
    def test_linh_vuc_ngoai_kinh_doanh_bi_loai(self, ma, ten):
        assert not la_linh_vuc_kinh_doanh(ma), ten

    def test_dung_ma_cua_trang_bieu_mau_khong_phai_trang_van_ban(self):
        """Mã 1 ở đây là "An toàn thực phẩm", KHÔNG phải "Doanh nghiệp".

        Danh mục văn bản đánh "Doanh nghiệp" = 1; danh mục biểu mẫu đánh = 11.
        Lấy nhầm bộ mã thì whitelist trỏ sang một tập lĩnh vực hoàn toàn khác mà
        vẫn chạy trót lọt.
        """
        assert 11 in BIEU_MAU_BUSINESS_FIELDS
        assert 12 not in BIEU_MAU_BUSINESS_FIELDS   # 12 = Đảng ở danh mục biểu mẫu


# ──────────────────────────────────────────────
# Tầng 2
# ──────────────────────────────────────────────
class TestTang2QuyTac:
    """SỐ ĐO THẬT trên 67 mẫu hợp đồng đã cào, ngày 18/08/2026:

        tầng 2 quyết được  21/67  = 31%   (giữ 20, loại 1)
        đẩy lên tầng 3     46/67  = 68%

    Tỉ lệ này là KẾT QUẢ MONG MUỐN, không phải điểm yếu. Tầng 2 chỉ được kết luận
    khi CHẮC; nới điều kiện để nó quyết nhiều hơn là đổi lấy sai sót âm thầm mà
    không ai kiểm được, trong khi đẩy lên tầng 3 chỉ tốn thêm ít tiền. Mẫu duy
    nhất bị loại là "HỢP ĐỒNG THUÊ NHÀ Ở CÔNG VỤ DO BỘ QUỐC PHÒNG BAN HÀNH" —
    đúng loại mà chủ doanh nghiệp không bao giờ điền.

    Nếu con số này tụt mạnh sau khi sửa bộ từ khoá, hãy đo lại trước khi tin: rất
    có thể vừa nới một dấu hiệu quá rộng.
    """

    def test_mau_kho_bac_bi_loai(self):
        """Mẫu báo cáo ngân sách của Kho bạc Nhà nước: doanh nghiệp không điền."""
        td, ruot = ruot_va_tieu_de("bieumau_detail_47156_khobac", "bieumau", "47156")
        kq = quyet_dinh_quy_tac(td, ruot)
        assert kq.audience == CO_QUAN_NHA_NUOC
        assert kq.diem_giu == 0
        assert "kho bạc nhà nước" in kq.dau_hieu_loai

    def test_mau_doi_nguoi_dai_dien_duoc_giu(self):
        td, ruot = ruot_va_tieu_de(
            "bieumau_detail_47131_doi_nguoi_dai_dien", "bieumau", "47131")
        kq = quyet_dinh_quy_tac(td, ruot)
        assert kq.audience == DOANH_NGHIEP
        assert kq.diem_loai == 0
        assert kq.diem_giu >= NGUONG_CHAC

    def test_hai_ben_deu_co_diem_thi_khong_ket_luan(self):
        """Mẫu vừa nhắc doanh nghiệp vừa nhắc cơ quan nhà nước là thật sự nhập nhằng.

        Ví dụ điển hình: biên bản kiểm tra do đoàn kiểm tra lập TẠI doanh nghiệp.
        Quy tắc đoán ở đó là đoán sai, phải để mô hình đọc.
        """
        kq = quyet_dinh_quy_tac(
            "MẪU BIÊN BẢN KIỂM TRA DOANH NGHIỆP",
            "Đoàn kiểm tra của Ủy ban nhân dân tỉnh lập biên bản tại doanh nghiệp",
        )
        assert kq.audience is None
        assert kq.diem_giu > 0 and kq.diem_loai > 0

    def test_doanh_nghiep_nha_nuoc_khong_bi_quet_nham(self):
        """Từ khoá "nhà nước" trần sẽ quét sạch cả nhóm doanh nghiệp nhà nước.

        Đây đúng là lỗi mà src/analysis/lexicon.py sinh ra để chặn: "nước" từng
        khớp "nhà nước" và kéo 97/314 văn bản vào nhầm ngành. Ở đây hậu quả trực
        tiếp hơn — mẫu hợp lệ bị vứt.
        """
        kq = quyet_dinh_quy_tac(
            "MẪU BÁO CÁO CỦA DOANH NGHIỆP NHÀ NƯỚC",
            "Tên doanh nghiệp: … Mã số thuế: … Vốn điều lệ: …",
        )
        assert kq.audience == DOANH_NGHIEP

    def test_chi_doc_phan_dau_ruot_mau(self):
        """Khối tự khai nằm ở đầu; phần thân toàn chỗ điền trống, không nói gì."""
        from src.forms.relevance import KY_TU_DAU_RUOT

        xa = "x" * KY_TU_DAU_RUOT + " kho bạc nhà nước ngân sách nhà nước dự toán ngân sách"
        assert quyet_dinh_quy_tac("MẪU ĐƠN", xa).diem_loai == 0


# ──────────────────────────────────────────────
# Tầng 3
# ──────────────────────────────────────────────
def _mo_hinh_gia(payload: dict):
    def _goi(system, user, model="", max_tokens=0):
        return LLMResult(text=json.dumps(payload, ensure_ascii=False),
                         truncated=False, model="gia-lap")
    return _goi


class TestTang3MoHinh:
    def test_boc_duoc_json_lan_trong_van_xuoi(self):
        """Mô hình rẻ hay kèm một câu dẫn dù prompt đã cấm.

        Ném lỗi ở đây là vứt luôn lượt gọi đã trả tiền.
        """
        def goi(system, user, model="", max_tokens=0):
            return LLMResult(
                text='Đây là kết quả:\n{"nguoi_dien": "doanh_nghiep", '
                     '"do_tin_cay": 0.9, "nhom_nghiep_vu": ["dkkd"], "ly_do": "x"}\nXong.',
                truncated=False, model="gia-lap")

        kq = phan_loai("MẪU ĐƠN", "…", goi_mo_hinh=goi)
        assert kq.audience == DOANH_NGHIEP
        assert kq.nghiep_vu == ["dkkd"]

    def test_nhan_la_roi_ve_khac_chu_khong_vo(self):
        """Một mẫu xếp "khac" thì nằm chờ người duyệt; ném lỗi thì cả lô dừng."""
        kq = phan_loai("MẪU ĐƠN", "…",
                       goi_mo_hinh=_mo_hinh_gia({"nguoi_dien": "Doanh Nghiệp X"}))
        assert kq.audience == KHAC

    def test_nghiep_vu_la_bi_loai_khoi_tap_dong(self):
        """`nghiep_vu` là mục lục trang công khai và menu Telegram.

        Nhận nhóm mô hình tự nghĩ ra thì mục lục mọc thêm nhánh mỗi ngày.
        """
        kq = phan_loai("MẪU ĐƠN", "…", goi_mo_hinh=_mo_hinh_gia(
            {"nguoi_dien": "doanh_nghiep",
             "nhom_nghiep_vu": ["thue_hoa_don", "nhóm tôi tự nghĩ ra"]}))
        assert kq.nghiep_vu == ["thue_hoa_don"]

    def test_do_tin_cay_bi_kep_ve_0_1(self):
        kq = phan_loai("MẪU ĐƠN", "…", goi_mo_hinh=_mo_hinh_gia(
            {"nguoi_dien": "doanh_nghiep", "do_tin_cay": 7.5}))
        assert kq.confidence == 1.0

    def test_prompt_liet_ke_du_12_nhom_nghiep_vu(self):
        p = dung_prompt("MẪU ĐƠN", "ruột", can_cu=["91/2015/QH13"], linh_vuc="Doanh nghiệp")
        for ma in NGHIEP_VU:
            assert ma in p
        assert "91/2015/QH13" in p


# ──────────────────────────────────────────────
# Chạy cả phễu trên DB
# ──────────────────────────────────────────────
@pytest.fixture
def form_that(master_session, tmp_path):
    """Dựng bản ghi biểu mẫu trỏ tới trang HTML thật đã giải nén."""
    def _tao(ten_fixture, source, eid, title, field_code=11):
        p = tmp_path / f"{source}-{eid}.html"
        p.write_text(doc(ten_fixture), encoding="utf-8")
        f = LegalForm(
            form_key=f"{source}-{eid}", source=source, external_id=eid,
            title=title, field_code=field_code, crawl_status="OK",
            body_html_path=str(p), body_hash="h1",
        )
        master_session.add(f)
        master_session.commit()
        return f
    return _tao


class TestChayPheu:
    def test_kho_bac_bi_loai_o_tang_2_khong_ton_luot_goi_mo_hinh(
            self, master_session, form_that):
        form_that("bieumau_detail_47156_khobac", "bieumau", "47156",
                  "MẪU BÁO CÁO TÌNH HÌNH THỰC HIỆN NGÂN SÁCH TRUNG ƯƠNG "
                  "CỦA KHO BẠC NHÀ NƯỚC", field_code=21)

        def khong_duoc_goi(*a, **kw):
            raise AssertionError("tầng 2 đã chắc, không được gọi mô hình")

        tk = pheu.chay_pheu(master_session, goi_mo_hinh=khong_duoc_goi)
        assert tk.tang2_loai == 1 and tk.tang3_goi == 0
        f = master_session.query(LegalForm).one()
        assert f.is_business is False
        assert f.audience == CO_QUAN_NHA_NUOC
        assert f.audience_source == pheu.NGUON_QUY_TAC

    def test_mau_doanh_nghiep_duoc_giu(self, master_session, form_that):
        form_that("bieumau_detail_47131_doi_nguoi_dai_dien", "bieumau", "47131",
                  "MẪU GIẤY ĐỀ NGHỊ ĐĂNG KÝ THAY ĐỔI NGƯỜI ĐẠI DIỆN THEO PHÁP LUẬT")
        tk = pheu.chay_pheu(master_session, dung_mo_hinh=False)
        assert tk.tang2_giu == 1
        assert master_session.query(LegalForm).one().is_business is True

    def test_ngoai_linh_vuc_bi_cat_o_tang_1_khong_doc_ruot(
            self, master_session, form_that):
        form_that("bieumau_detail_47131_doi_nguoi_dai_dien", "bieumau", "47131",
                  "MẪU ĐƠN GÌ ĐÓ", field_code=18)   # 18 = Giáo dục
        tk = pheu.chay_pheu(master_session, dung_mo_hinh=False)
        assert tk.tang1_loai == 1
        f = master_session.query(LegalForm).one()
        assert f.is_business is False
        assert f.excluded_reason.startswith(pheu.LY_DO_NGOAI_LINH_VUC)

    def test_hop_dong_bo_qua_tang_1(self, master_session, form_that):
        """Mẫu hợp đồng không có lĩnh vực — bắt nó qua tầng 1 là loại sạch 662 mẫu."""
        form_that("hopdong_detail_46696_khoanviec", "hopdong", "46696",
                  "HỢP ĐỒNG KHOÁN VIỆC", field_code=None)
        tk = pheu.chay_pheu(master_session, goi_mo_hinh=_mo_hinh_gia(
            {"nguoi_dien": "doanh_nghiep", "do_tin_cay": 0.8,
             "nhom_nghiep_vu": ["hop_dong", "lao_dong_bhxh"]}))
        assert tk.tang1_loai == 0 and tk.tang3_goi == 1
        f = master_session.query(LegalForm).one()
        assert f.is_business is True
        assert json.loads(f.nghiep_vu) == ["hop_dong", "lao_dong_bhxh"]

    def test_mo_hinh_hong_thi_khong_gan_nhan(self, master_session, form_that):
        """Mẫu chưa phân loại sẽ được thử lại; một nhãn bịa thì nằm lại vĩnh viễn."""
        form_that("hopdong_detail_46696_khoanviec", "hopdong", "46696",
                  "HỢP ĐỒNG KHOÁN VIỆC", field_code=None)

        def hong(*a, **kw):
            raise RuntimeError("nhà cung cấp mô hình chết")

        tk = pheu.chay_pheu(master_session, goi_mo_hinh=hong)
        assert tk.loi_mo_hinh == 1
        assert master_session.query(LegalForm).one().audience is None

    def test_chay_lai_bo_qua_mau_da_phan_loai(self, master_session, form_that):
        form_that("bieumau_detail_47131_doi_nguoi_dai_dien", "bieumau", "47131",
                  "MẪU GIẤY ĐỀ NGHỊ ĐĂNG KÝ THAY ĐỔI NGƯỜI ĐẠI DIỆN THEO PHÁP LUẬT")
        pheu.chay_pheu(master_session, dung_mo_hinh=False)
        lan_hai = pheu.chay_pheu(master_session, dung_mo_hinh=False)
        assert lan_hai.tang2_giu == 0 and lan_hai.giu == 0

    def test_khong_doc_duoc_ruot_thi_de_trong_chu_khong_ket_luan(
            self, master_session):
        master_session.add(LegalForm(
            form_key="bieumau-999", source="bieumau", external_id="999",
            title="MẪU ĐƠN", field_code=11, crawl_status="OK",
            body_html_path="/khong/ton/tai.html",
        ))
        master_session.commit()
        tk = pheu.chay_pheu(master_session, dung_mo_hinh=False)
        assert tk.khong_doc_duoc_ruot == 1
        f = master_session.query(LegalForm).one()
        assert f.is_business is None          # KHÔNG phải False
        assert f.excluded_reason == pheu.LY_DO_CHUA_CO_RUOT


def test_ket_qua_phan_loai_mac_dinh_khong_rong():
    assert KetQuaPhanLoai(audience=KHAC).nghiep_vu == []


@pytest.fixture
def form_tho(master_session, tmp_path):
    """Dựng biểu mẫu với HTML tự viết — kiểm soát chính xác tín hiệu trong ruột.

    Fixture trang thật không dùng được cho các ca này: mẫu /bieumau/47131 thì tầng
    2 quyết được (điểm giữ 3), còn thân "khoán việc" có "Mã số thuế" nên vừa có
    tín hiệu giữ vừa có tín hiệu loại — không phải ca loại thuần.
    """
    def _tao(form_key, source, title, than):
        p = tmp_path / f"{form_key}.html"
        p.write_text(
            f'<html><body><div class="divTNPL"><div>{than}</div></div></body></html>',
            encoding="utf-8")
        f = LegalForm(
            form_key=form_key, source=source, external_id=form_key.split("-")[-1],
            title=title, crawl_status="OK", body_html_path=str(p), body_hash="h",
            field_code=11 if source == "bieumau" else None,
        )
        master_session.add(f)
        master_session.commit()
        return f
    return _tao


#: Thân mẫu KHÔNG chứa tín hiệu nào của cả hai phía — buộc tầng 2 phải bó tay.
THAN_TRUNG_TINH = ("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM Độc lập - Tự do - Hạnh phúc "
                   "Hôm nay, ngày … tháng … năm …, tại … " * 6)


class TestMacDinhTheoKho:
    """LỖI ĐÃ XẢY RA THẬT, ĐO ĐƯỢC: 548/662 mẫu hợp đồng biến mất.

    Bản đầu để mọi mẫu mà hai tầng quy tắc không dám kết luận rơi vào hư vô, chờ
    tầng 3. Người dùng tắt tầng 3 (không có quota mô hình), nên cào đủ 662 mẫu mà
    trang công khai chỉ có 105 — 105 giữ + 9 loại + 548 KHÔNG AI XỬ LÝ.

    Mặc định phải NGƯỢC NHAU giữa hai kho vì bản chất hai kho ngược nhau. Đây là
    GIẢ ĐỊNH về kho, không phải bằng chứng về mẫu, nên `audience_source` ghi
    "mac_dinh_nguon" chứ không ghi "quy_tac".
    """

    def test_hop_dong_khong_ket_luan_duoc_thi_GIU(self, master_session, form_tho):
        """Hợp đồng là văn bản giao dịch — không loại được thì giữ."""
        form_tho("hopdong-9003", "hopdong", "HỢP ĐỒNG KHOÁN VIỆC", THAN_TRUNG_TINH)
        tk = pheu.chay_pheu(master_session, dung_mo_hinh=False)
        assert tk.mac_dinh_giu == 1
        f = master_session.query(LegalForm).one()
        assert f.is_business is True
        assert f.audience_source == pheu.NGUON_MAC_DINH
        assert "Mặc định theo kho" in f.audience_reason

    def test_bieu_mau_khong_ket_luan_duoc_thi_KHONG_giu(self, master_session,
                                                       form_tho):
        """Kho /bieumau 33.820 mẫu phần lớn là báo cáo nội bộ cơ quan nhà nước.

        Mặc định giữ ở đây sẽ nhấn chìm kho bằng biểu quyết toán ngân sách — đúng
        thứ phễu sinh ra để lọc.
        """
        form_tho("bieumau-9001", "bieumau", "MẪU ĐƠN KHÔNG RÕ AI ĐIỀN",
                 THAN_TRUNG_TINH)
        tk = pheu.chay_pheu(master_session, dung_mo_hinh=False)
        assert tk.mac_dinh_giu == 0
        assert master_session.query(LegalForm).one().is_business is None

    def test_quy_tac_LOAI_thang_mac_dinh_giu(self, master_session, form_tho):
        """9 mẫu bị loại đúng: viên chức, quốc phòng, kho bạc, học sinh.

        Mặc định theo kho KHÔNG được ghi đè kết luận có bằng chứng.
        """
        form_tho("hopdong-9002", "hopdong",
                 "HỢP ĐỒNG LÀM VIỆC KHÔNG XÁC ĐỊNH THỜI HẠN ĐỐI VỚI VIÊN CHỨC",
                 THAN_TRUNG_TINH)
        tk = pheu.chay_pheu(master_session, dung_mo_hinh=False)
        assert tk.tang2_loai == 1 and tk.mac_dinh_giu == 0
        f = master_session.query(LegalForm).one()
        assert f.is_business is False
        assert f.audience_source == pheu.NGUON_QUY_TAC

    def test_mac_dinh_ghi_do_tin_cay_0(self, master_session, form_tho):
        """Giả định về kho không phải bằng chứng — độ tin cậy phải là 0."""
        form_tho("hopdong-9004", "hopdong", "HỢP ĐỒNG KHOÁN VIỆC", THAN_TRUNG_TINH)
        pheu.chay_pheu(master_session, dung_mo_hinh=False)
        assert master_session.query(LegalForm).one().audience_confidence == 0.0
