# VerifAI v2 — Solution Architecture & BA Acceptance Criteria

## A. Logical layers (11-layer architecture mapping)

| Layer | MVP v2 component | Coverage |
|---|---|---|
| 1. Presentation | `static/index.html` | Functional |
| 2. API & orchestration | FastAPI + per-job worker thread | Local prototype |
| 3. Media ingestion | Upload, video metadata, sampled frames | Functional |
| 4. Perception | Optional OCR/ASR + Ollama VLM | Functional when installed/enabled |
| 5. Evidence normalization | `verifai_core/evidence.py` canonical schema, dedup, provenance | Functional |
| 6. Product truth | `products` table (text fields only) | Partial: no reference product image |
| 7. Validation / rules | Price/restricted phrases + VLM candidates | Partial: no policy/compliance engine |
| 8. Decision | Needs Review / Regenerate recommendations | Conservative; never auto-Pass |
| 9. Human-in-the-loop | Reviewer confirmation and final decision | Functional |
| 10. Persistence & audit | SQLite, frame files, audit log, JSON export | Local prototype |
| 11. Evaluation / monitoring | Basic precision/recall on labels + coverage | Feasibility only |

The mapping describes implemented logical responsibilities, **not a deployment with 11 separate microservices**. For a 15–20 video pilot, a modular monolith is deliberate to reduce overhead.

## B. Processing sequence

1. Upload video and select product reference. Create queued job.
2. Decode up to 60 frames with timestamps; optional OCR/ASR generate raw evidence.
3. Compute shot-aware temporal pair signals (histogram, pixel delta, pHash, ORB).
4. If `VLM_ENABLED=1`, check local Ollama model. Run up to 4 single-frame and 2 pair analyses, validate JSON against Pydantic schema.
5. Normalize evidence and record all original raw sources; do not merge unrelated modalities.
6. Apply deterministic rules on OCR/ASR; attach evidence IDs. VLM issues above a conservative confidence/basis threshold become **medium** reviewer flags, not definitive errors.
7. Store job decision, coverage, evidence, findings, model/prompt version and audit.
8. Reviewer verifies frames, confirms/rejects findings, saves decision, optionally exports JSON and assigns ground-truth label.

## C. BA user stories and acceptance criteria

**US-01 VLM readiness**: As a reviewer I can see whether Ollama and the configured model are available. If unavailable, job still completes with `coverage.vlm=error` and no synthetic VLM findings.

**US-02 Multimodal evidence**: As a reviewer I can inspect VLM observations and issues with timestamp, frame(s), source model and reported confidence. All HTML text is escaped to avoid interpreting model output as HTML.

**US-03 Evidence normalization**: As a reviewer I see repeated OCR text grouped into one canonical item with first/last timestamp and raw source count; different modalities remain independent. Every finding with supporting evidence links to a canonical ID.

**US-04 Visual consistency**: As a reviewer I can compare two sampled frames of a likely same-shot segment. The app separates `VIS-SCREEN` heuristics from VLM `VIS-xx` candidate findings and does not claim definitive AI-generated artifacts.

**US-05 Re-analysis**: As a reviewer I can re-run an existing video after enabling VLM without re-uploading. The prior final decision is cleared; audit history is preserved.

**US-06 Export**: As an evaluator I can export machine-readable JSON with provenance, coverage, evidence and findings for manual evaluation.

**US-07 Human override**: No VLM-only finding triggers automatic final rejection; the reviewer remains responsible for final Pass / Needs Review / Regenerate.

## D. Next technical priorities after v2 pilot

- Product reference image(s), region-of-interest localization and object-level tracking (needed for meaningful SKU visual matching).
- Shot segmentation with PySceneDetect, higher temporal resolution around candidate windows, frame-pair calibration and benchmark labels per failure category.
- Evidence quality scoring and consensus evaluation (at least 2 independent annotators per clip), confusion matrix per rule/model.
- Persistent job queue (RQ/Celery), PostgreSQL, object storage, identity/RBAC, secure upload validation, model observability, retention controls.

## E. Data migration contract

v2 adds only nullable/defaulted columns to `evidence` and `findings`. `products`, `jobs`, `labels`, `audits` are unchanged. v1 jobs remain readable. Old evidence has empty `metadata` and no end timestamp; API falls back to the original timestamp. Re-analysis replaces per-job findings/evidence and resets reviewer decision, while audit log remains append-only.
