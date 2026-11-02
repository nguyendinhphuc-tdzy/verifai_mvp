"""Download and load OCR/ASR weights once (used at Docker build time)."""
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('VERIFAI_SKIP_DOTENV', '1')

from verifai_core.perception import OCRService  # noqa: E402

results, status = OCRService().extract(np.full((64, 64, 3), 255, dtype=np.uint8))
print('ocr warm-up:', status)
if status != 'ok':
    raise SystemExit('OCR model failed to load')

from faster_whisper import WhisperModel  # noqa: E402

WhisperModel(os.environ.get('WHISPER_MODEL', 'small'), device='cpu', compute_type='int8')
print('asr warm-up: ok')
