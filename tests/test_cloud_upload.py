"""Nhóm — đẩy file lên mây và hàng đợi thử lại.

Lỗi gốc muốn chặn: upload hỏng một phần nhưng bên gọi tưởng đã xong rồi xoá
file local. Khi đó bản gốc mất mà trên mây cũng không có — không có đường phục
hồi nào.
"""
import pytest

from src.storage import cloud_drive
from src.storage.cloud_drive import UploadOutcome
from src.storage.database import (
    clear_upload_queue,
    enqueue_upload,
    pending_uploads,
    upsert_document,
)
from src.utils import disk_guard


class TestKetQuaUpload:
    def test_du_file_moi_tinh_la_xong(self):
        assert UploadOutcome("gdrive", uploaded=["docx", "metadata"]).ok

    def test_thieu_mot_file_la_chua_xong(self):
        """Đánh dấu đã đồng bộ khi còn thiếu file nghĩa là cho phép xoá bản gốc."""
        assert not UploadOutcome("gdrive", uploaded=["docx"], failed=["metadata"]).ok

    def test_khong_len_duoc_gi_la_chua_xong(self):
        assert not UploadOutcome("gdrive").ok


class TestThoatKyTuTruyVanDrive:
    """Tên thư mục lấy từ số hiệu, mà số hiệu là dữ liệu bên ngoài đưa vào.

    Ba văn bản trong kho thật có số hiệu bắt đầu bằng dấu nháy đơn — Bộ Tư pháp
    trả về đúng như vậy. Nhét thẳng vào `name='...'` làm truy vấn Drive vỡ cú
    pháp và trả HTTP 400, nên riêng ba văn bản đó không lên được mây trong khi
    1020 văn bản khác đều xong. Hỏng lặng lẽ đúng kiểu khó thấy nhất.
    """

    def test_dau_nhay_don_duoc_thoat(self):
        from src.storage.gdrive import _escape_query_value

        assert _escape_query_value("'18/2024/TT-BCT") == "\\'18/2024/TT-BCT"

    def test_dau_cheo_nguoc_thoat_truoc(self):
        """Thoát nháy trước rồi mới thoát chéo sẽ thoát nhầm chính dấu chéo
        vừa thêm vào, biến \\' thành \\\\' và lại vỡ truy vấn.
        """
        from src.storage.gdrive import _escape_query_value

        assert _escape_query_value("a\\b") == "a\\\\b"
        assert _escape_query_value("a\\'b") == "a\\\\\\'b"

    @pytest.mark.parametrize("value", ["", None])
    def test_rong_khong_no(self, value):
        from src.storage.gdrive import _escape_query_value

        assert _escape_query_value(value) == ""

    def test_ten_binh_thuong_khong_bi_doi(self):
        from src.storage.gdrive import _escape_query_value

        assert _escape_query_value("18_2024_TT-BCT") == "18_2024_TT-BCT"


class TestChonNoiLuuTru:
    def test_doc_tu_bien_cau_hinh(self, monkeypatch):
        monkeypatch.setattr(cloud_drive, "CLOUD_DRIVE_PROVIDER", "gdrive")
        assert cloud_drive.active_provider() == "gdrive"

    def test_gia_tri_la_thi_lui_ve_lark_chu_khong_no(self, monkeypatch):
        monkeypatch.setattr(cloud_drive, "CLOUD_DRIVE_PROVIDER", "dropbox")
        assert cloud_drive.active_provider() == "lark"

    def test_van_ban_ngu_canh_MAC_DINH_van_len_drive(self, monkeypatch):
        """Yêu cầu vận hành: mọi văn bản tải về đều phải lưu Drive trước.

        Văn bản kéo về theo dẫn chiếu được nêu đích danh trong yêu cầu đó —
        văn bản bị bãi bỏ là mắt xích giải thích vì sao quy định hiện hành ra
        đời, người đọc báo cáo cần mở được nó. Bản trước tự ý loại nhóm này.
        """
        monkeypatch.delenv("UPLOAD_CLOSURE_NODES", raising=False)
        monkeypatch.setattr(cloud_drive, "CLOUD_DRIVE_PROVIDER", "gdrive")
        monkeypatch.setattr(
            cloud_drive, "_upload_gdrive",
            lambda d: UploadOutcome("gdrive", uploaded=["metadata"]),
        )
        outcome = cloud_drive.upload_document(
            {"doc_num": "83/2015/QH13", "is_closure_node": True}
        )
        assert not outcome.skipped and outcome.ok

    def test_tat_duoc_bang_bien_moi_truong(self, monkeypatch):
        """Bao đóng có thể kéo về vài nghìn văn bản nền, mỗi bản 4 file."""
        monkeypatch.setenv("UPLOAD_CLOSURE_NODES", "false")
        monkeypatch.setattr(cloud_drive, "CLOUD_DRIVE_PROVIDER", "gdrive")
        outcome = cloud_drive.upload_document(
            {"doc_num": "83/2015/QH13", "is_closure_node": True}
        )
        assert outcome.skipped_reason == "van_ban_ngu_canh"

    def test_cau_hinh_doc_lai_luc_goi(self, monkeypatch):
        """Đóng băng lúc import thì tiến trình chạy dài ngày không nhận cấu
        hình mới, và phải khởi động lại mới đổi được.
        """
        from src import config

        monkeypatch.setenv("UPLOAD_CLOSURE_NODES", "false")
        assert not config.upload_closure_nodes()
        monkeypatch.setenv("UPLOAD_CLOSURE_NODES", "true")
        assert config.upload_closure_nodes()

    def test_van_ban_nghiep_vu_khong_bi_bo_qua(self, monkeypatch):
        monkeypatch.setattr(cloud_drive, "CLOUD_DRIVE_PROVIDER", "gdrive")
        monkeypatch.setattr(
            cloud_drive, "_upload_gdrive",
            lambda d: UploadOutcome("gdrive", uploaded=["metadata"]),
        )
        outcome = cloud_drive.upload_document(
            {"doc_num": "292/2026/NĐ-CP", "is_closure_node": False}
        )
        assert not outcome.skipped and outcome.ok


class TestHangDoiUpload:
    def _doc(self, session, doc_num="292/2026/NĐ-CP"):
        doc, _ = upsert_document(session, {
            "doc_num": doc_num, "title": "X", "agency_name": "Chính phủ",
        })
        session.flush()
        return doc

    def test_xep_hang_khi_upload_hong(self, master_session):
        doc = self._doc(master_session)
        enqueue_upload(master_session, doc, "gdrive", ["docx"], "mat mang")
        rows = pending_uploads(master_session)
        assert len(rows) == 1
        assert rows[0]["doc_num"] == doc.doc_num
        assert rows[0]["file_kinds"] == "docx"
        assert rows[0]["attempts"] == 1

    def test_hong_lan_nua_thi_tang_so_lan_chu_khong_chat_dong(self, master_session):
        doc = self._doc(master_session)
        enqueue_upload(master_session, doc, "gdrive", ["docx"], "loi 1")
        enqueue_upload(master_session, doc, "gdrive", ["docx", "metadata"], "loi 2")
        rows = pending_uploads(master_session)
        assert len(rows) == 1
        assert rows[0]["attempts"] == 2
        assert rows[0]["last_error"] == "loi 2"
        assert rows[0]["file_kinds"] == "docx,metadata"

    def test_hai_dich_luu_tru_la_hai_muc_rieng(self, master_session):
        doc = self._doc(master_session)
        enqueue_upload(master_session, doc, "gdrive", ["docx"], "x")
        enqueue_upload(master_session, doc, "lark", ["docx"], "x")
        assert len(pending_uploads(master_session)) == 2

    def test_len_may_du_thi_xoa_khoi_hang_doi(self, master_session):
        doc = self._doc(master_session)
        enqueue_upload(master_session, doc, "gdrive", ["docx"], "x")
        clear_upload_queue(master_session, doc.doc_key, "gdrive")
        assert pending_uploads(master_session) == []


class TestChotChanDungLuong:
    def test_con_nhieu_cho_thi_qua(self, tmp_path):
        assert disk_guard.check(min_free_gb=0.001, path=tmp_path).ok

    def test_cham_nguong_thi_dung_co_trat_tu(self, tmp_path):
        """Đĩa đầy giữa lúc SQLite đang ghi có thể làm hỏng cơ sở dữ liệu."""
        with pytest.raises(disk_guard.DiskSpaceExhausted):
            disk_guard.ensure_space(min_free_gb=10_000_000, path=tmp_path)

    def test_thong_bao_neu_ro_con_bao_nhieu(self, tmp_path):
        msg = disk_guard.check(min_free_gb=5, path=tmp_path).message()
        assert "GB" in msg and "ngưỡng dừng" in msg
