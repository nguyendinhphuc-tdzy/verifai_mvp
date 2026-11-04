"""Optional, local OCR and ASR adapters for the Windows-friendly VerifAI MVP.

No model is downloaded or imported at backend startup. Errors are returned as
coverage status so the reviewer never mistakes missing analysis for a clean video.
"""
from __future__ import annotations

import importlib.util
import math
import os
import threading
from pathlib import Path
from typing import Any


def ocr_installed() -> bool:
    try:
        return (importlib.util.find_spec('paddle') is not None
                and importlib.util.find_spec('paddleocr') is not None)
    except (ImportError, ValueError):
        return False


def has_audio_stream(path: Path | str) -> bool | None:
    """True/False when the container could be probed, None when unknown."""
    try:
        import av
    except ImportError:
        return None
    try:
        with av.open(str(path)) as container:
            return len(container.streams.audio) > 0
    except Exception:
        return None


def asr_installed() -> bool:
    try:
        return importlib.util.find_spec('faster_whisper') is not None
    except (ImportError, ValueError):
        return False


def unpack_ocr_result(result: Any) -> list[tuple[str, float]]:
    """Read PaddleOCR 3.x predict() results without assuming each line is valid."""
    lines: list[tuple[str, float]] = []
    for item in result or []:
        record = getattr(item, 'json', item)
        if callable(record):
            record = record()
        if not isinstance(record, dict):
            continue
        record = record.get('res', record)
        if not isinstance(record, dict):
            continue
        for text, score in zip(record.get('rec_texts') or [],
                               record.get('rec_scores') or []):
            text = str(text).strip()
            if not text:
                continue
            try:
                confidence = max(0.0, min(1.0, float(score)))
            except (TypeError, ValueError):
                continue
            lines.append((text, confidence))
    return lines


class OCRService:
    def __init__(self):
        self.model = None
        self.lock = threading.Lock()

    def extract(self, frame) -> tuple[list[tuple[str, float]], str]:
        if not ocr_installed():
            return [], 'not_installed'
        try:
            from paddleocr import PaddleOCR
            with self.lock:
                self._load(PaddleOCR)
                results = self.model.predict(frame)
            return unpack_ocr_result(results), 'ok'
        except Exception as exc:  # optional native Paddle runtime may fail
            return [], f'error: {str(exc)[:180]}'

    def _load(self, PaddleOCR) -> None:
        if self.model is None:
            # PP-OCRv5 supports Vietnamese; setting the language is
            # essential for text like "Giá", "sữa", "khăn ướt".
            self.model = PaddleOCR(
                lang=os.environ.get('OCR_LANG', 'vi'),
                ocr_version='PP-OCRv5',
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )

    def warm(self) -> str:
        """Load the model and run one tiny inference so the first video does not pay for it."""
        if not ocr_installed():
            return 'not_installed'
        try:
            import numpy as np
            from paddleocr import PaddleOCR
            with self.lock:
                self._load(PaddleOCR)
                self.model.predict(np.full((64, 160, 3), 255, dtype=np.uint8))
            return 'ok'
        except Exception as exc:
            return f'error: {str(exc)[:180]}'


def unpack_asr_segments(segments: Any) -> list[dict]:
    """Clean Whisper timestamps/text without changing established evidence keys.

    Include 'end' only if supplied and valid so older adapters stay compatible.
    Report empty-but-successful transcriptions as no segments, not fake speech.
    """
    lines = []
    for segment in segments:
        raw_text = getattr(segment, 'text', '')
        text = ' '.join(str(raw_text or '').split())[:1500]
        if not text:
            continue
        try:
            start = float(getattr(segment, 'start'))
        except (TypeError, ValueError, AttributeError):
            continue
        if not math.isfinite(start) or start < 0:
            continue
        data = {'at': round(start, 2), 'text': text, 'score': None}
        try:
            end = float(getattr(segment, 'end'))
        except (TypeError, ValueError, AttributeError):
            end = None
        if end is not None and math.isfinite(end) and end >= start:
            data['end'] = round(end, 2)
        lines.append(data)
    return lines


class ASRService:
    def __init__(self):
        self.model = None
        self.lock = threading.Lock()

    def extract(self, path: Path | str) -> tuple[list[dict], str]:
        if not asr_installed():
            return [], 'not_installed'
        if has_audio_stream(path) is False:
            # No audio track: there is nothing to hear, so the ASR check is
            # complete with zero speech (faster-whisper would raise IndexError).
            return [], 'ok'
        try:
            from faster_whisper import WhisperModel
            with self.lock:
                error = self._load(WhisperModel)
                if error:
                    return [], error
                segments, _ = self.model.transcribe(
                    str(path), beam_size=3, vad_filter=True,
                    language=os.environ.get('WHISPER_LANGUAGE', 'vi'),
                )
                # The iterator performs inference: consume it under the lock.
                lines = unpack_asr_segments(segments)
            return lines, 'ok'
        except Exception as exc:  # missing weights/codec/runtime
            return [], f'error: {str(exc)[:180]}'

    def _load(self, WhisperModel) -> str | None:
        if self.model is None:
            device = os.environ.get('WHISPER_DEVICE', 'cpu').lower()
            if device not in ('cpu', 'cuda'):
                return 'error: WHISPER_DEVICE must be cpu or cuda'
            compute = os.environ.get('WHISPER_COMPUTE_TYPE',
                                     'int8' if device == 'cpu' else 'float16')
            self.model = WhisperModel(
                os.environ.get('WHISPER_MODEL', 'base'),
                device=device, compute_type=compute,
            )
        return None

    def warm(self) -> str:
        """Load the Whisper weights ahead of the first video."""
        if not asr_installed():
            return 'not_installed'
        try:
            from faster_whisper import WhisperModel
            with self.lock:
                return self._load(WhisperModel) or 'ok'
        except Exception as exc:
            return f'error: {str(exc)[:180]}'
