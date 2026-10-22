# Sprint B1 — Multimodal Evidence Reliability

## Objective

Improve sampling coverage in local CPU-first video checks and stop reporting OCR as fully successful when only some frames were processed. Retain real Whisper speech-segment start/end ranges. This is a reliability change, **not a proven OCR accuracy gain**.

## Video and OCR sampling

The visual sampler previously sampled at a minimum interval of two seconds. B1 targets one second on short videos, capped at 60 visual frames total. For a 30-second video at 25 FPS, the target is about 30 samples. For 90 seconds the spacing is roughly 1.5 seconds; for 180 seconds, about 3 seconds. Actual counts vary with OpenCV codec and metadata.

Of these samples, OCR still processes at most OCR_MAX_FRAMES=12 by default.

- OCR_SAMPLING_MODE=hybrid (default): anchor frames spread over the timeline plus visibly changed frames based on thumbnail pixel differences. Returns original time order.
- OCR_SAMPLING_MODE=uniform: the original evenly-spaced selection strategy.
- On visually static clips, hybrid falls back to uniform.
- A visible change is NOT necessarily a text change. Short overlays can still be missed; only a manual video benchmark can demonstrate recall.

Set parameters before starting Uvicorn:

~~~powershell
$env:OCR_MAX_FRAMES="12"
$env:OCR_SAMPLING_MODE="hybrid"
python -m uvicorn backend:app --host 127.0.0.1 --port 8000
~~~

Use uniform in a second run with the same video, other settings unchanged, to compare. Keep the original evidence export when reanalyzing: reanalysis replaces old findings and clears the prior reviewer decision.

## OCR and ASR quality reporting

A completed job now contains details.perception_quality:

- sampling_version, sampling_stride_frames, ocr_sampling_mode.
- ocr.attempted_frames, successful_frames, failed_frames, empty_frames, text_lines, text_observed, errors (at most 5 unique messages).
- asr.status, segments, segments_with_end, speech_observed.

The status details.coverage.ocr is:

| Value | Operational interpretation |
| --- | --- |
| ok | Every OCR attempt succeeded, even if it found no text |
| partial | Some OCR attempts succeeded and some failed |
| not_installed | Every selected frame reports OCR engine not installed |
| error | Attempts all failed, not solely due to missing installation |
| skipped | No OCR frames selected |

None of these indicate OCR transcription accuracy. A successful frame without detected text is explicitly counted as empty_frames. Mixed failures are no longer silently hidden. The UI displays counts inside the existing technical details panel.

faster-whisper segments keep a valid end timestamp when present, after validating finite, nonnegative start/end times. The end is stored as evidence.metadata.segment_end_seconds and canonical evidence.end_timestamp. Score remains unknown rather than fabricated.

## Validation performed

- 25 B1 unit test cases passed on Python with the exact source blobs now pushed to this PR. They cover stride, hybrid/uniform selection, OCR partial/not-installed/error/no-text states, ASR timestamp validation and normalization.
- 35 tests passed on the available v2.1 source snapshot plus exact B1 modules (25 new + 10 legacy).
- New tests/test_multimodal_b1_api.py exercises FastAPI upload on generated MP4 with intermittent mocked OCR failure, plus ASR ranges and JSON evidence. These API tests must be executed on the **current A1+A2+A3+B1 code** at the user's Windows machine; local v2.1 snapshot is not the full current backend.

Windows review:

~~~powershell
git fetch origin
git switch --track origin/feature/b1-multimodal-coverage-sampling
python -m pytest -q
python -m pytest -q tests/test_media_quality_b1.py tests/test_multimodal_b1_api.py
~~~

Live model timing (local video only):

~~~powershell
python scripts/benchmark_perception.py --video "C:\Videos\my-video.mp4" --ocr-frames 12 --warm-runs 1 --output benchmark-b1.json
~~~

Note: The CLI benchmark samples OCR frames uniformly; it does not replicate the new hybrid application sampling. To evaluate whether hybrid improves the detection of text overlays, upload the SAME video through the app in both modes and compare their results against manually verified text and timestamps.

## Evaluation protocol

Test at least five human-labeled videos: brief overlays under two seconds, long text, multiple shot changes, spoken price/claim, and near-silent/blurry video. For each compare detection vs known transcript, frame selection and timing, failed/empty frames, incorrect findings, and A3 sufficiency status.

Do not declare a recall, precision or speed improvement until measured on those real clips.

## Scope

No database migration, no auth/RBAC, no new AI engines, no changes to the existing Product Truth policy, and no automatic approval. Uploaded videos and reviewer decisions remain local. The existing worker model is intended for a single Uvicorn process.
