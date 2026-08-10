"""Nhóm — dây chuyền chạy theo lịch.

launchd chạy script với MÔI TRƯỜNG TRỐNG: không có biến nào từ shell đăng nhập,
không có .env. Đây là nguồn lỗi âm thầm nguy hiểm nhất của phần tự động hoá, vì
script vẫn chạy hết, vẫn thoát mã 0, vẫn ghi "Pipeline xong" — chỉ là đã bỏ qua
những bước mà công tắc của chúng nằm trong .env.
"""
import os
import subprocess

import pytest

from src.config import PROJECT_ROOT

SCRIPTS = ("run_daily.sh", "run_quarterly.sh")


class TestNapEnvTrongScript:
    @pytest.mark.parametrize("ten", SCRIPTS)
    def test_script_tu_nap_env(self, ten):
        """python-dotenv chỉ nạp cho tiến trình Python, không cho shell."""
        src = (PROJECT_ROOT / "scripts" / ten).read_text(encoding="utf-8")
        assert 'PROJECT_DIR/.env' in src, f"{ten} không nạp .env"

    @pytest.mark.parametrize("ten", SCRIPTS)
    def test_khong_dung_source_tran(self, ten):
        """`source .env` diễn giải giá trị như lệnh shell.

        .env chứa khoá API và tên thư mục tiếng Việt có dấu cách — source sẽ
        thực thi chúng.
        """
        src = (PROJECT_ROOT / "scripts" / ten).read_text(encoding="utf-8")
        for xau in ("source .env", ". .env", 'source "$PROJECT_DIR/.env"'):
            assert xau not in src, f"{ten} dùng {xau!r}"

    @pytest.mark.parametrize("ten", SCRIPTS)
    def test_cu_phap_bash_hop_le(self, ten):
        r = subprocess.run(["bash", "-n", str(PROJECT_ROOT / "scripts" / ten)],
                           capture_output=True)
        assert r.returncode == 0, r.stderr.decode()

    def test_nap_duoc_trong_moi_truong_trong(self, tmp_path):
        """Kiểm bằng cách chạy thật với env rỗng, giống hệt launchd."""
        env_file = tmp_path / ".env"
        env_file.write_text(
            "# chú thích\n\n"
            "CONG_TAC=true\n"
            "CO_DAU_CACH=Kho văn bản pháp luật\n"
            "CO_DAU_BANG=sk-abc=def==\n",
            encoding="utf-8",
        )
        doan = (
            'PROJECT_DIR="%s"\n'
            'if [ -f "$PROJECT_DIR/.env" ]; then\n'
            '  while IFS= read -r line; do\n'
            '    case "$line" in\n'
            "      ''|'#'*) continue ;;\n"
            '      *=*) export "${line%%%%=*}"="${line#*=}" ;;\n'
            '    esac\n'
            '  done < "$PROJECT_DIR/.env"\n'
            'fi\n'
            'echo "$CONG_TAC|$CO_DAU_CACH|$CO_DAU_BANG"\n'
        ) % tmp_path
        r = subprocess.run(["bash", "-c", doan], capture_output=True,
                           env={"PATH": os.environ["PATH"]})
        assert r.returncode == 0, r.stderr.decode()
        assert r.stdout.decode().strip() == \
            "true|Kho văn bản pháp luật|sk-abc=def=="


class TestCacBuocTrongLichNgay:
    """Mỗi bước phải có mặt, và bước tốn tiền phải có công tắc."""

    def _src(self):
        return (PROJECT_ROOT / "scripts" / "run_daily.sh").read_text(encoding="utf-8")

    def _lenh(self):
        """Chỉ các dòng LỆNH, bỏ chú thích.

        Chú thích trong script giải thích vì sao đã bỏ --skip-gdrive và set -euo,
        nên khớp trên toàn văn sẽ báo đỏ vì chính lời giải thích.
        """
        return "\n".join(
            d for d in self._src().splitlines()
            if d.strip() and not d.strip().startswith("#")
        )

    @pytest.mark.parametrize("lenh", [
        "src.main", "scripts.run_closure", "--sync-vault-only",
        "--sync-rag-only", "scripts.run_report_worker", "src.utils.backup",
    ])
    def test_co_du_buoc(self, lenh):
        assert lenh in self._src()

    def test_khong_con_skip_cloud(self):
        """run_daily từng truyền --skip-gdrive vô điều kiện, nên dây chuyền hằng
        ngày chưa bao giờ đẩy file lên mây.
        """
        assert "--skip-gdrive" not in self._lenh()
        assert "--skip-cloud" not in self._lenh()

    def test_buoc_goi_llm_co_cong_tac(self):
        """Bước gọi mô hình tốn tiền thật — phải tắt được mà không sửa script."""
        assert "REPORT_WORKER_ENABLED" in self._src()

    def test_sao_luu_chay_ke_ca_khi_pipeline_hong(self):
        """Bản cũ dùng `set -e` nên pipeline lỗi là bỏ luôn backup, đúng lúc cần
        nó nhất.
        """
        lenh = self._lenh()
        assert "set -e\n" not in lenh and "set -euo" not in lenh
        i_backup = lenh.index("src.utils.backup")
        i_else = lenh.rindex("else")
        assert i_backup > i_else, "backup phải nằm ngoài nhánh thành công"
