# VerifAI MVP v2.1 — 80-case Dataset Workspace + VLM / Evidence / Visual

**Working local web application** upgraded from v1.0. Frontend: standalone `static/index.html`; backend: FastAPI + SQLite + OpenCV; VLM: **Gemini 3.8 Flash via Google API** (optional, cloud inference); OCR/ASR remain optional.

> Scope: evidence-first **review assistance**, not a deepfake detector, not automatic legal compliance, not a production service. A VLM assertion is an unverified candidate until a human confirms it. No product-reference image is stored, so precise visual SKU matching is not implemented.

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

Open http://127.0.0.1:8000. API docs: http://127.0.0.1:8000/docs.

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

## v2.1 — Sprint-2 Dataset Workspace (80 official evaluation cases)

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
6. Open Evaluation: the **Official evaluation — Actual runs only** panel has
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

In-process worker threads can still hang in native inference; no reliable
in-place cancellation is provided. Stop and restart the **single-worker**
Uvicorn process to recover interrupted jobs; after repeated interruptions,
affected jobs are marked failed for manual intervention. Public production
hosting still requires external durable queues and authentication.

## Sprint A1 — Price Parser v3

Vietnamese price extraction/verification now uses a conservative structured
parser instead of matching every four-digit number. It recognizes VND shorthand,
separates current/original/promotional amounts, and distinguishes `MATCH`,
`MISMATCH` and `INSUFFICIENT_EVIDENCE`. A detected mismatch is a
**reviewer-only medium-severity PRICE-01 candidate**, not automatic Regenerate.
Price assessments are stored in canonical evidence metadata and exported as JSON.

Read [Price Verification A1](docs/PRICE_VERIFICATION_A1.md) for formats,
examples, tests, limitations and safe re-analysis guidance.

## Sprint A2 — Product Truth & Claim Verification (v3-alpha2)

Reference products now support source URL/note, explicitly unverified/reviewed status, a revision counter, audit snapshots, and a revision-checked edit route. Restricted phrase detection distinguishes assertions from explicit negation and uncertain quotations, with all outcomes retained in evidence metadata. An asserted candidate is medium-severity and **requires human verification**, never automatic rejection. Old products/dataset importer remain compatible.

See [Product Truth & Claim Verification A2](docs/PRODUCT_TRUTH_CLAIMS_A2.md) for API, UI, tests, audit implications, and limitations.

## Sprint A3 — Cross-modal Verification Engine

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


## Sprint B1 — Multimodal Evidence Reliability (merged with Gemini)

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



## Session cleanup and full AI decision exports (MVP local)

In **Hàng đợi duyệt**, click **Export All Sessions (.zip)** to download:
- `session_summary.csv`: one row per submitted job (including failed and unreviewed), AI decision, verification status/reason, reviewer decision/note, Gemini model and OCR/ASR/VLM coverage.
- `ai_findings.csv`: all detected candidate problems and AI/rule observations classified as findings: code, severity, timestamp, detailed description, source, uncalibrated confidence, reviewer flag and evidence link.
- `sessions/*.json`: complete stored job details, Product Truth snapshot, verification checks, canonical OCR/ASR/VLM evidence, findings, independent labels and audit entries.
- `README.txt`: meaning and limitations. **Video files and JPEG frame bytes are not included**. Keep the ZIP private: it may contain marketing information and reviewer data. Snapshot export is not a guarantee of accuracy.

To start a fresh evaluation history, click **Xóa lịch sử phiên**, enter `XOA TAT CA PHIEN`, then confirm. This deletes rows from `jobs`, `evidence`, `findings`, `audits` and job `labels`, plus the uploaded video and frame folders **owned by these job IDs**, if filesystem cleanup succeeds. The server rejects deletion while jobs are queued/processing (409). The response reports any filesystem cleanup errors. Product Truth and imported workbook/case annotations **are not deleted**. The operation cannot be undone; export first.

In **Bộ kiểm thử**, expand **Xóa bộ Excel hiện tại**, enter `XOA EXCEL`, then confirm. This clears imported cases, simulated baseline predictions, policy references, workbook import history and case-level human annotations; historical video jobs, evidence, reviewer decisions and Product Truth stay in place, while the old case links on jobs are cleared. **Case-level reviewed labels are permanently deleted**. Export needed source data before clearing. A new workbook can then be imported using the existing `Import Excel (.xlsx)` button.

The Excel importer **still expects the official Sprint-2 80-case 7-sheet XLSX schema**, not a generic arbitrary spreadsheet or the separate evaluation review workbook. Old Product Truth is deliberately retained, and matching SKUs reuse existing products instead of overwriting their reference fields. Edit or verify Product Truth separately when importing a different version of the workbook.

Both destructive APIs require localhost access and an exact typed confirmation phrase. The endpoints are intended for a single local Uvicorn process; do not expose the MVP publicly or run several workers. No reset runs automatically on server startup or git pull.

API: `GET /api/sessions/export` downloads ZIP; `POST /api/sessions/reset` with JSON `{"confirmation":"XOA TAT CA PHIEN"}`; `POST /api/dataset/reset` with `{"confirmation":"XOA EXCEL"}`.
