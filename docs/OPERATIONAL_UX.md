# VerifAI — Operational UX redesign

## Product direction

This is **real application UI**, not a mockup: controls retain the existing
FastAPI jobs, products, dataset, reviewer and evaluation APIs. The reviewer
reviews *real analysis outputs*. The UI does **not** silently change decisions
or fabricate results. Incomplete OCR/ASR/VLM coverage is explicitly disclosed.

The initial page is **Hàng đợi duyệt** because review is the primary task.
The upload page collects only required inputs. Additional metadata is hidden
under **Tùy chọn nâng cao**. An analysis completes in the review queue.

## Main user flows

1. **Video intake:** Phân tích mới → Upload → chọn Product Truth → xử lý → Hàng đợi.
2. **Reviewer:** Hàng đợi → lọc Cần xử lý → Mở video → kiểm tra cảnh báo,
   timestamp và bằng chứng → Confirm/Reject → quyết định cuối.
3. **Missing coverage:** reviewer sees a brief warning; details are accessible
   in **Chi tiết kỹ thuật**; Pass requires extra confirmation when coverage
   is partial or findings are still unreviewed.
4. **Product operations:** Sản phẩm → danh mục → Thêm sản phẩm, with the form
   collapsed until requested.
5. **Evaluation:** Bộ kiểm thử → case → liên kết sản phẩm/video, nhãn;
   Đánh giá → only actual metrics visible by default, exploratory metrics
   are collapsed and explicitly marked unofficial.

## UI conventions

- Navigation is backed by the URL hash, browser back/forward are respected.
- Content is task-first: video, findings and decision before diagnostics.
- Technical coverage, evidence metadata, audit and manual labels are disclosure panels.
- Meaningful hover/focus, simple entry transitions, reduced-motion support.
- Small-screen layouts collapse the two-column review workspace.
- No illustrative metrics, decorative buttons or fake data.

## Verification

- Read existing backend routes and preserve corresponding JavaScript API calls.
- Static UI contract tests: `python -m pytest -q tests/test_workspace_ui.py`
- JS syntax: extract the inline `<script>` and run `node --check`.
- Manual browser QA still required: Chrome/Edge on Windows at 1440 px,
  1024 px, and narrow mobile, plus keyboard-only navigation.
- Check old upload/review/dataset flows with a test database, never overwrite
  real review records for UI QA.

## Blockers before public production deployment

**A clean operational UI is not itself production readiness.** Current backend
has no authentication or authorization; uploaded videos and evidence can be
read or edited by anyone with access to the server. Before exposing VerifAI on
the internet or a shared company network:

- Implement user authentication, RBAC (admin/reviewer/annotator), session
  security and per-job access controls.
- Review video upload safety (media validation, quotas, content limits) and
  security headers; add request limits and error monitoring.
- Move analysis jobs from in-process threads into a durable worker queue,
  preserve analysis versions and reviewer decisions on re-runs.
- Add migration management, backups, retention and privacy controls.
- Test OCR/ASR/VLM live on Windows and validate case-level performance.
- Add end-to-end/browser tests, CI, accessibility testing and deployment
  observability.

The present PR addresses **frontend IA, usability and workflow clarity**;
it does **not** claim the backend is suitable for an exposed production service.
