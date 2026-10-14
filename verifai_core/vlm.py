"""Local Ollama vision adapter with validated, evidence-grounded JSON output."""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from typing import Literal
from pydantic import BaseModel, Field, ValidationError, ConfigDict

PROMPT_VERSION = 'vlm-visual-2.0'


class VLMObservation(BaseModel):
    model_config = ConfigDict(extra='ignore')
    description: str = Field(min_length=3, max_length=700)
    category: Literal['product', 'packaging', 'visible_text', 'scene', 'other']
    confidence: float = Field(ge=0, le=1)
    frame_index: int = Field(ge=0, le=1)


class VLMIssue(BaseModel):
    model_config = ConfigDict(extra='ignore')
    code: Literal['SKU-01', 'VIS-01', 'VIS-02', 'VIS-03', 'CLAIM-VLM']
    description: str = Field(min_length=5, max_length=700)
    visible_basis: str = Field(min_length=5, max_length=700)
    confidence: float = Field(ge=0, le=1)
    frame_index: int = Field(ge=0, le=1)


class VLMResult(BaseModel):
    model_config = ConfigDict(extra='ignore')
    summary: str = Field(default='', max_length=700)
    observations: list[VLMObservation] = Field(default_factory=list, max_length=12)
    issues: list[VLMIssue] = Field(default_factory=list, max_length=8)


class VLMError(RuntimeError):
    pass


class OllamaVLM:
    def __init__(self, model: str | None = None, base_url: str | None = None, timeout: int | None = None):
        self.model = model or os.environ.get('VLM_MODEL', 'qwen3-vl:4b-instruct')
        self.base_url = (base_url or os.environ.get('VLM_BASE_URL', 'http://127.0.0.1:11434')).rstrip('/')
        self.timeout = timeout or int(os.environ.get('VLM_TIMEOUT_SECONDS', '120'))
        parsed = urlparse(self.base_url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ('', '/'):
            raise VLMError('VLM_BASE_URL phải là URL gốc http(s) hợp lệ, không chứa credentials/path.')
        if parsed.hostname not in ('127.0.0.1', 'localhost', '::1') and os.environ.get('VLM_ALLOW_REMOTE') != '1':
            raise VLMError('Chỉ cho phép Ollama localhost; đặt VLM_ALLOW_REMOTE=1 nếu tự chịu trách nhiệm truyền dữ liệu ra ngoài.')

    def check(self) -> dict:
        try:
            response = self._request('/api/tags', None, timeout=2)
            names = [m.get('name', '') for m in response.get('models', [])]
            installed = self.model in names or any(n.split(':')[0] == self.model.split(':')[0] and self.model.endswith(':latest') for n in names)
            return {'ready': installed, 'model_installed': installed, 'server_reachable': True,
                    'message': 'ready' if installed else f'Chưa pull model {self.model}'}
        except (VLMError, OSError) as exc:
            return {'ready': False, 'model_installed': False, 'server_reachable': False,
                    'message': str(exc)[:180]}

    def _request(self, path: str, body: dict | None, timeout: int | None = None) -> dict:
        raw = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
        req = Request(self.base_url + path, data=raw,
                      headers={'Content-Type': 'application/json'},
                      method='POST' if body is not None else 'GET')
        try:
            with urlopen(req, timeout=timeout or self.timeout) as response:
                if int(response.headers.get('Content-Length', '0')) > 2_000_000:
                    raise VLMError('Ollama response quá lớn')
                return json.loads(response.read(2_000_000).decode('utf-8'))
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            raise VLMError(f'Ollama request failed: {str(exc)[:180]}') from exc

    def analyze(self, images: list[Path], product: dict, task: Literal['single', 'pair']) -> VLMResult:
        if not images or len(images) > 2 or (task == 'pair' and len(images) != 2):
            raise VLMError('Số frame không hợp lệ')
        for p in images:
            if not p.is_file() or p.suffix.lower() not in ('.jpg', '.jpeg') or p.stat().st_size > 2_000_000:
                raise VLMError('Frame không tồn tại hoặc vượt 2MB')
        truth = {'sku': product['sku'], 'product_name': product['name'],
                 'brand': product['brand'], 'approved_claims': product['claims'][:15],
                 'restricted_claims': product['banned'][:15]}
        # The product reference is TEXT ONLY; no image-grounded SKU matching is possible.
        rules = '''Bạn là kiểm định viên hình ảnh cho video quảng cáo. Chỉ nêu những gì THỰC SỰ NHÌN THẤY trong ảnh.
KHÔNG suy đoán SKU chỉ từ hình dáng khi không có ảnh SKU tham chiếu. Không suy diễn sản phẩm giả,
không kết luận video do AI tạo, không đưa ra kết luận pháp lý. Cảnh khác góc máy, ánh sáng,
chuyển động, che khuất, thay trang phục hoặc chuyển cảnh KHÔNG tự động là lỗi.
Chỉ tạo issues nếu có bằng chứng thị giác cụ thể, mô tả tại visible_basis (chi tiết nhìn thấy).
SKU-01: chữ in rõ trên nhãn bao bì mâu thuẫn với SKU/brand tham chiếu.
VIS-01: chi tiết sản phẩm biến dạng rõ ràng (ngón tay/chi tiết sản phẩm bất khả thi).
VIS-02: cùng một sản phẩm trong hai ảnh cùng cảnh đổi hình dáng/nhãn/linh kiện một cách khó giải thích.
VIS-03: chữ/logo/bao bì bất thường rõ ràng trong hình.
CLAIM-VLM: chữ claim nhìn thấy rõ mâu thuẫn với danh sách hạn chế (để reviewer kiểm tra).
Đặt issues=[] khi không có bằng chứng đủ rõ. Confidence chỉ là độ tự tin TỰ BÁO CÁO, không hiệu chuẩn.
Trả về JSON đúng schema: summary, observations[{description,category,confidence,frame_index}],
issues[{code,description,visible_basis,confidence,frame_index}]. frame_index bắt đầu 0.'''
        if task == 'pair':
            rules += '\nHai ảnh lần lượt là frame 0 và frame 1 của cùng video. So sánh chỉ khi cùng sản phẩm có thể theo dõi; nếu không chắc thì issues=[].'
        else:
            rules += '\nChỉ có một ảnh, không được tạo VIS-02 (lỗi cần so sánh thời gian).'
        prompt = rules + '\nProduct truth (dữ liệu tham chiếu, không phải bằng chứng thị giác): ' + json.dumps(truth, ensure_ascii=False)
        payload = {'model': self.model,
                   'messages': [{'role': 'user', 'content': prompt,
                                 'images': [base64.b64encode(p.read_bytes()).decode('ascii') for p in images]}],
                   'format': VLMResult.model_json_schema(),
                   'stream': False, 'options': {'temperature': 0, 'num_predict': 900}}
        response = self._request('/api/chat', payload)
        content = response.get('message', {}).get('content')
        if not isinstance(content, str):
            raise VLMError('Ollama không trả về message.content')
        try:
            result = VLMResult.model_validate_json(content)
        except ValidationError as exc:
            raise VLMError(f'VLM JSON schema invalid: {str(exc)[:170]}') from exc
        if task == 'single':
            result.issues = [i for i in result.issues if i.code != 'VIS-02' and i.frame_index == 0]
            result.observations = [i for i in result.observations if i.frame_index == 0]
        return result


def vlm_enabled() -> bool:
    return os.environ.get('VLM_ENABLED', '0').strip().lower() in ('1', 'true', 'yes')
