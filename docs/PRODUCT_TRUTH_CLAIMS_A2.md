# Sprint A2 — Product Truth and Claim Verification (v3-alpha2)

## Operational goal

**Provide trustworthy reference inputs and conservative claims checking** for Vietnamese Mom & Baby promotional video reviews. The system still provides decision support, **not legal clearance or automated rejection**.

A2 extends A1. It does not replace the price parser, OCR/ASR/VLM, dataset evaluation, UI navigation, or existing jobs.

## 1. Product Truth source and revisions

Existing product fields are unchanged: `sku`, `name`, `brand`, `price`, `claims`, `banned`.

New optional fields (returned by `GET /api/products`):

| Field | Behavior |
| --- | --- |
| `reference_url` | http(s) URL supplied by operator; **not fetched or independently verified** |
| `reference_note` | Human-entered evidence/source note (max 800 characters) |
| `reference_status` | `unverified` by default; `reviewed` only when source URL or note exists |
| `revision` | Integer, starting at 1; increments on successful update |
| `updated_at` | Last local edit timestamp |

`reviewed` records the **operator's assertion** that the reference was examined; it is not an authenticity, pricing or regulatory certification. No user authentication is implemented in this sprint.

APIs:
- `POST /api/products`: preserves old request payload compatibility; accepts the optional fields.
- `GET /api/products/{id}`: expanded Product Truth.
- `PUT /api/products/{id}`: complete product replacement with required `expected_revision` (optimistic concurrency, HTTP 409 when stale).
- `GET /api/products/{id}/history`: append-only snapshots of manually created/updated versions.

Only the product CRUD endpoints validate new entries. Existing dataset importer uses the legacy 8-column `products` table; the new fields live in **separate tables** `product_truth_meta` and `product_truth_audits`. Consequently older records, workbook import and eight-column `INSERT INTO products VALUES(...)` statements remain compatible. Missing metadata is interpreted as unverified revision 1.

Normalization rejects blank SKU/name, duplicate case-insensitive SKU on ordinary create/edit, blank or overlong claims, and exact normalized conflicts between allowed and restricted claims. Duplicate claims inside a list are consolidated, preserving the first entered wording. Some semantically overlapping phrases may still require human review.

## 2. Conservative claim matching

`verifai_core/claims.py` matches restricted claims using case-insensitive **Unicode word boundaries** and flexible whitespace. It assigns each recognized mention:

| State | Example | Result |
| --- | --- | --- |
| `asserted` | “Sản phẩm chữa khỏi hoàn toàn” | Medium `CLAIM-01` review candidate |
| `negated` | “Sản phẩm **không** chữa khỏi hoàn toàn” | Preserve observation; no claim finding |
| `uncertain` | “**Nghe nói** chữa khỏi hoàn toàn” | Preserve observation; no claim finding |
| `uncertain` | “Câu nói ‘chữa khỏi hoàn toàn’” | Preserve quotation; no automatic claim finding |
| no match | Different phrase or partial-word collision | No claim finding |

Results are **heuristic contextual signals**, not semantic entailment. Detecting a phrase in OCR/ASR is insufficient to prove the product makes that claim. The engine favors conservative non-rejection when negation, quotation or uncertainty exists.

The result is attached to canonical evidence at `evidence.metadata.claim_v3` with phrase, start/end, state, reason, reference revision and status. An asserted finding has `source=claim_rule_v3`, `severity=medium` and links to its canonical evidence ID.

**A claim match never automatically sets the job to Regenerate.** Human reviewer validation remains mandatory. Old jobs are untouched; re-analysis applies new rules.

## 3. Analysis versioning and stale references

Every completed job now stores `details.claim_rule_version` and `details.product_truth_snapshot` containing the reference facts and revision used **at analysis time**. The UI warns if the current Product Truth revision differs from the analyzed version or when the reference has not been reviewed.

Re-analysis replaces job evidence/findings and clears previous final reviewer decision: **export evidence and record decisions first** when they matter. Product history is append-only, but per-job evidence is not yet versioned across re-analysis (planned in a later sprint).

## 4. Test and review instructions

```powershell
cd C:\Users\PC\Documents\verifai_mvp
git pull origin main
python -m pytest -q tests/test_claims_v3.py tests/test_product_claim_api_a2.py
python -m pytest -q
```

Check UI: **Sản phẩm → + Thêm sản phẩm → Nguồn tham chiếu & xác minh**. Save, edit existing Product Truth, and verify the revision changes and data remains after restart. Use a small test video with one asserted restricted phrase, one explicit negation and one uncertain reference; evidence should show distinct states.

Unit checks have been run locally against the A2 classifier. API tests are included in the PR and **must be re-run on the target Windows environment** before release.

## 5. Limitations and next steps

- Negation/quotation/hedging detection is **rule-based and clause-local**; complex paraphrases, Vietnamese ASR segmentation, image-only text, indirect claims and multilingual videos may be missed.
- Claims are compared as normalized phrases, not semantic equivalents. No LLM-based logical contradiction checking or legal-policy engine.
- `reference_status=reviewed` is self-attested; there is no authenticated reviewer identity by design in this phase.
- No references are downloaded or crawled. Source URL existence or accuracy is not checked.
- The product reference is text-only; no approved image/SKU grounding yet.
- Existing in-process workers remain intended for local single-worker execution.

**Next: PR-A3 Verification Engine**, which should reconcile repeated/conflicting OCR/ASR/VLM claims, product references, current/promotion prices and evidence sufficiency before issuing a single case-level verdict.
