"""Nhóm — chấm % tác động tới 21 ngành VSIC.

Con số này đi thẳng vào báo cáo bán cho khách, nên phải bảo vệ được khi bị chất
vấn. Ba thứ quyết định điều đó:
  - TÁI LẬP: cùng đầu vào phải ra cùng con số, không phụ thuộc thứ tự hay ngẫu nhiên
  - HAI LOẠI PHẦN TRĂM tách bạch: trộn "tác động tới ai" với "mạnh tới mức nào"
    là kiểu hỏng kinh điển
  - KHÔNG ĐOÁN: thiếu tín hiệu thì trả rỗng, không tự bịa ra một ngành
"""
import pytest

from src.analysis import centroids, scorer
from src.analysis.restrictions import RESTRICTION_TERMS, count_restrictions


class TestDemRangBuoc:
    def test_dem_duoc_menh_lenh_co_ban(self):
        r = count_restrictions("Doanh nghiệp phải nộp báo cáo và không được chậm trễ.")
        assert r.matched["phải"] == 1
        assert r.matched["không được"] == 1
        assert r.weighted == pytest.approx(1.0 + 2.0)

    def test_tru_bay_tu_ghep(self):
        """"bên phải" không phải mệnh lệnh — đúng cơ chế đã sửa lỗi "nhà nước"."""
        r = count_restrictions("Biển báo đặt ở bên phải đường.")
        assert "phải" not in r.matched
        assert r.weighted == 0

    def test_van_dem_dung_khi_co_ca_hai(self):
        r = count_restrictions("Xe đi bên phải và phải bật đèn.")
        assert r.matched["phải"] == 1

    def test_cum_dai_khong_bi_dem_hai_lan(self):
        """"nghiêm cấm" chứa "cấm"; đếm cả hai là tính trùng một mệnh đề."""
        r = count_restrictions("Nghiêm cấm hành vi gian lận.")
        assert r.matched.get("nghiêm cấm") == 1
        assert "cấm" not in r.matched
        assert r.weighted == pytest.approx(3.0)

    def test_khong_duoc_phep_khong_bi_dem_hai_lan(self):
        r = count_restrictions("Tổ chức không được phép chuyển nhượng.")
        assert r.matched.get("không được phép") == 1
        assert "không được" not in r.matched

    def test_cam_nang_hon_nghia_vu(self):
        """Đếm không trọng số thì "phải" (38,4% số đoạn) nuốt "nghiêm cấm" (0,4%)."""
        assert RESTRICTION_TERMS["nghiêm cấm"] > RESTRICTION_TERMS["phải"]

    @pytest.mark.parametrize("text", ["", None, "Điều 1. Phạm vi điều chỉnh"])
    def test_khong_co_rang_buoc_thi_bang_khong(self, text):
        assert count_restrictions(text).weighted == 0


class TestHaiLoaiPhanTram:
    def _impact(self, restriction=100.0, level=2):
        return scorer.score_document(
            doc_key="k", doc_num="X", restriction_weighted=restriction,
            relevance_lexicon={"K": 0.6, "F": 0.4},
            relevance_embedding={"K": 0.5, "F": 0.3, "A": 0.2},
            hierarchy_level=level,
        )

    def test_pct_doc_cong_lai_bang_100(self):
        """Trả lời "văn bản này tác động tới AI" nên phải là một phân phối."""
        impact = self._impact()
        assert sum(s.impact_pct_doc for s in impact.scores.values()) == pytest.approx(100.0)

    def test_pct_industry_doc_lap_giua_cac_nganh(self):
        """Trả lời "ngành j nên quan tâm TỚI MỨC NÀO" nên KHÔNG cộng thành 100.

        Trộn hai câu hỏi này là kiểu hỏng kinh điển: một thông tư kỹ thuật vô
        thưởng vô phạt vẫn ra "100% tác động" phân bổ đâu đó.
        """
        docs = [
            scorer.score_document("k1", "A", 10.0, {"K": 1.0}, {}, 2),
            scorer.score_document("k2", "B", 1000.0, {"K": 1.0}, {}, 2),
        ]
        scorer.assign_percentiles(docs)
        yeu, manh = docs[0].scores["K"], docs[1].scores["K"]
        assert yeu.impact_pct_doc == pytest.approx(100.0)
        assert manh.impact_pct_doc == pytest.approx(100.0)
        # nhưng cường độ thì khác hẳn
        assert manh.impact_pct_industry > yeu.impact_pct_industry

    def test_van_ban_ngu_canh_khong_lam_lech_phan_vi(self):
        """Bao đóng đưa vào kho 3.443 văn bản nền, phần lớn điểm thấp.

        Gộp chúng vào phân phối thì một văn bản nghiệp vụ ở giữa bảng nhảy lên
        gần đỉnh mà bản thân nó không đổi gì — ngưỡng ≥ 80 chọn ngành cho báo
        cáo (c) kích hoạt cho gần như mọi thứ. Đúng bệnh ngập báo cáo mà
        C_MIN_SHARE sinh ra để chặn, quay lại bằng cửa khác.
        """
        nghiep_vu = [
            scorer.score_document(f"nv{i}", f"NV{i}", 100.0 * i, {"K": 1.0}, {}, 2)
            for i in range(1, 11)
        ]
        ngu_canh = [
            scorer.score_document(f"nc{i}", f"NC{i}", 1.0, {"K": 1.0}, {}, 9)
            for i in range(200)
        ]
        keys = {d.doc_key for d in nghiep_vu}

        giua = nghiep_vu[4]        # hạng 5/10
        scorer.assign_percentiles(nghiep_vu + ngu_canh, reference_keys=keys)
        dung = giua.scores["K"].impact_pct_industry

        scorer.assign_percentiles(nghiep_vu + ngu_canh)   # gộp cả hai nhóm
        lech = giua.scores["K"].impact_pct_industry

        assert dung < 60, f"văn bản giữa bảng phải ở khoảng giữa, đang {dung}"
        assert lech > 90, "phép đo phải cho thấy sai lệch thật sự tồn tại"

    def test_van_gan_phan_vi_cho_van_ban_ngoai_nhom_tham_chieu(self):
        """Giới hạn PHÂN PHỐI, không giới hạn tập được gán điểm."""
        nv = scorer.score_document("nv", "NV", 100.0, {"K": 1.0}, {}, 2)
        nc = scorer.score_document("nc", "NC", 1.0, {"K": 1.0}, {}, 9)
        scorer.assign_percentiles([nv, nc], reference_keys={"nv"})
        assert nc.scores["K"].impact_pct_industry is not None
        assert nc.scores["K"].impact_pct_industry < nv.scores["K"].impact_pct_industry

    def test_nganh_vang_mat_trong_nhom_tham_chieu_khong_no(self):
        """Không được ném lỗi giữa một lượt chấm cả kho, cũng không được mượn
        phân phối của ngành khác.
        """
        nv = scorer.score_document("nv", "NV", 100.0, {"K": 1.0}, {}, 2)
        nc = scorer.score_document("nc", "NC", 50.0, {"A": 1.0}, {}, 9)
        scorer.assign_percentiles([nv, nc], reference_keys={"nv"})
        assert nc.scores["A"].impact_pct_industry == 0.0

    def test_van_ban_cap_cao_tac_dong_manh_hon(self):
        """Một điều cấm trong Luật không cùng sức nặng với trong quyết định tỉnh."""
        luat = self._impact(level=2)
        qd_tinh = self._impact(level=9)
        assert luat.scores["K"].impact_raw > qd_tinh.scores["K"].impact_raw

    def test_khong_phai_vbqppl_bi_ha_manh_nhung_khong_triet_tieu(self):
        """Công điện vẫn là tín hiệu chính sách, chỉ không phải căn cứ pháp lý."""
        from src.legal.hierarchy import LEVEL_NON_NORMATIVE

        w = scorer.hierarchy_weight(LEVEL_NON_NORMATIVE)
        assert 0 < w < scorer.hierarchy_weight(9)

    def test_khong_co_rang_buoc_thi_moi_diem_bang_khong(self):
        impact = self._impact(restriction=0.0)
        assert all(s.impact_raw == 0 for s in impact.scores.values())
        assert all(s.impact_pct_doc == 0 for s in impact.scores.values())


class TestHopNhatHaiTang:
    def test_du_ca_hai_tang_thi_tron_theo_trong_so(self):
        fused = scorer.fuse_relevance({"K": 1.0}, {"K": 0.0})
        assert fused["K"] == pytest.approx(centroids.LEXICON_WEIGHT)

    def test_thieu_tang_ngu_nghia_thi_tu_khoa_duoc_dung_nguyen(self):
        """Chia đôi khi một tầng rỗng sẽ hạ điểm vô cớ — 51% chunk không có

        từ khoá nào khớp, nếu bị chia đôi thì cả nhóm đó tụt hạng oan.
        """
        assert scorer.fuse_relevance({"K": 1.0}, {})["K"] == pytest.approx(1.0)

    def test_thieu_tang_tu_khoa_thi_ngu_nghia_duoc_dung_nguyen(self):
        assert scorer.fuse_relevance({}, {"K": 0.8})["K"] == pytest.approx(0.8)

    def test_hai_tang_rong_thi_khong_bia_ra_nganh(self):
        assert scorer.fuse_relevance({}, {}) == {}


class TestDaiSoVector:
    def test_softmax_cong_lai_bang_mot(self):
        out = centroids.softmax({"A": 1.0, "B": 2.0, "C": 3.0})
        assert sum(out.values()) == pytest.approx(1.0)

    def test_softmax_giu_thu_tu(self):
        out = centroids.softmax({"A": 1.0, "B": 3.0})
        assert out["B"] > out["A"]

    def test_cosine_vector_giong_nhau_bang_mot(self):
        assert centroids.cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)

    def test_cosine_lech_so_chieu_tra_khong(self):
        assert centroids.cosine([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0

    def test_zscore_sd_bang_khong_thi_tra_khong(self):
        """sd = 0 nghĩa là ngành đó không phân biệt được gì, không phải điểm vô cực."""
        assert centroids.zscore(5.0, 1.0, 0.0) == 0.0

    def test_phan_vi_dung_thu_hang(self):
        values = [1.0, 2.0, 3.0, 4.0]
        assert centroids.percentile_rank(0.5, values) == 0.0
        assert centroids.percentile_rank(4.0, values) == 100.0
        assert centroids.percentile_rank(2.0, values) == 50.0

    def test_phan_vi_khong_doi_khi_them_van_ban_o_giua(self):
        """Phân vị ổn định khi kho lớn lên, min-max thì không.

        Min-max: một đạo luật khổng lồ mới về sẽ co giãn lại toàn bộ điểm cũ.
        """
        assert centroids.percentile_rank(1.0, [1.0, 100.0]) == pytest.approx(50.0)
        assert centroids.percentile_rank(1.0, [1.0, 100.0, 10000.0]) == pytest.approx(33.3, abs=0.5)


class TestHoSoNganh:
    def test_du_21_nganh(self):
        assert len(centroids.all_profiles()) == 21

    def test_ma_nganh_khong_trung(self):
        codes = [p.vsic_code for p in centroids.all_profiles()]
        assert len(codes) == len(set(codes))

    def test_tu_khoa_duoc_boc_thanh_cau(self):
        """Model nhúng câu cho vector ổn định hơn nhúng một cụm danh từ rời."""
        texts = centroids.all_profiles()[0].texts
        assert any(t.startswith("Quy định pháp luật về ") for t in texts)

    def test_lay_top_k_chu_khong_trung_binh_toan_bo(self):
        """Luật 300 Điều nhắc ngân hàng ở 5 Điều VẪN là văn bản ngân hàng."""
        assert 1 < centroids.TOP_K_CHUNKS <= 10

    def test_trong_so_hai_tang_cong_bang_mot(self):
        assert centroids.LEXICON_WEIGHT + centroids.EMBEDDING_WEIGHT == pytest.approx(1.0)


class TestTaiLap:
    """Cùng đầu vào phải ra cùng con số ở mọi tiến trình.

    Điểm không tái lập được thì không bảo vệ được khi khách chất vấn — và đó là
    lý do chọn lexicon + embedding thay vì để LLM chấm.
    """

    def test_thu_tu_nganh_on_dinh_giua_cac_lan_goi(self):
        """Lặp trên set chuỗi cho thứ tự khác nhau giữa các tiến trình vì Python

        ngẫu nhiên hoá hash; thứ tự cộng khác nhau làm tổng dấu phẩy động lệch
        ở chữ số cuối. Đo thật trên kho: 2/16.905 dòng bị lệch.
        """
        fused = scorer.fuse_relevance(
            {"K": 0.3, "A": 0.2, "F": 0.5}, {"B": 0.1, "K": 0.4}
        )
        assert list(fused) == sorted(fused)

    def test_hai_lan_cham_ra_cung_ket_qua(self):
        args = dict(
            doc_key="k", doc_num="X", restriction_weighted=137.5,
            relevance_lexicon={"K": 0.31, "A": 0.19, "F": 0.5},
            relevance_embedding={"B": 0.11, "K": 0.44, "M": 0.45},
            hierarchy_level=5,
        )
        a = scorer.score_document(**args)
        b = scorer.score_document(**args)
        assert (
            [(s.vsic_code, s.impact_raw, s.impact_pct_doc) for s in a.scores.values()]
            == [(s.vsic_code, s.impact_raw, s.impact_pct_doc) for s in b.scores.values()]
        )

    def test_phan_vi_khong_phu_thuoc_thu_tu_van_ban_dau_vao(self):
        def build(order):
            docs = [
                scorer.score_document(f"k{i}", f"D{i}", r, {"K": 1.0}, {}, 2)
                for i, r in order
            ]
            scorer.assign_percentiles(docs)
            return {d.doc_num: d.scores["K"].impact_pct_industry for d in docs}

        xuoi = build([(0, 10.0), (1, 50.0), (2, 100.0)])
        nguoc = build([(2, 100.0), (1, 50.0), (0, 10.0)])
        assert xuoi == nguoc
