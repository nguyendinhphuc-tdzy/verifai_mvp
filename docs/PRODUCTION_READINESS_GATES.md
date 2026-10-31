# VerifAI production readiness — release gate (2026-10-31)

**Current classification: LOCAL RESEARCH MVP / NOT PRODUCTION-READY.**
This document establishes non-negotiable acceptance gates. It is NOT evidence
that these controls exist. A passing test suite alone cannot certify production.

## Confirmed scope of the six original product references

The project owner explicitly confirms the six original Sheet-1 product records
(SKU001–SKU006) are the **correct references for the VerifAI test dataset**.
This does not establish their truth for real commercial products.

Use `reference_status=test_reference_approved` with a note that references
the test dataset and the human who reviewed it. Unlike `reviewed`, this status
is scoped to **testing only**, and the app displays `Pass (bộ kiểm thử)` when
all other verification conditions are satisfied.

To mark a reference through the UI:

1. Product Truth → SKU001 → Chỉnh sửa.
2. Verify that SKU, name, price, variant and Approved Claims match Sheet 1.
3. Set "Chuẩn kiểm thử đã xác nhận", add a note that it is a synthetic test
   reference, and save. Repeat for the six reference SKUs as appropriate.
4. Re-analyze any existing job to use its updated Product Truth snapshot.
   Export existing annotations/reviews before reanalysis; previous review
   decisions are cleared.
5. Distinguish the **AI proposal** (Pass/Review/Regenerate within tested
   scope) from the **final reviewer decision**.

Importing an XLSX never silently upgrades its references to approved.

## Critical production release blockers — all must be resolved

| ID | Release gate | Current evidence | Minimum acceptance |
|---|---|---|---|
| P0-01 | Authentication and RBAC | **Absent**; single-user localhost MVP | Authenticated APIs; permissions for import, export, deletion, reference approval and reviewer decision; cross-role denial tests |
| P0-02 | Secrets and network security | Gemini key is an environment variable; no TLS / remote auth | Secret manager, key rotation, TLS, audit of exposed surfaces; security test and threat-model review |
| P0-03 | Reliable job processing | In-process threads + SQLite local files | Durable queue with deduplication, retries, dead-letter handling, cancellation, restarts and verified multi-worker behavior |
| P0-04 | Data integrity and recovery | SQLite, basic migrations/audits, no tested restore procedure | Transactional migrations, automated encrypted backups, documented and timed restore exercises, retention/purge policy |
| P0-05 | Import/export/delete correctness | Isolated tests, multiple PRs not yet integrated | End-to-end tests using real six-sheet template, large/corrupt ZIP/XLSX inputs, crash recovery, deletion boundaries and download checks |
| P0-06 | Model performance | OCR/ASR/Gemini available, but no independent held-out video evaluation | Independently reviewed frame/case labels, leak-free split by source, per-rule precision/recall/F1 and false-negative review |
| P0-07 | Reliability and SLO | One 8-second user video ran 92.75 sec (OCR 77.8 sec) | Agree latency/throughput SLO, measure p50/p95 on target hardware, load and soak test, set actionable alert thresholds |
| P0-08 | CI/CD & supply chain | Local tests passed earlier; GitHub Actions failure logs unavailable | Green, reproducible CI, locked dependencies, vulnerability/license scanning, release tag, rollback drill |
| P0-09 | Observability | Job audit logs and partial timing; no centralized alerts | Structured tracing/logs, PII redaction, model spend/rate-limit/error monitoring, on-call escalation and dashboards |
| P0-10 | Regulatory/data governance | Human review hints, not a compliance classifier | Define intended jurisdictions, privacy basis, consent, retention, review policy and legal sign-off |

These blockers are not magically resolved by a model, a dataset or an approval
checkbox. **Do not expose VerifAI to the Internet or real customer data** until
they have passed. A public deployment requires replacing the local-only
access guard with real authenticated authorization.

## Changes included in this hardening PR

- Explicit `test_reference_approved` with required human reference note;
  updates increment revision and write an auditable Product Truth snapshot.
- Distinct `reference_scope=test` so the user sees **Pass (bộ kiểm thử)**,
  not a commercial certification. Unreviewed references still get Review.
- Verification refuses clean conclusions with no observed OCR/ASR/VLM content
  even if a module reports `ok`.
- Local-only access gate for all routes and same-origin guard on mutation
  requests. Adds no-store and baseline anti-sniff/frame headers.
- Tests for reference scope, no-evidence conditions, API isolation and the
  audit/revision path.
- Existing UI, API and legacy data are retained. No existing reference is
  silently approved or migrated to a synthetic approved status.

## Local validation protocol

```powershell
cd C:\Users\PC\Documents\verifai_mvp
python -m pytest -q
python -m pytest tests/test_production_foundations.py -v
python -m py_compile backend.py
python -m uvicorn backend:app --host 127.0.0.1 --port 8001
```

Then run:
- VID_GOC01 with `unverified` → AI Review.
- Same video after explicitly approving the **test** reference and
  reanalysis → potentially AI Pass (test scope), if no findings, observed
  content evidence and coverage are satisfactory.
- One video with a deliberate wrong price, a wrong variant, and an
  unsupported claim → REVIEW with timestamped evidence (not automatic
  legal violation).
- One file upload with invalid XLSX, oversized video and invalid video
  container → controlled error; no damaged database or leaked key.
- Remote and cross-origin HTTP requests → 403.
- Reviewer decision must remain independent of the AI proposal.

A **green PR with local tests alone is a stage-1 prerequisite**, not a
production release sign-off.
