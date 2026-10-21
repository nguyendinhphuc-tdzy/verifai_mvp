# PR-A1 · Price Parser v3 (Vietnamese)

## Purpose

Replace the MVP's broad numeric-price regex with a **conservative, testable price extractor**. A number in a video is **not automatically a price**, and a different price is **not automatically a policy violation**.

This is Sprint A1 only. It does not implement product image recognition, claim semantics, discount policy, dynamic per-SKU pricing, or end-to-end model accuracy.

## Supported cases

| OCR / ASR text | Normalized | Meaning |
| --- | --- | --- |
| `Giá bán 149.000đ` | 149000 VND | current selling price |
| `149k`, `149000 vnd` | 149000 VND | explicit monetary amount |
| `1,2 triệu` | 1200000 VND | decimal multiplier |
| `Giá sale 99k, giá gốc 149k` | 99000 / 149000 VND | promotion vs original |
| `Sản xuất năm 2026`, `250ml` | none | not a selling price |
| `Voucher 20k`, `giảm 20k` | 20000 VND | non-price amount |
| `Giá từ 99k` | 99000 VND | price floor, not a fixed selling price |

More forms include separated-thousands commas/spaces, `₫`, `đồng`, `vnđ`, `nghìn`, `ngàn`, and `tr`.

## Verification states

- **MATCH:** Exactly one identifiable selling price equals the Product Truth reference.
- **MISMATCH:** An identifiable selling price differs from the reference. This is a **medium-severity PRICE-01 review candidate**, not an automatic rejection or legal finding.
- **INSUFFICIENT_EVIDENCE:** No price, missing Product Truth price, several unattributed prices, ranges, discount/voucher/shipping amounts, original-only prices, or promotions that might legitimately differ from the single reference price.

The last case matters: Product Truth currently stores **one integer price**, with no approval period, price type or allowed promotions. A sale price that differs from that value **cannot be ruled incorrect** without a future Product Truth upgrade.

## Stored evidence & compatibility

For OCR/ASR evidence containing a monetary candidate, `evidence.metadata.price_v3` includes:

- `status`, `reason`, `reference_vnd`, `compared_vnd`
- `mentions[]`: `amount_vnd`, raw text, role, context, explicit currency, start/end positions.

A `PRICE-01` finding links to its canonical evidence ID; `finding.metadata.price_assessment` carries the same structured assessment and the parser version. Successful jobs include `details.price_parser_version`.

**No database migration and no frontend changes.** Existing SQLite data is retained. Historical job results will not automatically be revised. Re-analyze only after exporting any old reviewer decision/evidence because re-analysis resets them.

## Tests

```powershell
python -m pytest -q tests/test_price_v3.py tests/test_price_api_v3.py
python -m pytest -q
```

Unit tests cover Vietnamese formats, numbers that are not prices, promotions, discounts, ambiguous quotes, status/reason and text positions. The integration test uses a *real generated MP4*, the existing FastAPI upload/job database flow, deterministic fake OCR/ASR, and JSON evidence export; no model weights are downloaded.

## Known limitations / Sprint A2 handoff

- The parser works on **recognized digit strings**, not fully spelled-out speech such as `một trăm bốn mươi chín nghìn`.
- OCR/ASR may split price qualifiers into separate segments, or misrecognize `k`, `triệu`, punctuation or digits.
- Only 1–100 million VND amounts are included by default; currency conversion and unusual packaging/bundle unit prices are not modeled.
- A clearly isolated currency amount may still be for another SKU, a fee, or a promotional offer whose qualifier was missed. Hence a mismatch is reviewer-only.
- A product's single `price` field cannot validate temporary coupons, marketplace discounts, effective-date ranges, variants or multiple SKU pricing.
- No cross-frame / OCR-versus-ASR conflict-resolution policy exists yet. That belongs in the later Verification Engine PR.

This release improves the **deterministic verification foundation**, not proof of price-verification recall/precision on real videos. The latter needs the 80-case dataset with valid ground truth.
