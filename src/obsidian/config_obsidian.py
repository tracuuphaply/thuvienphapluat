"""
Obsidian vault configuration and templates.
"""
from pathlib import Path
from src.config import PROJECT_ROOT

VAULT_DIR = PROJECT_ROOT / "Legal-Vault"

# Danh mục ngành theo Hệ thống ngành kinh tế Việt Nam (VSIC) cấp 1 — Quyết định
# 27/2018/QĐ-TTg. Thay cho 10 nhóm ngành tự đặt trước đây, để báo cáo dùng đúng
# mã ngành ghi trên giấy đăng ký kinh doanh của doanh nghiệp.
from src.obsidian.vsic import INDUSTRY_MAP, VSIC_LEVEL1, code_of, official_name  # noqa: F401
OBSIDIAN_TEMPLATE = """---
doc_num: "{doc_num}"
title: "{title}"
doc_type: "{doc_type}"
doc_type_norm: "{doc_type_norm}"
hierarchy_level: {hierarchy_level}
is_vbqppl: {is_vbqppl}
issue_date: "{issue_date}"
eff_from: "{eff_from}"
eff_to: "{eff_to}"
eff_status: "{eff_status}"
eff_state: "{eff_state}"
eff_state_as_of: "{eff_state_as_of}"
agency: "{agency}"
territorial_scope: "{territorial_scope}"
province: "{province}"
fields: {fields}
industries: {industries}
source_tvpl: {source_tvpl}
source_moj: {source_moj}
tvpl_url: "{tvpl_url}"
moj_url: "{moj_url}"
aliases: {aliases}
tags: {tags}
---

# {title}

## Thông tin cơ bản
- **Số hiệu**: {doc_num}
- **Loại văn bản**: {doc_type}
- **Cơ quan ban hành**: {agency}
- **Cấp hiệu lực pháp lý**: {hierarchy_label}
- **Phạm vi áp dụng**: {scope_label}
- **Ngày ban hành**: {issue_date}
- **Tình trạng hiệu lực**: {eff_state_label} *(tính đến {eff_state_as_of})*
- **Ngày có hiệu lực**: {eff_from}

## Lĩnh vực & Ngành nghề
- **Lĩnh vực**: {fields_str}
- **Ngành nghề**: {industries_str}

## Liên kết gốc
- [Thư viện Pháp luật]({tvpl_url})
- [Bộ Tư pháp]({moj_url})

## Văn bản liên quan
{references_md}

## Nội dung
{content}
"""

# Nhãn hiển thị cho từng cấp. Ghi kèm số để so sánh được bằng mắt, và ghi rõ
# "không phải VBQPPL" thay vì để trống — người đọc báo cáo cần biết văn bản này
# không dùng làm căn cứ pháp lý được.
HIERARCHY_LABELS: dict[int, str] = {
    1: "Cấp 1 — Hiến pháp",
    2: "Cấp 2 — Bộ luật, luật, nghị quyết của Quốc hội",
    3: "Cấp 3 — Pháp lệnh, nghị quyết của UBTVQH",
    4: "Cấp 4 — Lệnh, quyết định của Chủ tịch nước",
    5: "Cấp 5 — Nghị định, nghị quyết của Chính phủ",
    6: "Cấp 6 — Quyết định của Thủ tướng Chính phủ",
    7: "Cấp 7 — Thông tư",
    8: "Cấp 8 — Nghị quyết của HĐND cấp tỉnh",
    9: "Cấp 9 — Quyết định của UBND cấp tỉnh",
    99: "Không phải văn bản quy phạm pháp luật",
}

DASHBOARD_TEMPLATE = """---
cssclass: dashboard
---
# Hệ thống Văn bản Pháp luật (Legal-Vault)

Chào mừng bạn đến với kho dữ liệu pháp lý.

## Lĩnh vực (Fields)
```dataview
TABLE length(rows) AS "Số lượng văn bản"
FROM "Documents"
WHERE fields != null
FLATTEN fields AS field
GROUP BY field
SORT length(rows) DESC
```

## Ngành nghề (Industries)
```dataview
TABLE length(rows) AS "Số lượng văn bản"
FROM "Documents"
WHERE industries != null
FLATTEN industries AS ind
GROUP BY ind
SORT length(rows) DESC
```

## Mới cập nhật (Last 30 Days)
```dataview
TABLE doc_num AS "Số hiệu", issue_date AS "Ngày ban hành", agency AS "Cơ quan", eff_status AS "Trạng thái"
FROM "Documents"
WHERE issue_date >= (date(today) - dur(30 days))
SORT issue_date DESC
```
"""

MOC_TEMPLATE = """---
type: moc
category: "{category_type}"
name: "{name}"
---
# {name}

Danh sách các văn bản thuộc {category_type_vi}: **{name}**

```dataview
TABLE doc_num AS "Số hiệu", issue_date AS "Ngày ban hành", agency AS "Cơ quan ban hành", eff_status AS "Trạng thái"
FROM "Documents"
WHERE contains({category_field}, "{name}")
SORT issue_date DESC
```
"""
