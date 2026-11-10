"""Speed-ups of 04/11/2026: Gemini prefetch, mirror text reuse, model warm-up."""
import threading

import cv2
import numpy as np

from verifai_core.frame_anomaly import detect_mirror


def _clip(tmp_path, frames=40):
    path = tmp_path / 'm.mp4'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 10, (320, 180))
    for _ in range(frames):
        writer.write(np.full((180, 320, 3), 120, dtype=np.uint8))
    writer.release()
    return path


def test_mirror_skips_samples_whose_original_already_reads_brand_and_label(tmp_path):
    calls = []

    def ocr(img):
        calls.append(img.shape)
        return [], 'ok'
    known = lambda t: ['NutriGrow', 'Nội dung được tạo bởi AI']
    result = detect_mirror(_clip(tmp_path), ocr, 'NutriGrow', known_text_at=known)
    assert calls == []  # no OCR at all: no sample can read *only* when flipped
    assert result['flagged'] is False and result['samples_skipped'] == 10 and result['reused_scan_text']


def test_mirror_reuses_scan_text_instead_of_second_ocr(tmp_path):
    calls = []

    def ocr(img):  # flipped frame reveals the brand
        calls.append(1)
        return [('NutriGrow', 0.97)], 'ok'
    result = detect_mirror(_clip(tmp_path), ocr, 'NutriGrow', known_text_at=lambda t: ['Milk Powder'])
    assert len(calls) == 10  # one flipped OCR per sample, original text came from the scan
    assert result['flagged'] is True and len(result['hits']) == 10


def test_mirror_without_scan_text_keeps_original_double_ocr(tmp_path):
    calls = []

    def ocr(img):
        calls.append(1)
        return [('NutriGrow', 0.97)], 'ok'  # reads both ways -> not a mirror
    result = detect_mirror(_clip(tmp_path), ocr, 'NutriGrow')
    assert len(calls) == 20 and result['flagged'] is False and result['samples_skipped'] == 0


def test_gemini_calls_start_before_local_analysis_and_overlap(tmp_path, monkeypatch):
    import test_unknown_frame_count as helper
    import backend
    monkeypatch.setenv('VLM_COLOR_CHECK', '1')
    monkeypatch.setenv('VLM_TEXT_CHECK', '1')
    both_running = threading.Barrier(2, timeout=10)  # breaks unless colour and text overlap
    started = threading.Event()
    seen = {}

    def color(client, model, path):
        started.set(); both_running.wait()
        return {'status': 'ok', 'times': [0.5], 'issues': []}

    def text(client, model, path):
        both_running.wait()
        return {'status': 'ok', 'times': [0.5], 'issues': []}
    monkeypatch.setattr(backend, 'check_color_consistency', color)
    monkeypatch.setattr(backend, 'check_text_rendering', text)
    monkeypatch.setattr(backend._ProductionGeminiVLM, '_get_client', lambda self: object(), raising=False)
    original_progress = backend._set_progress

    def progress(job_id, stage, **data):
        if stage == 'asr' and 'asr' not in seen:
            # Sequential Gemini would only start after this stage.
            seen['asr'] = started.wait(timeout=5)
        return original_progress(job_id, stage, **data)
    monkeypatch.setattr(backend, '_set_progress', progress)
    native_calls = []
    job = helper._run(tmp_path, monkeypatch, native_calls=native_calls)
    assert job['status'] == 'completed', job['details']
    assert seen == {'asr': True}
    assert len(native_calls) == 1
    timings = job['details']['timings']
    assert timings['vlm_prefetch'] is True
    assert {'vlm_native_call_seconds', 'vlm_color_call_seconds', 'vlm_text_call_seconds',
            'vlm_wall_seconds'} <= set(timings)
    assert job['details']['vlm']['color_check']['status'] == 'ok'


def test_prefetch_can_be_switched_off(tmp_path, monkeypatch):
    import test_unknown_frame_count as helper
    import backend
    monkeypatch.setenv('VLM_PREFETCH', '0')
    monkeypatch.setattr(backend._ProductionGeminiVLM, '_get_client', lambda self: object(), raising=False)
    calls = []
    job = helper._run(tmp_path, monkeypatch, native_calls=calls)
    assert job['status'] == 'completed'
    assert job['details']['timings']['vlm_prefetch'] is False and len(calls) == 1


def test_warm_models_loads_ocr_then_asr(monkeypatch):
    import backend
    order = []
    monkeypatch.setattr(backend._ocr_service, 'warm', lambda: order.append('ocr') or 'ok')
    monkeypatch.setattr(backend._asr_service, 'warm', lambda: order.append('asr') or 'ok')
    monkeypatch.setenv('OCR_ENABLED', '1')
    monkeypatch.setenv('ASR_ENABLED', '1')
    backend.warm_models()
    assert order == ['ocr', 'asr']
    assert backend.MODEL_WARMUP['status'] == 'done' and backend.MODEL_WARMUP['ocr'] == 'ok'


def test_prefetched_colour_result_survives_full_video_503(tmp_path, monkeypatch):
    import test_unknown_frame_count as helper
    import backend
    from verifai_core.vlm import VLMError
    monkeypatch.setenv('VLM_COLOR_CHECK', '1')

    def color(client, model, path):
        return {'status': 'ok', 'times': [0.5, 2.5],
                'issues': [{'object': 'sữa tắm', 'from_color': 'trắng', 'to_color': 'xanh dương',
                            'visible_basis': 'dòng sữa trên tay', 'confidence': 0.95, 'timestamp': 2.5}]}
    monkeypatch.setattr(backend, 'check_color_consistency', color)
    monkeypatch.setattr(backend._ProductionGeminiVLM, '_get_client', lambda self: object(), raising=False)
    original = backend._start_vlm_prefetch

    def prefetch(path, product):
        started = original(path, product)

        def busy(*args):
            raise VLMError('Lỗi Gemini video: 503 UNAVAILABLE')
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(1) as pool:
            started['futures']['native'] = pool.submit(busy)
        return started
    monkeypatch.setattr(backend, '_start_vlm_prefetch', prefetch)
    job = helper._run(tmp_path, monkeypatch)
    assert job['status'] == 'completed', job['details']
    assert job['details']['coverage']['vlm'] == 'error'  # still fail-closed
    assert job['details']['vlm']['color_check']['status'] == 'ok'
    assert [f['code'] for f in job['findings'] if f['code'] == 'VIS-02'] == ['VIS-02']
    assert any('503' in e for e in job['details']['vlm']['errors'])
