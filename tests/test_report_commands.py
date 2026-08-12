"""
Lệnh điều khiển báo cáo qua Telegram.

Kiểm ở tầng lõi (không có Telegram, không async): mọi lệnh nhận session và trả
chuỗi, nên chạy được trên SQLite trong bộ nhớ.

Điều quan trọng nhất được chốt ở đây: KHÔNG lệnh nào sinh báo cáo tại chỗ.
Đường /report cũ gọi thẳng bộ sinh rồi xuất PDF, tức đi vòng qua cổng kiểm
trích dẫn — báo cáo có số hiệu bịa vẫn gửi được cho khách.
"""
from __future__ import annotations

import datetime
import inspect

import pytest
from sqlalchemy import text

from src.notification import report_commands as rc
from src.rag.reports import jobs
from src.storage.database import upsert_document


def _ma_thuc(src: str) -> str:
    """Mã nguồn sau khi bỏ docstring và chú thích."""
    import io, tokenize

    ra = []
    toks = tokenize.generate_tokens(io.StringIO(src).readline)
    truoc = tokenize.INDENT
    for tok in toks:
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and truoc in (
                tokenize.INDENT, tokenize.NEWLINE, tokenize.NL, tokenize.DEDENT):
            continue  # docstring
        ra.append(tok.string)
        if tok.type not in (tokenize.NL, tokenize.NEWLINE):
            truoc = tok.type
    return " ".join(ra)


def _job(session, **kw) -> int:
    nen = {"kind": "a", "status": jobs.QUEUED, "vsic_code": "K",
           "industry": "Tài chính", "priority": 0.0,
           "dedupe_key": f"k{id(kw)}{len(kw)}"}
    nen.update(kw)
    cols = ", ".join(nen)
    vals = ", ".join(f":{k}" for k in nen)
    session.execute(text(f"INSERT INTO report_jobs ({cols}) VALUES ({vals})"), nen)
    session.commit()
    return session.execute(text("SELECT last_insert_rowid()")).scalar()


class TestXepBaoCao:
    def test_xep_bao_cao_nganh(self, master_session):
        kq = rc.xep_bao_cao(master_session, "a", "K")
        master_session.commit()
        assert "Đã xếp hàng" in kq.van_ban
        row = master_session.execute(text(
            "SELECT kind, vsic_code, status, trigger_reason FROM report_jobs"
        )).mappings().first()
        assert (row["kind"], row["vsic_code"], row["status"]) == ("a", "K", "QUEUED")
        assert row["trigger_reason"] == "telegram"

    def test_ma_nganh_khong_ton_tai_thi_bao_loi(self, master_session):
        kq = rc.xep_bao_cao(master_session, "a", "ZZ")
        assert "Không có ngành" in kq.van_ban
        assert master_session.execute(
            text("SELECT COUNT(*) FROM report_jobs")).scalar() == 0

    def test_ma_nganh_chu_thuong_van_nhan(self, master_session):
        assert "Đã xếp hàng" in rc.xep_bao_cao(master_session, "a", "k").van_ban

    def test_thieu_ma_nganh_thi_nhac(self, master_session):
        assert "Thiếu mã ngành" in rc.xep_bao_cao(master_session, "a", "").van_ban

    def test_khong_xep_tay_duoc_bao_cao_c(self, master_session):
        """(c) tiêu thụ sidecar của (b); xếp tay là tạo job chắc chắn thất bại."""
        kq = rc.xep_bao_cao(master_session, "c", "K")
        assert "không đặt tay được" in kq.van_ban
        assert master_session.execute(
            text("SELECT COUNT(*) FROM report_jobs")).scalar() == 0

    def test_xep_trung_trong_ngay_thi_bao_da_co(self, master_session):
        rc.xep_bao_cao(master_session, "a", "K")
        master_session.commit()
        kq = rc.xep_bao_cao(master_session, "a", "K")
        assert "đã có trong hàng đợi" in kq.van_ban

    def test_bao_cao_b_khong_co_van_ban_moi_thi_khong_xep(self, master_session):
        kq = rc.xep_bao_cao(master_session, "b")
        assert "Không có văn bản mới" in kq.van_ban
        assert master_session.execute(
            text("SELECT COUNT(*) FROM report_jobs")).scalar() == 0

    def test_bao_cao_b_gom_van_ban_moi(self, master_session):
        upsert_document(master_session, {
            "doc_num": "01/2026/NĐ-CP", "title": "Nghị định thử",
            "agency_name": "Chính phủ", "moj_id": "1", "event_type": "A",
            "issue_date": datetime.date(2026, 1, 5)})
        master_session.commit()

        kq = rc.xep_bao_cao(master_session, "b")
        master_session.commit()
        assert "Đã xếp hàng" in kq.van_ban
        # subject_keys giữ doc_key ("số hiệu::cơ quan", đã hạ chữ thường), không
        # phải số hiệu trần: số hiệu chỉ duy nhất trong phạm vi một cơ quan.
        keys = master_session.execute(text(
            "SELECT subject_keys FROM report_jobs")).scalar()
        assert "01/2026/nđ-cp::chính phủ" in keys


class TestQuanLy:
    def test_hang_doi_rong(self, master_session):
        assert "trống" in rc.danh_sach_hang_doi(master_session).van_ban

    def test_hang_doi_liet_ke_va_dem(self, master_session):
        _job(master_session, dedupe_key="a1")
        _job(master_session, dedupe_key="a2", status=jobs.DONE)
        out = rc.danh_sach_hang_doi(master_session).van_ban
        assert "#1" in out and "#2" in out
        assert "đang chờ" in out and "xong" in out

    def test_xem_job_khong_ton_tai(self, master_session):
        assert "Không có báo cáo" in rc.chi_tiet_job(master_session, 999).van_ban

    def test_xem_job_bi_chan_giai_thich_ro(self, master_session):
        """Bị chặn là tình huống người dùng cần hiểu, không phải một mã lỗi."""
        i = _job(master_session, status=jobs.BLOCKED_CITATION,
                 citation_total=20, citation_missing=3, dedupe_key="b1")
        out = rc.chi_tiet_job(master_session, i).van_ban
        assert "3/20" in out
        assert "KHÔNG gửi đi" in out

    def test_xem_job_xong_thi_dinh_kem_pdf(self, master_session, tmp_path):
        pdf = tmp_path / "bc.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        i = _job(master_session, status=jobs.DONE, output_pdf_path=str(pdf),
                 dedupe_key="c1")
        kq = rc.chi_tiet_job(master_session, i)
        assert kq.file_dinh_kem == str(pdf)

    def test_pdf_mat_tren_dia_thi_khong_dinh_kem(self, master_session):
        i = _job(master_session, status=jobs.DONE,
                 output_pdf_path="/khong/ton/tai.pdf", dedupe_key="c2")
        assert rc.chi_tiet_job(master_session, i).file_dinh_kem is None


class TestHuy:
    def test_huy_job_dang_cho(self, master_session):
        i = _job(master_session, dedupe_key="h1")
        assert "Đã huỷ" in rc.huy_job(master_session, i).van_ban
        assert master_session.execute(text(
            "SELECT status FROM report_jobs WHERE id = :i"), {"i": i}
        ).scalar() == rc.CANCELLED

    def test_khong_huy_job_dang_chay(self, master_session):
        """Đánh dấu huỷ không dừng được lời gọi mô hình đang dở.

        Chỉ làm trạng thái trong DB nói sai về thực tế, rồi worker vẫn ghi đè
        kết quả khi xong.
        """
        i = _job(master_session, status=jobs.RUNNING, dedupe_key="h2")
        assert "không huỷ giữa chừng" in rc.huy_job(master_session, i).van_ban
        assert master_session.execute(text(
            "SELECT status FROM report_jobs WHERE id = :i"), {"i": i}
        ).scalar() == jobs.RUNNING

    def test_huy_job_da_xong_thi_bao_khong_con_gi(self, master_session):
        i = _job(master_session, status=jobs.DONE, dedupe_key="h3")
        assert "không còn gì để huỷ" in rc.huy_job(master_session, i).van_ban

    def test_trang_thai_huy_khac_skipped(self, master_session):
        """SKIPPED nghĩa là máy tự bỏ vì dưới ngưỡng; CANCELLED là người bỏ.

        Gộp hai thứ thì về sau không phân biệt được ai đã bỏ báo cáo đó.
        """
        assert rc.CANCELLED != jobs.SKIPPED


class TestKhongDiVongCongTrichDan:
    def test_khong_lenh_nao_goi_thang_bo_sinh_bao_cao(self):
        """Mọi lệnh phải xếp hàng, để worker chạy và cổng trích dẫn còn hiệu lực.

        Đường /report cũ gọi generate_compliance_report rồi xuất PDF bằng
        pdf_exporter, tức KHÔNG qua check_citations — báo cáo có số hiệu bịa vẫn
        gửi được cho khách hàng.
        """
        # Bỏ docstring và chú thích trước khi quét. Bản đầu quét thẳng mã nguồn
        # nên khớp vào chính đoạn văn giải thích vì sao KHÔNG được gọi những hàm
        # này — test đỏ vì lời cảnh báo, không vì hành vi. Đã mắc lỗi cùng dạng
        # ở hai test khác trong repo.
        src = _ma_thuc(inspect.getsource(rc))
        cam = ("generate_compliance_report", "generate_industry_report",
               "generate_update_report", "convert_md_to_pdf", "build_report_pdf")
        for ten in cam:
            assert ten not in src, (
                f"report_commands gọi {ten} — đi vòng qua cổng kiểm trích dẫn"
            )

    def test_lenh_chi_dung_hang_doi(self):
        src = _ma_thuc(inspect.getsource(rc.xep_bao_cao))
        # Tokenizer tách "jobs.enqueue" thành ba token nên chốt trên tên hàm.
        assert "enqueue" in src


class TestBoBanTinCaoDuLieu:
    def test_pipeline_khong_con_gui_ban_tin_cao(self):
        """Cào chạy ngầm; kết quả xem trên Drive, không nhắn Telegram.

        Bản tin cào là thông báo về công việc nội bộ của hệ thống — người đọc
        không quyết định gì từ nó, nên nó chỉ làm loãng kênh Telegram vốn để
        điều khiển và nhận báo cáo.
        """
        import pathlib

        src = _ma_thuc(pathlib.Path("src/main.py").read_text(encoding="utf-8"))
        for ten in ("send_daily_digest", "build_daily_digest"):
            assert ten not in src, f"src/main.py còn gọi {ten}"

    def test_van_giu_canh_bao_loi(self):
        """Bỏ bản tin cào KHÔNG có nghĩa là tắt cảnh báo lỗi.

        Pipeline chết mà im lặng thì hỏng nhiều ngày không ai biết.
        """
        import pathlib

        src = pathlib.Path("src/main.py").read_text(encoding="utf-8")
        assert "send_error_alert" in src

    def test_van_danh_dau_notified_at(self):
        """get_unnotified_documents() dựa vào cột này.

        Để NULL mãi thì mỗi lần chạy lại coi toàn bộ kho là chưa xử lý.
        """
        import pathlib

        src = pathlib.Path("src/main.py").read_text(encoding="utf-8")
        assert "notified_at = now" in src


class TestBoLenhTelegram:
    def test_moi_lenh_bao_cao_deu_dang_ky(self):
        import pathlib

        src = pathlib.Path(
            "src/notification/telegram_bot_server.py").read_text(encoding="utf-8")
        for lenh in ("baocao", "nganh", "hangdoi", "xem", "huy", "chay"):
            assert f'"{lenh}"' in src, f"chưa đăng ký /{lenh}"

    def test_lenh_cu_giu_lam_bi_danh(self):
        """/report và /industries im lặng biến mất thì trông như bot hỏng."""
        import pathlib

        src = pathlib.Path(
            "src/notification/telegram_bot_server.py").read_text(encoding="utf-8")
        assert '["baocao", "report"]' in src
        assert '["nganh", "industries"]' in src

    def test_bot_khong_con_duong_tat_qua_cong_trich_dan(self):
        """Bot không được gọi bộ sinh báo cáo hay bộ xuất PDF cũ.

        Đường /report cũ dùng generate_compliance_report + pdf_exporter, không
        qua check_citations — số hiệu bịa vẫn gửi được cho khách.
        """
        import pathlib

        src = _ma_thuc(pathlib.Path(
            "src/notification/telegram_bot_server.py").read_text(encoding="utf-8"))
        for ten in ("generate_compliance_report", "convert_md_to_pdf"):
            assert ten not in src, f"bot còn gọi {ten}"

    def test_khong_con_dung_bo_10_nganh_cu(self):
        """Cả hệ thống dùng 21 ngành VSIC; bot từng kẹt lại ở bộ 10 ngành."""
        import pathlib

        src = _ma_thuc(pathlib.Path(
            "src/notification/telegram_bot_server.py").read_text(encoding="utf-8"))
        assert "INDUSTRY_MAP" not in src


class TestHaiBanPDF:
    """Bản gửi khách và bản gửi đối tác, khác nhau đúng ở chân trang."""

    def _job_xong(self, session, tmp_path, ten_file: list[str]) -> int:
        for t in ten_file:
            (tmp_path / t).write_bytes(b"%PDF-1.4")
        return _job(session, status=jobs.DONE, dedupe_key=f"p{len(ten_file)}",
                    output_pdf_path=str(tmp_path / ten_file[0]))

    def test_co_ca_hai_ban_thi_gui_ca_hai(self, master_session, tmp_path):
        i = self._job_xong(master_session, tmp_path,
                           ["job1_khach.pdf", "job1_doitac.pdf"])
        kq = rc.chi_tiet_job(master_session, i)
        gui = [kq.file_dinh_kem, *kq.file_bo_sung]
        assert len(gui) == 2
        assert any("_khach" in g for g in gui)
        assert any("_doitac" in g for g in gui)
        assert "gửi doanh nghiệp" in kq.van_ban
        assert "gửi công ty luật" in kq.van_ban

    def test_ban_gui_khach_dung_dau(self, master_session, tmp_path):
        """Nếu người dùng chỉ mở file đầu tiên thì đó phải là bản không quảng bá."""
        i = self._job_xong(master_session, tmp_path,
                           ["job2_khach.pdf", "job2_doitac.pdf"])
        assert "_khach" in rc.chi_tiet_job(master_session, i).file_dinh_kem

    def test_chi_co_ban_khach_thi_khong_noi_gi_ve_ban_kia(self, master_session, tmp_path):
        i = self._job_xong(master_session, tmp_path, ["job3_khach.pdf"])
        kq = rc.chi_tiet_job(master_session, i)
        assert kq.file_bo_sung == []
        assert "gửi công ty luật" not in kq.van_ban

    def test_bao_cao_cu_mot_file_khong_hau_to_van_gui_duoc(self, master_session, tmp_path):
        """Báo cáo sinh trước khi tách hai bản chỉ có một file không hậu tố.

        Không xử lý thì mọi báo cáo cũ đột nhiên không tải về được nữa.
        """
        i = self._job_xong(master_session, tmp_path, ["job4.pdf"])
        kq = rc.chi_tiet_job(master_session, i)
        assert kq.file_dinh_kem.endswith("job4.pdf")
        assert kq.file_bo_sung == []

    def test_file_mat_tren_dia_thi_khong_dinh_kem(self, master_session, tmp_path):
        i = _job(master_session, status=jobs.DONE, dedupe_key="p9",
                 output_pdf_path=str(tmp_path / "khong_ton_tai_khach.pdf"))
        kq = rc.chi_tiet_job(master_session, i)
        assert kq.file_dinh_kem is None and kq.file_bo_sung == []
