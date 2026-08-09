"""Nhóm — ba loại báo cáo, hàng đợi và bốn cơ chế chống ngập.

Hai thứ dễ hỏng nhất và hậu quả nặng nhất:
  - báo cáo được sinh TRONG pipeline cào: một lỗi LLM đánh dấu cả lần cào là
    FAILED, kéo theo run_daily.sh bỏ luôn đồng bộ vault và RAG
  - 50 văn bản mới một ngày sinh 50 báo cáo: khách nhận 50 PDF trong một buổi
    sáng, không ai đọc, hoá đơn API thì có thật
"""
import datetime
import json
from pathlib import Path

import pytest
from sqlalchemy import text

from src.config import PROJECT_ROOT
from src.rag.reports import jobs
from src.rag.reports.prompts import PromptTemplateMissing, load_prompt


class TestNapPrompt:
    @pytest.mark.parametrize("kind", ["a", "b", "c"])
    def test_ba_loai_deu_nap_duoc(self, kind):
        assert len(load_prompt(kind)) > 1000

    @pytest.mark.parametrize("kind", ["a", "b", "c"])
    def test_ca_ba_deu_co_quy_tac_trich_dan(self, kind):
        """Quy tắc trích dẫn tồn tại ở 2/3 loại là một lỗi đang chờ được ship."""
        prompt = load_prompt(kind)
        assert "Cấm tuyệt đối" in prompt
        assert "Bịa số hiệu" in prompt

    @pytest.mark.parametrize("kind", ["a", "b", "c"])
    def test_ca_ba_deu_co_quy_uoc_markdown(self, kind):
        """Bộ dựng PDF phụ thuộc trực tiếp vào quy ước này."""
        assert "QUY ƯỚC MARKDOWN" in load_prompt(kind)

    @pytest.mark.parametrize("kind", ["a", "b", "c"])
    def test_cat_bo_tai_lieu_van_hanh(self, kind):
        """Hợp đồng dữ liệu và tham số API là tài liệu cho người, không phải

        chỉ dẫn cho mô hình — nạp vào chỉ tốn token và gây nhiễu.
        """
        assert "HỢP ĐỒNG DỮ LIỆU" not in load_prompt(kind)

    def test_loai_la_thi_bao_loi_chu_khong_dung_prompt_rut_gon(self):
        """Thiếu mẫu mà vẫn sinh báo cáo là mất toàn bộ cấu trúc bắt buộc,

        quy tắc trích dẫn và điều cấm — mà người dùng không hề biết.
        """
        with pytest.raises(PromptTemplateMissing):
            load_prompt("khong-ton-tai")

    def test_sua_phan_dung_chung_la_sua_cho_ca_ba(self):
        shared = (PROJECT_ROOT / "src/rag/prompts/_chung/dieu_cam_va_checklist.md"
                  ).read_text(encoding="utf-8")
        marker = "Bịa số hiệu"
        assert marker in shared
        assert all(marker in load_prompt(k) for k in "abc")


class TestDoiChieuVanBanCu:
    """Báo cáo (b) phải nói được quy định nào đã đổi, không chỉ số hiệu nào.

    Đó là toàn bộ lý do bao đóng dẫn chiếu kéo cả văn bản đã bị bãi bỏ về. Bản
    trước chỉ đưa METADATA của văn bản cũ vào ngữ cảnh, nên mô hình nói được
    "Nghị định 100 thay thế Nghị định 50" mà không nói được thay thế cái gì —
    thông tin thư mục, không phải phân tích.
    """

    def _kho(self, master_session, rag_db):
        from src.storage.database import insert_references, upsert_document

        moi, _ = upsert_document(master_session, {
            "doc_num": "100/2026/NĐ-CP", "title": "Nghị định mới",
            "agency_name": "Chính phủ", "doc_type": "Nghị định",
            "issue_date": datetime.date(2026, 3, 1), "eff_status": "Còn hiệu lực",
        })
        cu, _ = upsert_document(master_session, {
            "doc_num": "50/2020/NĐ-CP", "title": "Nghị định cũ",
            "agency_name": "Chính phủ", "doc_type": "Nghị định",
            "issue_date": datetime.date(2020, 1, 1),
            "eff_status": "Hết hiệu lực toàn bộ",
        })
        master_session.flush()
        insert_references(master_session, moi.id, [
            {"target_doc_num": "50/2020/NĐ-CP", "relation_type": "Thay thế"},
        ])
        master_session.commit()

        for doc, noi_dung in ((moi, "Vốn tối thiểu 10 tỷ đồng."),
                              (cu, "Vốn tối thiểu 3 tỷ đồng.")):
            rag_db.upsert_chunk({
                "doc_key": doc.doc_key, "doc_num": doc.doc_num, "chunk_index": 0,
                "heading": "Điều 5", "content": noi_dung,
                "char_count": len(noi_dung), "industries": [],
                "content_hash": f"h-{doc.doc_num}",
            })
        return moi

    def test_dua_dieu_khoan_cu_vao_ngu_canh(self, master_session, rag_db):
        from src.rag.reports.generators import build_update_context

        moi = self._kho(master_session, rag_db)
        payload = build_update_context(
            master_session, rag_db, [moi.doc_key], "v-test").payload

        cu = payload["van_ban_bi_tac_dong"]
        assert [d["doc_num"] for d in cu] == ["50/2020/NĐ-CP"]
        assert "3 tỷ" in cu[0]["dieu_khoan_cu"][0]["content_excerpt"], (
            "chỉ có metadata bản cũ — không đối chiếu được trước/sau"
        )

    def test_bao_thieu_khi_chua_co_toan_van_ban_cu(self, master_session, rag_db):
        """Thiếu toàn văn bản cũ thì phần 'thay đổi so với cái gì' không có căn
        cứ, và người đọc phải biết điều đó thay vì nhận một khoảng trống.
        """
        from src.rag.reports.generators import build_update_context

        moi = self._kho(master_session, rag_db)
        rag_db.db.execute("DELETE FROM legal_chunks WHERE doc_num='50/2020/NĐ-CP'")
        rag_db.db.commit()

        payload = build_update_context(
            master_session, rag_db, [moi.doc_key], "v-test").payload
        assert payload["han_che_du_lieu"]["van_ban_cu_chua_co_toan_van"] == [
            "50/2020/NĐ-CP"
        ]

    def test_khong_bao_thieu_khi_du(self, master_session, rag_db):
        from src.rag.reports.generators import build_update_context

        moi = self._kho(master_session, rag_db)
        payload = build_update_context(
            master_session, rag_db, [moi.doc_key], "v-test").payload
        assert "van_ban_cu_chua_co_toan_van" not in payload["han_che_du_lieu"]

    def test_cat_bot_van_ban_cu_qua_dai(self, master_session, rag_db):
        """Một đạo luật bị thay thế có thể 300 Điều; nhồi hết vào là đẩy phần
        phân tích ra khỏi cửa sổ ngữ cảnh.
        """
        from src.rag.reports.generators import CU_MAX_DOAN, build_update_context

        moi = self._kho(master_session, rag_db)
        cu_key = "50/2020/nđ-cp::chính phủ"
        for i in range(1, CU_MAX_DOAN + 20):
            rag_db.upsert_chunk({
                "doc_key": cu_key, "doc_num": "50/2020/NĐ-CP", "chunk_index": i,
                "heading": f"Điều {i}", "content": f"nội dung {i}",
                "char_count": 10, "industries": [], "content_hash": f"h{i}",
            })
        payload = build_update_context(
            master_session, rag_db, [moi.doc_key], "v-test").payload
        assert len(payload["van_ban_bi_tac_dong"][0]["dieu_khoan_cu"]) == CU_MAX_DOAN

    def test_prompt_noi_ro_truong_moi(self):
        """Dữ liệu có mà prompt không nhắc thì mô hình không dùng tới."""
        p = load_prompt("b")
        assert "dieu_khoan_cu" in p
        assert "van_ban_cu_chua_co_toan_van" in p


class TestCongTrongYeu:
    def test_nghi_dinh_tro_len_luon_duoc_bao(self):
        assert jobs.materiality(5, 0.0, False).should_queue
        assert jobs.materiality(2, 0.0, False).should_queue

    def test_doi_trang_thai_hieu_luc_luon_duoc_bao(self):
        """Văn bản đang áp dụng vừa hết hiệu lực là tin đáng báo nhất."""
        assert jobs.materiality(9, 0.0, True).should_queue

    def test_cuong_do_cao_thi_duoc_bao_du_cap_thap(self):
        assert jobs.materiality(9, 85.0, False).should_queue

    def test_quyet_dinh_tinh_cuong_do_thap_thi_khong_bao(self):
        """Một quyết định giá đất cấp tỉnh không đáng gửi báo cáo cho mọi công

        ty xây dựng cả nước.
        """
        d = jobs.materiality(9, 10.0, False)
        assert not d.should_queue and "duoi_nguong" in d.reason

    def test_ly_do_luon_duoc_ghi_lai(self):
        """Phải biết vì sao một văn bản được báo hoặc không được báo."""
        assert jobs.materiality(2, 0.0, False).reason
        assert jobs.materiality(99, 0.0, False).reason


class TestChongNgap:
    @pytest.fixture
    def db(self, master_session):
        # report_jobs nằm trong ORM nên fixture đã tạo sẵn; không gọi
        # run_migrations ở đây vì nó commit trên connection và làm hỏng
        # transaction của session.
        return master_session

    def test_gop_theo_nganh_va_ngay(self, db):
        """Hai lần xếp hàng cùng ngành cùng ngày chỉ ra MỘT báo cáo."""
        day = datetime.date(2026, 8, 7)
        first = jobs.enqueue(db, "b", "K", vsic_code="K", day=day)
        second = jobs.enqueue(db, "b", "K", vsic_code="K", day=day)
        assert first is not None and second is None

    def test_khac_ngay_thi_la_bao_cao_khac(self, db):
        assert jobs.enqueue(db, "b", "K", vsic_code="K",
                            day=datetime.date(2026, 8, 7)) is not None
        assert jobs.enqueue(db, "b", "K", vsic_code="K",
                            day=datetime.date(2026, 8, 8)) is not None

    def test_tran_ngay_thi_doi_sang_hom_sau_chu_khong_bo(self, db, monkeypatch):
        """Báo cáo bị đánh rơi im lặng là mất dữ liệu, không phải tiết kiệm."""
        monkeypatch.setattr(jobs, "MAX_REPORTS_PER_DAY", 2)
        day = datetime.date(2026, 8, 7)
        for code in ("A", "B", "C"):
            assert jobs.enqueue(db, "b", code, vsic_code=code, day=day) is not None

        rows = db.execute(text(
            "SELECT vsic_code, scheduled_for FROM report_jobs ORDER BY id"
        )).mappings().all()
        assert rows[0]["scheduled_for"] == "2026-08-07"
        assert rows[2]["scheduled_for"] == "2026-08-08", "job thứ ba phải dời sang mai"

    def test_thoi_gian_nguoi_chan_bao_cao_lap_lai(self, db):
        day = datetime.date(2026, 8, 7)
        jobs.enqueue(db, "b", "K", vsic_code="K", day=day)
        db.commit()
        assert jobs.in_cooldown(db, "K", day, hierarchy_level=9)

    def test_van_ban_cap_cao_bo_qua_thoi_gian_nguoi(self, db):
        """Một đạo luật mới đáng báo ngay kể cả khi tuần trước vừa có bản tin."""
        day = datetime.date(2026, 8, 7)
        jobs.enqueue(db, "b", "K", vsic_code="K", day=day)
        db.commit()
        assert not jobs.in_cooldown(db, "K", day, hierarchy_level=2)

    def test_van_ban_duoi_nguong_duoc_ghi_nhan_chu_khong_bien_mat(self, db):
        """Phải biết cái gì đã KHÔNG được báo cáo, để đưa vào bản định kỳ sau."""
        jobs.record_skip(db, "b", "40/2026/qd-ubnd", "duoi_nguong")
        db.commit()
        row = db.execute(text(
            "SELECT status, trigger_reason FROM report_jobs WHERE status='SKIPPED'"
        )).mappings().first()
        assert row and row["trigger_reason"] == "duoi_nguong"


class TestHangDoi:
    @pytest.fixture
    def db(self, master_session):
        # report_jobs nằm trong ORM nên fixture đã tạo sẵn; không gọi
        # run_migrations ở đây vì nó commit trên connection và làm hỏng
        # transaction của session.
        return master_session

    def test_lay_viec_uu_tien_cao_nhat_truoc(self, db):
        day = datetime.date(2026, 8, 7)
        jobs.enqueue(db, "b", "A", vsic_code="A", priority=10.0, day=day)
        jobs.enqueue(db, "b", "B", vsic_code="B", priority=90.0, day=day)
        db.commit()
        assert jobs.next_job(db, day)["vsic_code"] == "B"

    def test_khong_lay_viec_hen_ngay_mai(self, db):
        jobs.enqueue(db, "b", "A", vsic_code="A", day=datetime.date(2026, 8, 8))
        db.commit()
        assert jobs.next_job(db, datetime.date(2026, 8, 7)) is None

    def test_danh_dau_xong_thi_khong_lay_lai(self, db):
        day = datetime.date(2026, 8, 7)
        job_id = jobs.enqueue(db, "b", "A", vsic_code="A", day=day)
        jobs.mark(db, job_id, jobs.DONE, citation_total=5, citation_missing=0)
        db.commit()
        assert jobs.next_job(db, day) is None

    def test_bi_chan_trich_dan_cung_khong_lay_lai(self, db):
        """Báo cáo có số hiệu lạ không được tự động thử lại — phải người xem."""
        day = datetime.date(2026, 8, 7)
        job_id = jobs.enqueue(db, "b", "A", vsic_code="A", day=day)
        jobs.mark(db, job_id, jobs.BLOCKED_CITATION, citation_missing=3)
        db.commit()
        assert jobs.next_job(db, day) is None


class TestChonNganhChoBaoCaoC:
    """Chọn ngành sinh báo cáo chuyên sâu phải thoả CẢ HAI ngưỡng.

    Lỗi đo được trên dữ liệu thật: Luật Xây dựng 2025 đạt cường độ ≥ 80 ở 18/21
    ngành nên sinh 18 báo cáo, kể cả cho "Tổ chức và cơ quan quốc tế". Nguyên
    nhân là `impact_raw` tỷ lệ với TỔNG số ràng buộc, nên một đạo luật 300 Điều
    đứng ở phân vị cao trong phân phối của MỌI ngành.
    """

    def _ctx(self, rows):
        from src.rag.reports.context import ReportContext

        return ReportContext(payload={"diem_tac_dong_nganh": rows}, doc_nums=["X"])

    def _select(self, rows):
        from src.rag.reports.generators import _update_sidecar

        return {r["ma_nganh"] for r in
                _update_sidecar(self._ctx(rows))["industries_affected"]}

    def test_cuong_do_cao_nhung_ty_trong_thap_thi_khong_chon(self):
        """"Nằm trong top 15% văn bản tác động tới ngành T" đúng về số học nhưng

        vô nghĩa khi văn bản đó nằm trong top 15% của mọi thứ.
        """
        rows = [
            {"ma_nganh": "F", "ten_nganh": "Xây dựng",
             "ty_trong_tac_dong": 25.7, "cuong_do_tac_dong": 98.9},
            {"ma_nganh": "T", "ten_nganh": "Làm thuê hộ gia đình",
             "ty_trong_tac_dong": 2.0, "cuong_do_tac_dong": 87.2},
        ]
        assert self._select(rows) == {"F"}

    def test_ty_trong_cao_nhung_cuong_do_thap_thi_khong_chon(self):
        """Văn bản nhỏ nói đúng về một ngành vẫn chưa đáng một báo cáo riêng."""
        rows = [{"ma_nganh": "F", "ten_nganh": "Xây dựng",
                 "ty_trong_tac_dong": 40.0, "cuong_do_tac_dong": 20.0}]
        assert self._select(rows) == set()

    def test_nguong_ty_trong_bang_muc_phan_bo_deu(self):
        """Dưới mức phân bổ đều nghĩa là ngành nhận ít hơn cả phần ngẫu nhiên."""
        from src.rag.reports.generators import C_MIN_SHARE

        assert C_MIN_SHARE == pytest.approx(100 / 21)

    def test_giu_thu_tu_cuong_do_giam_dan(self):
        rows = [
            {"ma_nganh": "A", "ten_nganh": "A", "ty_trong_tac_dong": 10.0,
             "cuong_do_tac_dong": 85.0},
            {"ma_nganh": "B", "ten_nganh": "B", "ty_trong_tac_dong": 10.0,
             "cuong_do_tac_dong": 95.0},
        ]
        from src.rag.reports.generators import _update_sidecar

        out = _update_sidecar(self._ctx(rows))["industries_affected"]
        assert [r["ma_nganh"] for r in out] == ["B", "A"]


class TestGoKhoiMaBocBaoCao:
    """Mô hình thỉnh thoảng bọc cả báo cáo vào ```…``` dù prompt đã cấm.

    Đã gặp thật ở báo cáo (c) đầu tiên. Bộ dựng PDF parse theo tiền tố `###`,
    nên một dòng ``` ở đầu file làm mọi tiêu đề chương thành văn bản thường và
    bố cục vỡ hoàn toàn.
    """

    def _strip(self, text):
        from src.rag.reports.llm import strip_code_fence

        return strip_code_fence(text)

    def test_go_hang_rao_boc_ca_bao_cao(self):
        assert self._strip("```\n### CHƯƠNG I\nnội dung\n```") == "### CHƯƠNG I\nnội dung"

    def test_go_ca_khi_co_ten_ngon_ngu(self):
        assert self._strip("```markdown\n### CHƯƠNG I\n```") == "### CHƯƠNG I"

    def test_giu_nguyen_bao_cao_binh_thuong(self):
        text = "# BÁO CÁO\n\n### CHƯƠNG I\nnội dung"
        assert self._strip(text) == text

    def test_khong_dung_khoi_ma_nam_giua_noi_dung(self):
        """Khối mã giữa báo cáo có thể là trích dẫn có chủ ý."""
        text = "### CHƯƠNG I\n\n```\ntrich dan\n```\n\n### CHƯƠNG II"
        assert self._strip(text) == text

    @pytest.mark.parametrize("text", ["", "   ", None])
    def test_dau_vao_rong_khong_no(self, text):
        assert self._strip(text) == text
