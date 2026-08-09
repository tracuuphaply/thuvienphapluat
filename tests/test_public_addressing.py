"""Nhóm — địa chỉ công khai của một văn bản.

Ba lỗ hổng được vá cùng lúc vì chúng cùng trả lời một câu hỏi: "làm sao trỏ tới
đúng một văn bản cụ thể?"

  1. `moj_url` rỗng trên toàn bộ 1015 văn bản → mọi note Obsidian render
     "[Bộ Tư pháp]()". Trang công khai không đăng được nếu không ghi được nguồn.
  2. Tên note lấy từ số hiệu trần → "40/2026/QĐ-UBND" của hai tỉnh ra cùng một
     file, note sau ghi đè note trước mà không báo gì.
  3. `targetDocument.id` bị vứt khi parse → mất đường tải văn bản được dẫn
     chiếu, vì /doc/all bỏ qua mọi tham số lọc nên không tra ngược số hiệu được.
"""
import pytest
from sqlalchemy import create_engine, text

from src import config
from src.config import PROJECT_ROOT
from src.sources.moj_api import doc_source_url, parse_doc_detail
from src.storage.database import remember_moj_id
from src.storage.migrations import MIGRATIONS, applied_ids, run_migrations
from src.storage.models import MojIdIndex
from src.storage.public_slug import make_public_slug, slugify_doc_num


class TestMojUrl:
    def test_sinh_url_tu_moj_id(self):
        url = doc_source_url("140432")
        assert url.endswith("/doc/140432")
        assert url.startswith("https://")

    def test_id_dang_uuid_van_ra_url(self):
        uuid = "fe9afac0-8a37-11f1-9aac-ebd03da97a7f"
        assert doc_source_url(uuid).endswith(f"/doc/{uuid}")

    @pytest.mark.parametrize("empty", [None, "", "   "])
    def test_khong_co_id_thi_khong_bia_url(self, empty):
        """Văn bản chỉ có nguồn TVPL không có moj_id — 64 bản trong kho thật.

        Trả chuỗi rỗng để note hiện 'chưa có nguồn' thay vì một link chết.
        """
        assert doc_source_url(empty) == ""


class TestPublicSlug:
    def test_van_ban_trung_uong_giu_slug_tran(self):
        assert make_public_slug("78/2025/QH15", "78/2025/qh15::quốc hội") == "78-2025-QH15"

    def test_bo_dau_tieng_viet(self):
        """URL có dấu bị mã hoá percent thành chuỗi không đọc nổi trong báo cáo."""
        assert "Đ" not in slugify_doc_num("292/2026/NĐ-CP")
        assert "Đ" not in make_public_slug("01/2026/QĐ-UBND", "k")

    def test_chu_D_gach_ngang_khong_gop_voi_D_thuong(self):
        """Thư viện Pháp luật đăng bản dịch tiếng Anh dưới số hiệu ASCII, nên

        "296/2026/NĐ-CP" và "296/2026/ND-CP" cùng tồn tại trong kho. Bỏ dấu
        thành "D" khiến hai bản ghi khác nhau ra cùng slug và vi phạm ràng buộc
        duy nhất — đã gặp thật, làm gãy cả một lượt cào.
        """
        viet = make_public_slug("296/2026/NĐ-CP", "296/2026/nđ-cp::chính phủ")
        anh = make_public_slug("296/2026/ND-CP", "296/2026/nd-cp::")
        assert viet != anh
        assert viet == "296-2026-NDD-CP"

    def test_gach_ngang_doi_khong_gop_voi_gach_ngang_don(self):
        """Chuỗi phân cách bị slugify co lại thành một dấu.

        "05/2000/QĐ--BVHTT" và "05/2000/QĐ-BVHTT" cùng ra "05-2000-QDD-BVHTT" —
        đã gặp thật, làm gãy nguyên một lô bao đóng 300 văn bản.
        """
        doi = make_public_slug("05/2000/QĐ--BVHTT", "05/2000/qđ--bvhtt::bộ vhtt")
        don = make_public_slug("05/2000/QĐ-BVHTT", "05/2000/qđ-bvhtt::bộ vhtt")
        assert doi != don
        assert don == "05-2000-QDD-BVHTT"

    @pytest.mark.parametrize("doc_num", [
        "28/2024/QĐ-UBND..",      # dấu chấm cuối
        "10 /2024/TT-BTNMT",      # khoảng trắng trước dấu /
        "02/2022/TT-BTNMT (1)",   # ngoặc ở cuối
        "'18/2024/TT-BCT",        # nháy đơn ở đầu
    ])
    def test_phan_cach_dau_cuoi_cung_can_phan_biet(self, doc_num):
        """Bốn dạng có thật trong kho. Riêng "28/2024/QĐ-UBND.." còn trượt cả

        phần phân biệt dành cho văn bản tỉnh, vì regex hậu tố khớp "-UBND$" mà
        số hiệu này có hai dấu chấm ở sau.
        """
        assert "--" in make_public_slug(doc_num, f"{doc_num.lower()}::co quan")

    def test_so_hieu_binh_thuong_khong_bi_gan_them(self):
        """Gắn phần phân biệt cho mọi số hiệu thì slug hết đọc được và mọi URL
        đã in trong báo cáo cũ đều đổi.
        """
        assert make_public_slug("292/2026/NĐ-CP", "292/2026/nđ-cp::chính phủ") \
            == "292-2026-NDD-CP"

    def test_so_hieu_con_dau_khac_thi_them_phan_phan_biet(self):
        """Ký tự có dấu ngoài Đ vẫn bị gộp khi bỏ dấu — hiếm (7 lần trong kho)

        nhưng vẫn phải chặn, nếu không hai số hiệu khác nhau ra cùng slug.
        """
        slug = make_public_slug("Số 12/2026/TT-BTC", "so 12::x")
        assert "--" in slug

    def test_van_ban_dia_phuong_luon_co_phan_phan_biet(self):
        a = make_public_slug("40/2026/QĐ-UBND", "40/2026/qđ-ubnd::ubnd tỉnh cà mau")
        b = make_public_slug("40/2026/QĐ-UBND", "40/2026/qđ-ubnd::ubnd tỉnh gia lai")
        assert a != b
        assert a.startswith("40-2026-QDD-UBND--")

    def test_hdnd_cung_duoc_phan_biet(self):
        a = make_public_slug("12/2026/NQ-HĐND", "12/2026/nq-hđnd::hđnd tỉnh a")
        b = make_public_slug("12/2026/NQ-HĐND", "12/2026/nq-hđnd::hđnd tỉnh b")
        assert a != b

    def test_khong_so_khong_dung_nhau(self):
        """165 cạnh dẫn chiếu trỏ tới 'Không số' — đó là thùng rác số hiệu

        không parse được, không phải một văn bản. Chúng phải ra các slug khác nhau.
        """
        a = make_public_slug("Không số", "không số::bộ tài chính")
        b = make_public_slug("Không số", "không số::bộ công thương")
        assert a != b
        assert a.startswith("Khong-so--")

    def test_on_dinh_giua_cac_lan_chay(self):
        """URL đã in vào báo cáo PDF không được đổi khi kho lớn lên.

        Vì vậy slug chỉ suy từ chính văn bản, không từ trạng thái toàn kho.
        """
        args = ("40/2026/QĐ-UBND", "40/2026/qđ-ubnd::ubnd tỉnh cà mau")
        assert make_public_slug(*args) == make_public_slug(*args)


class TestGiuTargetMojId:
    def _detail(self, target):
        return {"data": {
            "id": "111", "docNum": "01/2026/NĐ-CP", "title": "Nghị định thử",
            "references": [{"targetDocument": target, "referenceType": 3}],
        }}

    def test_lay_duoc_id_van_ban_dich(self):
        parsed = parse_doc_detail(self._detail({"id": 25811, "docNum": "72/2010/QĐ-TTg"}))
        ref = parsed["references"][0]
        assert ref["target_doc_num"] == "72/2010/QĐ-TTg"
        assert ref["target_moj_id"] == "25811"

    def test_payload_khong_co_id_thi_de_None_chu_khong_bia(self):
        parsed = parse_doc_detail(self._detail({"docNum": "72/2010/QĐ-TTg"}))
        assert parsed["references"][0]["target_moj_id"] is None

    def test_van_ban_nguon_co_moj_url(self):
        parsed = parse_doc_detail(self._detail({"id": 1, "docNum": "X"}))
        assert parsed["moj_url"].endswith("/doc/111")


class TestMojIdIndex:
    def test_ghi_nho_cap_moi(self, master_session):
        assert remember_moj_id(master_session, "83/2015/QH13", "12345", "reference")
        master_session.flush()
        row = master_session.get(MojIdIndex, {"doc_num": "83/2015/QH13", "moj_id": "12345"})
        assert row is not None and row.source == "reference"

    def test_khong_ghi_trung(self, master_session):
        remember_moj_id(master_session, "83/2015/QH13", "12345", "reference")
        master_session.flush()
        assert not remember_moj_id(master_session, "83/2015/QH13", "12345", "detail")

    @pytest.mark.parametrize("doc_num,moj_id", [("", "1"), ("X", ""), ("X", None)])
    def test_thieu_ve_nao_cung_khong_ghi(self, master_session, doc_num, moj_id):
        assert not remember_moj_id(master_session, doc_num, moj_id, "reference")


class TestCauHinhTapTrung:
    """Cấu hình LLM từng nằm rải rác bằng os.getenv, không có ở config.py lẫn

    .env.example. Người làm đúng theo hướng dẫn bàn giao nhận được crawler chạy
    tốt và bộ sinh báo cáo chết câm.
    """

    LLM_VARS = (
        "V98_API_KEY", "OPENAI_API_BASE", "OPENAI_API_KEY", "GEMINI_API_KEY",
        "REPORT_MODEL", "REPORT_MAX_TOKENS", "REPORT_PROMPT_PATH",
        "EMBEDDING_MODEL", "EMBEDDING_DIM", "EMBEDDING_BATCH_SIZE",
    )

    def test_moi_bien_llm_deu_co_trong_env_example(self):
        text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
        thieu = [v for v in self.LLM_VARS if f"\n{v}=" not in f"\n{text}"]
        assert not thieu, f"thiếu trong .env.example: {thieu}"

    def test_khong_con_doc_env_rai_rac_trong_tang_rag(self):
        """Mọi biến cấu hình phải đi qua config.py để còn một chỗ duy nhất

        trả lời câu hỏi 'hệ thống đọc những biến nào'.
        """
        for name in ("src/rag/report_generator.py", "src/rag/embeddings_api.py"):
            src = (PROJECT_ROOT / name).read_text(encoding="utf-8")
            assert "os.getenv" not in src, f"{name} vẫn đọc os.getenv trực tiếp"

    def test_cau_hinh_llm_doc_lai_luc_goi_chu_khong_dong_bang(self, monkeypatch):
        """Đóng băng lúc import thì đổi model phải khởi động lại tiến trình,

        và bot Telegram chạy dài ngày không bao giờ nhận cấu hình mới.
        """
        monkeypatch.setenv("REPORT_MODEL", "mo-hinh-thu-nghiem")
        assert config.report_model() == "mo-hinh-thu-nghiem"

    def test_khong_co_khoa_nao_thi_tra_rong_chu_khong_no(self, monkeypatch):
        for var in ("V98_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        assert config.llm_api_key() == ""


class TestMigrations:
    def _conn(self, tmp_path):
        """Lược đồ thật từ ORM, đúng như init_db() dựng.

        Bảng rút gọn tự chế sẽ thiếu cột mà migration giả định có sẵn, và test
        khi đó báo hỏng ở chỗ mà cơ sở dữ liệu thật không hề hỏng.
        """
        from src.storage.models import Base

        engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
        Base.metadata.create_all(engine)
        return engine.connect()

    def test_chay_lan_dau_ap_dung_het(self, tmp_path):
        conn = self._conn(tmp_path)
        ran = run_migrations(conn)
        assert ran == [m.id for m in MIGRATIONS]
        conn.close()

    def test_chay_lan_hai_khong_lam_gi(self, tmp_path):
        """init_db() chạy mỗi lần khởi động; migration phải chỉ áp dụng một lần."""
        conn = self._conn(tmp_path)
        run_migrations(conn)
        assert run_migrations(conn) == []
        assert applied_ids(conn) == {m.id for m in MIGRATIONS}
        conn.close()

    def test_id_migration_khong_trung_nhau(self):
        ids = [m.id for m in MIGRATIONS]
        assert len(ids) == len(set(ids))
