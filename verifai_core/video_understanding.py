"""Native Gemini video understanding with timeline-aware structured evidence.

Uses the Gemini Files API and generate_content on the original VIDEO, not
JPEG thumbnails. Gemini's standard video mode still samples internally
(typically ~1 visual frame/sec); it does not inspect every source frame.
"""
from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
import time
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from verifai_core.vlm import VLMError

VideoCategory = Literal['product','packaging','visible_text','scene','speech','other']
VideoIssueCode = Literal['SKU-01','VIS-01','VIS-02','VIS-03','CLAIM-VLM']


class VideoObservation(BaseModel):
    timestamp_seconds: float = Field(ge=0, le=7200)
    description: str = Field(min_length=3, max_length=700)
    category: VideoCategory
    confidence: float = Field(ge=0, le=1)


class VideoIssue(BaseModel):
    timestamp_seconds: float = Field(ge=0, le=7200)
    code: VideoIssueCode
    description: str = Field(min_length=5, max_length=700)
    visible_basis: str = Field(min_length=10, max_length=700)
    confidence: float = Field(ge=0, le=1)


class VideoUnderstandingResult(BaseModel):
    summary: str = Field(default='', max_length=1000)
    timeline_summary: str = Field(default='', max_length=2500)
    observations: list[VideoObservation] = Field(default_factory=list, max_length=100)
    issues: list[VideoIssue] = Field(default_factory=list, max_length=60)


def video_prompt(product: dict) -> str:
    reference = {
        'sku':product.get('sku',''),
        'name':product.get('name',''),
        'brand':product.get('brand',''),
        'variant':product.get('variant',''),
        'approved_claims':(product.get('claims') or [])[:15],
        'restricted_claims':(product.get('banned') or [])[:15],
        'reference_status':product.get('reference_status','unverified'),
    }
    return (
        'Bạn đang phân tích VIDEO QUẢNG CÁO LIÊN TỤC (gồm hình ảnh, âm thanh và sự kiện '
        'diễn ra theo thời gian), không phải một ảnh đơn lẻ.\n'
        'Hãy xem diễn biến từ đầu đến cuối video: sản phẩm xuất hiện, chữ/giá/claim '
        'trên màn hình, thay đổi bao bì, cảnh chuyển và câu nói liên quan. '
        'Tạo timeline_summary mô tả trình tự sự kiện.\n'
        'Mỗi observation và issue phải có timestamp_seconds dựa trên video, '
        'không phỏng đoán hay gán timestamp giả. Nếu không xác định rõ, bỏ qua mục đó.\n'
        'visible_text chỉ dùng cho chữ thật sự nhìn thấy trên video, không dùng cho '
        'lời nói; lời nói dùng category speech và không tự trở thành OCR.\n'
        'Chỉ báo các issue có căn cứ trực tiếp trong video: '
        'SKU-01 nhãn rõ khác tham chiếu; VIS-01 biến dạng; '
        'VIS-02 cùng sản phẩm thay đổi khó giải thích giữa các thời điểm; '
        'VIS-03 chữ/logo bất thường; CLAIM-VLM claim nhìn thấy cần kiểm tra.\n'
        'Ánh sáng, góc camera, cảnh cắt hoặc sản phẩm khác không tự là lỗi. '
        'Không tự nhận diện deepfake hoặc vi phạm pháp luật. '
        'Đừng suy diễn thương hiệu/giá nếu thiếu tham chiếu tin cậy. '
        'Product Truth là thông tin tham chiếu do người dùng cung cấp, '
        'KHÔNG phải bằng chứng được nhìn thấy. '
        'Đặc biệt nếu reference_status là unverified, KHÔNG coi so sánh '
        'với Product Truth là xác minh độc lập.\n'
        'Trả JSON theo schema gồm summary, timeline_summary, observations, issues. '
        'Confidence chỉ là tự đánh giá của model, chưa hiệu chuẩn. '
        'Nếu không có issue đủ căn cứ, issues=[].\n'
        'Product Truth (tham chiếu, không phải bằng chứng hình ảnh): ' +
        json.dumps(reference, ensure_ascii=False)
    )


_MIME = {
    '.mp4':'video/mp4', '.mov':'video/quicktime', '.webm':'video/webm',
    '.mpeg':'video/mpeg', '.mpg':'video/mpeg', '.avi':'video/x-msvideo',
    '.mkv':'video/x-matroska',
}


def _state(file) -> str:
    value = getattr(file, 'state', None)
    return str(getattr(value, 'name', value) or '').upper()


def analyze_native_video(adapter, path: Path | str, product: dict) -> VideoUnderstandingResult:
    """Upload, wait with bounded deadline, infer JSON, and delete remote copy."""
    path = Path(path)
    if not path.is_file():
        raise VLMError('Video không tồn tại')
    if not hasattr(adapter, '_get_client'):
        raise VLMError('Gemini adapter không hỗ trợ video gốc')
    client = adapter._get_client()
    mime = _MIME.get(path.suffix.lower())
    if not mime:
        raise VLMError('File video không thuộc định dạng Gemini hỗ trợ')
    uploaded = None
    try:
        from google.genai import types
        uploaded = client.files.upload(file=str(path),
            config=types.UploadFileConfig(mime_type=mime))
        timeout = max(30, min(900, int(os.getenv('VLM_VIDEO_PROCESS_TIMEOUT_SECONDS','240'))))
        poll_seconds = max(1, min(10, int(os.getenv('VLM_VIDEO_POLL_SECONDS','3'))))
        deadline = time.monotonic() + timeout
        while _state(uploaded) not in ('ACTIVE',):
            state = _state(uploaded)
            if state in ('FAILED', 'ERROR', 'CANCELLED'):
                raise VLMError('Gemini không thể xử lý video: '+state)
            if time.monotonic() >= deadline:
                raise VLMError('Hết thời gian đợi Gemini chuẩn bị video')
            time.sleep(poll_seconds)
            uploaded = client.files.get(name=uploaded.name)
        thinking = os.getenv('GEMINI_THINKING_LEVEL','low').lower()
        if thinking not in ('low','medium','high'):
            raise VLMError('GEMINI_THINKING_LEVEL không hợp lệ')
        response = client.models.generate_content(
            model=adapter.model,
            contents=[uploaded, video_prompt(product)],
            config=types.GenerateContentConfig(
                response_mime_type='application/json',
                response_schema=VideoUnderstandingResult,
                thinking_config=types.ThinkingConfig(thinking_level=thinking),
            ),
        )
        if not response.text:
            raise VLMError('Gemini không trả về nội dung phân tích video')
        return VideoUnderstandingResult.model_validate_json(response.text)
    except ValidationError as exc:
        raise VLMError('Gemini video JSON không đúng schema: '+str(exc)[:160]) from exc
    except VLMError:
        raise
    except Exception as exc:
        raise VLMError('Lỗi Gemini video: '+str(exc)[:200]) from exc
    finally:
        # Files uploaded to Gemini are not kept after an analysis is finished.
        if uploaded is not None and getattr(uploaded,'name',None):
            try:
                client.files.delete(name=uploaded.name)
            except Exception:
                # An API-side cleanup failure must never fabricate an AI result.
                pass
