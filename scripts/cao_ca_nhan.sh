#!/usr/bin/env bash
# Cào 18 lĩnh vực biểu mẫu phục vụ cá nhân, hai pha.
#
# VÌ SAO HAI PHA. Giai đoạn liệt kê tốn hàng trăm lượt tải và chạy TRƯỚC việc cần
# làm; nó đốt cf_clearance rồi Cloudflare dựng lại thử thách đúng lúc bộ cào bắt
# đầu tải trang chi tiết. Tách ra thì vượt thử thách một lần, rồi dùng trọn phiên
# còn tươi cho phần việc thật.
#
#     bash scripts/cao_ca_nhan.sh liet-ke     # pha 1: nạp hàng đợi
#     bash scripts/cao_ca_nhan.sh chi-tiet    # pha 2: tải ruột mẫu
#
# Pha 2 chạy lại được bao nhiêu lần cũng được — hàng đợi nằm trong DB, mẫu đã có
# HTML thì bỏ qua. Đứt giữa chừng chỉ cần gọi lại.
set -euo pipefail
cd "$(dirname "$0")/.."

# 18 lĩnh vực, xếp từ NHỎ ĐẾN LỚN. Lĩnh vực nhỏ xong trước thì một lần đứt mạng
# giữa chừng vẫn để lại kết quả dùng được, thay vì bỏ dở đúng cái lớn nhất.
LINH_VUC=(20 45 33 22 39 10 42 38 4 13 2 8 18 24 35 32 17 47)

case "${1:-}" in
  liet-ke)
    # KHÔNG nuốt lỗi và PHẢI thử lại. Lượt chạy đầu để `|| true` cuối đường ống
    # grep, nên 9/18 lĩnh vực hỏng mà script vẫn báo thành công — 2.703/12.139
    # mẫu vào hàng đợi và không có dòng nào nói rằng thiếu. Chạy riêng từng lĩnh
    # vực hỏng thì chúng xong ngay, tức lỗi chỉ là bị chặn tạm thời khi gọi liên
    # tiếp; đúng loại lỗi mà thử lại giải quyết được, và đúng loại mà im lặng
    # biến thành mất dữ liệu.
    thieu=()
    for ma in "${LINH_VUC[@]}"; do
      echo "═══ lĩnh vực $ma ═══"
      ok=0
      for lan in 1 2 3; do
        if python -m scripts.crawl_forms --source bieumau --field "$ma" \
             --chi-hang-doi 2>&1 | tee /dev/stderr | grep -q "Ghi .* mục mới\|Liệt kê được"; then
          ok=1; break
        fi
        echo "  lần $lan hỏng, nghỉ 30s rồi thử lại" >&2
        sleep 30
      done
      [ "$ok" = 1 ] || thieu+=("$ma")
      sleep 8
    done
    echo
    if [ ${#thieu[@]} -gt 0 ]; then
      echo "⚠️  CÒN THIẾU ${#thieu[@]} lĩnh vực: ${thieu[*]}"
      echo "   Chạy lại lệnh này; lĩnh vực đã xong sẽ không bị cào lại."
      exit 1
    fi
    echo "Xong pha liệt kê. Chạy tiếp:"
    echo "  bash scripts/cao_ca_nhan.sh chi-tiet"
    ;;
  chi-tiet)
    python -m scripts.crawl_forms --source bieumau --tiep-tuc --loc-tieu-de
    ;;
  *)
    echo "Dùng: bash scripts/cao_ca_nhan.sh {liet-ke|chi-tiet}" >&2
    exit 2
    ;;
esac
