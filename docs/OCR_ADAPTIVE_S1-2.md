# Adaptive full-coverage OCR (Sprint 1, S1-2)

**Status:** implemented, default `OCR_SCAN_MODE=adaptive`. Approved by the PO on 02/11/2026.
Code: `verifai_core/adaptive_ocr.py`. Experiment tool: `scripts/compare_ocr_modes.py`.

## Problem

`OCR_SCAN_MODE=all` runs PaddleOCR on every decoded frame. On the project workstation
(CPU, PaddleOCR 3.7 / PP-OCRv5, model warm) one call costs about **1.1 s per frame**
(measured: 2,780 s for 2,538 frames), plus about 15 s to load models. An 8 s clip took
about 3.5 min; a 30 s clip about 11.5 min. The PO requirement: every frame covered, but fast.

## Method (4 passes)

| Pass | What | Cost |
|---|---|---|
| 0 Change check | Every frame vs. the last OCR'd frame on a 160 px gray thumbnail, max per-tile (8x8) mean abs. difference | No OCR |
| 1 Grid + change | OCR at least every `OCR_MAX_GAP_SECONDS` (0.5 s); also when pass 0 exceeds `OCR_CHANGE_THRESHOLD` (12), at most every `OCR_MIN_GAP_SECONDS` (0.25 s) | Main |
| 2 Boundary | If two consecutive readings differ, bisect the frames between them to find where the text changed | ~log2(gap) calls per change |
| 3 Full resolution | First time a new text state has digits or a line scored < 0.85, OCR the original-resolution frame and keep the better reading | Few calls |

Frames not OCR'd inherit the reading of the OCR'd frame that covers them. Each OCR evidence
item stores `ocr_reason`, `inherited_frames` and `segment_end_seconds`; job details report
`perception_quality.ocr.adaptive` with `ocr_frames + inherited_frames == decoded_frames`.

Text-state comparison ignores lines scored < 0.9 (`signature_min_score`) and fragments
shorter than 3 characters; numbers must match exactly (149.000 vs 199.000 is a change).

## Experiment (02/11/2026)

Nine real project videos (4 originals incl. one 1080p, 3 controlled-error clips, 2 public
clips; 6.4 s to 29.8 s; 2,538 frames). The exhaustive scan is the reference.
**Stable text** = a distinct reading seen on >= 3 frames; single-frame readings on moving
footage are mostly OCR jitter (e.g. `s0e`, `80shoels`), so they are reported separately.

### Parameter sweep (adaptive replayed from the cached exhaustive OCR; time estimated)

| min gap (s) | change thr. | signature score | speed-up | stable texts missed |
|---|---|---|---|---|
| 0.20 | 12 | 0.8 | 3.06x | 2 / 310 (99.35% recall) |
| 0.20 | 12 | 0.9 | 3.17x | 3 |
| **0.25** | **12** | **0.9** | **3.39x** | **2 / 315 (99.37% recall)** (chosen) |
| 0.25 | 20 | 0.9 | 3.56x | 3 |
| 0.33 | 12 | 0.9 | 4.17x | 10 |

### Measured end-to-end (real PaddleOCR, pass 3 enabled)

| Video | Length | `all` | `adaptive` | Speed-up | Stable recall |
|---|---|---|---|---|---|
| VID_GOC01 | 8.0 s | 218 s | 115 s | 1.9x | 100% |
| PUB023 | 29.8 s | 693 s | 170 s | 4.1x | 100% |
| **Total** | | 911 s | 285 s | **3.2x** | 100% |

Pass 3 re-read 12 frames at full resolution; 10 readings improved.

## Findings and limits

* Acceptance target "recall >= 99%" is **met** (99.37% on 9 videos, 100% on the 2 measured).
* Acceptance target ">= 5x faster" is **not met** on this dataset (3.2x measured). The clips
  are AI-generated with constant camera motion, so the change trigger runs near its cap
  (4 OCR/s) and OCR jitter causes boundary searches. Longer, calmer footage gains more (4.1x on
  the 30 s public clip). Raising the minimum gap to 0.33 s reaches 4.2x but misses 10 texts.
* Missed stable texts: `tent:20g` (likely "Net content: 20g", visible 0.09 s on PUB002) and two
  fragments. Text shorter than the change-trigger spacing can be missed; `all` remains the
  exhaustive reference mode.
* On-screen text durations are short on this footage (median stable run 0.13 s to 1.1 s per
  video) because moving packaging text is read intermittently; durations are an OCR-observed
  lower bound, not the true display time.
* Sample size is small (9 videos, 3 of 44 clip families) and parameters were tuned on the same
  set; re-check on the full dataset before reporting final numbers.
* Next lever for speed is hardware, not sampling: the workstation has an RTX 4050 (6 GB);
  GPU PaddleOCR is untested here.

Reproduce:

```powershell
python scripts/compare_ocr_modes.py --cache-dir ocr_cache --simulate --output sim.json --video <v1> --video <v2>
python scripts/compare_ocr_modes.py --cache-dir ocr_cache --output measured.json --video <v1>
```
