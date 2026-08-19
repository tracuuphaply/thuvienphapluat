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


class TestLienKetDangCongKhai:
    """Liên kết Drive được ĐĂNG LÊN TRANG CÔNG KHAI, nên nó là dữ liệu rời tay.

    Đã lọt thật: 7 trang văn bản trên repo công khai mang chuỗi
    `?usp=drivesdk&ouid=103518860918943299966` — `ouid` là mã tài khoản Google
    của người tải lên. Bắt được trước khi đẩy, nhưng chỉ vì soát tay; nhóm test
    này để lần sau máy bắt.
    """

    def test_dung_URL_tu_ID_chu_khong_lay_webViewLink(self):
        from src.storage.gdrive import lien_ket_cong_khai

        assert (lien_ket_cong_khai("1AbC_dEf-2345")
                == "https://drive.google.com/file/d/1AbC_dEf-2345/view")

    def test_khong_mang_theo_ma_tai_khoan(self):
        """`webViewLink` của file Office luôn kèm ouid; URL dựng tay thì không."""
        from src.storage.gdrive import lien_ket_cong_khai

        assert "ouid" not in lien_ket_cong_khai("1AbC_dEf-2345")

    def test_khong_mang_theo_tham_so_truy_vet_nao(self):
        """`usp=drivesdk` vô hại nhưng nó là dấu hiệu link chưa qua tay mình —
        và chính chỗ đó là chỗ ouid đi kèm."""
        from src.storage.gdrive import lien_ket_cong_khai

        assert "?" not in lien_ket_cong_khai("1AbC_dEf-2345")


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


class TestThuLaiKhiBiGioiHanTocDo:
    """Google trả giới hạn tốc độ dưới dạng 403, không phải 429.

    Bộ thử lại cũ chỉ xét mã trạng thái nên coi mọi 403 là lỗi vĩnh viễn và ném
    ngay — 22 văn bản rơi vào hàng đợi lỗi trong một đợt upload dù chỉ cần chờ
    vài giây. Nhưng cũng không được gộp chung mọi 403: hết dung lượng và sai
    quyền là vĩnh viễn, thử lại chỉ tốn thời gian.
    """

    def _loi(self, status: int, reason: str):
        import json as _json

        from googleapiclient.errors import HttpError

        class _Resp:
            def __init__(self, s):
                self.status = s
                self.reason = ""
        body = _json.dumps({"error": {"errors": [{"reason": reason}],
                                      "code": status}}).encode()
        return HttpError(_Resp(status), body)

    @pytest.mark.parametrize("reason", [
        "rateLimitExceeded", "userRateLimitExceeded", "sharingRateLimitExceeded",
    ])
    def test_nhan_dien_403_qua_toc_do(self, reason):
        from src.storage.gdrive import _qua_toc_do

        assert _qua_toc_do(self._loi(403, reason))

    @pytest.mark.parametrize("reason", [
        "storageQuotaExceeded", "insufficientFilePermissions", "forbidden",
    ])
    def test_403_vinh_vien_khong_bi_nham_la_qua_toc_do(self, reason):
        from src.storage.gdrive import _qua_toc_do

        assert not _qua_toc_do(self._loi(403, reason))

    def test_than_loi_khong_doc_duoc_thi_do_tren_chuoi(self):
        """Thà thử lại thừa một lần còn hơn bỏ rơi văn bản vì lỗi parse JSON."""
        from googleapiclient.errors import HttpError

        from src.storage.gdrive import _qua_toc_do

        class _Resp:
            status = 403
            reason = "Rate Limit Exceeded"
        assert _qua_toc_do(HttpError(_Resp(), b"khong phai json"))

    def test_thu_lai_that_su_khi_qua_toc_do(self, monkeypatch):
        from src.storage import gdrive

        monkeypatch.setattr(gdrive.time, "sleep", lambda s: None)
        lan = {"n": 0}

        def hay_hay_hong():
            lan["n"] += 1
            if lan["n"] < 3:
                raise self._loi(403, "userRateLimitExceeded")
            return "xong"

        assert gdrive._retry_api_call(hay_hay_hong) == "xong"
        assert lan["n"] == 3

    def test_khong_thu_lai_khi_het_dung_luong(self, monkeypatch):
        from googleapiclient.errors import HttpError

        from src.storage import gdrive

        monkeypatch.setattr(gdrive.time, "sleep", lambda s: None)
        lan = {"n": 0}

        def luon_hong():
            lan["n"] += 1
            raise self._loi(403, "storageQuotaExceeded")

        with pytest.raises(HttpError):
            gdrive._retry_api_call(luon_hong)
        assert lan["n"] == 1, "lỗi vĩnh viễn mà vẫn thử lại là phí thời gian"


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


class TestDanhSachChoUpload:
    """Nhánh --upload-only phải hỏi CÙNG một nguồn cấu hình với upload_document.

    Bản trước chép cứng điều kiện loại văn bản nền vào câu truy vấn. Sau khi
    đổi mặc định sang "có đẩy", nhánh này vẫn báo "0 văn bản chờ upload" trong
    khi kho có 3.443 văn bản chưa lên — hỏng lặng lẽ, và lặng lẽ vì nó báo
    thành công.
    """

    def _kho(self, master_session):
        from src.storage.database import upsert_document

        for i, nen in enumerate([False, True, True]):
            upsert_document(master_session, {
                "doc_num": f"{i}/2026/NĐ-CP", "title": "x",
                "agency_name": "Chính phủ", "is_closure_node": nen,
            })
        master_session.commit()

    def _dem(self, session):
        from src.config import upload_closure_nodes
        from src.storage.models import Document

        q = session.query(Document).filter(Document.cloud_synced_at.is_(None))
        if not upload_closure_nodes():
            q = q.filter((Document.is_closure_node.is_(None))
                         | (Document.is_closure_node == False))  # noqa: E712
        return q.count()

    def test_mac_dinh_gom_ca_van_ban_nen(self, master_session, monkeypatch):
        monkeypatch.delenv("UPLOAD_CLOSURE_NODES", raising=False)
        self._kho(master_session)
        assert self._dem(master_session) == 3

    def test_tat_thi_chi_con_van_ban_nghiep_vu(self, master_session, monkeypatch):
        monkeypatch.setenv("UPLOAD_CLOSURE_NODES", "false")
        self._kho(master_session)
        assert self._dem(master_session) == 1

    def test_truy_van_trong_main_khong_chep_cung_dieu_kien(self):
        """Chặn việc điều kiện lại bị chép ra chỗ khác."""
        from src.config import PROJECT_ROOT

        src = (PROJECT_ROOT / "src" / "main.py").read_text(encoding="utf-8")
        i = src.index("def run_upload_only")
        than = src[i:i + 3000]
        assert "upload_closure_nodes()" in than, (
            "run_upload_only phải hỏi config chứ không tự quyết"
        )


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
