"""Nhóm #3 — số hiệu văn bản không duy nhất toàn quốc.

Lỗi gốc: UNIQUE(doc_num) coi "67/2026/QĐ-UBND" của Hải Phòng và của Đắk Lắk là
cùng một văn bản. Bản thứ hai trở đi bị coi là "đã biết" rồi bỏ qua im lặng —
đo trên một lần quét 6.906 văn bản thì 4.211 bản sẽ bị nuốt.
"""
import pytest

from src.storage.database import (
    get_document_by_doc_key,
    get_document_by_doc_num,
    get_documents_by_doc_num,
    make_doc_key,
    resolve_existing_document,
    upsert_document,
)


class TestMakeDocKey:
    def test_cung_so_hieu_khac_co_quan_ra_khoa_khac_nhau(self):
        a = make_doc_key("67/2026/QĐ-UBND", "UBND tỉnh Hải Phòng")
        b = make_doc_key("67/2026/QĐ-UBND", "UBND tỉnh Đắk Lắk")
        assert a != b

    def test_chuan_hoa_khoang_trang_va_hoa_thuong(self):
        assert make_doc_key("67/2026/QĐ-UBND", "UBND  tỉnh   Hải Phòng") == \
               make_doc_key("67/2026/qđ-ubnd", "ubnd tỉnh hải phòng")

    def test_chu_D_co_gach_duoc_ha_thap_dung(self):
        """lower() của SQLite chỉ xử lý ASCII: lower('QĐ') = 'qĐ'.

        Tính doc_key bằng SQL trong migration tạo ra khoá mà runtime không khớp
        lại được → mỗi lần cào lại sinh một bản ghi trùng. Thực tế đã lệch 227/314.
        """
        assert "Đ" not in make_doc_key("67/2026/QĐ-UBND", "Đắk Lắk")
        assert make_doc_key("67/2026/QĐ-UBND", "Đắk Lắk") == "67/2026/qđ-ubnd::đắk lắk"

    def test_thieu_co_quan_van_ra_khoa_dung_dinh_dang(self):
        assert make_doc_key("01/2026/NĐ-CP", None) == "01/2026/nđ-cp::"


class TestUpsertKhongNuotVanBan:
    def _doc(self, agency, **kw):
        d = {"doc_num": "67/2026/QĐ-UBND", "title": f"Quyết định của {agency}",
             "agency_name": agency}
        d.update(kw)
        return d

    def test_ba_tinh_cung_so_hieu_deu_duoc_luu(self, master_session):
        tinh = ["UBND tỉnh Hải Phòng", "UBND tỉnh Đắk Lắk", "UBND tỉnh Quảng Trị"]
        for t in tinh:
            _, moi = upsert_document(master_session, self._doc(t))
            master_session.commit()
            assert moi, f"{t} bị coi là trùng và bỏ qua"
        assert len(get_documents_by_doc_num(master_session, "67/2026/QĐ-UBND")) == 3

    def test_cung_tinh_thi_gop_chu_khong_nhan_ban(self, master_session):
        upsert_document(master_session, self._doc("UBND tỉnh Hải Phòng"))
        master_session.commit()
        _, moi = upsert_document(
            master_session, self._doc("UBND tỉnh Hải Phòng", eff_status="Còn hiệu lực")
        )
        master_session.commit()
        assert not moi
        assert len(get_documents_by_doc_num(master_session, "67/2026/QĐ-UBND")) == 1

    def test_gop_bang_moj_id_du_co_quan_ghi_khac(self, master_session):
        """Id của nguồn là bằng chứng mạnh nhất, thắng cả khác biệt tên cơ quan."""
        upsert_document(master_session, self._doc("UBND tỉnh Hải Phòng", moj_id="abc-123"))
        master_session.commit()
        _, moi = upsert_document(
            master_session, self._doc("UBND TP Hải Phòng", moj_id="abc-123")
        )
        master_session.commit()
        assert not moi

    def test_co_quan_lo_dien_sau_thi_khoa_duoc_tinh_lai(self, master_session):
        doc, _ = upsert_document(master_session, {
            "doc_num": "88/2026/QĐ-UBND", "title": "Chưa rõ cơ quan",
        })
        master_session.commit()
        assert doc.doc_key == "88/2026/qđ-ubnd::"

        doc2, moi = upsert_document(master_session, {
            "doc_num": "88/2026/QĐ-UBND", "title": "Đã rõ cơ quan",
            "agency_name": "UBND tỉnh Lào Cai",
        })
        master_session.commit()
        assert not moi, "phải nhận ra là cùng văn bản, không tạo bản mới"
        assert doc2.id == doc.id
        assert doc2.doc_key == "88/2026/qđ-ubnd::ubnd tỉnh lào cai"

    def test_khong_gop_bua_khi_nhap_nhang(self, master_session):
        """Đã có 2 bản cùng số hiệu chưa rõ cơ quan thì không được đoán."""
        for t in ["A", "B"]:
            upsert_document(master_session, {
                "doc_num": "99/2026/QĐ-UBND", "title": t,
                "agency_name": f"UBND tỉnh {t}",
            })
        master_session.commit()
        assert get_document_by_doc_num(master_session, "99/2026/QĐ-UBND") is None


class TestResolveExistingDocument:
    def test_uu_tien_moj_id_hon_doc_key(self, master_session):
        doc, _ = upsert_document(master_session, {
            "doc_num": "10/2026/NĐ-CP", "title": "A",
            "agency_name": "Chính phủ", "moj_id": "uuid-1",
        })
        master_session.commit()
        found = resolve_existing_document(master_session, {
            "doc_num": "SỐ HIỆU KHÁC HẲN", "moj_id": "uuid-1",
        })
        assert found is not None and found.id == doc.id

    def test_khong_tim_thay_thi_tra_none(self, master_session):
        assert resolve_existing_document(master_session, {
            "doc_num": "chua/co/bao/gio", "agency_name": "X",
        }) is None

    def test_tra_cuu_theo_doc_key(self, master_session):
        upsert_document(master_session, {
            "doc_num": "11/2026/TT-BTC", "title": "T", "agency_name": "Bộ Tài chính",
        })
        master_session.commit()
        key = make_doc_key("11/2026/TT-BTC", "Bộ Tài chính")
        assert get_document_by_doc_key(master_session, key) is not None


class TestInitDbTuChuaLanh:
    """init_db phải tự thêm doc_key cho kho cũ, nếu không pipeline gãy khi INSERT."""

    def _legacy_db(self, tmp_path):
        """Dựng một DB kiểu cũ: có UNIQUE(doc_num), chưa có doc_key."""
        import sqlite3
        p = tmp_path / "legacy.db"
        c = sqlite3.connect(p)
        c.executescript("""
            CREATE TABLE documents (
                id INTEGER NOT NULL,
                doc_num VARCHAR(100) NOT NULL,
                title TEXT NOT NULL,
                agency_name VARCHAR(255),
                PRIMARY KEY (id),
                UNIQUE (doc_num)
            );
            INSERT INTO documents (doc_num, title, agency_name)
            VALUES ('67/2026/QĐ-UBND', 'Cũ', 'UBND tỉnh Đắk Lắk');
        """)
        c.commit(); c.close()
        return p

    def test_them_cot_va_dien_doc_key(self, tmp_path):
        import sqlite3
        from sqlalchemy import create_engine, text
        from src.storage.database import _ensure_doc_key

        p = self._legacy_db(tmp_path)
        conn = sqlite3.connect(p)
        conn.execute("ALTER TABLE documents ADD COLUMN doc_key VARCHAR(300)")
        conn.commit(); conn.close()

        engine = create_engine(f"sqlite:///{p}")
        with engine.connect() as conn:
            _ensure_doc_key(conn)
            key = conn.execute(text("SELECT doc_key FROM documents")).scalar()
        engine.dispose()

        assert key == "67/2026/qđ-ubnd::ubnd tỉnh đắk lắk", \
            "doc_key phải tính bằng hàm Python, không bằng lower() của SQLite"

    def test_canh_bao_khi_con_unique_doc_num(self, tmp_path, caplog):
        import logging
        import sqlite3
        from sqlalchemy import create_engine
        from src.storage.database import _ensure_doc_key

        p = self._legacy_db(tmp_path)
        conn = sqlite3.connect(p)
        conn.execute("ALTER TABLE documents ADD COLUMN doc_key VARCHAR(300)")
        conn.commit(); conn.close()

        engine = create_engine(f"sqlite:///{p}")
        with caplog.at_level(logging.WARNING):
            with engine.connect() as conn:
                _ensure_doc_key(conn)
        engine.dispose()

        assert "migrate_doc_key" in caplog.text, "phải chỉ rõ script cần chạy"
