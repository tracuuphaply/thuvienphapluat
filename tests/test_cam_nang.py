"""
Pipeline sinh thân bài Cẩm nang — bốn chốt chặn cho bốn lỗi đã làm hỏng 653 bài.

Bốn chốt, mỗi cái một lớp test dưới đây:
  1. Cổng tiêu đề — tiêu đề lấy từ ruột tờ mẫu không được lọt sang bên xuất bản.
  2. Hợp đồng §1 — bản ghi giao đi phải ĐÚNG bốn trường, không thừa, không thiếu.
  3. Cổng trích dẫn — thiếu cờ cũng là TRƯỢT, vì thiếu cờ nghĩa là cổng chưa chạy.
  4. Vân tay nguồn — căn cứ hết hiệu lực phải kích hoạt sinh lại dù ruột mẫu y nguyên.
"""
import json
import sqlite3

import pytest

from src.camnang import cong
from src.camnang.kho import (
    BieuMau, chon_ung_vien, doc_kho, ruot_mau_tu_trang,
)
from src.camnang.sinh import SinhThatBai, dung_ngu_canh, sinh_bai
from src.camnang.trang_thai import SoTrangThai
from src.rag.reports.llm import LLMResult
from src.rag.reports.prompts import load_cam_nang_prompt

RUOT_MAU_MAU = (
    "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\n"
    "Độc lập - Tự do - Hạnh phúc\n\n"
    "HỢP ĐỒNG LÀM GIA SƯ\n\n"
    "Hôm nay, ngày ... tháng ... năm ..., tại ..., chúng tôi gồm:\n"
    "BÊN A (Bên thuê gia sư): ...\n"
    "Địa chỉ: ...   Số CCCD: ...\n"
    "BÊN B (Bên nhận dạy): ...\n"
    "Điều 1. Nội dung công việc\n"
    "Bên B nhận dạy môn ... cho ... buổi/tuần, mỗi buổi ... giờ.\n"
    "Điều 2. Thù lao và phương thức thanh toán\n"
    "Mức thù lao ... đồng/buổi, thanh toán vào ngày ... hàng tháng.\n"
    "Điều 3. Quyền và nghĩa vụ của các bên\n"
    "Điều 4. Chấm dứt hợp đồng\n"
    "Điều 5. Điều khoản thi hành\n"
    "Hợp đồng lập thành 02 bản, mỗi bên giữ 01 bản có giá trị như nhau.\n"
) * 3


def _trang_bieu_mau(ruot: str = RUOT_MAU_MAU) -> str:
    """Trang .md đúng khuôn PAGE_TEMPLATE của src/publish/form_exporter.py."""
    return (
        "---\ntitle: \"Hợp đồng làm gia sư\"\nform_key: \"hopdong-101\"\n---\n\n"
        "# HỢP ĐỒNG LÀM GIA SƯ\n\n## Tải về\n\n[.docx](x.docx)\n\n"
        "## Căn cứ pháp lý\n\n- 91/2015/QH13\n\n"
        f"## Nội dung biểu mẫu\n\n{ruot}\n\n"
        "## Nguồn\n\n<https://thuvienphapluat.vn/…>\n"
    )


@pytest.fixture
def vault(tmp_path):
    """Checkout legal-vault-public tối giản: chỉ mục + hai trang biểu mẫu."""
    goi = {
        "tao_luc": "2026-08-24",
        "nghiep_vu": [{"ma": "hop_dong", "ten": "Hợp đồng"}],
        "hieu_luc_bm": {"khong_ro": "Chưa xác minh", "con_hieu_luc": "Còn hiệu lực"},
        "van_ban": [
            {"s": "bo-luat-dan-su-91-2015-qh13", "n": "91/2015/QH13",
             "t": "Bộ luật Dân sự", "e": "con_hieu_luc", "g": "DRIVEID12345"},
            {"s": "nghi-dinh-301-2026-nd-cp", "n": "301/2026/NĐ-CP",
             "t": "Nghị định 301", "e": "con_hieu_luc"},
        ],
        "bieu_mau": [
            {"s": "bm-tvpl-101", "k": "hopdong-101", "t": "HỢP ĐỒNG LÀM GIA SƯ",
             "v": ["hop_dong"], "e": "con_hieu_luc", "c": ["91/2015/QH13"]},
            {"s": "bm-tvpl-102", "k": "hopdong-102", "t": "HỢP ĐỒNG MƯỢN TÀI SẢN",
             "v": ["hop_dong"], "e": "khong_ro", "c": []},
        ],
    }
    (tmp_path / "tro-ly").mkdir()
    (tmp_path / "tro-ly" / "du-lieu.json").write_text(
        json.dumps(goi, ensure_ascii=False), encoding="utf-8")
    bm_dir = tmp_path / "content" / "bieu-mau"
    bm_dir.mkdir(parents=True)
    (bm_dir / "bm-tvpl-101.md").write_text(_trang_bieu_mau(), encoding="utf-8")
    (bm_dir / "bm-tvpl-102.md").write_text(_trang_bieu_mau(), encoding="utf-8")
    return tmp_path


@pytest.fixture
def docs_db(tmp_path):
    """DB tạm cho cổng trích dẫn — chỉ có bảng documents."""
    path = tmp_path / "legal_docs.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE documents (doc_num TEXT)")
    conn.executemany("INSERT INTO documents (doc_num) VALUES (?)",
                     [("91/2015/QH13",), ("301/2026/NĐ-CP",)])
    conn.commit()
    conn.close()
    return path


def _llm_gia(tieu_de="Hợp đồng làm gia sư: 7 chỗ hở cần vá trước khi ký",
             mo_ta="Mẫu hợp đồng gia sư thiếu điều khoản gì.",
             than_bai="## Khi nào bạn cần dùng mẫu này\n\nTheo 91/2015/QH13, …",
             truncated=False):
    """Mô hình giả — test không được gọi mạng, và không được tốn tiền."""
    ds = []

    def goi(he_thong, nguoi_dung, model="", max_tokens=0):
        ds.append((he_thong, nguoi_dung))
        i = min(len(ds) - 1, len(tieu_de_ds) - 1) if isinstance(tieu_de, list) else 0
        td = tieu_de_ds[i] if isinstance(tieu_de, list) else tieu_de
        return LLMResult(
            text=json.dumps({"tieu_de": td, "mo_ta": mo_ta, "than_bai": than_bai},
                            ensure_ascii=False),
            truncated=truncated, model="test-model",
        )

    tieu_de_ds = tieu_de if isinstance(tieu_de, list) else [tieu_de]
    goi.loi_goi = ds
    return goi


class TestCongTieuDe:
    """Chốt 1 — tiêu đề mang dấu hiệu ruột tờ mẫu bị loại tại chỗ sinh."""

    @pytest.mark.parametrize("xau", [
        "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
        "CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM",   # HOÀ, biến thể dấu
        "CỘNG HÒA VIỆT NAM",                     # thiếu XÃ HỘI CHỦ NGHĨA
        "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM.",   # thừa dấu chấm cuối
        "CỘNG  HÒA   XÃ HỘI CHỦ NGHĨA  VIỆT NAM",     # thừa khoảng trắng
        "Độc lập - Tự do - Hạnh phúc",
        "Độc lập – Tự do",                       # gạch dài
        "Mẫu số 01-ĐK-TCT",
        "Phụ lục II ban hành kèm theo Thông tư",
        "Biểu mẫu số 3 về đăng ký kinh doanh",
        "Đơn vị: Công ty TNHH ABC",
        "Tên cơ quan/đơn vị chủ quản",
    ])
    def test_loai_dau_hieu_ruot_mau(self, xau):
        assert not cong.cong_tieu_de(xau)

    def test_bat_ca_dang_NFD(self):
        """NFD tách dấu ra ký tự riêng — chuỗi trông y hệt nhưng byte khác hẳn."""
        import unicodedata
        nfd = unicodedata.normalize("NFD", "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM")
        assert nfd != "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"   # đúng là khác byte
        assert not cong.cong_tieu_de(nfd)

    @pytest.mark.parametrize("tot", [
        "Hợp đồng làm gia sư: 7 chỗ hở cần vá trước khi ký",
        "Hợp đồng mượn tài sản: ai chịu rủi ro khi tài sản hỏng",
        "Đơn vị tính trong hợp đồng xây dựng ghi sai thì mất tiền ở đâu",
    ])
    def test_nhan_tieu_de_dung(self, tot):
        assert cong.cong_tieu_de(tot), cong.cong_tieu_de(tot).ly_do

    def test_don_vi_khong_bat_nham_tu_ghep(self):
        """'Đơn vị:' neo vào dấu hai chấm — 'đơn vị tính' là tiếng Việt bình thường.

        Bắt theo cụm "don vi" trần thì loại oan mọi tiêu đề có chữ "đơn vị", mà
        đó là chữ hay gặp trong hợp đồng.
        """
        assert cong.cong_tieu_de("Cách ghi đơn vị tính cho đúng trong hợp đồng")
        assert not cong.cong_tieu_de("Đơn vị: Công ty TNHH ABC")
        assert not cong.cong_tieu_de("Đơn vị  : Công ty TNHH ABC")

    def test_do_dai(self):
        assert not cong.cong_tieu_de("Hđ")
        assert not cong.cong_tieu_de("Hợp đồng " * 40)


class TestHopDong:
    """Chốt 2 — bản ghi giao đi phải đúng §1, không thừa khoá, không thiếu cờ."""

    def _ban_ghi(self, **ghi_de):
        goc = {
            "form_key": "hopdong-101",
            "tieu_de": "Hợp đồng làm gia sư: 7 chỗ hở cần vá trước khi ký",
            "mo_ta": "Mẫu hợp đồng gia sư thiếu gì.",
            "than_bai": "## Khi nào cần\n\nNội dung.",
            "citation_ok": True,
        }
        goc.update(ghi_de)
        return goc

    def test_ban_ghi_dung_thi_qua(self):
        assert cong.cong_hop_dong(self._ban_ghi())

    def test_thieu_form_key_bi_loai(self):
        assert not cong.cong_hop_dong(self._ban_ghi(form_key=""))

    def test_mo_ta_qua_dai_bi_loai(self):
        assert not cong.cong_hop_dong(self._ban_ghi(mo_ta="x" * 501))

    def test_than_bai_rong_bi_loai(self):
        assert not cong.cong_hop_dong(self._ban_ghi(than_bai="   "))

    def test_than_bai_qua_dai_bi_loai(self):
        """Trần thân bài giữ chỗ cho ruột mẫu + hộp hiệu lực trong trần 200k HTML."""
        assert not cong.cong_hop_dong(
            self._ban_ghi(than_bai="x" * (cong.THAN_BAI_MAX + 1)))

    @pytest.mark.parametrize("co", [False, None, "true", 1])
    def test_citation_ok_khong_phai_true_deu_bi_loai(self, co):
        """Chốt quan trọng nhất: THIẾU cờ cũng trượt, không chỉ `false`.

        Bản hợp đồng trước viết kiểu "chỉ loại khi === false" nên bài thiếu hẳn
        cờ lọt 100% — cổng bắt buộc thành ra tuỳ chọn.
        """
        assert not cong.cong_hop_dong(self._ban_ghi(citation_ok=co))

    def test_thieu_han_khoa_citation_ok_bi_loai(self):
        ban = self._ban_ghi()
        del ban["citation_ok"]
        assert not cong.cong_hop_dong(ban)

    def test_ban_ghi_khong_thua_khoa(self, vault, docs_db):
        """Bên xuất bản tự dựng slug/chủ đề/hộp hiệu lực — không sinh trùng."""
        kho = doc_kho(vault)
        u = chon_ung_vien(kho)[0]
        bai = sinh_bai(u, kho, tai_toan_van_ve=False, db_path=docs_db,
                       goi_llm=_llm_gia())
        assert set(bai.ban_ghi()) == {
            "form_key", "tieu_de", "mo_ta", "than_bai", "citation_ok"}


class TestCongTrichDan:
    """Chốt 3 — số hiệu bịa bị chặn, số hiệu có trong nguồn thì không."""

    def test_so_hieu_bia_lam_trach_cong(self, docs_db):
        nguon = cong.NguonTrichDan()
        dat, bao_cao = cong.cong_trich_dan(
            "Theo Nghị định 999/2099/NĐ-CP thì …", nguon, db_path=docs_db)
        assert not dat
        assert "999/2099/NĐ-CP" in bao_cao.missing

    def test_so_hieu_trong_kho_thi_qua(self, docs_db):
        dat, _ = cong.cong_trich_dan(
            "Theo 91/2015/QH13 …", cong.NguonTrichDan(), db_path=docs_db)
        assert dat

    def test_so_hieu_co_trong_nguon_thi_qua(self, docs_db):
        """Văn bản cũ bị bãi bỏ có thật trong toàn văn nguồn — không phải bịa."""
        nguon = cong.NguonTrichDan()
        nguon.them_van_ban("… thay thế Nghị định 18/2016/NĐ-CP …")
        dat, _ = cong.cong_trich_dan(
            "Mẫu này thay cho bản theo 18/2016/NĐ-CP.", nguon, db_path=docs_db)
        assert dat

    def test_nhom_bao_chung_dung_tu_nguon_chu_khong_tu_dau_ra(self, vault, docs_db):
        """Nhóm `extra_allowed` chỉ được dựng từ ruột mẫu + căn cứ + toàn văn.

        Dựng nó từ đầu ra mô hình thì mọi số bịa tự bảo chứng cho chính nó và
        cổng tự vô hiệu hoá.
        """
        kho = doc_kho(vault)
        u = chon_ung_vien(kho)[0]
        _, nguon = dung_ngu_canh(u, kho, tai_toan_van_ve=False)
        assert "91/2015/QH13" in nguon.so_hieu       # căn cứ trong kho
        assert "999/2099/NĐ-CP" not in nguon.so_hieu  # số mô hình có thể bịa

    def test_bai_co_so_hieu_bia_van_sinh_ra_nhung_citation_ok_false(
            self, vault, docs_db):
        kho = doc_kho(vault)
        u = chon_ung_vien(kho)[0]
        bai = sinh_bai(
            u, kho, tai_toan_van_ve=False, db_path=docs_db,
            goi_llm=_llm_gia(than_bai="## Mục\n\nTheo 999/2099/NĐ-CP …"),
        )
        assert bai.citation_ok is False
        assert not cong.cong_hop_dong(bai.ban_ghi())   # nên không được giao đi


class TestVanTayNguon:
    """Chốt 4 — chỉ sinh lại thứ đã đổi, nhưng phải sinh lại ĐỦ thứ đã đổi."""

    def _bm(self, **ghi_de) -> BieuMau:
        goc = dict(form_key="hopdong-101", slug="bm-101", tieu_de="HỢP ĐỒNG",
                   hieu_luc="con_hieu_luc", can_cu=["91/2015/QH13"],
                   ruot_mau=RUOT_MAU_MAU)
        goc.update(ghi_de)
        return BieuMau(**goc)

    def test_hash_on_dinh(self):
        assert self._bm().nguon_hash() == self._bm().nguon_hash()

    def test_can_cu_doi_thi_hash_doi(self):
        assert self._bm().nguon_hash() != self._bm(can_cu=["12/2020/NĐ-CP"]).nguon_hash()

    def test_hieu_luc_doi_thi_hash_doi(self):
        """Ruột mẫu y nguyên, nhưng căn cứ chết là lý do chính đáng nhất để viết lại."""
        assert self._bm().nguon_hash() != self._bm(hieu_luc="het_hieu_luc").nguon_hash()

    def test_can_cu_khac_thu_tu_thi_hash_khong_doi(self):
        a = self._bm(can_cu=["91/2015/QH13", "301/2026/NĐ-CP"])
        b = self._bm(can_cu=["301/2026/NĐ-CP", "91/2015/QH13"])
        assert a.nguon_hash() == b.nguon_hash()

    def test_so_bo_qua_bai_chua_doi(self, tmp_path):
        so = SoTrangThai(tmp_path / "da-sinh.json")
        bm = self._bm()
        assert so.can_sinh_lai(bm.form_key, bm.nguon_hash())
        so.ghi_nhan(bm.form_key, bm.nguon_hash(), citation_ok=True)
        assert not so.can_sinh_lai(bm.form_key, bm.nguon_hash())

    def test_so_sinh_lai_bai_truot_cong(self, tmp_path):
        """Bài `citation_ok:false` bị bên xuất bản loại vĩnh viễn — phải sinh lại."""
        so = SoTrangThai(tmp_path / "da-sinh.json")
        bm = self._bm()
        so.ghi_nhan(bm.form_key, bm.nguon_hash(), citation_ok=False)
        assert so.can_sinh_lai(bm.form_key, bm.nguon_hash())

    def test_so_ghi_va_doc_lai(self, tmp_path):
        duong_dan = tmp_path / "da-sinh.json"
        bm = self._bm()
        so = SoTrangThai(duong_dan)
        so.ghi_nhan(bm.form_key, bm.nguon_hash(), citation_ok=True)
        so.luu()
        assert not SoTrangThai(duong_dan).can_sinh_lai(bm.form_key, bm.nguon_hash())

    def test_so_hong_thi_coi_nhu_rong(self, tmp_path):
        duong_dan = tmp_path / "da-sinh.json"
        duong_dan.write_text("{ hỏng", encoding="utf-8")
        assert SoTrangThai(duong_dan).can_sinh_lai("hopdong-101", "abc")


class TestDocKho:
    def test_doc_du_hai_nguon(self, vault):
        kho = doc_kho(vault)
        assert len(kho.bieu_mau) == 2
        assert kho.tra_van_ban("91/2015/QH13").tieu_de == "Bộ luật Dân sự"
        assert kho.theo_khoa()["hopdong-101"].co_ruot_mau

    def test_so_hieu_lech_dau_van_tra_duoc(self, vault):
        """'301/2026/ND-CP' và '301/2026/NĐ-CP' phải tra ra cùng một văn bản."""
        kho = doc_kho(vault)
        assert kho.tra_van_ban("301/2026/ND-CP") is not None

    def test_cat_dung_ruot_mau(self):
        ruot = ruot_mau_tu_trang(_trang_bieu_mau())
        assert ruot.startswith("CỘNG HÒA")
        assert "thuvienphapluat.vn" not in ruot   # không nuốt sang mục Nguồn
        assert "## Tải về" not in ruot

    def test_trang_thieu_thi_khong_vo(self, vault):
        (vault / "content" / "bieu-mau" / "bm-tvpl-102.md").unlink()
        kho = doc_kho(vault)
        assert kho.theo_khoa()["hopdong-102"].ruot_mau == ""


class TestChonUngVien:
    def test_uu_tien_co_toan_van(self, vault):
        """172 mẫu có căn cứ + toàn văn viết được bài sâu nhất — chạy trước."""
        ds = chon_ung_vien(doc_kho(vault))
        assert ds[0].bieu_mau.form_key == "hopdong-101"
        assert ds[0].co_toan_van

    def test_loc_chi_co_toan_van(self, vault):
        ds = chon_ung_vien(doc_kho(vault), chi_co_toan_van=True)
        assert [u.bieu_mau.form_key for u in ds] == ["hopdong-101"]

    def test_loai_bieu_mau_da_bi_go(self, vault):
        """Nguồn đã gỡ mẫu thì hướng dẫn cho nó là hướng dẫn cho tờ giấy không tồn tại."""
        chi_muc = vault / "tro-ly" / "du-lieu.json"
        goi = json.loads(chi_muc.read_text(encoding="utf-8"))
        goi["bieu_mau"][0]["g"] = 1
        chi_muc.write_text(json.dumps(goi, ensure_ascii=False), encoding="utf-8")
        ds = chon_ung_vien(doc_kho(vault))
        assert "hopdong-101" not in [u.bieu_mau.form_key for u in ds]

    def test_loai_mau_khong_co_ruot(self, vault):
        (vault / "content" / "bieu-mau" / "bm-tvpl-102.md").write_text(
            "## Nội dung biểu mẫu\n\nĐang cập nhật.\n\n## Nguồn\n", encoding="utf-8")
        ds = chon_ung_vien(doc_kho(vault))
        assert "hopdong-102" not in [u.bieu_mau.form_key for u in ds]

    def test_thu_tu_tat_dinh(self, vault):
        kho = doc_kho(vault)
        assert ([u.bieu_mau.form_key for u in chon_ung_vien(kho)]
                == [u.bieu_mau.form_key for u in chon_ung_vien(kho)])


class TestSinhBai:
    def test_ngu_canh_canh_bao_khi_khong_co_can_cu(self, vault):
        """74% kho mang cờ khong_ro — nhóm này phải được dặn KHÔNG trích Điều nào."""
        kho = doc_kho(vault)
        u = next(u for u in chon_ung_vien(kho)
                 if u.bieu_mau.form_key == "hopdong-102")
        ngu_canh, _ = dung_ngu_canh(u, kho, tai_toan_van_ve=False)
        assert "KHÔNG CÓ" in ngu_canh
        assert "KHÔNG trích Điều" in ngu_canh

    def test_ngu_canh_co_ruot_mau_va_can_cu(self, vault):
        kho = doc_kho(vault)
        u = chon_ung_vien(kho)[0]
        ngu_canh, _ = dung_ngu_canh(u, kho, tai_toan_van_ve=False)
        assert "HỢP ĐỒNG LÀM GIA SƯ" in ngu_canh
        assert "91/2015/QH13" in ngu_canh
        assert "không chép lại vào bài" in ngu_canh

    def test_sinh_lai_mot_lan_khi_truot_cong_tieu_de(self, vault, docs_db):
        goi = _llm_gia(tieu_de=[
            "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",           # lượt 1 — trượt
            "Hợp đồng làm gia sư: 7 chỗ hở cần vá",          # lượt 2 — đạt
        ])
        kho = doc_kho(vault)
        bai = sinh_bai(chon_ung_vien(kho)[0], kho, tai_toan_van_ve=False,
                       db_path=docs_db, goi_llm=goi)
        assert bai.sinh_lai and len(goi.loi_goi) == 2
        assert "LƯU Ý SỬA LỖI" in goi.loi_goi[1][1]

    def test_truot_hai_lan_thi_bo(self, vault, docs_db):
        goi = _llm_gia(tieu_de="Mẫu số 01-ĐK-TCT")
        kho = doc_kho(vault)
        with pytest.raises(SinhThatBai, match="cổng tiêu đề"):
            sinh_bai(chon_ung_vien(kho)[0], kho, tai_toan_van_ve=False,
                     db_path=docs_db, goi_llm=goi)
        assert len(goi.loi_goi) == 2       # thử đúng hai lần, không hơn

    def test_bai_bi_cat_khong_duoc_giao(self, vault, docs_db):
        """Bài chạm trần token mang theo cả câu cảnh báo về REPORT_MAX_TOKENS."""
        kho = doc_kho(vault)
        with pytest.raises(SinhThatBai, match="bị cắt"):
            sinh_bai(chon_ung_vien(kho)[0], kho, tai_toan_van_ve=False,
                     db_path=docs_db, goi_llm=_llm_gia(truncated=True))

    def test_boc_json_khi_mo_hinh_boc_hang_rao_ma(self, vault, docs_db):
        kho = doc_kho(vault)

        def goi(he_thong, nguoi_dung, model="", max_tokens=0):
            return LLMResult(
                text='```json\n{"tieu_de":"Hợp đồng gia sư: 7 chỗ hở",'
                     '"mo_ta":"x","than_bai":"## A\\n\\nB"}\n```',
                truncated=False, model="test-model")

        bai = sinh_bai(chon_ung_vien(kho)[0], kho, tai_toan_van_ve=False,
                       db_path=docs_db, goi_llm=goi)
        assert bai.than_bai.startswith("## A")

    def test_dau_ra_khong_phai_json_thi_bo_chu_khong_giao_bai_rong(
            self, vault, docs_db):
        kho = doc_kho(vault)

        def goi(he_thong, nguoi_dung, model="", max_tokens=0):
            return LLMResult(text="Xin lỗi, tôi không thể…", truncated=False,
                             model="test-model")

        with pytest.raises(SinhThatBai):
            sinh_bai(chon_ung_vien(kho)[0], kho, tai_toan_van_ve=False,
                     db_path=docs_db, goi_llm=goi)


class TestPrompt:
    def test_nap_duoc_va_gian_include(self):
        t = load_cam_nang_prompt()
        assert "VĂN PHONG" in t          # giong_van_doanh_nghiep.md
        assert "ĐIỀU CẤM" in t           # dieu_cam_va_checklist.md
        assert "{{include:" not in t

    def test_dung_quy_uoc_web_chu_khong_phai_ban_pdf(self):
        """Bản PDF cấm liên kết — bê sang là ra bài web không có link nào."""
        t = load_cam_nang_prompt()
        assert "QUY ƯỚC MARKDOWN (bài đăng web" in t
        assert "### CHƯƠNG I" not in t
        assert "[chữ hiển thị](https://…)" in t

    def test_noi_ro_bon_thu_ben_xuat_ban_tu_dung(self):
        t = load_cam_nang_prompt()
        for k in ["Slug", "hộp hiệu lực", "Ruột tờ mẫu", "footer"]:
            assert k.lower() in t.lower(), k
