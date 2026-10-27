# VerifAI — final demo recording script

**Deliverable pending:** recording must be captured on an actual running Windows instance, not synthesized from screenshots.

Recommended 3–5 minute shot list:

1. Show `git rev-parse --short HEAD`, `python -m pytest -q`, `/api/health`. Keep secrets out of screen.
2. Confirm health reports OCR=true, ASR=true and VLM enabled/ready with selected Gemini model.
3. Show a pre-consented clean clip and a known controlled-error clip; explicitly disclose that the cases are linked to human-confirmed references.
4. For each: upload, select correct SKU, wait for completed job; show the evidence list, exact timestamp, OCR or ASR text, VLM findings and model coverage.
5. Open Product Truth source/revision and explain that reviewed state is an operator attestation.
6. Reviewer confirms or rejects a flag with explanation; demonstrate decision audit and export evidence.
7. Open verified evaluation JSON and show counts and Precision/Recall/F1. If none eligible, state N/A rather than invented results.
8. Close with known limitations: model outages, non-certified legal checks, human final decision.

Recording acceptance: file plays, audio readable, no API key or private information exposed, all real outputs shown, commit SHA and date documented.
