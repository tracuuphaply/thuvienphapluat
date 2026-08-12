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


class TestBaoThieuVanBanDanChieu:
    """Văn bản bị dẫn chiếu mà bao đóng không lấy được phải hiện ra.

    Ba nhóm, ba lý do khác hẳn nhau. Quan trọng nhất là `vuot_tran_do_sau`:
    nó nói rằng việc truy vết dẫn chiếu bị cắt ở một khoảng cách nhất định,
    nên danh mục văn bản liên quan KHÔNG đầy đủ. Thiếu khối này thì báo cáo dẫn
    một đồ thị đã cắt cụt mà không nói gì.
    """

    def _frontier(self, session, **states):
        for i, (state, n) in enumerate(states.items()):
            for j in range(n):
                session.execute(text(
                    "INSERT INTO crawl_frontier (moj_id, doc_num, depth, priority, "
                    "state, attempts) VALUES (:m, 'X', 1, 1.0, :s, 0)"),
                    {"m": f"{state}-{i}-{j}", "s": state.upper()})
        session.commit()

    def test_dem_du_ba_nhom(self, master_session):
        from src.rag.reports.context import van_ban_dan_chieu_khong_lay_duoc

        self._frontier(master_session, failed=2, no_id=3, too_deep=4, done=9,
                       pending=5)
        assert van_ban_dan_chieu_khong_lay_duoc(master_session) == {
            "khong_tai_duoc": 2, "khong_co_id": 3, "vuot_tran_do_sau": 4,
        }

    def test_khong_thieu_gi_thi_khong_them_khoi(self, master_session):
        from src.rag.reports.context import (
            limitations, van_ban_dan_chieu_khong_lay_duoc,
        )

        self._frontier(master_session, done=3, pending=2)
        out = limitations([], [], bao_dong=van_ban_dan_chieu_khong_lay_duoc(
            master_session))
        assert "van_ban_dan_chieu_chua_co_trong_kho" not in out

    def test_co_thieu_thi_vao_han_che_du_lieu(self, master_session):
        from src.rag.reports.context import (
            limitations, van_ban_dan_chieu_khong_lay_duoc,
        )

        self._frontier(master_session, too_deep=242)
        out = limitations([], [], bao_dong=van_ban_dan_chieu_khong_lay_duoc(
            master_session))
        assert out["van_ban_dan_chieu_chua_co_trong_kho"]["vuot_tran_do_sau"] == 242

    def test_checklist_nhac_mo_hinh_dung_khoi_nay(self):
        """Dữ liệu có mà prompt không nhắc thì mô hình không dùng tới."""
        for kind in ("a", "b", "c"):
            p = load_prompt(kind)
            assert "van_ban_dan_chieu_chua_co_trong_kho" in p, f"prompt {kind}"
            assert "vuot_tran_do_sau" in p, f"prompt {kind}"


class TestBaoCaoNganhVaoWorker:
    """Báo cáo (a) từng nằm ngoài gói reports/ nên worker không chạy được nó.

    Nó chỉ sinh được bằng tay qua scripts/generate_industry_reports.py, Telegram
    hoặc CLI — tức loại báo cáo có trigger định kỳ lại là loại duy nhất không
    tự chạy được.
    """

    def test_worker_khong_con_nhanh_chua_ho_tro_cho_a(self):
        import inspect

        from src.rag.reports import worker

        src = inspect.getsource(worker.run_job)
        assert 'kind == "a"' in src
        assert "generate_industry_report" in src

    def test_bo_sinh_a_nam_trong_goi_reports(self):
        from src.rag.reports import generators

        assert hasattr(generators, "generate_industry_report")
        assert hasattr(generators, "build_industry_context")

    def test_ngu_canh_rong_thi_khong_goi_mo_hinh(self, master_session, rag_db):
        """Một bản sinh từ hư không trông vẫn có thẩm quyền — đó mới là nguy hiểm."""
        from src.rag.reports.generators import generate_industry_report
        from src.rag.reports.llm import LLMUnavailable

        with pytest.raises(LLMUnavailable):
            generate_industry_report(master_session, rag_db, "K", "v-test")

    def test_do_dai_khop_voi_prompt(self):
        """Mặc định cũ 8–15 trang mâu thuẫn mục 4 của prompt (4–6 trang)."""
        from src.rag.reports.generators import DO_DAI_MAC_DINH

        assert "4–6 trang" in DO_DAI_MAC_DINH


class TestLichHangQuy:
    """Trigger cho (a): "kết thúc 1 quý/6 tháng" theo yêu cầu vận hành."""

    def test_khoa_ky_on_dinh_trong_cung_mot_quy(self):
        import datetime

        from scripts.enqueue_quarterly_reports import ky_bao_cao

        assert ky_bao_cao(datetime.date(2026, 7, 1)) == "2026-Q3"
        assert ky_bao_cao(datetime.date(2026, 9, 30)) == "2026-Q3"

    def test_sang_quy_moi_thi_doi_khoa(self):
        import datetime

        from scripts.enqueue_quarterly_reports import ky_bao_cao

        assert ky_bao_cao(datetime.date(2026, 9, 30)) != \
            ky_bao_cao(datetime.date(2026, 10, 1))

    @pytest.mark.parametrize("thang,ky", [
        (1, "Q1"), (3, "Q1"), (4, "Q2"), (6, "Q2"),
        (7, "Q3"), (9, "Q3"), (10, "Q4"), (12, "Q4"),
    ])
    def test_moc_quy_dung_ranh_gioi(self, thang, ky):
        import datetime

        from scripts.enqueue_quarterly_reports import ky_bao_cao

        assert ky_bao_cao(datetime.date(2026, thang, 15)).endswith(ky)

    def test_plist_quy_dung_mang_bon_moc(self):
        """StartCalendarInterval nhận MỘT MẢNG dict. Một dict duy nhất chỉ đặt
        được một mốc, nên bản chỉ có Day+Month chạy một quý mỗi năm chứ không
        phải bốn — sai lặng lẽ, ba quý sau mới phát hiện.
        """
        from src.config import PROJECT_ROOT

        sh = (PROJECT_ROOT / "scripts" / "install_scheduler.sh").read_text(
            encoding="utf-8")
        assert "vn.legalvault.quarterly" in sh
        for thang in (1, 4, 7, 10):
            assert f"<key>Month</key><integer>{thang}</integer>" in sh

    def test_script_chay_quy_ton_tai_va_chay_duoc(self):
        import os

        from src.config import PROJECT_ROOT

        path = PROJECT_ROOT / "scripts" / "run_quarterly.sh"
        assert path.exists() and os.access(path, os.X_OK)


class TestXuatPdfTrongWorker:
    """PDF chỉ được dựng SAU khi qua cổng trích dẫn.

    PDF là dạng gửi cho khách, markdown là bản để soi mô hình đã bịa số hiệu
    nào. Dựng cả hai cùng lúc thì bản bị chặn cũng có PDF, và sớm muộn có người
    gửi nhầm.
    """

    def _job(self, kind="b", **kw):
        return {"id": 7, "kind": kind, "vsic_code": kw.get("vsic_code"),
                "industry": kw.get("industry"), "parent_job_id": None,
                "subject_keys": "[]"}

    def _result(self, sidecar=None):
        from src.rag.reports.generators import ReportResult

        return ReportResult(kind="b", markdown="# X\n\nNội dung.",
                            sidecar=sidecar or {}, model="thu-nghiem")

    def test_nhan_bia_cua_b_la_so_hieu(self):
        from src.rag.reports.worker import _nhan_bia

        r = self._result({"doc_nums": ["301/2026/NĐ-CP", "63/2024/NĐ-CP"]})
        assert _nhan_bia(self._job("b"), r) == "301/2026/NĐ-CP, 63/2024/NĐ-CP"

    def test_nhan_bia_cat_bot_khi_qua_nhieu_so_hieu(self):
        from src.rag.reports.worker import _nhan_bia

        r = self._result({"doc_nums": [f"{i}/2026/NĐ-CP" for i in range(6)]})
        assert _nhan_bia(self._job("b"), r).endswith("…")

    def test_nhan_bia_cua_a_va_c_la_ten_nganh(self):
        from src.rag.reports.worker import _nhan_bia

        job = self._job("c", vsic_code="Q", industry="Y tế và trợ giúp xã hội")
        assert _nhan_bia(job, self._result()) == "Q · Y tế và trợ giúp xã hội"

    def test_thieu_ca_ma_lan_ten_thi_khong_de_bia_trong(self):
        from src.rag.reports.worker import _nhan_bia

        assert _nhan_bia(self._job("a"), self._result()) == "Chưa xác định"

    def test_dung_duoc_pdf_that(self, tmp_path):
        from src.rag.reports.worker import _build_pdf

        md = tmp_path / "bc.md"
        md.write_text("# Thử\n\nMột đoạn.", encoding="utf-8")
        out = _build_pdf(self._job("a", vsic_code="K", industry="Tài chính"),
                         md, self._result())
        assert out and Path(out).exists() and Path(out).suffix == ".pdf"
        assert Path(out).stat().st_size > 1000

    def test_loi_dung_pdf_khong_lam_job_that_bai(self, tmp_path, monkeypatch):
        """Markdown đã qua cổng rồi — mất PDF là mất một định dạng, không mất
        nội dung. Nhưng phải trả None để bên gọi biết mà đừng ghi đường dẫn.
        """
        import src.utils.report_pdf as rp
        from src.rag.reports.worker import _build_pdf

        def no(*a, **k):
            raise RuntimeError("thiếu font")
        monkeypatch.setattr(rp, "build_report_pdf", no)

        md = tmp_path / "bc.md"
        md.write_text("# X", encoding="utf-8")
        assert _build_pdf(self._job("a"), md, self._result()) is None


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


class TestDanhSachSoHieuHopLe:
    """Danh sách số hiệu phải nổi bật, không chìm trong JSON.

    Đo được: báo cáo ngành Y tế dẫn "Luật số 51/2024/QH15" và "Nghị quyết
    66.18/2026/NQ-CP" — cả hai không có trong ngữ cảnh, mô hình lấy từ kiến
    thức nền. Ngữ cảnh lúc đó KHÔNG mỏng (22 văn bản, ngang ngành chạy trót
    lọt), nên nguyên nhân là danh sách khó thấy giữa 22 bản ghi × 15 trường.
    """

    def _payload(self):
        return {
            "danh_sach_van_ban": [{"doc_num": "292/2026/NĐ-CP"},
                                  {"doc_num": "83/2015/QH13"}],
            "van_ban_bi_tac_dong": [{"doc_num": "63/2024/NĐ-CP"}],
        }

    def test_liet_ke_ca_van_ban_moi_va_van_ban_bi_tac_dong(self):
        from src.rag.reports.generators import _danh_sach_so_hieu

        out = _danh_sach_so_hieu(self._payload())
        for n in ("292/2026/NĐ-CP", "83/2015/QH13", "63/2024/NĐ-CP"):
            assert n in out
        assert "3 văn bản" in out

    def test_khong_trung_lap_va_sap_xep_on_dinh(self):
        from src.rag.reports.generators import _danh_sach_so_hieu

        p = {"danh_sach_van_ban": [{"doc_num": "A"}, {"doc_num": "A"}],
             "van_ban_bi_tac_dong": [{"doc_num": "A"}]}
        assert _danh_sach_so_hieu(p).count("  A\n") == 1

    def test_rong_thi_khong_chen_khoi_thua(self):
        from src.rag.reports.generators import _danh_sach_so_hieu

        assert _danh_sach_so_hieu({}) == ""

    def test_noi_ro_phai_sao_chep_nguyen_van(self):
        """Lỗi đã gặp là BÓP MÉO số hiệu ("66.18/2026/NQ-CP"), không phải bịa
        hoàn toàn — nên chỉ dẫn phải cấm ghép và rút gọn.
        """
        from src.rag.reports.generators import _danh_sach_so_hieu

        out = _danh_sach_so_hieu(self._payload())
        assert "NGUYÊN VĂN" in out
        assert "Không ghép" in out

    def test_co_trong_message_gui_mo_hinh(self):
        from src.rag.reports.generators import _user_message

        msg = _user_message({"NGANH": "K"}, self._payload(), ["ghi chú"])
        assert "DANH SÁCH SỐ HIỆU ĐƯỢC PHÉP TRÍCH DẪN" in msg
        # Phải nằm SAU khối JSON và TRƯỚC phần lưu ý — chỗ mô hình đọc cuối.
        assert msg.index("DANH SÁCH SỐ HIỆU") > msg.index("DỮ LIỆU THỰC TẾ")
        assert msg.index("DANH SÁCH SỐ HIỆU") < msg.index("LƯU Ý QUAN TRỌNG")


class TestChanTrangHopTac:
    """Lời ngỏ hợp tác ở chân trang."""

    def _dung(self, tmp_path, **kw):
        from pypdf import PdfReader

        from src.utils.report_pdf import ReportMeta, build_report_pdf
        out = tmp_path / "t.pdf"
        build_report_pdf("### MỤC\n\n" + ("Một đoạn. " * 300), out,
                         ReportMeta(industry="Thử", period="Kỳ", cutoff="12/08/2026", **kw))
        return "\n".join(p.extract_text() or "" for p in PdfReader(str(out)).pages)

    def test_loi_ngo_hien_ra_lam_phu_de(self, tmp_path):
        """partner_pitch phải hiện ở đâu đó, không chỉ làm công tắc bật/tắt.

        Bản trước chỉ dùng nó để quyết định có dựng khối hay không, nên người
        sửa report_branding.json gõ câu chào mời vào một chỗ vô dụng.
        """
        txt = self._dung(tmp_path, partner_title="ĐỒNG HÀNH",
                         partner_pitch="Tìm công ty luật đồng hành.")
        assert "Tìm công ty luật đồng hành." in txt.replace("\n", " ")

    def test_khong_co_loi_ngo_thi_lui_ve_chan_trang_gon(self, tmp_path):
        """Để trống phải tắt được khối hợp tác mà không phải sửa code."""
        txt = self._dung(tmp_path, company="thongtincty")
        assert "HỢP TÁC" not in txt
        assert "thongtincty" in txt

    def test_phu_de_qua_dai_thi_bao_bang_ba_cham(self, tmp_path):
        """Không nuốt im lặng phần thừa — người viết phải biết là nó không vừa."""
        txt = self._dung(tmp_path, partner_title="T",
                         partner_pitch="Từ khoá rất dài. " * 30)
        assert "…" in txt

    def test_ngat_theo_tu_khong_cat_giua_tu(self, tmp_path):
        from src.utils.report_pdf import FONT, _ngat_dong, _register_fonts
        _register_fonts()
        goc = "Quý công ty luật tài trợ chi phí gửi thư điện tử hằng tháng"
        dong = _ngat_dong(goc, 160, FONT, 6.2, toi_da=2)
        assert len(dong) <= 2
        for d in dong:
            for tu in d.replace("…", "").split():
                assert tu in goc, f"cắt giữa từ: {tu!r}"


class TestKhoiThuNgo:
    """Khối thư ngỏ hợp tác ở cuối báo cáo."""

    def _meta(self, **kw):
        from src.utils.report_pdf import ReportMeta
        nen = dict(industry="Thử", period="Kỳ", cutoff="12/08/2026",
                   company="thongtincty",
                   partner_title="THƯ NGỎ HỢP TÁC TRUYỀN THÔNG",
                   partner_pitch="Tìm công ty luật đồng hành.",
                   partner_cta="HỢP TÁC CÙNG CHÚNG TÔI",
                   partner_contact="Liên hệ: thongtincty.com",
                   partner_col1_title="Chúng tôi cung cấp",
                   partner_col1=["Hệ thống rà soát tự động",
                                 "Báo cáo pháp lý theo ngành"],
                   partner_col2_title="Công ty luật nhận được",
                   partner_col2=["Thương hiệu trên mọi báo cáo",
                                 "Thông tin liên hệ khách tiềm năng"])
        nen.update(kw)
        return ReportMeta(**nen)

    def _txt(self, tmp_path, meta):
        from pypdf import PdfReader

        from src.utils.report_pdf import build_report_pdf
        out = tmp_path / "t.pdf"
        build_report_pdf("### MỤC\n\n" + ("Một đoạn. " * 120), out, meta)
        return "\n".join(p.extract_text() or "" for p in PdfReader(str(out)).pages)

    def test_in_o_cuoi_bao_cao_khong_lap_moi_trang(self, tmp_path):
        """Khối chiếm gần một phần ba trang; lặp mỗi trang thì báo cáo thành tờ rơi."""
        txt = self._txt(tmp_path, self._meta())
        assert txt.count("THƯ NGỎ HỢP TÁC TRUYỀN THÔNG") == 1

    def test_hai_cot_gia_tri_deu_hien(self, tmp_path):
        """Hai cột lấy từ report_branding.json; nơi gọi quên truyền thì chúng
        biến mất mà khối vẫn dựng bình thường — đã xảy ra thật."""
        txt = self._txt(tmp_path, self._meta())
        for c in ("Chúng tôi cung cấp", "Công ty luật nhận được",
                  "Hệ thống rà soát tự động", "Thương hiệu trên mọi báo cáo"):
            assert c in txt, c

    def test_chieu_cao_tang_theo_so_muc(self, tmp_path):
        """Cố định chiều cao thì mục dài tràn ra ngoài và đè lên dòng liên hệ."""
        from src.utils.report_pdf import KhoiThuNgo, _register_fonts
        _register_fonts()
        it = KhoiThuNgo(self._meta(partner_col1=["Một mục"]), 480)
        nhieu = KhoiThuNgo(self._meta(
            partner_col1=[f"Mục số {i} viết dài để phải xuống dòng thứ hai" for i in range(4)]), 480)
        assert nhieu.height > it.height

    def test_khong_co_loi_ngo_thi_khong_co_khoi(self, tmp_path):
        txt = self._txt(tmp_path, self._meta(partner_pitch=""))
        assert "THƯ NGỎ" not in txt
        assert "HỢP TÁC CÙNG CHÚNG TÔI" not in txt

    def test_anh_thieu_thi_van_dung_duoc(self, tmp_path, monkeypatch):
        """Thiếu file ảnh không được làm chết cả bản PDF."""
        from src.utils import report_pdf
        monkeypatch.setattr(report_pdf.ReportMeta, "anh_hop_tac", lambda self: None)
        assert "THƯ NGỎ HỢP TÁC TRUYỀN THÔNG" in self._txt(tmp_path, self._meta())
