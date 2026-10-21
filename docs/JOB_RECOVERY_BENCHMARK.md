# OCR/ASR speed checks and interrupted job recovery

## Local-only operational scope

This implementation is intended for **one Uvicorn server worker on one machine**.
Do not run `--workers 2` or multiple server instances against the same SQLite
database. Production deployments with multiple workers require a persistent
external job queue, leases/heartbeats and process isolation.

**Backup** `data/verifai.sqlite3` and `data/uploads/` before upgrading.

## What changed

- **Bounded analysis concurrency:** `MAX_CONCURRENT_JOBS=1` by default,
  maximum 2 allowed in this local implementation.
- **Separate frame budgets:** up to 60 frames for visual checks and only
  `OCR_MAX_FRAMES=12` evenly spaced frames for OCR by default. OCR may
  miss brief overlays between sampled frames. Increase to 20–30 if recall is
  more important than latency; decreasing the count can lower detection
  coverage. This is a performance/coverage trade-off, not a proven optimum.
- **Stage timings** in each successful job's `details.timings`: decoding,
  OCR seconds and average per frame, ASR, visual and VLM times.
- **Progress updates** in `details.progress`, readable through
  `GET /api/jobs/{id}`, including stage name, last timestamp and OCR
  completed/total frame count. The Review UI shows this while processing.
- **Restart recovery:** during app startup, jobs left `queued` are launched;
  jobs left `processing` from the previous process are reset to `queued`
  and restarted from the original file. Prior recovery attempts are counted
  and recorded in the audit trail. After **2 unsuccessful restarts**, a
  further interrupted `processing` job is marked `failed`, requiring
  a human-triggered Re-analyze. Missing source files fail with a clear reason.
- **Duplicate worker guard:** only a job with `status=queued` can be
  atomically claimed for processing. A local semaphore limits concurrency.
- **Schema migration:** adds only
  `jobs.recovery_attempts INTEGER NOT NULL DEFAULT 0`; existing product,
  video, review and audit rows are retained.

### Important limitations

Restart recovery is NOT an in-process timeout/cancellation mechanism.
OCR/ASR/VLM model calls run inside Python threads; native inference cannot
safely be force-killed. If progress is unchanged for a long time, inspect
the terminal, available RAM and model initialization. For an actual hang,
stop Uvicorn with Ctrl+C and start it again. Recovery takes place when the
new server process starts. Avoid killing the server during model file
downloads if they are incomplete.

Running `uvicorn --reload` while editing Python will interrupt analysis
threads. For stable local evaluation prefer `python -m uvicorn backend:app
--host 127.0.0.1 --port 8000` **without** `--reload`.

## Benchmark your actual video on Windows

Install OCR/ASR using `requirements-ai.txt` in the same Python environment
that runs Uvicorn, then run in PowerShell:

```powershell
cd C:\Users\PC\Documents\verifai_mvp
git pull origin main
python -m pytest -q

python scripts/benchmark_perception.py --video "C:\Videos\VID_LOI01.mp4" --ocr-frames 12 --warm-runs 1 --output benchmark-VID_LOI01.json
```

Replace the video path with an existing **real video file on your computer**.
The benchmark reads and processes the file locally; it does not send it to
ChatGPT or GitHub. It may download model weights from providers on first use,
which is included in the cold-run wall-clock time.

**Interpretation:**
- `ocr[0]` is the cold model initialization + selected-frame extraction
  time; `ocr[1]` is the warm pass reusing OCR weights.
- `asr[0]` is the cold entire-video transcription time; `asr[1]` is warm.
- `decode_seconds` is local video seek/decode time for benchmark frames.
- Compare runs on videos of similar length, resolution, content and platform
  before choosing `OCR_MAX_FRAMES`.
- An `ok` status with zero text/audio evidence may be correct for a silent
  video or could indicate missed content. Validate against ground truth.
- This script **does not run VLM**; VLM timings are in the application's
  completed job details.

For a more realistic measure, test at least one original/clean video, one
controlled-error video, and one public video. A benchmark result is not
an Accuracy/Precision/Recall claim.

## Run and inspect jobs

```powershell
$env:OCR_MAX_FRAMES="12"
$env:MAX_CONCURRENT_JOBS="1"
python -m uvicorn backend:app --host 127.0.0.1 --port 8000

# In another PowerShell:
Invoke-RestMethod http://127.0.0.1:8000/api/jobs/YOUR_JOB_ID |
  Select-Object -ExpandProperty details | ConvertTo-Json -Depth 7
```

The API's last `progress.updated_at` timestamp lets you distinguish a
slow step from no recent progress. An existing `processing` job from a
previous crashed process will be recovered at the next startup.

**Safety:** Re-analyze still resets prior reviewer decision and findings.
Confirm you have captured previous evidence/decision before triggering it.
