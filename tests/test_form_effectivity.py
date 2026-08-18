"""Hiệu lực biểu mẫu — suy từ căn cứ, không đoán.

BIỂU MẪU KHÔNG CÓ HIỆU LỰC RIÊNG. Nó là phụ lục kèm theo một văn bản quy phạm nên
sống chết theo văn bản đó. TVPL KHÔNG công bố điều này — trang chỉ ghi "Cập nhật:
<ngày>", tức ngày họ sửa trang, không phải ngày pháp lý. Cả module tồn tại để trả
lời câu mà nguồn không trả lời.

BA CA THẬT, ĐO TRÊN KHO NGÀY 18/08/2026 — dùng làm mốc cho các test dưới đây:

  hopdong-18138  HỢP ĐỒNG MUA BÁN ĐIỆN PHỤC VỤ MỤC ĐÍCH SINH HOẠT
                 căn cứ 16/2023/TT-BCT đã hết hiệu lực, thay bởi 12/2026/TT-BCT
  hopdong-353    HỢP ĐỒNG THUÊ ĐẤT
                 căn cứ 102/2024/NĐ-CP bị 151/2025/NĐ-CP thay thế
  hopdong-499    VĂN BẢN CHUYỂN NHƯỢNG HỢP ĐỒNG MUA BÁN NHÀ Ở THƯƠNG MẠI
                 ba căn cứ: một chưa có trong kho, hai đã hết hiệu lực

Ca thứ ba là ca khó nhất và là lý do "thứ tệ nhất thắng": biểu mẫu có một căn cứ
sống và một căn cứ chết là biểu mẫu ĐÁNG NGỜ, không phải biểu mẫu tốt.
"""
import json
from datetime import date

import pytest

from src.forms.effectivity import (
    CAN_KIEM_TRA,
    CANH_BAO,
    CO_BAN_THAY_THE,
    CON_HIEU_LUC,
    HET_HIEU_LUC,
    KHONG_RO,
    NHAN,
    suy_hieu_luc,
    tinh_hieu_luc,
)
from src.legal import effectivity as eff_vb
from src.storage.models import Document, DocumentReference, LegalForm, LegalFormRef

MOC = date(2026, 8, 18)


@pytest.fixture
def kho(master_session):
    """Xưởng dựng văn bản, quan hệ và biểu mẫu."""

    class Xuong:
        def van_ban(self, doc_num, eff_state, doc_key=None):
            d = Document(doc_num=doc_num, doc_key=doc_key or f"{doc_num}::x",
                         title=f"VB {doc_num}", eff_state=eff_state,
                         eff_status=eff_vb.label(eff_state))
            master_session.add(d)
            master_session.commit()
            return d

        def quan_he(self, nguon: Document, so_hieu_dich: str, loai: str):
            master_session.add(DocumentReference(
                source_doc_id=nguon.id, target_doc_num=so_hieu_dich,
                relation_type=loai))
            master_session.commit()

        def bieu_mau(self, form_key, can_cu: list[tuple[str, str | None]]):
            """`can_cu` = [(doc_num, doc_key hoặc None nếu chưa có trong kho)]."""
            master_session.add(LegalForm(
                form_key=form_key, source="hopdong",
                external_id=form_key.split("-")[-1], title=f"MẪU {form_key}",
                crawl_status="OK", is_business=True))
            for doc_num, doc_key in can_cu:
                master_session.add(LegalFormRef(
                    form_key=form_key, doc_num=doc_num, doc_key=doc_key,
                    source="trong_ruot_mau"))
            master_session.commit()

    return Xuong()


class TestSuyTuCanCu:
    def test_can_cu_con_hieu_luc_thi_mau_con_hieu_luc(self, master_session, kho):
        kho.van_ban("55/2015/TTLT-BTC-BKHCN", eff_vb.CON_HIEU_LUC,
                    doc_key="tt55::btc")
        kho.bieu_mau("hopdong-1", [("55/2015/TTLT-BTC-BKHCN", "tt55::btc")])
        kq = suy_hieu_luc(master_session, "hopdong-1", MOC)
        assert kq.state == CON_HIEU_LUC
        assert not kq.can_canh_bao
        assert kq.as_of == MOC

    def test_can_cu_het_hieu_luc_thi_mau_het_hieu_luc(self, master_session, kho):
        """Ca thật hopdong-18138: hợp đồng mua bán điện trên Thông tư đã chết."""
        kho.van_ban("16/2023/TT-BCT", eff_vb.HET_TOAN_BO, doc_key="tt16::bct")
        moi = kho.van_ban("12/2026/TT-BCT", eff_vb.CON_HIEU_LUC, doc_key="tt12::bct")
        kho.quan_he(moi, "16/2023/TT-BCT", "Thay thế")
        kho.bieu_mau("hopdong-18138", [("16/2023/TT-BCT", "tt16::bct")])

        kq = suy_hieu_luc(master_session, "hopdong-18138", MOC)
        assert kq.state == HET_HIEU_LUC
        assert kq.can_canh_bao
        assert "12/2026/TT-BCT" in kq.thay_the_boi

    def test_can_cu_bi_thay_the_du_van_con_hieu_luc(self, master_session, kho):
        """Ca thật hopdong-353: 102/2024/NĐ-CP bị 151/2025/NĐ-CP thay thế.

        Tách riêng khỏi `het_hieu_luc` vì nó mang thông tin HÀNH ĐỘNG ĐƯỢC — số
        hiệu văn bản mới, tức chỗ để đi tìm biểu mẫu thay thế.
        """
        kho.van_ban("102/2024/NĐ-CP", eff_vb.CON_HIEU_LUC, doc_key="nd102::cp")
        moi = kho.van_ban("151/2025/NĐ-CP", eff_vb.CON_HIEU_LUC, doc_key="nd151::cp")
        kho.quan_he(moi, "102/2024/NĐ-CP", "Thay thế")
        kho.bieu_mau("hopdong-353", [("102/2024/NĐ-CP", "nd102::cp")])

        kq = suy_hieu_luc(master_session, "hopdong-353", MOC)
        assert kq.state == CO_BAN_THAY_THE
        assert kq.thay_the_boi == ["151/2025/NĐ-CP"]
        assert "tìm biểu mẫu mới" in kq.ghi_chu

    def test_can_cu_bi_sua_doi_thi_can_kiem_tra(self, master_session, kho):
        kho.van_ban("96/2024/NĐ-CP", eff_vb.CON_HIEU_LUC, doc_key="nd96::cp")
        sua = kho.van_ban("10/2026/NĐ-CP", eff_vb.CON_HIEU_LUC, doc_key="nd10::cp")
        kho.quan_he(sua, "96/2024/NĐ-CP", "Sửa đổi, bổ sung")
        kho.bieu_mau("hopdong-2", [("96/2024/NĐ-CP", "nd96::cp")])

        kq = suy_hieu_luc(master_session, "hopdong-2", MOC)
        assert kq.state == CAN_KIEM_TRA
        assert "10/2026/NĐ-CP" in kq.ghi_chu

    def test_can_cu_het_mot_phan_thi_can_kiem_tra(self, master_session, kho):
        kho.van_ban("1/2020/NĐ-CP", eff_vb.HET_MOT_PHAN, doc_key="nd1::cp")
        kho.bieu_mau("hopdong-3", [("1/2020/NĐ-CP", "nd1::cp")])
        assert suy_hieu_luc(master_session, "hopdong-3", MOC).state == CAN_KIEM_TRA


class TestKhongDoanBua:
    def test_can_cu_chua_co_trong_kho_thi_khong_ro_chu_khong_con_hieu_luc(
            self, master_session, kho):
        """Đo trên kho thật: 189/219 mẫu rơi vào đây vì kho mới có 4.467 văn bản.

        Mặc định "còn hiệu lực" ở đây là bịa dữ kiện pháp lý cho 86% kho — đúng
        thứ mà src/legal/effectivity.py đặt ra nguyên tắc để tránh.
        """
        kho.bieu_mau("hopdong-4", [("187/2026/NĐ-CP", None)])
        kq = suy_hieu_luc(master_session, "hopdong-4", MOC)
        assert kq.state == KHONG_RO
        assert kq.can_canh_bao
        assert "chưa có trong kho" in kq.ghi_chu

    def test_khong_co_can_cu_thi_khong_ro(self, master_session, kho):
        kho.bieu_mau("hopdong-5", [])
        kq = suy_hieu_luc(master_session, "hopdong-5", MOC)
        assert kq.state == KHONG_RO
        assert "không ghi căn cứ" in kq.ghi_chu

    def test_van_ban_trong_kho_nhung_chua_ro_hieu_luc(self, master_session, kho):
        kho.van_ban("9/2019/TT-X", eff_vb.KHONG_RO, doc_key="tt9::x")
        kho.bieu_mau("hopdong-6", [("9/2019/TT-X", "tt9::x")])
        assert suy_hieu_luc(master_session, "hopdong-6", MOC).state == KHONG_RO


class TestThuTeNhatThang:
    def test_mot_can_cu_song_mot_can_cu_chet_thi_lay_cai_chet(
            self, master_session, kho):
        """Ca thật hopdong-499. Biểu mẫu có căn cứ chết là biểu mẫu ĐÁNG NGỜ.

        Lấy cái sống sẽ dán nhãn "còn hiệu lực" lên một tờ giấy mà một nửa cơ sở
        pháp lý của nó đã mất — sai theo hướng nguy hiểm nhất.
        """
        kho.van_ban("65/2014/QH13", eff_vb.HET_TOAN_BO, doc_key="l65::qh")
        kho.van_ban("55/2015/TTLT", eff_vb.CON_HIEU_LUC, doc_key="tt55::x")
        kho.bieu_mau("hopdong-499", [
            ("19/2016/TT-BXD", None),              # chưa có trong kho
            ("65/2014/QH13", "l65::qh"),           # đã chết
            ("55/2015/TTLT", "tt55::x"),           # còn sống
        ])
        kq = suy_hieu_luc(master_session, "hopdong-499", MOC)
        assert kq.state == HET_HIEU_LUC

    def test_ghi_chu_giu_TOAN_BO_ly_do_khong_chi_ly_do_thang(
            self, master_session, kho):
        """Người đọc cần thấy cả ba căn cứ để tự quyết, không chỉ cái tệ nhất."""
        kho.van_ban("65/2014/QH13", eff_vb.HET_TOAN_BO, doc_key="l65::qh")
        kho.van_ban("55/2015/TTLT", eff_vb.CON_HIEU_LUC, doc_key="tt55::x")
        kho.bieu_mau("hopdong-499", [
            ("19/2016/TT-BXD", None),
            ("65/2014/QH13", "l65::qh"),
            ("55/2015/TTLT", "tt55::x"),
        ])
        gc = suy_hieu_luc(master_session, "hopdong-499", MOC).ghi_chu
        assert "19/2016/TT-BXD" in gc
        assert "65/2014/QH13" in gc
        assert "55/2015/TTLT" in gc

    def test_khong_ro_thang_con_hieu_luc(self, master_session, kho):
        """Một căn cứ chưa kiểm được thì KHÔNG được khẳng định cả mẫu còn hiệu lực."""
        kho.van_ban("55/2015/TTLT", eff_vb.CON_HIEU_LUC, doc_key="tt55::x")
        kho.bieu_mau("hopdong-7", [("55/2015/TTLT", "tt55::x"),
                                   ("999/2099/TT-XX", None)])
        assert suy_hieu_luc(master_session, "hopdong-7", MOC).state == KHONG_RO


class TestGhiXuongDB:
    def test_luu_ca_moc_tinh(self, master_session, kho):
        """Cờ không kèm mốc là lời nói dối kể từ hôm sau — cùng lý do với
        documents.eff_state_as_of.
        """
        kho.van_ban("16/2023/TT-BCT", eff_vb.HET_TOAN_BO, doc_key="tt16::bct")
        kho.bieu_mau("hopdong-8", [("16/2023/TT-BCT", "tt16::bct")])
        tinh_hieu_luc(master_session, as_of=MOC)
        f = master_session.query(LegalForm).one()
        assert f.eff_state == HET_HIEU_LUC
        assert f.eff_state_as_of == MOC
        assert f.eff_note

    def test_buoc_dang_lai_trang_cong_khai(self, master_session, kho):
        """Cờ hiệu lực nằm TRÊN trang. Đổi cờ mà không đăng lại là để một khẳng
        định sai nằm trên mạng dưới URL trông như chính thức.
        """
        kho.van_ban("16/2023/TT-BCT", eff_vb.HET_TOAN_BO, doc_key="tt16::bct")
        kho.bieu_mau("hopdong-9", [("16/2023/TT-BCT", "tt16::bct")])
        f = master_session.query(LegalForm).one()
        f.published_hash = "da-dang-roi"
        master_session.commit()

        tinh_hieu_luc(master_session, as_of=MOC)
        assert master_session.query(LegalForm).one().published_hash is None

    def test_luu_so_hieu_thay_the_dang_json(self, master_session, kho):
        kho.van_ban("102/2024/NĐ-CP", eff_vb.CON_HIEU_LUC, doc_key="nd102::cp")
        moi = kho.van_ban("151/2025/NĐ-CP", eff_vb.CON_HIEU_LUC, doc_key="nd151::cp")
        kho.quan_he(moi, "102/2024/NĐ-CP", "Thay thế")
        kho.bieu_mau("hopdong-10", [("102/2024/NĐ-CP", "nd102::cp")])
        tinh_hieu_luc(master_session, as_of=MOC)
        f = master_session.query(LegalForm).one()
        assert json.loads(f.eff_replaced_by) == ["151/2025/NĐ-CP"]

    def test_dem_theo_trang_thai(self, master_session, kho):
        kho.van_ban("16/2023/TT-BCT", eff_vb.HET_TOAN_BO, doc_key="tt16::bct")
        kho.bieu_mau("hopdong-11", [("16/2023/TT-BCT", "tt16::bct")])
        kho.bieu_mau("hopdong-12", [("999/2099/TT-XX", None)])
        dem = tinh_hieu_luc(master_session, as_of=MOC)
        assert dem == {HET_HIEU_LUC: 1, KHONG_RO: 1}


class TestTapDong:
    def test_moi_trang_thai_deu_co_nhan_tieng_viet(self):
        for ma in (CON_HIEU_LUC, CO_BAN_THAY_THE, CAN_KIEM_TRA, HET_HIEU_LUC,
                   KHONG_RO):
            assert ma in NHAN and NHAN[ma]

    def test_chi_con_hieu_luc_la_khong_canh_bao(self):
        """Mọi trạng thái khác đều phải cảnh báo — kể cả "chưa xác minh được"."""
        assert CON_HIEU_LUC not in CANH_BAO
        assert CANH_BAO == {CO_BAN_THAY_THE, CAN_KIEM_TRA, HET_HIEU_LUC, KHONG_RO}
