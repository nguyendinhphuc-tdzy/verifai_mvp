# VerifAI v2.1 — Sprint-2 official 80-case evaluation workspace

Date: 2026-10-15

## Locked evaluation scope

- `VID_GOC01–06`: 6 original/clean reference scenarios (source workbook Sheet 1).
- `VID_LOI01–44`: 44 controlled-error scenarios (Sheet 2).
- `PUB001–030`: 30 public video records (Sheet 3; manual labels from Sheet 4).
- `80` simulation comparison rows (Sheets 5–6), stored in `dataset_simulated`.
- `10` rule/policy references (Sheet 7), stored but not automatically enforced.

**80 cases ≠ 80 analyzed video files.** Some are scenarios or source URLs only. Importing the workbook does not download video, verify product pages, or run the AI model.

## New in v2.1

- Dataset workspace in the existing HTML UI with workbook import, 80-case catalog, filters, planned expected/observed fields, product link, case-linked upload and independent manual annotations.
- Idempotent XLSX import with Python standard library; no extra AI dependencies.
- Automatic creation of six illustrative SKU references, preserving existing records and historical uploads.
- Disconnected public product URLs are not treated as verified source-of-truth. Actual video uploads require choosing a matching Product Truth record.
- Official actual-only Evaluation metrics require a completed real video job, useful OCR/ASR/VLM coverage and **two independent agreeing manual labels**. Disputes are excluded until resolved.
- Simulated predictions remain separate from actual model outputs. The old exploratory metrics are labeled as not official for the 80-case study.
- Backward-compatible additive migration: existing `jobs`, `reviews`, `audit` and `labels` are kept.
- Tests: 10/10 pass in this development environment, including synthetic XLSX parsing, import twice, independent label consensus and metrics isolation.

## Known limitations

- No Ecomobi internal videos, policies or CTR/CVR/GMV datasets.
- Product reference images, C2PA, verified claim semantics, review history versioning and security/authentication are outside this update.
- There is **no guarantee of model accuracy** from the workbook's simulated predictions.
- Some original price-parser and decision-engine issues documented in the code audit remain. Keep this on localhost (`127.0.0.1`) only until access controls are added.
- Public product sources may be in non-VND currencies, price ranges or have no SKU; they must be checked by a reviewer before deterministic pricing validation.

## Upgrade on Windows PowerShell

1. Stop your existing Uvicorn process.
2. Back up your current `data/` directory (especially `verifai.sqlite3`, `uploads/`, `frames/`).
3. Apply `VerifAI_v2_to_v2.1.patch` from the repo root using `git apply`, or copy the new/changed source files from the v2.1 ZIP. **Do not delete your existing `data/` folder.**
4. Run `pip install -r requirements.txt` (same core dependencies as v2).
5. Run `python -m pytest -q` for regression tests (pytest needs to be installed if absent).
6. Run `python -m uvicorn backend:app --host 127.0.0.1 --port 8000 --reload`.
7. Open the **Dataset (80)** tab, import `Sprint 2 - Thu thập & tạo dữ liệu thật.xlsx`.
8. Review imported cases, add missing verified Product Truth, associate video files with their case IDs, collect 2 independent annotations and inspect **Evaluation → Official evaluation**.

### Git instructions from existing repository root

```powershell
git checkout -b feature/sprint2-dataset-80
git apply "C:\path\to\VerifAI_v2_to_v2.1.patch"
python -m pytest -q
git add backend.py static/index.html verifai_core/dataset.py tests/test_dataset_v21.py README.md
git commit -m "feat: add Sprint 2 dataset-driven evaluation workspace"
git push -u origin feature/sprint2-dataset-80
```

Then open a Pull Request against `main`. Do not run `git reset --hard` on a working directory containing local changes.
