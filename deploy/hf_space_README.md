---
title: VerifAI
emoji: 🎬
colorFrom: indigo
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# VerifAI (demo đồ án)

Kiểm duyệt video quảng cáo: OCR quét toàn bộ frame (adaptive), ASR tiếng Việt,
Gemini phân tích video, đề xuất Pass / Needs Review / Regenerate và gợi ý nhãn
để reviewer xác nhận.

Truy cập cần mã truy cập (hộp đăng nhập của trình duyệt: tên đăng nhập bất kỳ,
mật khẩu là mã truy cập). Dữ liệu phiên mất khi Space khởi động lại (gói free
không có ổ đĩa lưu lâu dài); Product Truth được nạp lại từ `deploy/seed.sql`.

Secrets cần đặt trong Settings của Space: `GEMINI_API_KEY`, `VERIFAI_ACCESS_CODE`
(tối thiểu 8 ký tự).
