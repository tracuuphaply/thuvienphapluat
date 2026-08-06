"""
Obsidian vault configuration and templates.
"""
from pathlib import Path
from src.config import PROJECT_ROOT

VAULT_DIR = PROJECT_ROOT / "Legal-Vault"

INDUSTRY_MAP = {
    "Công nghệ thông tin": ["phần mềm", "công nghệ thông tin", "mạng", "viễn thông", "internet", "dữ liệu", "chữ ký số"],
    "Xây dựng & Bất động sản": ["xây dựng", "bất động sản", "nhà ở", "đất đai", "quy hoạch", "kiến trúc"],
    "Y tế & Dược phẩm": ["y tế", "dược", "khám bệnh", "chữa bệnh", "thuốc", "bệnh viện"],
    "Tài chính & Ngân hàng": ["tài chính", "ngân hàng", "tín dụng", "ngân quỹ", "cho vay", "tiền tệ"],
    "Giáo dục & Đào tạo": ["giáo dục", "đào tạo", "trường học", "giáo viên", "học sinh", "sinh viên", "đại học"],
    "Nông nghiệp & Thủy sản": ["nông nghiệp", "thủy sản", "trồng trọt", "chăn nuôi", "lâm nghiệp", "nông thôn"],
    "Giao thông & Vận tải": ["giao thông", "vận tải", "đường bộ", "đường sắt", "hàng không", "hàng hải", "đường thủy"],
    "Năng lượng & Môi trường": ["năng lượng", "môi trường", "điện", "khí", "nước", "chất thải", "khoáng sản"],
    "Sản xuất & Gia công": ["sản xuất", "gia công", "nhà máy", "công nghiệp", "chế biến"],
    "Thương mại & Dịch vụ": ["thương mại", "dịch vụ", "bán lẻ", "xuất nhập khẩu", "phân phối", "quảng cáo"],
}

OBSIDIAN_TEMPLATE = """---
doc_num: "{doc_num}"
title: "{title}"
doc_type: "{doc_type}"
issue_date: "{issue_date}"
eff_from: "{eff_from}"
eff_to: "{eff_to}"
eff_status: "{eff_status}"
agency: "{agency}"
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
- **Ngày ban hành**: {issue_date}
- **Trạng thái hiệu lực**: {eff_status}
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
