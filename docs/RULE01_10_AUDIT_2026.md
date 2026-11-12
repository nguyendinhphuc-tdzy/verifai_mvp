# RULE01–RULE10 — rà soát nghiệp vụ, pháp lý và source code hiện hành

**Ngày rà soát:** 01/11/2026 · **Source:** nhánh `main` sau PR #26 · **Phạm vi:** chỉ rà soát tài liệu, KHÔNG thay đổi Rule Engine · **Trạng thái:** đề xuất để nhóm phê duyệt, không phải tư vấn pháp lý.

## 1. Kết luận đúng để pitching

> VerifAI dùng **Hybrid AI**: PaddleOCR, faster-whisper và Gemini (model đã huấn luyện sẵn) nhận dạng/quan sát nội dung video; các hàm Python/regular expression điều kiện hóa bằng Product Truth tạo **cảnh báo ứng viên** ở Rule Engine; Verification tổng hợp xung đột/coverage và AI Recommendation gợi ý Pass / Needs Review / Regenerate; con người ra quyết định cuối. VerifAI **không tự train/fine-tune mô hình để học pháp luật**. Hiện tại **chưa mã hóa đủ RULE01–RULE10** và **không có công cụ kết luận pháp lý tự động**.

**Hai giới hạn cần nói minh bạch:**
1. Gemini **không chỉ xuất raw facts**. `video_understanding.py` còn yêu cầu `issues` dạng `SKU-01/VIS-01/VIS-02/VIS-03/CLAIM-VLM`; backend chuyển ứng viên phù hợp thành findings **medium**, không thành vi phạm pháp luật.
2. Giá khác giá tham chiếu **không tự suy ra quảng cáo trái luật**. Giá sale, giá niêm yết khác thời điểm/SKU, OCR/ASR sai, nguồn Product Truth chưa xác minh đều cần kiểm tra. `assess_price()` có trạng thái `INSUFFICIENT_EVIDENCE` cho khuyến mại và thông tin mơ hồ.

## 2. Bảng đối chiếu RULE01–RULE10

| Rule trong tài liệu | Trạng thái source code | Mã findings thực có | Điểm khác tài liệu | Chốt lại cho bảng pitching |
|---|---|---|---|---|
| RULE01 — claim ngoài Approved | **Một phần** | `CLAIM-01`, `CLAIM-02` | `CLAIM-01` chỉ kiểm tra danh sách **restricted/banned**; `CLAIM-02` chỉ nhận diện 7 cụm high-risk định sẵn nếu chưa có trong approved/restricted. **Không quét mọi câu ngoài Approved Claims**. Các cảnh báo `medium`. | Gọi “ứng viên claim bị hạn chế / high-risk chưa được duyệt”, không “xác nhận vi phạm luật”. |
| RULE02 — sữa thay thế sữa mẹ/độ tuổi | **Chưa có** | Không có rule chuyên biệt | Không có phân loại sản phẩm đáng tin cậy, intended age, trường cảnh báo bắt buộc hoặc logic Điều 6 NĐ 100/2014. Cụm “giống hệt ti mẹ” trong `CLAIM-02` chỉ là mẫu text chung, **không thay thế RULE02**. | “Dự kiến”, tách cấm quảng cáo sản phẩm theo độ tuổi và yêu cầu cảnh báo cho nhóm thực phẩm bổ sung được phép quảng cáo. |
| RULE03 — giá hiển thị so với giá chuẩn | **Một phần, hoạt động** | `PRICE-01` | `assess_price()` phân tích giá hiện hành/giá gốc/khuyến mại; chỉ ghi `MISMATCH` khi so sánh được. Mức **medium**, không phải “high”; không ghi mã `PRICE_MISMATCH` và không tự tuyên bố vi phạm. Giá tham chiếu là `products.price` + reference status, không có product_snapshots độc lập theo hiệu lực. | Rule cảnh báo `PRICE_MISMATCH_CANDIDATE` ánh xạ sang `PRICE-01`, ưu tiên cao *theo chính sách đề xuất*, chưa implement severity high. |
| RULE04 — brand / SKU / variant | **Một phần** | `SKU-01`, `VARIANT-01`, `TEXT-01` | OCR rule brand chủ yếu phát hiện **đảo trật tự hai phần thương hiệu** trên >=2 frames; variant so khớp ml/kg/g/tờ/size; VLM có thể đề nghị SKU-01. **Không có chuẩn full-SKU visual matching**. | “Ứng viên sai thương hiệu/quy cách”, không phát biểu đã đối chiếu hình ảnh SKU chuẩn. |
| RULE05 — căn cứ xử phạt bổ trợ | **Chưa có** | Không có enforcement mapper | Không có dữ liệu pháp lý có phiên bản, không có quy trình xác nhận vi phạm hoặc tự tính mức phạt. **Nguồn cũ NĐ 38/2021 đã hết hiệu lực**. | Giữ vai trò “chú giải căn cứ pháp lý sau khi human/legal review”, **không tạo finding riêng** hoặc số tiền phạt tự động. |
| RULE06 — OCR/phụ đề sai so với ASR/truth | **Một phần rất hẹp** | `TEXT-01` (lỗi brand typo), `PRICE-01`, `VARIANT-01` | Không có bộ so sánh tổng quát OCR↔ASR theo timestamp; không có `TEXT_RENDER_ERROR` chính thức. | Chỉ mô tả “các tín hiệu chữ/giá/quy cách sơ bộ”; tính năng text–speech fusion chưa có. |
| RULE07 — hình ảnh sản phẩm không nhất quán | **Một phần heuristic** | `VIS-01`, `VIS-02`, `VIS-03`, `VIS-SCREEN`, `VIS-06` | OpenCV xét frame pair và blur; Gemini đề xuất ứng viên thị giác. **Không có `product_images` chuẩn** để xác minh màu/nhãn/sản phẩm; không phải chứng cứ deepfake. | “Tín hiệu bất thường cần reviewer xem frame/video”, mức medium/low theo code. |
| RULE08 — EU AI Act disclosure | **Chưa có** | Không có `AI_DISCLOSURE` | Không có AI-generation classifier/provenance xác thực, không có detector nhãn post-level, không kiểm tra phạm vi địa lý/phạm vi EU. | “Roadmap”, không được báo vi phạm từ việc không thấy badge trong frame. |
| RULE09 — TikTok/Meta nhãn AIGC | **Chưa có** | Không có `AI_DISCLOSURE` | Không đọc API metadata bài đăng/toggle/nhãn nền tảng; không có policy version/rule theo TikTok Ads/Spark/organic, Meta. | “Roadmap theo platform và post context”, không mặc định nhãn phải nằm trong video. |
| RULE10 — C2PA | **Chưa có** | Không có `PROVENANCE` | `backend.py` ghi `coverage['c2pa']='not_implemented'`. Không parse/verify C2PA signature. **Không có manifest không chứng minh nội dung AI hoặc vi phạm.** | Nếu triển khai: `manifest_valid / invalid / not_present / inaccessible`, đây là bằng chứng provenance chứ không phải quy tắc pháp luật độc lập. |

**Tổng quan:** Không rule nào trong 10 rule đã hoạt động đúng toàn bộ điều kiện + mã lỗi + độ ưu tiên + căn cứ pháp luật + điều kiện chấp thuận như bảng gốc. RULE01/03/04/06/07 có một số phần tương ứng; RULE02/05/08/09/10 chưa có quy tắc đầy đủ.

## 3. Mô hình vận hành 4 tầng — dùng chung thuật ngữ

1. **Perception:** `backend.py`, `perception.py`, `video_ocr.py`, `video_understanding.py`. Video/frames/audio → OCR/ASR/timeline + `observations` và **VLM issues ứng viên**. Gemini pretrained, không train/fine-tune luật.
2. **Deterministic candidate detection:** `price.py`, `claims.py`, `sprint2_rules.py`, `brand.py` và các câu lệnh `flag(...)` trong `backend.py`. Đối chiếu bằng regex/ngữ cảnh/giá trị Product Truth → finding có `code`, `severity`, `evidence`, timestamp. Các findings hiện thiên về **medium**, không là quyết định pháp lý.
3. **Evidence reconciliation / recommendation:** `evidence.py` chuẩn hóa; `verification.py` so sánh, ghi `CANDIDATE / CONFLICT / INSUFFICIENT_EVIDENCE`; `recommendation.py` gợi ý Pass/Needs Review/Regenerate.
4. **Human review:** `POST /api/jobs/{jid}/review`, `PATCH .../findings/{fid}`: chỉ người duyệt mới xác nhận findings/quyết định. Code hiện cho phép reviewer tự chọn quyết định, chưa phải kiểm duyệt pháp lý tự động.

**Những dữ liệu đầu vào còn thiếu** nếu muốn thực thi đúng cả 10: product category/classification + độ tuổi + tình trạng chứng từ; Product Truth có nguồn, kỳ hiệu lực/giá bán/khuyến mại; danh mục closed-world Approved Claims nếu có; `product_images` chuẩn; nền tảng và post/page-level AIGC labels; provenance C2PA; jurisdiction, `legal_basis_version`, ngày đăng tải.

## 4. Bảng RULE01–RULE10 đề xuất CHỐT (điều kiện/căn cứ/mức ưu tiên là TARGET, không nhận là đã code)

- **RULE01 (Cao theo chính sách):** nếu thấy một claim khẳng định và `claim ∈ banned_claims` đã kiểm duyệt, phát `CLAIM_RESTRICTED_CANDIDATE`. Nếu claim không có trong `approved_claims` của **danh sách duyệt đóng** (chỉ khi Product Truth được xác minh và completeness=true), phát `CLAIM_NOT_APPROVED_CANDIDATE`. Không suy luận “ngoài danh sách” = vi phạm pháp luật.
- **RULE02 (Rất cao khi áp dụng):** phân loại đúng sản phẩm dinh dưỡng trẻ nhỏ và nhóm tuổi. Nếu là sữa thay thế sữa mẹ dành cho trẻ dưới 24 tháng tuổi trong bối cảnh quảng cáo thuộc phạm vi cấm → `INFANT_FORMULA_AD_REVIEW`. Nếu quảng cáo thức ăn bổ sung trẻ dưới 24 tháng thuộc diện được quảng cáo, kiểm tra thông tin cảnh báo theo Điều 6 khoản 2 NĐ 100/2014, không gộp với khoản 1. Thiếu phân loại/tuổi → `NEEDS_REVIEW`, không tự kết án.
- **RULE03 (Cao khi đủ chứng cứ):** xác định cùng SKU, cùng thời điểm bán, giá so sánh tương ứng với chính sách khuyến mại và Product Truth được xác minh; nếu giá công bố rõ ràng khác giá có hiệu lực → `PRICE_MISMATCH_CANDIDATE`. Missing/khuyến mại/chưa rõ → `INSUFFICIENT_EVIDENCE`. Không gắn “vi phạm pháp luật” tự động.
- **RULE04 (Cao):** nếu tên/brand/variant OCR/ASR/visual được xác nhận và khác dữ liệu tham chiếu phù hợp cùng SKU → `PRODUCT_IDENTITY_MISMATCH_CANDIDATE`; nếu không có product image chuẩn hoặc OCR mờ, cần review.
- **RULE05 (Bổ trợ, không phát finding):** sau khi có xác nhận phù hợp, đưa căn cứ pháp lý có version và **ngày hiệu lực** vào hồ sơ reviewer. Từ 15/05/2026 không lấy NĐ 38/2021 làm căn cứ xử phạt hiện hành. Với quảng cáo sai/gây nhầm lẫn, tham khảo NĐ 87/2026 Điều 50(5)(c) **và điều kiện/ngoại lệ/mức phạt theo chủ thể**. Không tự tính tiền.
- **RULE06 (Trung bình):** so sánh cùng nội dung giá/claim/dung tích giữa OCR và ASR có liên kết timestamp và cùng đối tượng; nếu xung đột không giải thích được bằng lời thoại/khuyến mại → `TEXT_AUDIO_CONFLICT_CANDIDATE`. “Chữ méo/lỗi render” nên là mã riêng `TEXT_RENDER_CANDIDATE`, không lẫn với lỗi đối chiếu giá.
- **RULE07 (Trung bình):** chỉ flag `VISUAL_INCONSISTENCY_CANDIDATE` sau khi xác định cùng sản phẩm/cùng shot, có frame-pair và bối cảnh loại trừ thay đổi góc/ánh sáng/chuyển cảnh; nếu so với product image thật cần nguồn quyền sử dụng và revision.
- **RULE08 (Cao *nếu trong scope*):** chứng minh loại nội dung và nghĩa vụ disclosure theo **EU AI Act Article 50**, có xác định jurisdiction/deployer/loại deepfake và ngoại lệ; kiểm tra nhãn theo nội dung/bài đăng thích hợp. Không có nhãn trong 1 frame ≠ vi phạm.
- **RULE09 (Cao nếu áp dụng):** kiểm tra platform policy theo TikTok Ads/Spark/organic hoặc Meta, nhãn trong post/metadata/toggle, version chính sách, loại chỉnh sửa AI. Không dùng một vị trí badge cố định cho mọi platform.
- **RULE10 (Provenance check, Cao khi xác thực lỗi chữ ký):** parse/validate Content Credentials theo công cụ C2PA tin cậy. `invalid_signature` ⇒ `PROVENANCE_INVALID_CANDIDATE` cho reviewer; `not_present` ⇒ `PROVENANCE_NOT_AVAILABLE`, **không** mặc định sai hay AI-generated.

**Mức độ trong mục 4 là ưu tiên review đề xuất của nhóm**; severity runtime hiện tại không tương ứng đầy đủ.

## 5. Ví dụ RULE03: logic if/else an toàn hơn

```python
# Ví dụ mục tiêu, KHÔNG phải code đã merge
if not product_truth.verified or not product_truth.price_at(published_at):
    status = "INSUFFICIENT_EVIDENCE"
elif not same_sku or not observed_price.is_unambiguous_current_price:
    status = "INSUFFICIENT_EVIDENCE"
elif observed_price.is_promotion and not pricing_policy.can_compare(observed_price):
    status = "NEEDS_REVIEW"
elif observed_price.vnd != product_truth.price_at(published_at):
    flag(
        rule_id="RULE03",
        code="PRICE_MISMATCH_CANDIDATE",
        priority="high",  # policy priority, NOT legal certainty
        evidence_refs=[observed_price.evidence_id],
        reference_revision=product_truth.revision,
        legal_assessment="not_determined",
    )
```

**Phân biệt 5 trường:** `rule_id`, `finding_code`, `review_priority`, `legal_assessment`, `legal_basis`. Hiện source mới có code/severity/findings và không có legal-basis versioned engine.

## 6. Truy vết code minh bạch

- `backend.py`: phân tích từng video; `coverage.c2pa=not_implemented`; `flag()`; `find_restricted_claims`, `check_variant`, `check_unapproved_high_risk_claims`, `assess_price`, `PRICE-01 severity=medium`, reviewer endpoints.
- `verifai_core/price.py`: `assess_price`, special-case sale/original/ambiguity.
- `verifai_core/claims.py`: restricted claim + negation/quotation/question context, không phân tích tất cả unapproved claims.
- `verifai_core/sprint2_rules.py`: 7 high-risk claim phrases, variant ml/kg/g/tờ/size, few brand typos; không phải trained weights.
- `verifai_core/brand.py`: OCR-backed transposed-brand checks, >= 2 frames.
- `verifai_core/visual.py`: histogram/pHash/ORB heuristic; không có ảnh SKU chuẩn.
- `verifai_core/video_understanding.py`: Gemini native video prompt + video timeline + model `issues` (ứng viên).
- `verifai_core/verification.py`: `REVIEW_REQUIRED`, `INSUFFICIENT_EVIDENCE`, `NO_ISSUES_OBSERVED`; `requires_human_review=True`.
- `verifai_core/recommendation.py`: chỉ `Regenerate` khi high severity có liên kết bằng chứng từ nguồn không phải Gemini/heuristic, và đủ coverage + Product Truth reviewed; Pass không chứng nhận pháp lý.

## 7. Điểm pháp lý/chính sách cập nhật (cần legal review trước phát hành)

1. Luật Quảng cáo 16/2012/QH13 đã sửa đổi bởi **75/2025/QH15** hiệu lực **01/01/2026**, đặc biệt Điều 19 về trung thực/chính xác/rõ ràng: https://vanban.chinhphu.vn/?classid=1&docid=214561&pageid=27160
2. Luật Bảo vệ quyền lợi người tiêu dùng **19/2023/QH15**, Điều 10(1)(a) nói về lừa dối/gây nhầm lẫn; **Điều 10(1)(e)** đề cập nghĩa vụ đền bù/đổi trả và không nên dẫn như một điều khoản giống hệt “cấm quảng cáo giá sai”: https://congbao.chinhphu.vn/van-ban/luat-so-19-2023-qh15-39843.htm
3. NĐ **100/2014/NĐ-CP**, Điều 6 khoản 1 **cấm quảng cáo** sữa thay thế sữa mẹ cho trẻ <24 tháng, thực phẩm bổ sung dưới 6 tháng và một số sản phẩm; khoản 2 là yêu cầu riêng cho quảng cáo thức ăn bổ sung cho trẻ <24 tháng được phép quảng cáo: https://vpcp.chinhphu.vn/cam-quang-cao-sua-thay-the-sua-me-11511189.htm
4. NĐ **38/2021/NĐ-CP** và sửa đổi 128/2022 **hết hiệu lực 15/05/2026**; NĐ **87/2026/NĐ-CP** có hiệu lực ngày đó. Tham khảo Điều 50 khoản 5 điểm c, 80–100 triệu ở khung điều khoản (không tự suy diễn phạt từng clip): https://vbpl.moj.gov.vn/bovanhoathethao/Pages/vbpq-toanvan.aspx?ItemID=187899&Keyword=&dvid=323
5. EU AI Act Article 50 có **phạm vi vai trò và đối tượng cụ thể**, áp dụng từ 02/08/2026; không phải mọi clip có AI đều bắt buộc badge nội khung hình hoặc chịu quyền tài phán EU: https://ai-act-service-desk.ec.europa.eu/en/ai-act/article-50
6. TikTok Ads AIGC: có trường hợp disclosure bằng platform toggle/label, caption hoặc sticker; không thể chỉ OCR video rồi kết luận: https://ads.tiktok.com/help/article/add-disclaimers-to-ads?lang=en
7. Meta đã sử dụng nhãn **“AI info”** và các vị trí nhãn thay đổi theo kiểu chỉnh sửa; không dùng mã “Made with AI” như một tiêu chuẩn bất biến: https://about.fb.com/news/2024/04/metas-approach-to-labeling-ai-generated-content-and-manipulated-media/
8. C2PA là cơ chế xác minh **manifest và chữ ký**, không phải bằng chứng bắt buộc mọi video phải có manifest: https://spec.c2pa.org/specifications/specifications/2.4/specs/C2PA_Specification.html

## 8. Acceptance criteria cho bước code tiếp theo

- [ ] Tạo registry `rule_id`, `finding_code`, `legal_basis_id`, `legal_basis_version`, `effective_from/to`, `jurisdiction`, `policy_scope`, `review_priority`, `status`.
- [ ] Đảm bảo chạy các rule chỉ khi đủ prerequisites, ví dụ verified product/price, xác định loại sữa và độ tuổi, xác định nền tảng/bài đăng.
- [ ] Chuẩn hóa `candidate` ≠ `confirmed_issue` ≠ `legal_violation`; reviewer có thể xác nhận hoặc bác bỏ.
- [ ] Lưu bằng chứng + timestamp + OCR/ASR model + tham chiếu revision vào mỗi finding.
- [ ] Negative tests: giá sale, SKU khác, claim bị phủ định, camera angle/scene cut, video re-encoded strip metadata, TikTok post label không nằm trong video.
- [ ] RULE02, RULE06, RULE08/09 và C2PA có integration test với dữ liệu thật và failure modes.
- [ ] Chỉ công bố “đã implement RULE01–RULE10” khi từng rule có test acceptance riêng và kiểm tra pháp lý.
- [ ] Rà soát luật/chính sách theo mỗi sprint hoặc mỗi 2 sprint; khi có sửa đổi hiệu lực, lưu version và regression.

**Trạng thái cuối:** đây là bản **đối chiếu và đề xuất sửa tài liệu**, không phải cam kết đã implement các rule còn thiếu. Chưa cập nhật code runtime hoặc merge thay đổi.
