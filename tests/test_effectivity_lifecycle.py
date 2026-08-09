"""Đề xuất #3 và #6 — vòng đời hiệu lực không được đóng băng, không được đoán bừa.

Lỗi gốc:
  - upsert_document chỉ ghi khi trường cũ rỗng → văn bản đã "Còn hiệu lực" thì
    vĩnh viễn không chuyển được sang "Hết hiệu lực"; document_status_history có 0 dòng.
  - validate_results loại luôn cả văn bản chỉ bị SỬA ĐỔI, và dùng từ vựng quan
    hệ không khớp với dữ liệu thật.
"""
import datetime

from src.rag.graph_traversal import (
    cascade_retrieve,
    effect_warnings,
    impact_analysis,
    validate_results,
)
from src.storage.database import REFRESHABLE_FIELDS, resolve_reference_targets, upsert_document
from src.storage.models import Document, DocumentReference, DocumentStatusHistory


class TestUpsertDocument:
    def _base(self, **kw):
        data = {
            "doc_num": "99/2026/NĐ-CP",
            "title": "Nghị định thử nghiệm",
            "eff_status": "Còn hiệu lực",
            "source_moj": True,
        }
        data.update(kw)
        return data

    def test_trang_thai_hieu_luc_duoc_cap_nhat(self, master_session):
        """Đây là lỗi nghiêm trọng nhất của tầng lưu trữ: trạng thái đóng băng."""
        doc, is_new = upsert_document(master_session, self._base())
        master_session.commit()
        assert is_new and doc.eff_status == "Còn hiệu lực"

        doc, is_new = upsert_document(
            master_session, self._base(eff_status="Hết hiệu lực toàn bộ")
        )
        master_session.commit()
        assert not is_new
        assert doc.eff_status == "Hết hiệu lực toàn bộ", "trạng thái vẫn bị đóng băng"

    def test_ghi_lich_su_khi_doi_trang_thai(self, master_session):
        upsert_document(master_session, self._base())
        master_session.commit()
        upsert_document(master_session, self._base(eff_status="Hết hiệu lực toàn bộ"))
        master_session.commit()

        rows = master_session.query(DocumentStatusHistory).all()
        assert len(rows) == 1
        assert rows[0].old_status == "Còn hiệu lực"
        assert rows[0].new_status == "Hết hiệu lực toàn bộ"
        assert rows[0].detected_by == "MOJ"

    def test_khong_ghi_lich_su_khi_trang_thai_khong_doi(self, master_session):
        upsert_document(master_session, self._base())
        master_session.commit()
        upsert_document(master_session, self._base())
        master_session.commit()
        assert master_session.query(DocumentStatusHistory).count() == 0

    def test_eff_to_va_ngay_thang_duoc_lam_moi(self, master_session):
        upsert_document(master_session, self._base())
        master_session.commit()
        doc, _ = upsert_document(
            master_session, self._base(eff_to=datetime.date(2026, 12, 31))
        )
        master_session.commit()
        assert doc.eff_to == datetime.date(2026, 12, 31)

    def test_truong_ngoai_whitelist_khong_bi_ghi_de(self, master_session):
        """Nguồn yếu không được đạp lên dữ liệu đã có của trường không thuộc vòng đời."""
        upsert_document(master_session, self._base(tvpl_url="https://goc.example/a"))
        master_session.commit()
        doc, _ = upsert_document(
            master_session, self._base(tvpl_url="https://khac.example/b")
        )
        master_session.commit()
        assert doc.tvpl_url == "https://goc.example/a"
        assert "tvpl_url" not in REFRESHABLE_FIELDS

    def test_eff_status_nam_trong_whitelist(self):
        for field in ("eff_status", "eff_to", "eff_from", "doc_type", "agency_name"):
            assert field in REFRESHABLE_FIELDS


class TestResolveReferenceTargets:
    def test_noi_lai_canh_treo_khi_van_ban_dich_ve_kho(self, master_session):
        src, _ = upsert_document(master_session, {"doc_num": "01/2026/NĐ-CP", "title": "A"})
        master_session.commit()
        master_session.add(
            DocumentReference(
                source_doc_id=src.id, target_doc_num="02/2026/NĐ-CP", relation_type="Bãi bỏ"
            )
        )
        master_session.commit()
        assert resolve_reference_targets(master_session) == 0  # đích chưa có

        tgt, _ = upsert_document(master_session, {"doc_num": "02/2026/NĐ-CP", "title": "B"})
        master_session.commit()
        assert resolve_reference_targets(master_session) == 1
        master_session.commit()

        edge = master_session.query(DocumentReference).first()
        assert edge.target_doc_id == tgt.id

    def test_noi_bang_moj_id_khi_so_hieu_lech_chuoi(self, master_session):
        """Payload đã ghi sẵn id chính xác của đích — dò theo chuỗi số hiệu là
        tự bỏ đi thông tin mạnh hơn.

        199 văn bản nền trong kho thật không có cạnh vào nào chỉ vì chuỗi số
        hiệu lệch (khoảng trắng, dấu nháy, tiền tố "Số ..."), nên không tính
        được độ sâu bao đóng của chúng.
        """
        src, _ = upsert_document(master_session, {"doc_num": "01/2026/NĐ-CP", "title": "A"})
        master_session.commit()
        master_session.add(DocumentReference(
            source_doc_id=src.id, target_doc_num="Số 02/2026/NĐ-CP",
            target_moj_id="777", relation_type="Căn cứ"))
        master_session.commit()

        tgt, _ = upsert_document(master_session, {
            "doc_num": "02/2026/NĐ-CP", "title": "B", "moj_id": "777"})
        master_session.commit()

        assert resolve_reference_targets(master_session) == 1
        master_session.commit()
        assert master_session.query(DocumentReference).first().target_doc_id == tgt.id

    def test_khong_noi_bua_khi_so_hieu_trung_nhieu_co_quan(self, master_session):
        """Dò theo số hiệu trả về một bản BẤT KỲ trong nhóm trùng."""
        src, _ = upsert_document(master_session, {"doc_num": "01/2026/NĐ-CP", "title": "A"})
        for agency in ("UBND Thành phố Huế", "UBND Tỉnh Tây Ninh"):
            upsert_document(master_session, {
                "doc_num": "64/2026/QĐ-UBND", "title": "Q", "agency_name": agency})
        master_session.commit()
        master_session.add(DocumentReference(
            source_doc_id=src.id, target_doc_num="64/2026/QĐ-UBND",
            relation_type="Căn cứ"))
        master_session.commit()

        assert resolve_reference_targets(master_session) == 0, \
            "không biết là tỉnh nào thì để treo, đừng đoán"

    def test_sua_lai_canh_khi_dich_dung_da_co_trong_kho(self, master_session):
        """moj_id đến từ payload Bộ Tư pháp nên là căn cứ; target_doc_id là suy
        diễn. Có đích đúng trong kho thì trỏ lại cho đúng.
        """
        src, _ = upsert_document(master_session, {"doc_num": "01/2026/NĐ-CP", "title": "A"})
        hue, _ = upsert_document(master_session, {
            "doc_num": "64/2026/QĐ-UBND", "title": "Huế",
            "agency_name": "UBND Thành phố Huế", "moj_id": "111"})
        tay_ninh, _ = upsert_document(master_session, {
            "doc_num": "64/2026/QĐ-UBND", "title": "Tây Ninh",
            "agency_name": "UBND Tỉnh Tây Ninh", "moj_id": "222"})
        master_session.commit()

        master_session.add(DocumentReference(
            source_doc_id=src.id, target_doc_num="64/2026/QĐ-UBND",
            target_moj_id="222", target_doc_id=hue.id, relation_type="Căn cứ"))
        master_session.commit()

        assert resolve_reference_targets(master_session) == 1
        master_session.commit()
        assert master_session.query(DocumentReference).first().target_doc_id == tay_ninh.id

    def test_bo_lien_ket_suy_dien_o_cap_tinh_khi_id_lech(self, master_session):
        """Đích đúng chưa có trong kho, liên kết hiện tại mang moj_id khác.

        Với cấp tỉnh, trùng số hiệu là chuyện thường nên không chứng minh được
        liên kết đúng. Trả cạnh về trạng thái treo để bao đóng đi tải đúng văn
        bản theo moj_id — cạnh treo trung thực hơn cạnh sai.
        """
        src, _ = upsert_document(master_session, {"doc_num": "01/2026/NĐ-CP", "title": "A"})
        hue, _ = upsert_document(master_session, {
            "doc_num": "64/2026/QĐ-UBND", "title": "Huế", "moj_id": "111",
            "agency_name": "UBND Thành phố Huế", "territorial_scope": "tinh"})
        master_session.commit()
        master_session.add(DocumentReference(
            source_doc_id=src.id, target_doc_num="64/2026/QĐ-UBND",
            target_moj_id="999", target_doc_id=hue.id, relation_type="Căn cứ"))
        master_session.commit()

        assert resolve_reference_targets(master_session) == 1
        master_session.commit()
        assert master_session.query(DocumentReference).first().target_doc_id is None

    def test_giu_lien_ket_trung_uong_du_id_lech(self, master_session):
        """Bộ Tư pháp cấp nhiều id cho cùng một văn bản — Luật 71/2014/QH13 tồn
        tại dưới cả "40742" lẫn "vbpqta_11034". Số hiệu trung ương duy nhất toàn
        quốc nên liên kết vẫn đúng văn bản; xoá đi là mất cạnh thật.
        """
        src, _ = upsert_document(master_session, {"doc_num": "01/2026/NĐ-CP", "title": "A"})
        luat, _ = upsert_document(master_session, {
            "doc_num": "71/2014/QH13", "title": "Luật", "moj_id": "40742",
            "agency_name": "Quốc hội", "territorial_scope": "trung_uong"})
        master_session.commit()
        master_session.add(DocumentReference(
            source_doc_id=src.id, target_doc_num="71/2014/QH13",
            target_moj_id="vbpqta_11034", target_doc_id=luat.id,
            relation_type="Căn cứ"))
        master_session.commit()

        assert resolve_reference_targets(master_session) == 0
        assert master_session.query(DocumentReference).first().target_doc_id == luat.id

    def test_chay_lai_khong_dem_thua(self, master_session):
        src, _ = upsert_document(master_session, {"doc_num": "01/2026/NĐ-CP", "title": "A"})
        tgt, _ = upsert_document(master_session, {
            "doc_num": "02/2026/NĐ-CP", "title": "B", "moj_id": "777"})
        master_session.commit()
        master_session.add(DocumentReference(
            source_doc_id=src.id, target_doc_num="02/2026/NĐ-CP",
            target_moj_id="777", relation_type="Căn cứ"))
        master_session.commit()

        assert resolve_reference_targets(master_session) == 1
        master_session.commit()
        assert resolve_reference_targets(master_session) == 0


class TestValidateResults:
    def test_loai_van_ban_da_bi_bai_bo(self, rag_db, edge_factory):
        edge_factory("10/2026/NĐ-CP", "05/2020/NĐ-CP", "Bãi bỏ")
        chunks = [{"doc_num": "05/2020/NĐ-CP", "content": "x"}]
        assert validate_results(rag_db, chunks) == []

    def test_loai_van_ban_bi_thay_the(self, rag_db, edge_factory):
        edge_factory("10/2026/NĐ-CP", "05/2020/NĐ-CP", "Thay thế")
        assert validate_results(rag_db, [{"doc_num": "05/2020/NĐ-CP", "content": "x"}]) == []

    def test_GIU_LAI_van_ban_chi_bi_sua_doi(self, rag_db, edge_factory):
        """Văn bản bị sửa đổi vẫn là luật hiện hành ở phần chưa bị sửa.

        Bản cũ nếu bật lên sẽ xoá nhầm cả nhóm này khỏi báo cáo.
        """
        edge_factory("10/2026/NĐ-CP", "05/2020/NĐ-CP", "Sửa đổi, bổ sung")
        kept = validate_results(rag_db, [{"doc_num": "05/2020/NĐ-CP", "content": "x"}])
        assert len(kept) == 1
        assert "10/2026/NĐ-CP" in kept[0]["canh_bao_hieu_luc"]

    def test_can_cu_khong_anh_huong_hieu_luc(self, rag_db, edge_factory):
        """Quan hệ chiếm đa số trong kho — không được coi là làm mất hiệu lực."""
        edge_factory("10/2026/QĐ-UBND", "72/2025/QH15", "Căn cứ")
        kept = validate_results(rag_db, [{"doc_num": "72/2025/QH15", "content": "x"}])
        assert len(kept) == 1
        assert "canh_bao_hieu_luc" not in kept[0]

    def test_khong_co_quan_he_thi_giu_nguyen(self, rag_db):
        chunks = [{"doc_num": "88/2026/TT-BTC", "content": "x"}]
        assert validate_results(rag_db, chunks) == chunks

    def test_khong_lam_hong_chunk_thieu_doc_num(self, rag_db):
        assert len(validate_results(rag_db, [{"content": "x"}])) == 1


class TestImpactAnalysis:
    def test_tra_ve_ca_hai_chieu(self, rag_db, edge_factory):
        """Câu hỏi 'văn bản này bị ai bãi bỏ' mới là câu quan trọng khi thẩm định."""
        edge_factory("A/2026", "B/2020", "Bãi bỏ")
        edge_factory("C/2026", "A/2026", "Sửa đổi, bổ sung")

        rels = {(d.doc_num, d.relation) for d in impact_analysis(rag_db, "A/2026")}
        assert ("B/2020", "Bãi bỏ") in rels, "thiếu chiều xuôi"
        assert any(
            doc == "C/2026" and "bị" in rel for doc, rel in rels
        ), "thiếu chiều ngược"

    def test_effect_warnings_tach_bach_hai_nhom(self, rag_db, edge_factory):
        edge_factory("X/2026", "Y/2020", "Bãi bỏ")
        edge_factory("Z/2026", "Y/2020", "Sửa đổi, bổ sung")
        w = effect_warnings(rag_db, "Y/2020")
        assert [s for s, _ in w["terminated_by"]] == ["X/2026"]
        assert [s for s, _ in w["amended_by"]] == ["Z/2026"]


class TestCascadeRetrieve:
    def test_khong_lap_vo_han_khi_do_thi_co_vong(self, rag_db, edge_factory):
        edge_factory("A/2026", "B/2026", "Căn cứ")
        edge_factory("B/2026", "A/2026", "Căn cứ")
        assert len(cascade_retrieve(rag_db, "A/2026", max_depth=3)) == 2


class TestValidateResultsTheoEffStatus:
    """Trạng thái tự thân của văn bản, không chỉ dựa vào đồ thị quan hệ.

    Kho có 204 văn bản "Hết hiệu lực toàn bộ" và 220 "Hết hiệu lực một phần" —
    hai nhóm này phải được xử lý khác nhau.
    """

    def _chunk(self, rag_db, doc_num, eff_status):
        rag_db.upsert_chunk({
            "doc_id": None, "doc_num": doc_num, "chunk_index": 0,
            "heading": "Điều 1", "content": "nội dung", "char_count": 8,
            "field_name": None, "field_code": None, "industries": [],
            "eff_status": eff_status, "issue_date": None, "doc_type": None,
            "agency_name": None, "content_hash": f"h-{doc_num}",
        })
        return [{"doc_num": doc_num, "content": "nội dung"}]

    def test_het_hieu_luc_toan_bo_bi_loai(self, rag_db):
        chunks = self._chunk(rag_db, "01/2010/NĐ-CP", "Hết hiệu lực toàn bộ")
        assert validate_results(rag_db, chunks) == []

    def test_het_hieu_luc_MOT_PHAN_duoc_giu_kem_canh_bao(self, rag_db):
        """220/1015 văn bản thuộc nhóm này — loại nhầm là mất 1/5 kho."""
        chunks = self._chunk(rag_db, "02/2010/NĐ-CP", "Hết hiệu lực một phần")
        kept = validate_results(rag_db, chunks)
        assert len(kept) == 1
        assert "MỘT PHẦN" in kept[0]["canh_bao_hieu_luc"]

    def test_chua_co_hieu_luc_duoc_giu_kem_canh_bao(self, rag_db):
        chunks = self._chunk(rag_db, "03/2026/NĐ-CP", "Chưa có hiệu lực")
        kept = validate_results(rag_db, chunks)
        assert len(kept) == 1 and "CHƯA có hiệu lực" in kept[0]["canh_bao_hieu_luc"]

    def test_con_hieu_luc_khong_bi_gan_canh_bao(self, rag_db):
        chunks = self._chunk(rag_db, "04/2026/NĐ-CP", "Còn hiệu lực")
        kept = validate_results(rag_db, chunks)
        assert len(kept) == 1 and "canh_bao_hieu_luc" not in kept[0]

    def test_gop_ca_hai_nguon_canh_bao(self, rag_db, edge_factory):
        chunks = self._chunk(rag_db, "05/2020/NĐ-CP", "Hết hiệu lực một phần")
        edge_factory("99/2026/NĐ-CP", "05/2020/NĐ-CP", "Sửa đổi, bổ sung")
        kept = validate_results(rag_db, chunks)
        canh_bao = kept[0]["canh_bao_hieu_luc"]
        assert "MỘT PHẦN" in canh_bao and "99/2026/NĐ-CP" in canh_bao

    def test_do_thi_van_thang_khi_eff_status_noi_con_hieu_luc(self, rag_db, edge_factory):
        """Nguồn ghi 'Còn hiệu lực' nhưng đồ thị nói đã bị bãi bỏ → vẫn loại."""
        chunks = self._chunk(rag_db, "06/2015/NĐ-CP", "Còn hiệu lực")
        edge_factory("88/2026/NĐ-CP", "06/2015/NĐ-CP", "Bãi bỏ")
        assert validate_results(rag_db, chunks) == []
