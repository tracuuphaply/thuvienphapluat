"""Bộ dữ liệu cho trang trợ lý.

VÌ SAO CÓ BỘ RIÊNG. Đo ngày 19/08/2026 trên chính kho này: `contentIndex.json` của
Quartz là 17,42 MB thô (gzip 1,72 MB) cho 4.308 trang, trong đó 77% là trường
`content` — toàn văn từng trang, chỉ phục vụ tìm kiếm. Bộ này 1,50 MB thô
(gzip 0,28 MB) và không có cú `JSON.parse` 17 MB chặn luồng chính.

Ba chốt quan trọng nhất ở đây:
  - đồ thị dùng CHỈ SỐ, không dùng slug (slug làm phình gấp ~5 lần)
  - cạnh trỏ tới văn bản chưa có trang thì BỎ, không giữ nửa cạnh
  - KHÔNG có nút tag: trong sơ đồ Quartz, 17 nút tag sinh 12.600 cạnh (22% toàn
    bộ) và riêng "van-ban-ngu-canh" có 3.255 cạnh
"""
import json
from datetime import date

import pytest

from src.publish.assistant_export import TEN_FILE, chep_ung_dung, xuat_du_lieu
from src.storage.models import Document, DocumentReference, LegalForm, LegalFormRef


@pytest.fixture
def kho(master_session):
    def vb(doc_num, slug, **kw):
        d = Document(
            doc_num=doc_num, doc_key=f"{doc_num}::x", public_slug=slug,
            title=kw.get("title", f"Văn bản {doc_num}"),
            doc_type=kw.get("doc_type", "Nghị định"),
            is_vbqppl=kw.get("is_vbqppl", True),
            tvpl_field_code=kw.get("field", 1),
            eff_state=kw.get("eff", "con_hieu_luc"),
            hierarchy_level=kw.get("cap", 5),
            territorial_scope=kw.get("scope", "trung_uong"),
            issue_date=kw.get("ngay", date(2024, 7, 24)),
        )
        master_session.add(d)
        master_session.commit()
        return d

    def canh(nguon, so_hieu_dich, loai="Thay thế"):
        master_session.add(DocumentReference(
            source_doc_id=nguon.id, target_doc_num=so_hieu_dich, relation_type=loai))
        master_session.commit()

    def bm(form_key, slug, can_cu=(), **kw):
        f = LegalForm(
            form_key=form_key, source="hopdong", external_id=form_key.split("-")[-1],
            title=kw.get("title", f"MẪU {form_key}"), public_slug=slug,
            is_business=kw.get("kd", True), crawl_status="OK",
            nghiep_vu=json.dumps(kw.get("nv", ["hop_dong"])),
            eff_state=kw.get("eff", "con_hieu_luc"),
            docx_path=kw.get("docx"), pdf_path=kw.get("pdf"),
            delisted_at=kw.get("go"),
        )
        master_session.add(f)
        for n in can_cu:
            master_session.add(LegalFormRef(form_key=form_key, doc_num=n,
                                            source="truong_can_cu"))
        master_session.commit()
        return f

    return type("Kho", (), {"vb": staticmethod(vb), "canh": staticmethod(canh),
                            "bm": staticmethod(bm)})


def doc_goi(master_session, tmp_path):
    xuat_du_lieu(master_session, tmp_path)
    return json.loads((tmp_path / TEN_FILE).read_text(encoding="utf-8"))


class TestVanBan:
    def test_chi_lay_vbqppl_da_co_slug(self, master_session, kho, tmp_path):
        kho.vb("1/2024/NĐ-CP", "1-2024-ndd-cp")
        kho.vb("2/2024/CV", None, is_vbqppl=True)          # chưa có slug
        kho.vb("3/2024/TB", "3-2024-tb", is_vbqppl=False)  # không phải QPPL
        g = doc_goi(master_session, tmp_path)
        assert [v["n"] for v in g["van_ban"]] == ["1/2024/NĐ-CP"]

    def test_du_truong_can_thiet_de_loc_va_hien(self, master_session, kho, tmp_path):
        kho.vb("96/2024/NĐ-CP", "96-2024-ndd-cp", field=12, eff="het_mot_phan", cap=5)
        (v,) = doc_goi(master_session, tmp_path)["van_ban"]
        assert v["n"] == "96/2024/NĐ-CP" and v["f"] == 12
        assert v["e"] == "het_mot_phan" and v["c"] == 5 and v["p"] == "tw"

    def test_khong_ship_toan_van(self, master_session, kho, tmp_path):
        """Đây là toàn bộ lý do bộ này nhỏ hơn contentIndex ~11 lần."""
        kho.vb("1/2024/NĐ-CP", "1-2024-ndd-cp")
        (v,) = doc_goi(master_session, tmp_path)["van_ban"]
        assert "content" not in v and "noi_dung" not in v


class TestDoThi:
    def test_canh_dung_chi_so_khong_dung_slug(self, master_session, kho, tmp_path):
        a = kho.vb("1/2024/NĐ-CP", "1-2024-ndd-cp")
        kho.vb("2/2020/NĐ-CP", "2-2020-ndd-cp")
        kho.canh(a, "2/2020/NĐ-CP")
        g = doc_goi(master_session, tmp_path)
        assert g["do_thi"]["canh"] == [[0, 1, 0]]
        assert g["do_thi"]["quan_he"] == ["Thay thế"]

    def test_bo_canh_tro_toi_van_ban_chua_co_trang(self, master_session, kho, tmp_path):
        """Cạnh treo lơ lửng không vẽ được và cũng không nói lên điều gì."""
        a = kho.vb("1/2024/NĐ-CP", "1-2024-ndd-cp")
        kho.canh(a, "999/2099/KHONG-CO")
        assert doc_goi(master_session, tmp_path)["do_thi"]["canh"] == []

    def test_khong_co_nut_tag(self, master_session, kho, tmp_path):
        """Trong sơ đồ Quartz, 17 nút tag sinh 12.600 cạnh — 22% toàn bộ."""
        kho.vb("1/2024/NĐ-CP", "1-2024-ndd-cp")
        g = doc_goi(master_session, tmp_path)
        assert "tag" not in json.dumps(g["do_thi"])

    def test_khu_canh_trung_va_bo_tu_noi_chinh_no(self, master_session, kho, tmp_path):
        a = kho.vb("1/2024/NĐ-CP", "1-2024-ndd-cp")
        kho.vb("2/2020/NĐ-CP", "2-2020-ndd-cp")
        kho.canh(a, "2/2020/NĐ-CP")
        kho.canh(a, "2/2020/NĐ-CP")          # trùng
        kho.canh(a, "1/2024/NĐ-CP")          # tự nối chính nó
        assert doc_goi(master_session, tmp_path)["do_thi"]["canh"] == [[0, 1, 0]]


class TestBieuMau:
    def test_chi_lay_mau_kinh_doanh_da_dang(self, master_session, kho, tmp_path):
        kho.bm("hopdong-1", "bm-hopdong-1")
        kho.bm("hopdong-2", None)                    # chưa đăng
        kho.bm("bieumau-3", "bm-bieumau-3", kd=False)  # không phải mẫu doanh nghiệp
        g = doc_goi(master_session, tmp_path)
        assert [b["k"] for b in g["bieu_mau"]] == ["hopdong-1"]

    def test_kem_ten_file_tai_ve_va_can_cu(self, master_session, kho, tmp_path):
        kho.bm("hopdong-1", "bm-hopdong-1", can_cu=["96/2024/NĐ-CP"],
               docx="/x/y/hopdong-1.docx", pdf="/x/y/hopdong-1.pdf")
        (b,) = doc_goi(master_session, tmp_path)["bieu_mau"]
        assert b["w"] == "hopdong-1.docx" and b["p"] == "hopdong-1.pdf"
        assert b["c"] == ["96/2024/NĐ-CP"]

    def test_co_co_da_bi_go(self, master_session, kho, tmp_path):
        kho.bm("hopdong-1", "bm-hopdong-1", go=date(2026, 8, 19))
        assert doc_goi(master_session, tmp_path)["bieu_mau"][0]["g"] == 1


class TestGoiDuLieu:
    def test_co_bang_giai_nghia_truong_viet_tat(self, master_session, tmp_path):
        """Tên trường một chữ cái tiết kiệm ~50 KB, nhưng không được thành bí ẩn."""
        g = doc_goi(master_session, tmp_path)
        assert g["_truong"]["van_ban"]["n"] == "số hiệu"
        assert "chỉ số" in g["_truong"]["do_thi"]["canh"]

    def test_co_bang_tra_nhan_de_khong_hardcode_o_frontend(self, master_session, tmp_path):
        g = doc_goi(master_session, tmp_path)
        assert g["hieu_luc_vb"]["con_hieu_luc"] == "Còn hiệu lực"
        assert g["hieu_luc_bm"]["co_ban_thay_the"]
        assert len(g["linh_vuc"]) == 27
        assert len(g["nghiep_vu"]) == 12

    def test_json_khong_co_khoang_trang_thua(self, master_session, kho, tmp_path):
        """Với 23.801 cạnh thì mỗi khoảng trắng sau dấu phẩy là thêm ~90 KB."""
        kho.vb("1/2024/NĐ-CP", "1-2024-ndd-cp")
        xuat_du_lieu(master_session, tmp_path)
        raw = (tmp_path / TEN_FILE).read_text(encoding="utf-8")
        assert '", "' not in raw and '": "' not in raw

    def test_thong_ke_khop_du_lieu(self, master_session, kho, tmp_path):
        a = kho.vb("1/2024/NĐ-CP", "1-2024-ndd-cp")
        kho.vb("2/2020/NĐ-CP", "2-2020-ndd-cp")
        kho.canh(a, "2/2020/NĐ-CP")
        kho.bm("hopdong-1", "bm-hopdong-1")
        tk = xuat_du_lieu(master_session, tmp_path)
        assert tk.van_ban == 2 and tk.bieu_mau == 1 and tk.canh == 1
        assert tk.kich_thuoc_kb >= 0


def test_chep_ung_dung_ra_index_html(tmp_path):
    p = chep_ung_dung(tmp_path)
    assert p.name == "index.html"
    noi = p.read_text(encoding="utf-8")
    assert "du-lieu.json" in noi          # app phải trỏ đúng tên file dữ liệu
    assert "<!doctype html>" in noi.lower()
