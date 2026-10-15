"""Deterministic OCR/ASR integration unit tests: no model download required."""
from types import SimpleNamespace
import sys

from verifai_core import perception


def test_unpack_paddleocr_3_json():
    payload = [SimpleNamespace(json={'res': {
        'rec_texts': ['  Giá 149.000đ  ', '', 'BabyGentle', 'bad score'],
        'rec_scores': [0.93, 0.9, 0.81, 'oops']
    }})]
    assert perception.unpack_ocr_result(payload) == [
        ('Giá 149.000đ', 0.93), ('BabyGentle', 0.81)]


def test_ocr_is_lazy_and_uses_vietnamese_model(monkeypatch):
    events = []
    class FakeOCR:
        def __init__(self, **kwargs):
            events.append(kwargs)
        def predict(self, frame):
            return [{'res': {'rec_texts': ['99.000đ'], 'rec_scores': [0.88]}}]
    monkeypatch.setattr(perception, 'ocr_installed', lambda: True)
    monkeypatch.setitem(sys.modules, 'paddleocr', SimpleNamespace(PaddleOCR=FakeOCR))
    engine = perception.OCRService()
    assert events == []  # lazy until first use
    assert engine.extract(object()) == ([('99.000đ', 0.88)], 'ok')
    assert engine.extract(object())[1] == 'ok'
    assert len(events) == 1
    assert events[0]['lang'] == 'vi'
    assert events[0]['ocr_version'] == 'PP-OCRv5'


def test_asr_lazy_cpu_and_vietnamese(monkeypatch):
    events = []
    class FakeWhisper:
        def __init__(self, *args, **kwargs):
            events.append((args, kwargs))
        def transcribe(self, file, **kwargs):
            events.append(kwargs)
            yield_segments = (SimpleNamespace(start=0.1, text=t) for t in ('Xin chào', '  '))
            return yield_segments, None
    monkeypatch.setattr(perception, 'asr_installed', lambda: True)
    monkeypatch.setitem(sys.modules, 'faster_whisper', SimpleNamespace(WhisperModel=FakeWhisper))
    for key in ('WHISPER_MODEL','WHISPER_DEVICE','WHISPER_COMPUTE_TYPE','WHISPER_LANGUAGE'):
        monkeypatch.delenv(key, raising=False)
    engine = perception.ASRService()
    assert events == []
    segments, state = engine.extract('sample.mp4')
    assert state == 'ok'
    assert segments == [{'at': 0.1, 'text': 'Xin chào', 'score': None}]
    assert events[0][0] == ('base',)
    assert events[0][1] == {'device':'cpu','compute_type':'int8'}
    assert events[1]['language'] == 'vi'


def test_missing_modules_are_reported(monkeypatch):
    monkeypatch.setattr(perception, 'ocr_installed', lambda: False)
    monkeypatch.setattr(perception, 'asr_installed', lambda: False)
    assert perception.OCRService().extract(None) == ([], 'not_installed')
    assert perception.ASRService().extract('missing.mp4') == ([], 'not_installed')
