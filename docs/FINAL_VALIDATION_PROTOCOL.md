# VerifAI — final validation and acceptance protocol (27 October 2026)

Status: **validation protocol prepared; live model benchmark and human review pending.** Do not present planned tests as completed.

## Scope and invariant

VerifAI assists a human reviewer; no score certifies legality, authenticity or permission to publish. Distinguish **API health**, **unit tests**, **real video inference**, **independent reference verification** and **model quality**. A smoke test only proves connectivity/schema.

## Milestone 1 — Standardize Gemini

Configure `VLM_ENABLED=1`, `VLM_MODEL=gemini-3.5-flash-lite`, `GEMINI_THINKING_LEVEL=low`, `VLM_TIMEOUT_SECONDS=90`, `GEMINI_MAX_ATTEMPTS=1`, `VLM_MAX_FRAMES=1` and `VLM_MAX_PAIRS=0`. Set API key locally using a secure terminal prompt; **never commit it**. Keep OCR/ASR enabled.

Run `python scripts/check_vlm.py --text-only` and `python scripts/check_vlm.py`; record model name and timestamp. Then upload real videos and inspect each evidence export's `details.vlm.model`, `calls_attempted`, `calls_succeeded`, `coverage.vlm` and errors. A success on synthetic DEMO is not a model accuracy benchmark. 503/504, circuit breaker and model fallback must be recorded as missing coverage, never absence of errors.

Acceptance: smoke passes, at least one successful real-video VLM call, errors and coverage visible to reviewer, and no auto-approval on missing truth.

## Milestone 2 — Product Truth and Ground Truth

For every SKU, maintain: source URL or stored reference screenshot; capture date; brand, SKU, variant, listed price and price effective date; approved and restricted claims; reviewer identity; source revision and evidence of review. `reference_status=reviewed` is only a manually asserted review state; it does NOT verify that the source is accurate.

For each test video, collect: job ID, origin video group, source reference and two *distinct* annotators' independent labels. Resolve disagreements before recording `adjudication_status=verified`; preserve notes. Use `data/ground_truth_verified.template.csv` as the import layout. Do not copy system predictions into human labels. Mask personal data and only test authorized media.

Known dataset risks: 44 controlled errors trace to only six originals; do group-level splitting to prevent leakage. Public clips need source rights and independent label adjudication. Simulated Sprint 2 labels do not count as model outcomes.

Acceptance: no evaluated case without source and two agreeing annotators; zero leakage across video origin groups in comparisons.

## Milestone 3 — Actual Precision/Recall/F1

While the local app is running, create a full evidence export with immutable hashes and a BLANK annotation draft:

```powershell
python scripts/export_evaluation_bundle.py --base-url http://127.0.0.1:8001 --out-dir evaluation_bundle
```

The script exports completed jobs only. It does not alter video jobs, reviewer decisions or labels. `manifest.csv` records filenames, SKU, model, coverage, findings and SHA-256; `ground_truth_TO_LABEL.csv` starts with all labels blank and is never overwritten. **Do not publish the bundle or place it in GitHub.** Repeated filenames are warned, but a shared original clip can still appear under multiple filenames.

Two independent reviewers must inspect each video and Product Truth source. Copy the draft to `data/ground_truth_verified.csv` and complete all fields, including a stable `source_group` shared by every derivative of the same original. Different reviewers must not use model predictions to assign labels. Only after manual adjudication set `adjudication_status=verified`. Never use the Sprint-2 simulated 80-case outcomes as actual predictions.

Then run:

```powershell
python scripts/evaluate_real_jobs.py --ground-truth data/ground_truth_verified.csv --exports-dir evaluation_bundle/exports --out reports/real_eval.json
```

The script excludes unverifiable ground truth, jobs without evidence, and jobs lacking model coverage or findings. It reports TP, FP, FN, TN, accuracy, precision, recall, F1, by-source and VLM-coverage results, and FP/FN review cases. Overall scores are not Gemini-only scores; use the VLM coverage strata to distinguish OCR-only fallback. Exported evidence files are snapshots and must not be replaced silently during a benchmark. It does not fabricate a number from missing video uploads. Review error cases with timestamps and flag codes and maintain a changelog of rule/model changes. A `source_group` with derived variations should be considered one correlated cluster, not independent samples.

Acceptance: non-zero eligible cases and numerical metrics; FP/FN analysis reviewed by a human. With a small sample report uncertainty and counts, not just percentages.

## Milestone 4 — Reviewer UI acceptance

Human walk-through checklist:
- Each warning exposes time or frame, evidence ID, evidence source, severity and relevant Product Truth revision.
- Coverage errors (Gemini 503/504 or OCR/ASR failure) are visible and do not silently read as clean.
- `unverified` Product Truth and stale revisions remain prominent.
- Distinguish heuristic visual candidates from VLM-backed findings; model confidence is uncalibrated.
- The user can confirm/reject each flag and enter a reviewer name, note and final disposition.
- After re-analysis, previous review decision is not silently retained; export prior evidence first.

Acceptance requires screenshots and a reviewer sign-off for an actual uploaded test video. Existing UI panels provide much of this, but a browser-based sign-off is still necessary.

## Milestone 5 — Handoff

Use `docs/FINAL_REPORT_DRAFT.md` and `docs/DEMO_SHOTLIST.md`. Fill in live run IDs, dataset version, numbers, human sign-off and recorded demo file before calling the milestone completed.

Release gate = full test suite green + live Gemini run + verified Ground Truth + actual evaluation + manual reviewer acceptance + recorded demo. Block release when any gate has no evidence.
