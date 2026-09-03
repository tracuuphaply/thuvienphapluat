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
            gdrive_fulltext_link=kw.get("drive"),
            agency_name=kw.get("cq"),
            eff_from=kw.get("hl_tu"),
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
            delisted_at=kw.get("go"), gdrive_docx_link=kw.get("drive"),
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

    def test_can_cu_khop_duoc_voi_so_hieu_van_ban_da_xuat(
            self, master_session, kho, tmp_path):
        """`c` của biểu mẫu phải nối được vào `n` của văn bản, không chỉ có mặt.

        Trang trợ lý rọi biểu mẫu lên sơ đồ bằng cách tra SỐ HIỆU CĂN CỨ trong
        bảng số hiệu → văn bản. Biểu mẫu không phải nút trong đồ thị (đồ thị chỉ
        gồm văn bản), nên đây là chỗ neo duy nhất của nó.

        Hai bên phải cùng một dạng chuỗi. Lệch đi một khoảng trắng hay một cách
        viết hoa thì phép tra ra rỗng, và triệu chứng là trỏ vào biểu mẫu mà sơ
        đồ đứng yên — không lỗi, không cảnh báo, chỉ là không có gì xảy ra. Test
        `test_kem_ten_file_tai_ve_va_can_cu` không bắt được ca này: nó soi `c`
        một mình, không đối chiếu với phía văn bản.
        """
        kho.vb("96/2024/NĐ-CP", "vb-96-2024")
        kho.bm("hopdong-1", "bm-hopdong-1", can_cu=["96/2024/NĐ-CP"])
        g = doc_goi(master_session, tmp_path)
        so_hieu = {v["n"] for v in g["van_ban"]}
        (b,) = g["bieu_mau"]
        assert b["c"], "biểu mẫu mất căn cứ thì không rọi được lên sơ đồ"
        assert set(b["c"]) <= so_hieu, (
            f"căn cứ {b['c']} không khớp số hiệu nào đã xuất: {sorted(so_hieu)}")

    def test_co_co_da_bi_go(self, master_session, kho, tmp_path):
        kho.bm("hopdong-1", "bm-hopdong-1", go=date(2026, 8, 19))
        assert doc_goi(master_session, tmp_path)["bieu_mau"][0]["x"] == 1

    def test_co_bi_go_va_id_drive_khong_dung_chung_khoa(self, master_session, kho,
                                                        tmp_path):
        """Mẫu vừa bị gỡ vừa có bản Drive phải giữ được CẢ HAI thông tin.

        Bản trước đặt cả hai vào khoá "g", nên dòng gán ID Drive ghi đè cờ bị gỡ
        và cờ đó biến mất. Lúc phát hiện chưa hỏng dữ liệu — 0 mẫu bị gỡ — nhưng
        cả 2.467 mẫu nay đều có link Drive, nên mẫu đầu tiên bị nguồn gỡ sẽ mất
        cờ mà không ai thấy. Bảng mô tả trường cũng khai "g" hai lần và Python
        chỉ giữ cái sau, nên đọc tài liệu cũng không phát hiện được.
        """
        kho.bm("hopdong-1", "bm-hopdong-1", go=date(2026, 8, 19),
               drive="https://drive.google.com/file/d/1RAMQ50O1equNkCM91tL/view")
        bm = doc_goi(master_session, tmp_path)["bieu_mau"][0]
        assert bm["x"] == 1, "cờ bị gỡ phải còn"
        assert bm["g"] == "1RAMQ50O1equNkCM91tL", "ID Drive phải còn"

    def test_co_doi_tuong_de_ben_doc_dung_bo_loc(self, master_session, kho, tmp_path):
        """Không có cờ đối tượng thì phía giao diện không dựng nổi bộ lọc
        Doanh nghiệp / Cá nhân, dù kho đã phân loại đủ."""
        kho.bm("hopdong-1", "bm-hopdong-1")
        assert doc_goi(master_session, tmp_path)["bieu_mau"][0].get("b") == 1
    def test_khong_go_thi_khong_co_co(self, master_session, kho, tmp_path):
        """Mẫu bình thường KHÔNG được mang cờ đã-gỡ.

        Ca này trước đây không có, và chính khoảng trống đó để lọt lỗi ở
        test kế bên: cờ đã-gỡ và ID Drive từng cùng ghi vào khoá `g`.
        """
        kho.bm("hopdong-1", "bm-hopdong-1",
               drive="https://drive.google.com/file/d/1AbC_dEf-23456789/view")
        assert "x" not in doc_goi(master_session, tmp_path)["bieu_mau"][0]

    def test_co_da_go_khong_bi_ID_drive_de_mat(self, master_session, kho, tmp_path):
        """Mẫu vừa bị gỡ vừa có bản Drive phải giữ được CẢ HAI dữ kiện.

        Lỗi đã xảy ra thật: `delisted_at` ghi vào `g`, rồi `gdrive_docx_link`
        ghi đè cũng vào `g`. Vì 653/653 mẫu đều có link Drive nên `g` luôn
        truthy, và trang trợ lý dán nhãn đỏ "Nguồn đã gỡ — không nên dùng để
        nộp" lên TOÀN BỘ kho biểu mẫu, đồng thời mất hẳn khả năng nhận ra mẫu
        bị gỡ thật. Hai dữ kiện độc lập thì phải nằm ở hai khoá.
        """
        kho.bm("hopdong-1", "bm-hopdong-1", go=date(2026, 8, 19),
               drive="https://drive.google.com/file/d/1AbC_dEf-23456789/view")
        (b,) = doc_goi(master_session, tmp_path)["bieu_mau"]
        assert b["x"] == 1
        assert b["g"] == "1AbC_dEf-23456789"


class TestCoQuanVaNgayHieuLuc:
    """Hai dữ kiện trang Quartz vẫn hiện mà trang trợ lý thì không.

    Với người tra cứu pháp luật, "ai ban hành" là dữ kiện đọc đầu tiên — thiếu nó
    thì popup trợ lý nghèo hơn hẳn trang tĩnh cùng nói về một văn bản.
    """

    def test_co_thi_ship(self, master_session, kho, tmp_path):
        kho.vb("1/2024/NĐ-CP", "1-2024-ndd-cp",
               cq="Chính phủ", hl_tu=date(2024, 9, 1))
        (v,) = doc_goi(master_session, tmp_path)["van_ban"]
        assert v["a"] == "Chính phủ"
        assert v["h"] == "2024-09-01"

    def test_vang_thi_bo_han_khoa(self, master_session, kho, tmp_path):
        """Không có thì BỎ khoá, không ship chuỗi rỗng — 4.201 chuỗi rỗng là rác."""
        kho.vb("1/2024/NĐ-CP", "1-2024-ndd-cp")
        (v,) = doc_goi(master_session, tmp_path)["van_ban"]
        assert "a" not in v and "h" not in v


class TestLienKetDrive:
    """Bản toàn văn trên Drive là thứ DUY NHẤT trong bộ này mở ra nội dung thật.

    Hai địa chỉ nguồn còn lại đều là ngõ cụt với người đọc: cổng Bộ Tư pháp trả
    về XML thô, Thư viện Pháp luật chặn truy cập tự động. Đo ngày 19/08/2026:
    3.883/4.201 văn bản đã có bản Drive.
    """

    def test_ship_ID_chu_khong_ship_URL(self, master_session, kho, tmp_path):
        """Tiền tố URL dài 32 ký tự, lặp y hệt ở 3.883 văn bản — ~124 KB rỗng."""
        kho.vb("1/2024/NĐ-CP", "1-2024-ndd-cp",
               drive="https://drive.google.com/file/d/1AbC_dEf-23456789/view?usp=drivesdk")
        (v,) = doc_goi(master_session, tmp_path)["van_ban"]
        assert v["g"] == "1AbC_dEf-23456789"

    def test_van_ban_chua_co_ban_drive_thi_vang_truong(self, master_session, kho, tmp_path):
        """Vắng trường, KHÔNG phải chuỗi rỗng: bên đọc phân biệt bằng `if (v.g)`,
        mà chuỗi rỗng thì cũng falsy nhưng vẫn tốn 6 byte × 318 văn bản."""
        kho.vb("1/2024/NĐ-CP", "1-2024-ndd-cp")
        (v,) = doc_goi(master_session, tmp_path)["van_ban"]
        assert "g" not in v

    def test_bieu_mau_cung_ship_ID(self, master_session, kho, tmp_path):
        kho.bm("hopdong-1", "bm-hopdong-1",
               drive="https://drive.google.com/file/d/1XyZ_uvw-987654321/view")
        (b,) = doc_goi(master_session, tmp_path)["bieu_mau"]
        assert b["g"] == "1XyZ_uvw-987654321"

    def test_url_la_thu_khong_nhan_ra_thi_bo_qua(self, master_session, kho, tmp_path):
        """Provider đổi dạng URL là chuyện xảy ra. Ship ID sai còn tệ hơn không
        ship: nó dựng ra một link chết mà trông y như link sống."""
        kho.vb("1/2024/NĐ-CP", "1-2024-ndd-cp", drive="https://example.com/khong-phai-drive")
        (v,) = doc_goi(master_session, tmp_path)["van_ban"]
        assert v.get("g", "") == ""

    def test_bang_giai_nghia_noi_ro_cach_ghep_URL(self, master_session, tmp_path):
        """Ship ID tiết kiệm chỗ nhưng chỉ dùng được nếu bên đọc biết ghép."""
        g = doc_goi(master_session, tmp_path)
        assert "drive.google.com/file/d/" in g["_truong"]["van_ban"]["g"]
        assert "drive.google.com/file/d/" in g["_truong"]["bieu_mau"]["g"]


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
