"""
Sinh thân bài Cẩm nang cho biểu mẫu, giao sang bên xuất bản qua một file JSON.

VÌ SAO GÓI NÀY TỒN TẠI Ở ĐÂY chứ không ở bên xuất bản: session Claude Code khoá
theo chủ sở hữu repo, nên chỉ bên này mới nắm đủ cả kho biểu mẫu
(`legal-vault-public`) lẫn thư viện prompt + cổng đối chiếu trích dẫn. Hai bên
gặp nhau qua đúng một file: `bai.json`.

    tracuuphaply (sinh nội dung)                 thongtincty (xuất bản)
      legal-vault-public  (kho biểu mẫu)  ─┐
      thuvienphapluat     (prompt + cổng) ─┴─►  bai.json  ─►  npm run import:phapluat

RANH GIỚI TRÁCH NHIỆM — đây là chốt chặn cho bốn lỗi đã làm hỏng 653 bài lần
trước. Gói này sinh ĐÚNG bốn trường: `form_key`, `tieu_de`, `mo_ta`, `than_bai`
(cộng cờ `citation_ok` do cổng ghi). Slug, chủ đề, hộp hiệu lực, ruột tờ mẫu và
footer nguồn do bên xuất bản tự dựng từ kho — sinh trùng là tạo ra bài nói hai
lần, lệch nhau.
"""
