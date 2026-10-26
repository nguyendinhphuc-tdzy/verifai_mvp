"""Gemini Flash vision adapter. Sends selected JPEG frames, not entire videos.

Explicit opt-in via VLM_ENABLED=1 and GEMINI_API_KEY. Images leave the local
machine: obtain consent/rights before processing sensitive advertising media.
Results remain UNVERIFIED reviewer candidates, never ground truth.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Literal

from pydantic import ValidationError
from verifai_core.vlm import VLMResult, VLMError, PROMPT_VERSION


DEFAULT_MODEL = 'gemini-3.8-flash'


def _prompt(product: dict, task: Literal['single', 'pair']) -> str:
    reference = {
        'sku': product.get('sku', ''),
        'product_name': product.get('name', ''),
        'brand': product.get('brand', ''),
        'approved_claims': (product.get('claims') or [])[:15],
        'restricted_claims': (product.get('banned') or [])[:15],
    }
    rules = """Bạn là trợ lý kiểm duyệt hình ảnh quảng cáo, không phải cơ quan pháp lý.
Chỉ mô tả những chi tiết thực sự nhìn thấy ở frame đã cung cấp.
Không tự bịa chữ trên bao bì, giá bán, kích thước hoặc thông tin sản phẩm.
Thông tin Product Truth chỉ là dữ liệu tham chiếu, KHÔNG phải bằng chứng thị giác.
Không suy diễn SKU chỉ từ hình dạng nếu thiếu hình sản phẩm chuẩn.
Không tự kết luận rằng video được AI tạo hoặc có vi phạm pháp luật.
Thay đổi góc quay, ánh sáng, chuyển động, cảnh nền không mặc nhiên là lỗi.
Chỉ tạo issues với visible_basis cụ thể; nếu thiếu bằng chứng, issues=[].
Các mã issues: SKU-01 (chữ nhãn nhìn rõ khác brand/SKU tham chiếu);
VIS-01 (biến dạng hình ảnh rõ ràng); VIS-02 (cùng sản phẩm trong hai frame cùng
cảnh thay đổi hình dạng/nhãn một cách khó giải thích); VIS-03 (chữ/logo/bao bì
bất thường rõ ràng); CLAIM-VLM (chữ claim quan sát rõ cần đối chiếu).
Trả JSON theo schema gồm summary, observations, issues; frame_index bắt đầu từ 0.
Confidence là độ tin cậy mô hình tự khai báo, KHÔNG hiệu chuẩn."""
    if task == 'single':
        rules += '\nChỉ có một frame, tuyệt đối không tạo VIS-02.'
    else:
        rules += '\nHai frame theo thứ tự 0 và 1; chỉ so sánh VIS-02 khi là cùng sản phẩm, cùng cảnh.'
    return rules + '\nProduct Truth (reference, not visual evidence): ' + json.dumps(reference, ensure_ascii=False)


class GeminiVLM:
    def __init__(self, model: str | None = None, client=None):
        self.model = model or os.getenv('VLM_MODEL', DEFAULT_MODEL)
        self._client = client
        self._key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')

    def check(self) -> dict:
        if not self._key and self._client is None:
            return {'ready': False, 'server_reachable': False,
                    'message': 'GEMINI_API_KEY chưa được thiết lập'}
        try:
            from google import genai  # noqa: F401 - test the optional SDK
        except ImportError:
            return {'ready': False, 'server_reachable': False,
                    'message': 'Thiếu google-genai: pip install google-genai'}
        return {'ready': True, 'server_reachable': None,
                'message': 'Gemini configured; API reachability checked during inference'}

    def _get_client(self):
        if self._client is None:
            if not self._key:
                raise VLMError('GEMINI_API_KEY chưa được thiết lập')
            try:
                from google import genai
                seconds = max(10, int(os.getenv('VLM_TIMEOUT_SECONDS', '120')))
                self._client = genai.Client(
                    api_key=self._key, http_options={'timeout': seconds * 1000})
            except (ImportError, TypeError, ValueError) as exc:
                raise VLMError(f'Không tạo được Gemini client: {str(exc)[:150]}') from exc
        return self._client

    def analyze(self, images: list[Path],
                product: dict, task: Literal['single', 'pair']) -> VLMResult:
        if task not in ('single', 'pair') or not images or len(images) > 2 or (task == 'pair' and len(images) != 2):
            raise VLMError('Số frame hoặc tác vụ không hợp lệ')
        for path in images:
            if not path.is_file() or path.suffix.lower() not in ('.jpg', '.jpeg') or path.stat().st_size > 2_000_000:
                raise VLMError('Frame không tồn tại, không phải JPEG hoặc vượt 2MB')
        try:
            from google.genai import types
            contents = [_prompt(product, task)]
            contents.extend(types.Part.from_bytes(data=p.read_bytes(), mime_type='image/jpeg')
                            for p in images)
            config = types.GenerateContentConfig(
                response_mime_type='application/json',
                response_schema=VLMResult,
                temperature=0,
            )
        except (ImportError, ValueError, TypeError) as exc:
            raise VLMError(f'Không tạo được Gemini request: {str(exc)[:160]}') from exc

        client = self._get_client()
        attempts = max(1, min(4, int(os.getenv('GEMINI_MAX_ATTEMPTS', '3'))))
        for attempt in range(attempts):
            try:
                response = client.models.generate_content(
                    model=self.model, contents=contents, config=config)
                raw_text = response.text
                if not raw_text:
                    raise VLMError('Gemini không trả về JSON; có thể bị chặn hoặc thiếu output')
                result = VLMResult.model_validate_json(raw_text)
                if task == 'single':
                    result.issues = [i for i in result.issues
                                     if i.code != 'VIS-02' and i.frame_index == 0]
                    result.observations = [i for i in result.observations
                                           if i.frame_index == 0]
                return result
            except ValidationError as exc:
                raise VLMError(f'Gemini JSON schema invalid: {str(exc)[:180]}') from exc
            except VLMError:
                raise
            except Exception as exc:
                code = str(getattr(exc, 'code', '') or getattr(exc, 'status', ''))
                msg = str(exc)
                retriable = any(t in code or t in msg for t in ('429', '503', 'UNAVAILABLE', 'RESOURCE_EXHAUSTED'))
                if retriable and attempt + 1 < attempts:
                    time.sleep(min(12, 2 ** (attempt + 1)))
                    continue
                raise VLMError(f'Gemini request failed: {msg[:220]}') from exc
        raise VLMError('Gemini retry budget exhausted')
