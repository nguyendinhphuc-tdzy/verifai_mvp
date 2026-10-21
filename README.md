# VerifAI MVP v2.1 — 80-case Dataset Workspace + VLM / Evidence / Visual

**Working local web application** upgraded from v1.0. Frontend: standalone `static/index.html`; backend: FastAPI + SQLite + OpenCV; VLM: **Qwen3-VL-4B-Instruct via local Ollama** (optional); OCR/ASR remain optional.

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

## 3. Enable a real local VLM (Qwen3-VL)

Install [Ollama](https://ollama.com/download) and ensure its server is running. **Ollama 0.12.7 or newer** is required for Qwen3-VL. Download the model once:

```bash
ollama pull qwen3-vl:4b-instruct
ollama list
```

If Ollama is not already running as a service, start it in a separate terminal with `ollama serve`.

**Windows PowerShell**, from the `verifai_mvp` folder:

```powershell
$env:VLM_ENABLED="1"
$env:VLM_MODEL="qwen3-vl:4b-instruct"
$env:VLM_MAX_FRAMES="4"
$env:VLM_MAX_PAIRS="2"
uvicorn backend:app --host 127.0.0.1 --port 8000 --reload
```

**macOS/Linux**:

```bash
export VLM_ENABLED=1
export VLM_MODEL=qwen3-vl:4b-instruct
export VLM_MAX_FRAMES=4
export VLM_MAX_PAIRS=2
uvicorn backend:app --host 127.0.0.1 --port 8000 --reload
```

Test model connectivity:

```bash
curl http://127.0.0.1:8000/api/health
python scripts/check_vlm.py
```

`/api/health` should show `"vlm":{"enabled":true,"ready":true,...}`. `scripts/check_vlm.py` sends a generated **synthetic image** to Ollama and validates its response; it is a live smoke test, **not an accuracy benchmark**.

The 4B quantized weights are about **3.3 GB** on disk, plus RAM/VRAM overhead. CPU inference may be slow; allow a few minutes per video, especially for multiple frame/pair requests. Use `VLM_MAX_FRAMES=2` and `VLM_MAX_PAIRS=1` on limited hardware. A local 8B model can be substituted after checking hardware.

**VLM configuration** (environment variables):

| Variable | Default | Meaning |
|---|---|---|
| `VLM_ENABLED` | `0` | Opt-in to VLM calls |
| `VLM_MODEL` | `qwen3-vl:4b-instruct` | Ollama model tag |
| `VLM_BASE_URL` | `http://127.0.0.1:11434` | Ollama root URL |
| `VLM_TIMEOUT_SECONDS` | `120` | Timeout per VLM request |
| `VLM_MAX_FRAMES` | `4` | Single-frame checks, capped at 8 |
| `VLM_MAX_PAIRS` | `2` | Same-shot pair checks, capped at 6 |
| `VLM_ALLOW_REMOTE` | `0` | Allow non-loopback Ollama only when explicitly `1` (privacy risk) |
| `WHISPER_MODEL` | `tiny` | ASR model (if installed) |
| `VERIFAI_DATA` | `./data` | Persistent storage root |

**Privacy:** Default Ollama endpoint is localhost. Setting `VLM_ALLOW_REMOTE=1` may send image frames to another host. Do not use cloud/remote endpoints for sensitive videos without explicit authorization.

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

**VLM is separate**: Python dependencies do not install the Ollama executable
or Qwen3-VL model. See section 3 to install Ollama, `ollama pull`, and set
`VLM_ENABLED=1` in the terminal running the backend.

References: [PaddleOCR installation](https://www.paddleocr.ai/main/en/version3.x/installation.html),
[PaddleOCR multilingual OCR](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html),
[faster-whisper](https://github.com/SYSTRAN/faster-whisper).

## 5. What the v2 pipeline actually does

```text
Video + Product Truth
  -> OpenCV frame sampling (max 60 frames) + optional PaddleOCR + faster-whisper
  -> Temporal signals: HSV histogram, frame pixel delta, pHash, ORB matches
  -> Same-shot pair selection (avoid likely scene cuts)
  -> Optional Ollama VLM: sampled single frames + up to 2 frame pairs
  -> Pydantic JSON schema validation + evidence provenance
  -> Evidence normalization (dedup adjacent repeated OCR/ASR, keep timestamps)
  -> Deterministic price/restricted-claim rules + visual candidate flags
  -> Findings linked to canonical evidence IDs
  -> Human review + audit log + JSON evidence export
```

**Evidence Normalization:** Each canonical item has `kind`, `timestamp`, `end_timestamp`, `content`, `score`, `frame`, `frame2`, `source_model`, `fingerprint`, `metadata.sources` (original raw observations). It merges only repeated OCR/ASR from the same source within a 2.3-second gap; it **does not** merge different modalities or VLM assertions, avoiding false corroboration.

**Visual Consistency Checking:** OpenCV compares consecutive sampled frames and classifies likely scene cuts vs same-shot candidates. The VLM compares selected same-shot pairs for apparent changes to product details. `VIS-01`/`VIS-02`/`VIS-03` are **review candidates**, not proven defects. Natural movement, transitions, lighting, occlusion and camera angles can cause false positives. Two sampled frames cannot establish the exact frame where a transient anomaly occurred.

**VLM:** Uses `POST /api/chat` with base64-encoded local JPEG frames and a Pydantic-generated JSON Schema in `format`. Requests have `temperature=0`. Outputs are validated and stored with model + prompt versions; malformed output or unreachable Ollama produces `coverage.vlm=error`/`partial` rather than fabricated findings. `confidence` is **self-reported, not calibrated**. No automatic `Regenerate` from VLM-only flags.

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

Automated tests cover: v1 smoke flow; evidence dedup/provenance; scene-cut and temporal candidate signals; VLM schema and invalid JSON; security of remote model endpoint; SQLite v1->v2 migration; **end-to-end job with a mocked VLM** including linked findings, JSON export, re-analysis and audit log. They do **not** evaluate the accuracy or speed of the real Qwen3-VL model.

## 8. Known limitations

- Research MVP only: single user, local SQLite, in-process background threads, no authentication, roles, encryption, antivirus, retention, production queue, or distributed job management. Keep it on `127.0.0.1`.
- Visual signals are screening heuristics, not robust object tracking, optical flow-based segmentation, product reference-image matching, deepfake detection, or frame-level truth labels.
- A VLM can hallucinate; all findings require human review. OCR/ASR may miss text or transcribe incorrectly. Price rules can flag unrelated amounts.
- No C2PA provenance verification, legal-compliance certification, online benchmark, or Ecomobi integration.
- Official workbook v2.1 contains 80 evaluation case records (6 original / 44 error scenarios / 30 public sources), not necessarily 80 available or analyzed video files. Actual precision/recall remains exploratory.

For architecture details and upgrade checklist see [ARCHITECTURE.md](ARCHITECTURE.md).

## Open-source references

- [Ollama](https://github.com/ollama/ollama), [Qwen3-VL](https://ollama.com/library/qwen3-vl:4b-instruct)
- [FastAPI](https://github.com/fastapi/fastapi), [OpenCV](https://github.com/opencv/opencv)
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR), [faster-whisper](https://github.com/SYSTRAN/faster-whisper)

Review individual library/model licenses before commercial use.

## v2.1 — Sprint-2 Dataset Workspace (80 official evaluation cases)

The latest Sprint-2 workbook defines **80 evaluation cases**: `VID_GOC01–06`
(6 originals), `VID_LOI01–44` (44 controlled-error scenarios) and `PUB001–030`
(30 public examples). These are **case records, not proof that 80 actual video
files have been downloaded or run through VerifAI**.

1. Run the existing app (after backing up `data/`) with `python -m uvicorn backend:app --reload`.
2. Open **Dataset (80) → Import workbook**, select `Sprint 2 - Thu thập & tạo dữ liệu thật.xlsx`.
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
