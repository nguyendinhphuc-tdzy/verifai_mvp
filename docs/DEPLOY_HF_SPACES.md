# Deploy VerifAI lên Hugging Face Spaces

Cập nhật: 02/11/2026.

> **Thay đổi 02/11/2026:** khi tạo Space, Hugging Face hiển thị SDK **Docker là gói trả phí**,
> và CPU Basic bị khóa với tài khoản free (ảnh chụp màn hình của PO). Phương án demo miễn phí hiện dùng là
> **chạy trên máy + Cloudflare Quick Tunnel**:
>
> 1. Thêm `VERIFAI_ACCESS_CODE=<mã ít nhất 8 ký tự>` vào `.env`.
> 2. `powershell -ExecutionPolicy Bypass -File scripts\start_public_demo.ps1`
> 3. Gửi link `https://....trycloudflare.com` hiện trong cửa sổ; đăng nhập bằng tên bất kỳ,
>    mật khẩu là mã truy cập. Máy phải bật suốt buổi demo; mỗi lần chạy lại sẽ có link mới.
>
> Dữ liệu demo nằm trong `data_demo/`, được nạp 8 sản phẩm từ `deploy/seed.sql`; DB thật không bị dùng.
> Phần dưới đây vẫn đúng nếu sau này có gói Docker trả phí hoặc một host Docker khác.

## Vì sao không dùng Render free cho backend

| | Render Free | Hugging Face Spaces CPU Basic (free) |
|---|---|---|
| RAM / CPU | Render chưa ghi rõ thông số gói free; trang instance types có dòng 512 MB / 0,1 CPU nhưng không ghi tên gói | 2 vCPU, 16 GB RAM |
| Ổ đĩa | Tạm thời, mất khi restart hoặc spin-down | Tạm thời (50 GB), mất khi restart |
| Ngủ | Sau 15 phút không có request | Sau 48 giờ không có truy cập |
| PaddleOCR + Whisper | Không đủ RAM | Chạy được (chậm hơn máy local) |

Nguồn: [render.com/docs/free](https://render.com/docs/free),
[render.com/docs/compute-plans](https://render.com/docs/compute-plans),
[Hugging Face Spaces overview](https://huggingface.co/docs/hub/en/spaces-overview),
[Spaces GPUs and hardware](https://huggingface.co/docs/hub/en/spaces-gpus). Thông số có thể thay đổi;
kiểm tra lại trước khi đưa vào báo cáo.

Supabase (Postgres + Storage) và Vercel là bước sau hạn nộp: chuyển SQLite sang Postgres
đòi hỏi viết lại lớp dữ liệu. Gói free của Supabase cũng giới hạn mỗi file upload ở 50 MB
(nguồn: [supabase.com/pricing](https://supabase.com/pricing)).

## Các bước (khoảng 15 phút thao tác + 15 đến 25 phút build)

1. Tạo tài khoản tại huggingface.co. Vào **New Space**, chọn SDK **Docker**,
   hardware **CPU basic (free)**, visibility **Public** (app đã có mã truy cập).
2. Trong **Settings, Variables and secrets** của Space, thêm 2 **Secrets**:
   * `GEMINI_API_KEY`: key Gemini.
   * `VERIFAI_ACCESS_CODE`: mã truy cập cho giám khảo, tối thiểu 8 ký tự.
3. Tạo token có quyền **Write** tại huggingface.co/settings/tokens.
4. Trên máy, trong thư mục dự án (Git Bash):

   ```bash
   HF_TOKEN=hf_xxx HF_SPACE=<username>/<ten-space> bash scripts/deploy_hf_space.sh
   ```

   Script đẩy code hiện tại (không gồm `.env`, `data/`, `tests/`, `docs/`) và thay
   README bằng `deploy/hf_space_README.md`. Script dừng lại nếu phát hiện file chứa API key.
5. Theo dõi tab **Logs** trên Space. Build tải PaddleOCR, Whisper `small` và model weights,
   nên mất nhiều thời gian.
6. Mở `https://<username>-<ten-space>.hf.space`. Trình duyệt hỏi đăng nhập: tên bất kỳ,
   mật khẩu là `VERIFAI_ACCESS_CODE`. Mở trực tiếp link `.hf.space`, không mở qua trang
   huggingface.co, vì app chặn hiển thị trong iframe.

## Lưu ý vận hành

* Mỗi lần Space khởi động lại thì job và nhãn sẽ mất. Product Truth được nạp lại từ
  `deploy/seed.sql`, gồm 8 sản phẩm ở trạng thái "Chuẩn kiểm thử đã xác nhận". Trước buổi chấm,
  **Export All Sessions** để lưu kết quả.
* CPU 2 lõi chậm hơn máy local (12 lõi). Clip 8 giây mất khoảng 2 phút OCR trên máy local,
  trên Space sẽ lâu hơn (chưa đo). Nên demo với clip ngắn.
* Dựng lại seed sau khi sửa Product Truth ở máy local:
  `python scripts/build_seed_db.py --out deploy/seed.sqlite3 --approve-test-reference "<ghi chú>"`
  (bỏ `--approve-test-reference` để giữ trạng thái gốc).
* Frontend đã được backend phục vụ tại cùng địa chỉ. Một frontend riêng trên Vercel
  sẽ cần CORS và giới hạn upload qua proxy, nên chưa làm trong đợt này.
