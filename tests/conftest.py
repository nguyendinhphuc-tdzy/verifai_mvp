"""Fixtures for fast, deterministic API workflow tests.

Real PaddleOCR/faster-whisper inference is checked separately using
scripts/check_perception.py --live --video <path>.
"""
import atexit
import os
import shutil
import tempfile

import pytest

# `import backend` runs init() against VERIFAI_DATA at import time. Point it at
# a throwaway directory BEFORE any test imports backend, so the suite can never
# migrate or write the developer's real data/verifai.sqlite3, uploads or frames.
_TEST_DATA = tempfile.mkdtemp(prefix='verifai-test-data-')
os.environ['VERIFAI_DATA'] = _TEST_DATA
atexit.register(shutil.rmtree, _TEST_DATA, ignore_errors=True)

# Never bill or call the live Gemini API from the offline suite. Tests that
# exercise VLM paths enable it explicitly with monkeypatch and a mocked client.
os.environ['VERIFAI_SKIP_DOTENV'] = '1'
os.environ['VLM_ENABLED'] = '0'
os.environ['VLM_COLOR_CHECK'] = '0'  # enabled explicitly where tested
for _key in ('GEMINI_API_KEY', 'GOOGLE_API_KEY'):
    os.environ.pop(_key, None)


@pytest.fixture
def stub_perception(monkeypatch):
    """Stub costly OCR/ASR without changing upload, jobs, rules or mocked VLM."""
    import backend

    monkeypatch.setattr(backend, 'frame_ocr', lambda frame: ([], 'not_installed'))
    monkeypatch.setattr(backend, 'transcribe', lambda path: ([], 'not_installed'))
