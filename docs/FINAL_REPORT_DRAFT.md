# VerifAI — Final Report (evidence-controlled draft)

**Status: INCOMPLETE.** This is a report skeleton, not a claim of final acceptance.

## 1. Executive summary
VerifAI is a local reviewer-support MVP for advertising video. It combines sampled video frames, OCR, optional ASR, Gemini VLM and conservative deterministic validation against Product Truth. Human reviewers make the final decision.

## 2. Problem, scope and stakeholders
The objective is to reduce manual screening effort while surfacing evidence-linked differences in product name, brand, price, claims and image consistency. The system is NOT proof that a video is AI-generated and is not a legal compliance certifier.

## 3. Technical architecture and implementation
FastAPI orchestration -> FFmpeg/OpenCV media sampling -> PaddleOCR / faster-whisper / Gemini -> canonical evidence -> Product Truth -> validation -> reviewer queue -> local persistence and exports. Capture actual commit SHA, Python version, model ID and runtime configuration for each benchmark.

## 4. Data audit and labeling
The project dataset has 6 original clips, 44 controlled-error derivatives and 30 public clips. The controlled derivatives share six sources; labels and reference authenticity require additional independent verification. Record eligible real-video sample count: **not yet measured**. Record consensus and source groups.

## 5. Model evaluation
Actual evaluated clips: **pending**.
TP / FP / FN / TN: **pending**.
Precision / Recall / F1: **pending**.
Latency / inference costs / Gemini failure rate: **pending**.
Never substitute code test-pass rate, mocked inference, simulated labels or synthetic Gemini smoke results.

Document case IDs and error explanations after running `scripts/evaluate_real_jobs.py`.

## 6. Business value and ROI
Expected impact: fewer manual review minutes and more traceable reviewer findings. Baseline review time, assisted review time, API cost, reviewer labor cost, false-alert burden and measured savings: **pending study**. Without real operations data, report a sensitivity scenario, not demonstrated ROI.

## 7. Risks and limitations
Unverified Product Truth; small/correlated datasets; mixed TikTok/Shopee coverage; OCR errors in Vietnamese; ASR may return zero segments when speech is absent; API 503/504 and cost; hallucinated VLM observations; privacy and media rights; lack of authenticated reviewer roles; no C2PA implementation. Reviewer remains accountable.

## 8. Release and project closure
Required evidence: passing complete tests, real VLM run, signed adjudication sheet, measured evaluation, UI walkthrough, demo recording, ownership and follow-up maintenance plan. Current gate: **NO-GO until completed**.

## 9. Appendix
Attach exact Git SHA, sanitized environment flags, video inventory, evidence export IDs, data dictionary, rule versions, test report, consent/source log and demo link.
