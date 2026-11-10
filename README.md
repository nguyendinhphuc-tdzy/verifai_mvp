# VerifAI: AI Video Quality & Readiness Checker

VerifAI là prototype hỗ trợ kiểm tra chất lượng video quảng cáo do AI tạo **trước khi xuất bản**. Hệ thống đọc chữ trên hình (OCR), nghe lời thoại (ASR), phân tích hình ảnh (OpenCV và Gemini), đối chiếu với dữ liệu chuẩn của sản phẩm (Product Truth) rồi đề xuất **Pass / Needs Review / Regenerate** kèm bằng chứng và mốc thời gian. Người duyệt luôn là người quyết định cuối cùng.

Nhóm 06 · Học phần Dự án Trí tuệ nhân tạo · Chương trình Công nghệ và Đổi mới sáng tạo, Viện Đổi mới sáng tạo, UEH.

- Video demo: https://drive.google.com/file/d/18nhrztrHlZcnP9e7tKsnjRsJqovjXirf/view?usp=drive_link
- Mã nguồn: https://github.com/nguyendinhphuc-tdzy/verifai_mvp
- Hồ sơ dự án (website tĩnh): thư mục [`site/`](site/), mở trực tiếp `site/index.html` bằng trình duyệt.

> Phạm vi: đây là prototype phục vụ nghiên cứu, chạy trên máy cục bộ. VerifAI không tự phê duyệt hay đăng video, không đưa ra kết luận pháp lý và chưa được doanh nghiệp nào triển khai.

---

## Mục lục

1. [Yêu cầu hệ thống](#1-yêu-cầu-hệ-thống)
2. [Cài đặt từ file ZIP](#2-cài-đặt-từ-file-zip)
3. [Chạy ứng dụng](#3-chạy-ứng-dụng)
4. [Bật đầy đủ các bước phân tích (OCR, ASR, Gemini)](#4-bật-đầy-đủ-các-bước-phân-tích-ocr-asr-gemini)
5. [Thử phân tích một video](#5-thử-phân-tích-một-video)
6. [Chạy bộ kiểm thử tự động](#6-chạy-bộ-kiểm-thử-tự-động)
7. [Các script tiện ích](#7-các-script-tiện-ích)
8. [Xử lý sự cố thường gặp](#8-xử-lý-sự-cố-thường-gặp)
9. [Cấu trúc thư mục](#9-cấu-trúc-thư-mục)
10. [Bảo mật và giới hạn](#10-bảo-mật-và-giới-hạn)

---

## 1. Yêu cầu hệ thống

| Thành phần | Yêu cầu |
|---|---|
| Hệ điều hành | Windows 10/11 64-bit (nhóm đã kiểm thử). macOS/Linux chạy được phần cơ bản nhưng nhóm chưa kiểm thử đầy đủ. |
| Python | **Python 3.11** (khuyến nghị, đã kiểm thử). Các gói OCR (PaddlePaddle 3.2.0) được chọn cho Python 3.11 trên Windows x64. |
| Dung lượng | Khoảng 260 MB cho môi trường cơ bản. Gói OCR/ASR và mô hình tải về lần đầu cần thêm nhiều dung lượng hơn (vài GB tùy mô hình). |
| Internet | Cần khi cài thư viện, khi OCR/ASR tải mô hình lần đầu và khi gọi Gemini. |
| FFmpeg | Không bắt buộc, nên có trong PATH để xử lý một số định dạng video. |
| API key Gemini | Không bắt buộc. Chỉ cần nếu muốn bật phân tích hình ảnh bằng Gemini (mục 4.2). |

Kiểm tra phiên bản Python:

```powershell
py -3.11 --version      # Windows có Python Launcher
python --version        # hoặc lệnh python thông thường
```

Nếu chưa có Python 3.11, tải tại https://www.python.org/downloads/ và chọn **Add python.exe to PATH** khi cài.

---

## 2. Cài đặt từ file ZIP

Sau khi tải ZIP từ GitHub (nút **Code → Download ZIP**) và giải nén, thư mục thường có tên `verifai_mvp-main`. Mọi lệnh bên dưới chạy **trong thư mục này**.

### Windows (PowerShell)

```powershell
# 1. Vào thư mục đã giải nén (sửa đường dẫn cho đúng máy của thầy/cô)
cd "$HOME\Downloads\verifai_mvp-main"

# 2. Tạo và kích hoạt môi trường ảo
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Cài thư viện cơ bản (FastAPI, OpenCV, Gemini SDK)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# 4. Tạo file cấu hình từ file mẫu, nạp sẵn 8 sản phẩm mẫu cho lần chạy đầu
Copy-Item .env.example .env
(Get-Content .env) -replace '^VERIFAI_SEED_DB=.*', 'VERIFAI_SEED_DB=deploy/seed.sql' | Set-Content .env -Encoding utf8
```

Nếu bước 2 báo lỗi *running scripts is disabled on this system*, chạy lệnh sau rồi kích hoạt lại (chỉ áp dụng cho cửa sổ PowerShell hiện tại):

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Nếu máy không có lệnh `py`, thay `py -3.11` bằng `python` (với điều kiện `python --version` là 3.11).

### macOS / Linux (bash, chưa được nhóm kiểm thử đầy đủ)

```bash
cd ~/Downloads/verifai_mvp-main
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
sed -i.bak 's|^VERIFAI_SEED_DB=.*|VERIFAI_SEED_DB=deploy/seed.sql|' .env
```

### Về file `.env`

`backend.py` tự đọc file `.env` khi khởi động. Biến đã đặt sẵn trong terminal sẽ được ưu tiên hơn giá trị trong `.env`. File `.env` đã nằm trong `.gitignore`, không đưa lên GitHub.

Dòng `VERIFAI_SEED_DB=deploy/seed.sql` chỉ có tác dụng khi **chưa có cơ sở dữ liệu** (lần chạy đầu). Ứng dụng sẽ tạo `data/verifai.sqlite3` và nạp 8 sản phẩm mẫu:

| SKU | Sản phẩm |
|---|---|
| SKU001 | Sữa tắm gội toàn thân |
| SKU002 | Bình sữa |
| SKU003 | Tã dán |
| SKU004 | Sữa bột |
| SKU005 | Khăn ướt |
| SKU006 | Kem dưỡng da mặt |
| SKU007 | Ghế ăn dặm Abiie Beyond Junior Y High Chair |
| SKU008 | TendeRoo Baby Nappy Care Cream 20g |

Dữ liệu sản phẩm SKU001-SKU006 là dữ liệu giả lập phục vụ kiểm thử, không phải dữ liệu nội bộ của doanh nghiệp.

---

## 3. Chạy ứng dụng

Kích hoạt môi trường ảo (nếu đang mở cửa sổ mới) rồi khởi động server:

```powershell
.\.venv\Scripts\Activate.ps1                     # macOS/Linux: source .venv/bin/activate
python -m uvicorn backend:app --host 127.0.0.1 --port 8000
```

Khi terminal hiện `Application startup complete.`, mở trình duyệt:

| Địa chỉ | Nội dung |
|---|---|
| http://127.0.0.1:8000 | Trang chủ giới thiệu VerifAI |
| http://127.0.0.1:8000/app | Không gian làm việc của reviewer (phân tích và duyệt video) |
| http://127.0.0.1:8000/one-pager | Product one-pager |
| http://127.0.0.1:8000/docs | Tài liệu API tự sinh (Swagger) |

Dừng server: nhấn `Ctrl+C` trong terminal.

Kiểm tra nhanh trạng thái các thành phần (mở terminal thứ hai):

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Depth 4
# macOS/Linux: curl http://127.0.0.1:8000/api/health
```

Kết quả cho biết `ocr`, `asr` đã được cài hay chưa và Gemini (`vlm`) đang bật hay tắt. Với cài đặt cơ bản ở mục 2, kết quả mong đợi là `ocr: false`, `asr: false`, `vlm.enabled: false`.

---

## 4. Bật đầy đủ các bước phân tích (OCR, ASR, Gemini)

Ứng dụng chạy được ngay sau mục 2, nhưng khi chỉ có cài đặt cơ bản, mỗi video chỉ được kiểm tra bằng OpenCV và bộ quy tắc trên phần dữ liệu có sẵn. Hệ thống được thiết kế để **không đề xuất Pass khi thiếu nguồn kiểm tra**, nên phần lớn video sẽ nhận **Needs Review** với lý do "nguồn kiểm tra chưa đầy đủ". Đây là hành vi đúng thiết kế, không phải lỗi.

| Thành phần | Vai trò | Cách bật |
|---|---|---|
| OpenCV | Tách khung hình, phát hiện thay đổi hình ảnh | Có sẵn sau mục 2 |
| OCR (PaddleOCR) | Đọc chữ, giá, dung tích trên video | Mục 4.1 |
| ASR (faster-whisper) | Chuyển lời thoại thành văn bản | Mục 4.1 |
| Gemini | Phân tích hình ảnh, ngữ cảnh, màu sắc, chữ hiển thị | Mục 4.2 |

### 4.1. OCR và ASR (chạy trên máy, không gửi dữ liệu ra ngoài)

```powershell
python -m pip install -r requirements-ai.txt
python -m pip check
python scripts/check_perception.py
```

Kết quả mong đợi: `OCR installed: True` và `ASR installed: True`. Khởi động lại server (mục 3) để áp dụng.

Lần phân tích đầu tiên sẽ tải mô hình OCR và Whisper về máy nên có thể chậm vài phút. Có thể tải trước bằng:

```powershell
python scripts/check_perception.py --live --video "C:\duong\dan\toi\video.mp4"
```

Mặc định OCR và ASR chạy trên CPU. Với video dài, CPU có thể mất vài phút cho mỗi video; nên thử với video ngắn (dưới 30 giây) trước.

### 4.2. Gemini (phân tích trên cloud của Google)

1. Tạo API key tại Google AI Studio: https://aistudio.google.com/apikey
2. Mở file `.env` bằng trình soạn thảo, sửa hai dòng:

   ```ini
   VLM_ENABLED=1
   GEMINI_API_KEY=dan_api_key_vao_day
   ```

   Model mặc định trong `.env.example` là `VLM_MODEL=gemini-3.5-flash`.
3. Kiểm tra kết nối, rồi khởi động lại server:

   ```powershell
   python scripts/check_vlm.py --text-only
   ```

   Kết quả mong đợi: `TEXT-ONLY GEMINI CHECK PASSED`.

Lưu ý:

- Khi bật Gemini, khung hình và video được gửi lên dịch vụ của Google. Chỉ dùng video có quyền sử dụng. Ứng dụng chỉ gửi lên Gemini khi người tải lên khai báo quyền sử dụng phù hợp.
- Việc gọi API Gemini có thể phát sinh chi phí và chịu giới hạn theo gói của tài khoản Google.
- Nếu Google báo `503 UNAVAILABLE` (model quá tải), ứng dụng vẫn hoàn tất phân tích với OCR/ASR và đánh dấu Gemini là lỗi; video sẽ nhận Needs Review. Có thể thử lại sau vài phút bằng nút **Phân tích lại**.
- Không đưa API key vào mã nguồn, ảnh chụp màn hình hay commit.

### 4.3. Tăng tốc OCR bằng GPU (không bắt buộc)

Nhóm đã thử OCR trên GPU NVIDIA bằng một môi trường ảo riêng `.venv-gpu` cài `paddlepaddle-gpu`, nhanh hơn CPU nhiều lần. Thiết lập này phụ thuộc phiên bản CUDA/cuDNN của từng máy nên không nằm trong hướng dẫn chính. Biến `OCR_DEVICE` trong `.env` cho phép chọn `cpu` hoặc `gpu:0`.

---

## 5. Thử phân tích một video

1. Mở http://127.0.0.1:8000/app, chọn **Phân tích video** (hoặc nút **+ Phân tích mới**).
2. Tải lên một video **MP4, MOV, MKV hoặc WEBM**, tối đa **150 MB** và **180 giây** (giới hạn mặc định, chỉnh bằng `MAX_VIDEO_MB` và `MAX_VIDEO_SECONDS` trong `.env`).
3. Chọn sản phẩm tham chiếu (SKU), khai báo quyền sử dụng video và video có do AI tạo hay không.
4. Chờ phân tích xong. Kết quả xuất hiện trong **Danh sách duyệt**: đề xuất của AI, danh sách cảnh báo kèm khung hình và mốc thời gian.
5. Với từng cảnh báo, chọn **Đúng là lỗi** hoặc **Không phải lỗi**, sau đó chọn quyết định cuối: **Chấp thuận**, **Cần kiểm tra** hoặc **Yêu cầu sửa**.
6. Nút **Xuất bằng chứng** tải về file JSON gồm kết quả AI, bằng chứng và quyết định của reviewer.

Bộ 80 video dùng để đánh giá không nằm trong repository vì dung lượng lớn và quyền sử dụng của video công khai. Có thể dùng bất kỳ video quảng cáo ngắn nào, hoặc xem luồng chạy đầy đủ trong video demo ở đầu tài liệu này.

Mọi dữ liệu (cơ sở dữ liệu, video tải lên, khung hình trích xuất) được lưu trong thư mục `data/` trên máy.

---

## 6. Chạy bộ kiểm thử tự động

Bộ kiểm thử chạy offline, không cần API key, không gọi Gemini và không ghi vào `data/` (test tự bỏ qua file `.env`).

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Kết quả tại thời điểm 10/11/2026 trên bản tải từ GitHub với cài đặt cơ bản: **333 passed**.

---

## 7. Các script tiện ích

Chạy trong môi trường ảo đã kích hoạt, tại thư mục gốc của dự án.

| Lệnh | Công dụng |
|---|---|
| `python scripts/check_perception.py` | Kiểm tra OCR/ASR đã cài chưa; thêm `--live --video <file>` để nạp mô hình thật |
| `python scripts/check_vlm.py --text-only` | Kiểm tra kết nối Gemini bằng một câu hỏi ngắn; bỏ `--text-only` để thử cả phân tích ảnh |
| `python scripts/run_eval_batch.py --data-dir <thư mục tạm> --out report.json --video "duong\dan\video.mp4=SKU001"` | Chạy một hoặc nhiều video qua toàn bộ pipeline trong thư mục dữ liệu riêng, không ảnh hưởng `data/`; thêm `:public` sau SKU cho video công khai |
| `python scripts/evaluate_dataset.py --help` | Quy trình đánh giá cả bộ dữ liệu video và xuất bảng tổng hợp (cách dùng ở phụ lục kỹ thuật) |
| `python scripts/build_vercel_site.py` | Dựng lại website tĩnh trong `site/` từ trang chủ, one-pager và `site_src/ho-so.html` |
| `python scripts/build_seed_db.py --out deploy/seed.sqlite3` | Xuất dữ liệu sản phẩm từ cơ sở dữ liệu hiện tại thành file seed |
| `powershell -ExecutionPolicy Bypass -File scripts\start_public_demo.ps1` | Mở bản demo công khai qua Cloudflare Tunnel (cần cài `cloudflared` và đặt `VERIFAI_ACCESS_CODE` ít nhất 8 ký tự trong `.env`); dữ liệu demo lưu riêng ở `data_demo/` |

---

## 8. Xử lý sự cố thường gặp

| Hiện tượng | Cách xử lý |
|---|---|
| `running scripts is disabled on this system` khi kích hoạt `.venv` | Chạy `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` rồi kích hoạt lại |
| `'py' is not recognized` | Dùng `python` thay cho `py -3.11`, sau khi kiểm tra `python --version` là 3.11 |
| Cổng 8000 đang bận (`address already in use`) | Đổi cổng: `python -m uvicorn backend:app --host 127.0.0.1 --port 8001`, rồi mở http://127.0.0.1:8001 |
| Cài `requirements-ai.txt` thất bại | Kiểm tra đang dùng Python 3.11 64-bit; các phiên bản PaddlePaddle trong file được chọn cho Python 3.11 |
| Danh sách sản phẩm trống | `VERIFAI_SEED_DB` chỉ nạp khi chưa có cơ sở dữ liệu. Có thể tạo sản phẩm trong trang **Sản phẩm**, hoặc bắt đầu lại như dòng cuối bảng này |
| Video nào cũng nhận Needs Review | Kiểm tra `/api/health`: nếu OCR/ASR/Gemini chưa bật thì đây là hành vi đúng thiết kế (mục 4) |
| Gemini báo `503 UNAVAILABLE` | Model đang quá tải phía Google; thử lại sau vài phút |
| Lần phân tích đầu tiên rất chậm | OCR/ASR đang tải mô hình về máy; các lần sau nhanh hơn |
| Muốn xóa toàn bộ dữ liệu và bắt đầu lại | Dừng server rồi xóa `data/verifai.sqlite3` cùng hai thư mục `data/uploads/` và `data/frames/` (thao tác này xóa mọi video và kết quả đã có) |

---

## 9. Cấu trúc thư mục

| Đường dẫn | Nội dung |
|---|---|
| `backend.py` | Ứng dụng FastAPI: API, hàng chờ phân tích, luồng xử lý video, lưu kết quả vào SQLite |
| `verifai_core/` | Các module kiểm tra: OCR thích ứng, đối chiếu giá, claim, thương hiệu, nhãn AI, nhất quán màu sắc và chữ, kết nối Gemini, logic đề xuất |
| `static/` | Giao diện: trang chủ (`home.html`), không gian reviewer (`index.html`), one-pager |
| `scripts/` | Script kiểm tra, đánh giá, dựng dữ liệu demo và website |
| `tests/` | Bộ kiểm thử tự động |
| `deploy/seed.sql` | 8 sản phẩm mẫu cho lần chạy đầu |
| `site/`, `site_src/` | Website tĩnh "Hồ sơ dự án" (đưa lên Vercel, không cần backend) |
| `docs/` | Tài liệu kỹ thuật bổ sung |
| `ARCHITECTURE.md` | Kiến trúc hệ thống |
| `.env.example` | File cấu hình mẫu, giải thích từng biến |
| `requirements*.txt` | Thư viện: cơ bản (`requirements.txt`), OCR/ASR (`requirements-ai.txt`), kiểm thử (`requirements-dev.txt`), phiên bản cố định đã kiểm thử (`requirements-lock.txt`) |

---

## 10. Bảo mật và giới hạn

- Ứng dụng chỉ nhận kết nối từ máy cục bộ (`127.0.0.1`). Truy cập từ xa chỉ mở khi đặt cả `VERIFAI_PUBLIC_MODE=1` và mã truy cập `VERIFAI_ACCESS_CODE`.
- Không có tài khoản người dùng, phân quyền hay mã hóa dữ liệu; đây là prototype một người dùng, không dùng cho môi trường production.
- Kết quả đánh giá trên 80 video (02/11/2026): Recall 83,33%, Precision 71,43%, FPR 69,23% theo quy ước gắn cờ, trên nhãn nội bộ của nhóm. Kết quả chưa được kiểm chứng trên tập dữ liệu độc lập.
- Đề xuất Pass không có nghĩa video chắc chắn đúng; mọi cảnh báo cần người duyệt xác minh trước khi quyết định phát hành.

---

# Phụ lục: ghi chú kỹ thuật chi tiết (tiếng Anh)

Phần dưới đây là nhật ký kỹ thuật qua các sprint, giữ nguyên để tra cứu. Một số mục mô tả cấu hình của phiên bản cũ (ví dụ tên model Gemini hoặc giá trị mặc định đã thay đổi); khi khác với hướng dẫn ở trên, **hướng dẫn ở trên và file `.env.example` là bản hiện hành**.

## 1. Upgrade an existing v1 installation (preserve your data)

1. **Stop** your running v1 server. Back up the entire `data/` directory, especially `data/verifai.sqlite3`.
2. Unzip v2 into a new directory (`verifai_mvp`). If you want your old jobs and products, **copy your existing `data/` directory into this new directory** before starting. Do not overwrite the backup.
3. Create/activate a virtual environment (or reuse v1's venv if dependencies are compatible).
4. `pip install -r requirements.txt`
5. Start the backend. At startup it adds v2 columns to existing SQLite `evidence` and `findings` tables **without deleting v1 rows**. The migration is idempotent.
6. Open existing jobs in the Review Queue; click **Re-analyze** to apply v2 modules to a previously uploaded video. **Re-analyze resets existing findings and the final reviewer decision**, while preserving the audit history, product, original video, and labels. Record the previous decision first if needed.

**Python 3.10+** is recommended. `FFmpeg` on PATH is recommended. For initial testing, keep the web app local on `127.0.0.1`.

## 2. Run base app (without a VLM)

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend:app --host 127.0.0.1 --port 8000 --reload
```

Open http://127.0.0.1:8000 (home page) or http://127.0.0.1:8000/app (reviewer
workspace). API docs: http://127.0.0.1:8000/docs. `tests/test_ui_feature_contract.py`
fails if a UI change drops a control that a backend feature needs (usage rights,
AI-generated flag, RULE02 product fields, SKU change, AI label suggestion, rule basis).

With VLM disabled, OpenCV temporal checks still run, and potential visual changes appear as **VIS-SCREEN** low-severity review prompts. This does **not** imply AI-generated defects.

## 3. Enable Gemini Flash (cloud VLM)

Video frames are sampled locally by OpenCV, then selected JPEG frames are sent to Gemini.
**Privacy:** selected frames leave your device. Obtain permission and avoid transmitting personal/sensitive video without authorization.
Do not commit your API key. Run in PowerShell:

```powershell
$env:GEMINI_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host -AsSecureString -Prompt 'Gemini API key')).Password
$env:VLM_ENABLED="1"
$env:VLM_MODEL="gemini-3.8-flash"
$env:VLM_MAX_FRAMES="1"
$env:VLM_MAX_PAIRS="0"
$env:GEMINI_MAX_ATTEMPTS="1"
$env:VLM_TIMEOUT_SECONDS="45"
$env:VLM_TOTAL_BUDGET_SECONDS="120"
$env:OCR_ENABLED="1"
$env:ASR_ENABLED="1"
$env:WHISPER_MODEL="tiny"
python -m pip install -r requirements-ai.txt
python scripts/check_vlm.py --text-only  # minimal API connectivity check
python scripts/check_vlm.py              # full structured vision smoke test
python -m uvicorn backend:app --host 127.0.0.1 --port 8001
```

On Windows, `Read-Host -AsSecureString` masks the key while entering it. Do not paste keys into chat logs or commits. If a key was disclosed, rotate it in Google AI Studio.

If an API call returns `503 UNAVAILABLE` or `504 DEADLINE_EXCEEDED`, the production adapter now disables SDK's hidden HTTP retries and uses one application-level attempt by default. Default timeout is 45 seconds per call, and a soft 120-second budget prevents scheduling further calls; a single active SDK call cannot be interrupted by the soft budget. You can still test `python scripts/check_vlm.py --text-only` to isolate API issues. If text-only works but the vision smoke test fails, inspect the vision schema/request. The server can still be overloaded; do not claim a passed live test until it actually succeeds.

Gemini is still billed/rate-limited according to your project and plan.
The MVP sends selected JPEG frames, not the full video/audio. OCR and ASR are enabled in the suggested Windows setup and **require** optional native dependencies and speech/OCR model weights. First install/model initialization can download large files and take time. Missing OCR/ASR or unverified Product Truth never counts as evidence of compliance.
The schema of VLM findings and Human Review remains unchanged.

**VLM configuration** (environment variables):

| Variable | Default | Meaning |
|---|---|---|
| `VLM_ENABLED` | `0` | Opt-in to VLM calls |
| `GEMINI_THINKING_LEVEL` | `low` | Gemini 3.8 Flash reasoning effort (low/medium/high; minimal unsupported) |
| `VLM_MODEL` | `gemini-3.8-flash` | Gemini API model ID |
| `GEMINI_API_KEY` | unset | Gemini API key, set in shell and never commit |
| `VLM_TIMEOUT_SECONDS` | `45` | Per-request SDK timeout in seconds; not a hard overall job deadline |
| `VLM_MAX_FRAMES` | `1` | Single-frame checks, capped at 8 |
| `VLM_MAX_PAIRS` | `1` | Same-shot pair checks, capped at 6 |
| `GEMINI_MAX_ATTEMPTS` | `1` | Application-level attempts; SDK retries disabled by default |
| `VLM_TOTAL_BUDGET_SECONDS` | `120` | Soft VLM budget; skip remaining calls once exceeded |
| `VLM_STOP_AFTER_FAILURES` | `2` | Stop scheduling calls after consecutive API failures |
| `OCR_ENABLED` | `1` | Set to `0` to skip local OCR processing |
| `ASR_ENABLED` | `1` | Set to `0` to skip local ASR processing |
| `WHISPER_MODEL` | `tiny` | CPU-friendly ASR model; first run may download weights |
| `VERIFAI_DATA` | `./data` | Persistent storage root |

**Privacy:** Gemini runs in Google's cloud, so selected image frames leave the local machine. Ensure processing rights and user consent before enabling it.

## 4. Enable OCR + ASR on Windows (Python 3.11, CPU first)

The base install `requirements.txt` intentionally has **no heavy OCR/ASR engines**.
Install the AI extras separately in the **same Python environment** used by
Uvicorn. These versions were selected for Windows x64 / Python 3.11 compatibility
(PaddlePaddle 3.2.0, PaddleOCR 3.7.0, faster-whisper 1.2.1); they are not claims
of benchmark accuracy. GPU deployments need a separate CUDA-specific setup.

```powershell
cd C:\Users\PC\Documents\verifai_mvp
# If using a venv, activate it first: .\.venv\Scripts\Activate.ps1
python --version
python -m pip install --upgrade pip
python -m pip install -r requirements-ai.txt
python -m pip check
python scripts/check_perception.py
```

OCR uses PP-OCRv5 configured for Vietnamese (`OCR_LANG=vi`) and PaddlePaddle
CPU inference. ASR uses faster-whisper with Vietnamese (`WHISPER_LANGUAGE=vi`),
`WHISPER_MODEL=base`, CPU/INT8 by default. For potentially better transcription
at a higher memory/latency cost, set `$env:WHISPER_MODEL="small"` before
starting Uvicorn. `WHISPER_MODEL=tiny` is faster but less reliable.

First live inference can download pretrained OCR and ASR models and may be slow.
This is a deliberate local runtime choice, not automatic at installation time:

```powershell
python scripts/check_perception.py --live --video "C:\path\to\your\video.mp4"
python -m uvicorn backend:app --host 127.0.0.1 --port 8000 --reload
Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Depth 5
```

Check `ocr:true`, `asr:true` in health and **`coverage.ocr:ok` /
`coverage.asr:ok`** in a *new or re-analyzed* video job. Health booleans
confirm package presence only; they do not prove the native engine loads,
that model weights exist, or that recognition is accurate. If `coverage` is
`error: ...`, check the server traceback and run the live diagnostic above.
An `ok` status with zero recognized lines may mean no readable text or speech.
Re-analysis resets current findings and reviewer decision (preserves audit).

`ffmpeg` on PATH is optional for faster-whisper audio decoding (PyAV bundles
its own FFmpeg libraries), but is recommended for video conversion/troubleshooting.

**VLM is API-based:** The Python SDK is installed by `requirements.txt`; no Ollama weights are required. Set `GEMINI_API_KEY` and `VLM_ENABLED=1` before starting the backend.

References: [PaddleOCR installation](https://www.paddleocr.ai/main/en/version3.x/installation.html),
[PaddleOCR multilingual OCR](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html),
[faster-whisper](https://github.com/SYSTRAN/faster-whisper).

## 5. What the v2 pipeline actually does

```text
Video + Product Truth
  -> OpenCV frame sampling (max 60 frames) + optional PaddleOCR + faster-whisper
  -> Temporal signals: HSV histogram, frame pixel delta, pHash, ORB matches
  -> Same-shot pair selection (avoid likely scene cuts)
  -> Optional Gemini VLM: sampled single frames + up to 2 frame pairs
  -> Pydantic JSON schema validation + evidence provenance
  -> Evidence normalization (dedup adjacent repeated OCR/ASR, keep timestamps)
  -> Deterministic price/restricted-claim rules + visual candidate flags
  -> Findings linked to canonical evidence IDs
  -> Human review + audit log + JSON evidence export
```

**Evidence Normalization:** Each canonical item has `kind`, `timestamp`, `end_timestamp`, `content`, `score`, `frame`, `frame2`, `source_model`, `fingerprint`, `metadata.sources` (original raw observations). It merges only repeated OCR/ASR from the same source within a 2.3-second gap; it **does not** merge different modalities or VLM assertions, avoiding false corroboration.

**Visual Consistency Checking:** OpenCV compares consecutive sampled frames and classifies likely scene cuts vs same-shot candidates. The VLM compares selected same-shot pairs for apparent changes to product details. `VIS-01`/`VIS-02`/`VIS-03` are **review candidates**, not proven defects. Natural movement, transitions, lighting, occlusion and camera angles can cause false positives. Two sampled frames cannot establish the exact frame where a transient anomaly occurred.

**VLM:** Uses Gemini `models.generate_content` with locally sampled JPEG frames and structured JSON response schema. Requests use `temperature=0`. Outputs are validated and stored with model + prompt versions; malformed output, rate limits or API failures produce `coverage.vlm=error`/`partial` rather than fabricated findings. `confidence` is **self-reported, not calibrated**. No automatic `Regenerate` from VLM-only flags.

**Product truth:** Product name, SKU, brand, price, approved/restricted claims are *textual reference information*, **not an image of the actual product**. The system cannot reliably detect lookalike packaging or prove SKU mismatch from appearance alone. `SKU-01` is only a tentative visible-label contradiction.

## 6. API endpoints added in v2

- `GET /api/health`: module readiness, including VLM model availability.
- `POST /api/jobs/{id}/reanalyze`: reprocess existing video with current module configuration; clears previous final reviewer decision, keeps audit history.
- `GET /api/jobs/{id}/evidence/export`: download JSON of canonical evidence, findings, provenance, coverage, and model versions.
- `GET /api/jobs/{id}`: backward-compatible v1 response, with new evidence metadata, `end_timestamp`, `frame2`, `fingerprint`, and linked finding IDs.

## 7. Tests

```bash
pip install pytest httpx
python -m pytest -q tests
```

Automated tests cover: v1 smoke flow; evidence dedup/provenance; scene-cut and temporal candidate signals; VLM schema and invalid JSON; Gemini API adapter; SQLite v1->v2 migration; **end-to-end job with a mocked VLM** including linked findings, JSON export, re-analysis and audit log. They do **not** evaluate the accuracy or speed of the real Gemini model.

## 8. Known limitations

- Research MVP only: single user, local SQLite, in-process background threads, no authentication, roles, encryption, antivirus, retention, production queue, or distributed job management. Keep it on `127.0.0.1`.
- Visual signals are screening heuristics, not robust object tracking, optical flow-based segmentation, product reference-image matching, deepfake detection, or frame-level truth labels.
- A VLM can hallucinate; all findings require human review. OCR/ASR may miss text or transcribe incorrectly. Price rules can flag unrelated amounts.
- No C2PA provenance verification, legal-compliance certification, online benchmark, or Ecomobi integration.
- Official workbook v2.1 contains 80 evaluation case records (6 original / 44 error scenarios / 30 public sources), not necessarily 80 available or analyzed video files. Actual precision/recall remains exploratory.

For architecture details and upgrade checklist see [ARCHITECTURE.md](ARCHITECTURE.md).

## Open-source references

- [Google Gemini API](https://ai.google.dev/gemini-api/docs/get-started)
- [FastAPI](https://github.com/fastapi/fastapi), [OpenCV](https://github.com/opencv/opencv)
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR), [faster-whisper](https://github.com/SYSTRAN/faster-whisper)

Review individual library/model licenses before commercial use.

## v2.1 - Sprint-2 Dataset Workspace (80 official evaluation cases)

The latest Sprint-2 workbook defines **80 evaluation cases**: `VID_GOC01–06`
(6 originals), `VID_LOI01–44` (44 controlled-error scenarios) and `PUB001–030`
(30 public examples). These are **case records, not proof that 80 actual video
files have been downloaded or run through VerifAI**.

1. Run the existing app (after backing up `data/`) with `python -m uvicorn backend:app --reload`.
2. Open **Bộ kiểm thử → Import Excel (.xlsx)** (visible at the top of the Dataset page), select the **official Sprint-2 workbook** `Sprint 2 - Thu thập & tạo dữ liệu thật.xlsx` (max 8 MB; required tabs beginning with `1. Kich ban goc` through `7. Policy Rules`). This is **not** a generic spreadsheet import: the separately generated Actual Evaluation Review Pack is not accepted as the 80-case source workbook. Re-import retains prior verified labels and product links.
3. The importer creates 6 sample Product Truth records. Public cases with no
   verified SKU are kept unlinked. Review prices/variants/claims before using
   them as hard rules; product info and legal references are not auto-verified.
4. Select a case, optionally link the correct Product Truth, and choose
   **Upload video cho case**. A corresponding **real video file** is required
   to produce an actual result.
5. Add at least **two independent agreeing annotations** under Dataset. Ground
   truth from one workbook reviewer or a controlled *script plan* is not treated
   as verified real-video ground truth.
6. Open Evaluation: the **Official evaluation - Actual runs only** panel has
   no metrics until both real-video results and independently verified labels
   exist. Metrics are based on the latest completed run per case with perception
   coverage; coverage-only and weak visual heuristics are excluded.

### Isolation and scope rules

- The Sheet 5/6 `VerifAI báo` fields are **simulated baseline predictions**:
  stored in `dataset_simulated`, never mixed with actual `jobs`/model metrics.
- Sheet 7 policy rules are imported as **unverified references**, not activated
  as executable law/compliance judgments.
- Re-imports are idempotent for cases, predictions, rules and sample products.
  Existing reviewed case/product links and annotation records are preserved.
- No automatic video download or scraping. The public links are metadata only.
- This remains a **localhost research prototype without authentication**; do
  not expose it publicly or upload private/customer/children data without proper safeguards.
- Running `python -m pytest -q` includes the new v2.1 importer regression tests.

New API endpoints: `POST /api/dataset/import`, `GET /api/dataset/cases`,
`GET /api/dataset/summary`, `GET /api/dataset/policies`,
`POST /api/dataset/cases/{code}/link`,
`POST /api/dataset/cases/{code}/annotations`. `POST /api/jobs` accepts optional
`case_code` form data so video jobs can be linked to evaluation cases.


## OCR/ASR performance and interrupted-job recovery

For real-video cold/warm CPU benchmarking and automatic recovery after
Uvicorn restarts, see [Job Recovery & Benchmark](docs/JOB_RECOVERY_BENCHMARK.md).

Run `python scripts/benchmark_perception.py --video "C:\\path\\to\\video.mp4" --ocr-frames 12 --output benchmark.json`
on Windows after installing the AI dependencies. The tool reads video locally,
does not upload the file, and reports separate OCR and ASR times.
`OCR_MAX_FRAMES` defaults to 12 to avoid running expensive OCR on all sampled
visual frames (up to 60). This trades off speed against coverage.
`MAX_CONCURRENT_JOBS` defaults to 1 for local CPU operation.

**Speed-ups of 04/11/2026** (all on by default, each can be switched off):

- `VLM_PREFETCH=1`: the three Gemini calls (native video, colour, text) start
  right after frame sampling and run side by side, in parallel with local
  OCR/ASR. Results are consumed at the VLM stage exactly as before. Timings
  record `vlm_<call>_call_seconds` and `vlm_wall_seconds`.
- Mirror check (VIS-04) reuses the full-video OCR text: a sample whose original
  frame already reads both the brand and the AI label is skipped, and the
  original frame is never OCR'd twice (`frame_anomaly.mirror.samples_skipped`).
- `WARM_MODELS=1`: OCR then ASR load in a background thread at startup
  (about 36 s on the team laptop), so the first video does not pay for it.

Measured on the team laptop (CPU, one video at a time, Gemini unavailable):
VID_LOI26 89 s → 62 s (mirror check 12.6 s → 2.3 s). VID_LOI30/LOI32 are still
flagged VIS-04 and VID_GOC01 is not. OCR is now ~90% of the time; avoid running
more than 2-3 videos at once on one CPU (8 parallel videos made each 4-6x slower).

**GPU OCR (NVIDIA, tested on RTX 4050 Laptop, driver CUDA 13.1):**

```powershell
& 'C:\Users\PC\AppData\Local\Programs\Python\Python311\python.exe' -m venv --system-site-packages .venv-gpu
.venv-gpu\Scripts\python.exe -m pip install paddlepaddle-gpu==3.2.0 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
```

`scripts\start_public_demo.ps1` uses `.venv-gpu` automatically when it exists;
delete the folder to return to CPU. `OCR_DEVICE=cpu|gpu:0` forces a device.
Same model and frames: 1.05 s → 0.095 s per OCR frame; text identical except one
already-garbled line. End to end, Gemini off: LOI26 62 s → 13 s, LOI30 152 s → 25 s,
LOI32 58 s → 11 s, GOC01 118 s → 15 s, with the same findings (VIS-04 on LOI30/32,
TEXT-02 on LOI26, nothing new on GOC01). Model warm-up 36 s → 18 s.

In-process worker threads can still hang in native inference; no reliable
in-place cancellation is provided. Stop and restart the **single-worker**
Uvicorn process to recover interrupted jobs; after repeated interruptions,
affected jobs are marked failed for manual intervention. Public production
hosting still requires external durable queues and authentication.

## Sprint A1 - Price Parser v3

Vietnamese price extraction/verification now uses a conservative structured
parser instead of matching every four-digit number. It recognizes VND shorthand,
separates current/original/promotional amounts, and distinguishes `MATCH`,
`MISMATCH` and `INSUFFICIENT_EVIDENCE`. A detected mismatch is a
**reviewer-only medium-severity PRICE-01 candidate**, not automatic Regenerate.
Price assessments are stored in canonical evidence metadata and exported as JSON.

Read [Price Verification A1](docs/PRICE_VERIFICATION_A1.md) for formats,
examples, tests, limitations and safe re-analysis guidance.

## Sprint A2 - Product Truth & Claim Verification (v3-alpha2)

Reference products now support source URL/note, explicitly unverified/reviewed status, a revision counter, audit snapshots, and a revision-checked edit route. Restricted phrase detection distinguishes assertions from explicit negation and uncertain quotations, with all outcomes retained in evidence metadata. An asserted candidate is medium-severity and **requires human verification**, never automatic rejection. Old products/dataset importer remain compatible.

See [Product Truth & Claim Verification A2](docs/PRODUCT_TRUTH_CLAIMS_A2.md) for API, UI, tests, audit implications, and limitations.

## Sprint A3 - Cross-modal Verification Engine

The review workspace now shows a concise, evidence-linked case-level verification
result, built from existing A1 price and A2 claim metadata plus conservative VLM
and visual findings. It classifies observations as candidates, differing signals,
consistent signals or insufficient evidence. The overall report status is
`REVIEW_REQUIRED`, `INSUFFICIENT_EVIDENCE` or `NO_ISSUES_OBSERVED`.
**None of these is an automated approval/rejection.** Repeated frames within
one modality are not counted as independent corroboration.

Reports are stored at `GET /api/jobs/{id}` → `details.verification`, and can
be read directly at `GET /api/jobs/{id}/verification`. Both reports and
canonical evidence links are included in the JSON evidence export. Old jobs
remain readable; only a deliberate Re-analyze creates an A3 report for them.

See [Verification Engine A3](docs/VERIFICATION_ENGINE_A3.md) for the exact
status semantics, data contract, tests and known limitations.


## Sprint B1 - Multimodal Evidence Reliability (merged with Gemini)

The video sampler targets one frame/second on short clips, capped at 60 frames. OCR selection can use `OCR_SAMPLING_MODE=hybrid` (temporal anchors plus changed frames) or `uniform`. The OCR engine still analyzes up to `OCR_MAX_FRAMES=12` frames by default, unless `OCR_ENABLED=0` disables OCR entirely.

The app reports OCR attempted/successful/failed/empty frame counts and ASR segment timing under `details.perception_quality`. ASR end timestamps are retained in evidence when valid. These counts are operational coverage, not proof of OCR or claim accuracy.

See [Sprint B1 Reliability](docs/MULTIMODAL_RELIABILITY_B1.md) for technical details. **Cloud privacy change:** when `VLM_ENABLED=1`, the sampled JPEG images sent to Gemini leave the local machine. Explicit rights/consent remain required.

### Fast demo + OCR/ASR verification (v2.2.1)

The actual model run on `VID_LOI01` lasted >21 minutes: four of six Gemini calls failed with 503/504 even though OpenCV sampling took under two seconds. The pipeline now schedules a maximum of **one selected single-frame call (temporal pair optionally enabled)** by default; you may increase this during coverage benchmarking. This does **not** guarantee a specific real response time. Progress exposes `vlm done/total` and attempted, successful and skipped call counts after completion.

Visible text reported by Gemini as `vlm_observation` with `category=visible_text` and confidence ≥0.80 now enters the existing deterministic price/claim parsing rules. Example: candidate 99.000đ against 149.000đ creates a medium `PRICE-01` warning, source `price_rule_vlm`, linked to its frame and flagged as self-reported VLM evidence; it is **not** an automatic violation, and discounts / unreviewed Product Truth require human verification. Product, packaging and scene descriptions do not enter these text rules. OCR/ASR retain distinct independent provenance.

On the current Windows workstation, enter `$env:OCR_ENABLED="1"` and `$env:ASR_ENABLED="1"` **in the shell where Uvicorn is started**; the `.env.example` file is an example, not automatically loaded. Install `requirements-ai.txt` in that Python environment, inspect `python scripts/check_perception.py`, and then restart Uvicorn. Existing processing jobs can be recovered at startup and may run before new uploads. Do not upload the same video repeatedly while the queue is blocked.

### Brand consistency and Gemini outage safety (Sprint B2)

**Brand screening:** OCR evidence such as `BabySkin` on a tube and
`SkinBaby` in advertising copy generates a **review-only** `SKU-01`
candidate only when a clear transposed two-part brand token is detected
with confidence >=0.90 on at least **two distinct frames**.
The finding retains the original OCR text and canonical evidence ID, and
Verification displays a linked `brand` candidate. This is not broad
brand recognition, not a product SKU match, and cannot auto-reject a video.
Unrelated words and a single OCR reading remain unflagged.

**Gemini failure handling:** the app defaults to one Cloud request per
video (`VLM_MAX_FRAMES=1`, `VLM_MAX_PAIRS=0`), capped by its per-call SDK
timeout. Once two consecutive transient API errors occur (503/504/429/etc.),
an in-process circuit breaker skips Gemini for queued videos for the next
180 seconds. OCR, ASR, rule evaluation and human review still complete, but
`coverage.vlm=error`, not `ok`. After the cooldown, the next job may try
Gemini again. This limits wasted waiting; **it cannot repair a Google API
outage or ensure successful Gemini responses**. Increasing the pair count
improves temporal coverage at the cost of another Cloud request.

In PowerShell **before starting Uvicorn**:

```powershell
$env:OCR_ENABLED="1"
$env:ASR_ENABLED="1"
$env:VLM_ENABLED="1"
$env:VLM_MAX_FRAMES="1"
$env:VLM_MAX_PAIRS="0"
$env:VLM_CIRCUIT_ENABLED="1"
$env:VLM_CIRCUIT_FAILURES="2"
$env:VLM_CIRCUIT_COOLDOWN_SECONDS="180"
$env:VLM_TIMEOUT_SECONDS="45"
# Set a NEW GEMINI_API_KEY securely in the same shell; do not paste it in logs.
python -m uvicorn backend:app --host 127.0.0.1 --port 8001
```

The circuit state is local to the Python process; restarting resets it.
If Gemini is not essential for a price/brand-rule evaluation, set
`VLM_ENABLED=0` to test OCR/ASR independently. Do not interpret incomplete
Gemini coverage as evidence of compliance.


## Final validation handoff (October 2026)

- Default Gemini model for new local configuration: `gemini-3.5-flash-lite`. Set `VLM_ENABLED=1`, provide `GEMINI_API_KEY` privately, then run `python scripts/check_vlm.py --text-only` and `python scripts/check_vlm.py`. Actual API availability and model quality must be verified independently.
- Keep `OCR_ENABLED=1` and `ASR_ENABLED=1` for full local perception.
- For real classification evaluation, use `data/ground_truth_verified.template.csv` and `scripts/evaluate_real_jobs.py`. It requires two agreeing independent annotations and a source reference for each included job.
- Acceptance checklist and limitations: [Final validation protocol](docs/FINAL_VALIDATION_PROTOCOL.md).
- [Final report draft](docs/FINAL_REPORT_DRAFT.md) and [demo shot list](docs/DEMO_SHOTLIST.md). Neither implies an actual benchmark or recording exists.
- Local verification: `python -m pytest -q`, `python scripts/check_vlm.py`, then launch `python -m uvicorn backend:app --host 127.0.0.1 --port 8001` and inspect `http://127.0.0.1:8001/api/health`.



## NEW - Six original products only for Excel import

The MVP Excel button now uploads **only the six original video product
references (Sheet `1. Kich ban goc`)** through
`POST /api/products/import`. It does **not** import 44 error
scenarios, public-video labels, policy simulations or evaluation predictions.
An XLSX file containing only this sheet is supported. It preserves existing
SKUs and never silently overwrites a manually reviewed Product Truth record.
Imported variants and expected video descriptions appear in the Product page.
Source type 'Giả lập' remains unverified.

`POST /api/products/import/reset` with typed `XOA EXCEL` clears
the import only when no job references its products. Manually reviewed
Product Truth is preserved.

The 44 error scenarios can be converted into a separate rule-design and
in-context example library via `python scripts/build_sprint2_examples.py
--xlsx "Sprint 2 - Thu thập & tạo dữ liệu thật (2).xlsx"
--out reports/sprint2_scenario_examples.json`.
This is **not Gemini weight fine-tuning** and **not real-video performance**.
Added conservative `VARIANT-01`, `CLAIM-02` and `TEXT-01` reviewer
candidates. See [Sheet 1 import / scenario adaptation](docs/SHEET1_PRODUCT_IMPORT_RULE_ADAPTATION.md).

The older `/api/dataset/import` is retained for legacy automated tests
and historical evaluation compatibility only. Its former 80-case import
instructions below are legacy, not the new UI upload path.


## AI recommendation versus reviewer decision (Pass / Review / Regenerate)

Completed video jobs now expose `ai_recommendation` separately from
`review_decision` in `GET /api/jobs` and `GET /api/jobs/{id}`.
The first is a **deterministic suggestion based on the OCR/ASR/Gemini
verification report and persisted findings**, not an authoritative legal
decision or a live model-issued pass certificate. The second is the
reviewer's independent choice. Existing completed jobs derive a suggestion
when read and **do not need re-analysis just to show a label**.

- **Pass (proposed):** Product Truth was manually source-reviewed during
  analysis, OCR/ASR/VLM coverage all `ok`, verification reports
  `NO_ISSUES_OBSERVED`, and there are no findings. Means no issues observed
  *in checked scope*, not proof that every frame, law or product property
  was validated.
- **Review (proposed):** Product Truth unverified, model coverage partial,
  candidate issues, conflicts, missing context or ambiguous claims. No
  findings alone never overrides an unverified reference.
- **Regenerate (proposed):** A non-VLM-only **high-severity** finding linked
  to actual evidence and not rejected, with reviewed Product Truth and
  complete OCR/ASR/VLM coverage. Current OCR/VLM rule candidates
  are intentionally medium-severity and normally remain Review pending
  adjudication; the system does not manufacture Regenerate verdicts.

For example, **VID_GOC01.mp4** may have zero findings, matching
149,000 VND price and all three modules `ok` but Product Truth
`reference_status: unverified`: it must show **AI recommendation: Review**
with a source-validation explanation, while reviewer choice remains
`Chưa duyệt`. In the Product Truth editor, provide a legitimate source
URL or detailed review note, mark the reference reviewed, save, then
**re-analyze** to generate a new snapshot. For demonstration/illustrative
reference data, this is a review of the provided fictional scenario, not
certification of real commercial facts.

Re-analysis clears the previous human verdict and regenerates evidence;
export or record the previous review first. Existing jobs preserve
historical `jobs.decision` and human decisions; the dynamic
`ai_recommendation` is the canonical displayed suggestion on older jobs.


## Export All Sessions (current UI, local-only)

From either **Tổng quan** or **Hàng đợi duyệt**, use
**↓ Export All Sessions**. A single ZIP downloads from
`GET /api/sessions/export`. This endpoint is **read-only**, not a data
reset and not a destructive operation.

Contents:
- `session_summary.csv`: all jobs including failed/queued/unreviewed,
  proposed AI decision/reason, coverage, verification state, finding count,
  final reviewer decision/name/note.
- `ai_findings.csv`: every stored candidate finding, code, severity,
  timestamp, full explanation, source, linked evidence ID, reviewer flag.
- `sessions/*.json`: complete per-job JSON including Product Truth snapshot,
  OCR/ASR/Gemini evidence, verification, proposed AI decision, reviewer
  decision, independent labels and audit history.
- `README.txt`: scope and export notes.

The ZIP intentionally excludes raw videos and frame image binaries. Keep the
ZIP private: it can contain confidential input and reviewer notes. Candidate
findings are not proven violations. No sessions are deleted by export.

The export API is localhost-only under the current local security middleware.
Its presence does **not** imply production readiness: proper authentication,
role authorization, secret management, backup/restore and audit of downloads
remain required before multi-user/public deployment. The product-only Excel
import and test-only Product Truth approval are retained unchanged.


## Full video analysis (OCR all frames + Gemini native video)

The OCR and Gemini pipeline now has two *independent* coverage controls:

```powershell
$env:OCR_ENABLED="1"
$env:OCR_SCAN_MODE="all"
$env:ASR_ENABLED="1"
$env:VLM_ENABLED="1"
$env:VLM_INPUT_MODE="video"
$env:VLM_MODEL="gemini-3.5-flash-lite"
$env:VLM_VIDEO_PROCESS_TIMEOUT_SECONDS="240"
python -m uvicorn backend:app --host 127.0.0.1 --port 8001
```

- **OCR_SCAN_MODE=all** (default on this branch): the pipeline reopens the
  input file and decodes *every frame* sequentially; PaddleOCR is invoked once
  for each decoded frame. A 30 FPS / 10-second video normally means about
  300 OCR calls. No 4-, 12- or 60-frame OCR cap. OCR text records include
  `source_frame_index` and timestamps. JPEGs are stored for OCR frames only
  if text was extracted. This mode can take hours for longer videos on CPU;
  users must monitor `timings.ocr_frames` and `perception_quality.ocr`.
- **OCR_SCAN_MODE=sampled**: retains the prior `OCR_MAX_FRAMES` (e.g. 4)
  plus `OCR_SAMPLING_MODE` (hybrid / uniform) behavior.
- The existing OpenCV thumbnail / scene-change subsystem still retains
  **up to 60 sampled frames** for UI and temporal heuristics. Full OCR
  scans the input a second time. This is deliberate to avoid keeping every
  decoded image in memory.
- **VLM_INPUT_MODE=video** (default): Gemini's Files API receives the
  **original video including audio**, not 1/4 chosen JPEGs. The request
  asks for temporal context, a timeline summary and timestamped
  `observations`/`issues`. This uses a Gemini-side default video sampling
  strategy (typically about **1 visual FPS**), **NOT guaranteed source-frame
  by source-frame processing**. Model-produced timestamps are estimates.
  The service attempts to delete the uploaded Gemini file in a finally
  block. The video leaves the local machine; ensure appropriate rights.
- **VLM_INPUT_MODE=frames**: retains the old static image analysis path
  with `VLM_MAX_FRAMES` and `VLM_MAX_PAIRS`.

Expected output: `details.vlm.input_mode=video`,
`details.vlm.timeline_summary`, `details.vlm.video_summary`,
`evidence.kind=vlm_video_observation` with `timestamp_source=model_reported`.
All existing evidence/finding/verification/reviewer/export APIs are reused.
Failed Gemini video uploads/processing are marked as incomplete VLM coverage
and require a human review; there is **no hidden image-mode fallback**.

**Important limitations:** OCR can only process decodable frames; low-resolution,
blurry and quickly moving text may still be misread. Full video OCR may multiply
CPU latency by hundreds. Gemini native video analysis samples media internally;
neither its JSON timestamps nor its confidence scores are calibrated proof.
This change does not remove the current required `product_id` for uploads;
public videos without a verified product reference still need a separate
observation-first public-discovery mode. Do not assign the six synthetic SKUs
to unrelated commercial videos.


## Sprint 1 (11/2026): stabilization changes

- **Reproducible environment:** use Python 3.11. `python -m pip install -r requirements-lock.txt -r requirements-dev.txt`
  installs the exact versions verified by the offline suite; OCR/ASR extras remain in `requirements-ai.txt`.
  CI now also runs on every push to `main`.
- **Test isolation:** `tests/conftest.py` points `VERIFAI_DATA` at a temporary directory and removes Gemini keys
  before `backend` is imported, so `python -m pytest -q` can no longer touch `data/verifai.sqlite3` or call the live API.
- **Videos without frame-count metadata** (common for WEBM/MKV): frames are now counted by decoding (bounded by
  `MAX_VIDEO_SECONDS`), so the length limit is enforced and Gemini timeline events after 1 s are no longer dropped.
  `details.frame_count_source` is `container` or `decoded`.
- **Usage rights gate for Gemini:** native video stays the default (`VLM_INPUT_MODE=video`), but video or frames are
  sent to Google only when the upload declares a usage right. The upload form now requires the field. Allowed values:
  `self_created`, `permission_granted`, `public_review_only`, `unknown`. With `unknown`, OCR/ASR still run,
  `coverage.vlm=skipped_rights`, and the AI suggestion stays **Needs Review**. Restrict eligible rights with
  `VLM_CLOUD_RIGHTS` (default `self_created,permission_granted,public_review_only`).
- **Adaptive full-coverage OCR (default):** `OCR_SCAN_MODE=adaptive` checks every decoded frame but runs OCR only on a
  <=0.5 s grid, on visual changes (at most every 0.25 s), at text-change boundaries, and re-reads new numeric text at
  full resolution. Measured 3.2x faster than `all` with 100% stable-text recall on two real clips (99.37% over nine in
  simulation). `all` stays available as the exhaustive reference. Details and limits:
  [docs/OCR_ADAPTIVE_S1-2.md](docs/OCR_ADAPTIVE_S1-2.md). Frames saved by full/adaptive OCR (`ocr-XXXXXXXX.jpg`) are now
  served to the UI (previously rejected by the frame route).
- **Regenerate is reachable (02/11/2026):** previously every rule emitted `medium`, so the AI suggestion could never
  be Regenerate (51 of 52 historical jobs were Needs Review). Strong deterministic evidence is now `high`: a wrong price
  or restricted/high-risk claim read by OCR on >= 2 frames at score >= 0.90 or heard by ASR, a repeated brand
  transposition or substitution (`SoftCare` for `SoftDry`). Regenerate still requires a reviewed or test-approved
  Product Truth and complete OCR and ASR; Gemini-only findings never force it.
- **AI disclosure label (`AI-LABEL-01`):** uploads declare `ai_generated` (`yes`/`no`/`unknown`). For `yes`, every OCR,
  ASR and Gemini text item is searched for a disclosure such as "Nội dung được tạo bởi AI" (tolerant of OCR dropping
  diacritics). Missing after a complete OCR scan is `high`; with incomplete OCR it is `medium`.
- **Lossy OCR tolerance:** claim checks also match accent-free text (`Tăng chiu cao vưt tri` is still the high-risk
  claim) and flag absolute wording not in Approved Claims as a weaker candidate.
- **No audio track:** ASR reports `ok` with `audio_stream: false` instead of failing with `IndexError`.
- **AI-suggested labels:** each completed job exposes `label_suggestion` (label, error types, reason). The session
  reviewer accepts or overrides it; labels store `ai_suggested_label` and `label_source`. Because the reviewer sees the
  suggestion first, `/api/metrics` reports these labels as reviewer agreement, not independent accuracy.
- **Cloud demo:** `Dockerfile` for Hugging Face Spaces, opt-in `VERIFAI_PUBLIC_MODE` with a shared access code,
  product-only `deploy/seed.sql`, `.env` auto-loading. See [docs/DEPLOY_HF_SPACES.md](docs/DEPLOY_HF_SPACES.md).
- **Batch evaluation:** `scripts/run_eval_batch.py` runs real videos through the API in an isolated data directory.

## Đánh giá toàn bộ bộ dữ liệu video (`scripts/evaluate_dataset.py`)

Một lệnh chạy toàn bộ video qua pipeline thật (OCR adaptive, ASR, Gemini, rule, đề xuất,
nhãn gợi ý) và xuất **một sheet session_summary, mỗi video một dòng, không trùng**:

```powershell
python scripts/evaluate_dataset.py run `
  --self-dir "C:\...\VIDEO TỰ TẠO" --public-dir "C:\...\VIDEO CÔNG KHAI" `
  --work-dir eval_runs/full --sheet eval_runs/session_summary_full.csv
```

* Chạy song song `--shards` luồng (mặc định 3), video tự tạo trước, video công khai từ ngắn đến dài.
  Mọi thứ chạy trên CPU của máy; máy phải bật suốt quá trình (80 video mất khoảng 3 đến 4 giờ).
* **Chạy tiếp được:** dừng giữa chừng rồi chạy lại cùng lệnh, video đã xong được bỏ qua; video bị lỗi
  Gemini tạm thời (503, rớt mạng) được chạy lại. `--only VID_LOI11 --force` chạy lại một số video.
* `python scripts/evaluate_dataset.py export --work-dir eval_runs/full --sheet <file.csv>` chỉ xuất lại sheet.
* SKU của từng video lấy từ `scripts/dataset_sku_map.json`. Video tự tạo không có trong bảng dùng SKU xoay vòng
  và ghi "Suy đoán"; video công khai không có trong bảng dùng sản phẩm NOREF (chưa có Product Truth).
* Sheet giữ 21 cột của session_summary, thêm: nhóm dữ liệu, loại lỗi, nguồn SKU, nhãn AI gợi ý, loại lỗi AI,
  chi tiết finding, số frame OCR, video có âm thanh, kiểm tra nhãn AI, thời gian chạy. Cột reviewer để trống.
* Kết quả lần chạy 02/11/2026 (80/80 video): bắt được 31/44 video lỗi; sai giá 8/8, claim 7/7, thiếu nhãn AI 6/6,
  sai brand/thông tin 6/7, lỗi hiển thị 2/7, không nhất quán hình ảnh 2/9; 5/6 video gốc được Pass.

## RULE01–RULE10: căn cứ cho từng cảnh báo (04/11/2026)

`verifai_core/rule_registry.py` ánh xạ mỗi mã cảnh báo sang RULE trong tài liệu "Bộ rule 1-10" của nhóm, kèm
căn cứ pháp lý/chính sách và mức ưu tiên xử lý. Mỗi cảnh báo trên giao diện, `GET /api/jobs/{id}`
(`findings[].rule`), `ai_findings.csv` và sheet đánh giá (`rule_ids`) đều có thông tin này; `GET /api/rules` trả toàn bộ bảng.
**Căn cứ do nhóm tổng hợp, chưa được pháp chế kiểm tra; app không kết luận vi phạm pháp luật và không hiển thị mức phạt (RULE05).**
Mức ưu tiên pháp lý tách riêng khỏi mức độ bằng chứng (quyết định Pass / Needs Review / Regenerate).

| Rule | Mã cảnh báo | Cách phát hiện |
|---|---|---|
| RULE01 | CLAIM-01/02, CLAIM-VLM | claim bị hạn chế, cụm rủi ro cao, cách nói tuyệt đối hóa |
| RULE02 | INFANT-01/02/03 | Product Truth có `category` + `target_age`: sản phẩm thuộc diện cấm quảng cáo theo NĐ 100/2014 Điều 6 (sữa thay thế sữa mẹ ≤ 24 tháng, bình bú/vú ngậm, thức ăn bổ sung ≤ 6 tháng); câu so sánh với sữa mẹ/ti mẹ (chịu được OCR mất dấu); thiếu độ tuổi khuyến nghị |
| RULE03 | PRICE-01 | so giá với Product Truth |
| RULE04 | SKU-01, TEXT-01, VARIANT-01 | thương hiệu, chính tả thương hiệu, quy cách |
| RULE06 | TEXT-02, TEXT-03, VIS-03 | chính tả tên sản phẩm; Gemini tìm chữ vô nghĩa/biến dạng trên 5 khung (`VLM_TEXT_CHECK`) |
| RULE07 | VIS-02, VIS-04, VIS-05 | Gemini so màu trên 5 khung; **lật gương**: chữ thương hiệu/nhãn AI chỉ đọc được khi lật ngang khung hình; **vỡ ô/mờ**: độ nét tụt < 10% kèm ô vuông lặp đều (`FRAME_ANOMALY_CHECK`) |
| RULE08 | AI-LABEL-01 | nhãn "Nội dung được tạo bởi AI" khi video được khai báo do AI tạo |
| RULE05, 09, 10 | - | chưa triển khai (RULE05 chỉ chú giải; 09/10 cần metadata nền tảng và C2PA) |

Đã áp dụng RULE02 cho bộ dữ liệu: SKU002 (bình sữa) = bình bú/vú ngậm, SKU004 (sữa bột) = sữa thay thế sữa mẹ 0–6 tháng,
nên **mọi video của hai SKU này (kể cả video gốc) sẽ ra Needs Review** theo quyết định của PO ngày 04/11/2026.
Kiểm chứng trên dữ liệu thật: lật gương bắt đúng LOI30/LOI32, vỡ ô bắt đúng LOI35/LOI37, câu so sánh sữa mẹ chỉ bắt LOI20,
không báo nhầm trong 84 video. Kiểm tra chữ vô nghĩa (Gemini) bắt 5/7 video công khai có lỗi chữ theo ground truth
nhưng báo nhầm GOC05 và PUB004 trong thử nghiệm.
