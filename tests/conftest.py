"""Fixtures for fast, deterministic API workflow tests.

Real PaddleOCR/faster-whisper inference is checked separately using
scripts/check_perception.py --live --video <path>.
"""
import pytest


@pytest.fixture
def stub_perception(monkeypatch):
    """Stub costly OCR/ASR without changing upload, jobs, rules or mocked VLM."""
    import backend

    monkeypatch.setattr(backend, 'frame_ocr', lambda frame: ([], 'not_installed'))
    monkeypatch.setattr(backend, 'transcribe', lambda path: ([], 'not_installed'))
