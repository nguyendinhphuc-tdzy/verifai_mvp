"""S1-2 adaptive OCR: every frame checked, OCR only where text may differ."""
import time

import cv2
import numpy as np
from fastapi.testclient import TestClient

from verifai_core.adaptive_ocr import (AdaptiveOCRConfig, AdaptiveOCRScanner,
                                       same_text, signature, tile_change, thumbnail)

FPS = 30


def frames_from(states, *, noise=False, full=False):
    """Synthetic frames: the 'text' of frame i is encoded as the brightness of a
    small box (0 = no text). Small brightness steps simulate a text change too
    subtle for the visual change check, which must then be found by bisection."""
    rng = np.random.default_rng(0)
    for i, value in enumerate(states):
        image = np.full((180, 320, 3), 90, dtype=np.uint8)
        if noise:
            image = rng.integers(0, 255, image.shape, dtype=np.uint8)
        image[10:40, 10:80] = value
        item = {'image': image, 'at': round(i / FPS, 3), 'frame': f'ocr-{i:08d}.jpg',
                'source_frame_index': i}
        if full:
            item['full'] = cv2.resize(image, (640, 360))
        yield item


class FakeOCR:
    def __init__(self, digits=False):
        self.calls = []
        self.digits = digits

    def __call__(self, image):
        self.calls.append(image.shape)
        value = int(image[image.shape[0] * 25 // 180, image.shape[1] * 45 // 320, 0])
        if value == 90:
            return [], 'ok'
        text = f'GIA {value}000' if self.digits else f'TEXT-{value}'
        score = 0.97 if image.shape[1] > 320 else 0.92
        return [(text, score)], 'ok'


def run(states, **kwargs):
    ocr = FakeOCR(digits=kwargs.pop('digits', False))
    noise = kwargs.pop('noise', False)
    full = kwargs.pop('full', False)
    scanner = AdaptiveOCRScanner(ocr, FPS, AdaptiveOCRConfig(**kwargs))
    events = list(scanner.scan(frames_from(states, noise=noise, full=full)))
    return scanner, events, ocr


def test_static_text_reads_on_half_second_grid_and_accounts_every_frame():
    scanner, events, ocr = run([200] * 90)
    stats = scanner.stats.snapshot(scanner.config, FPS)
    assert stats['decoded_frames'] == 90
    assert stats['all_frames_accounted'] is True
    # first + every 15 frames + last; far fewer than 90 exhaustive calls
    assert len(ocr.calls) == stats['ocr_frames'] == 7
    assert stats['ocr_frames'] + stats['inherited_frames'] == 90
    assert sum(1 + e.inherited_frames for e in events) == 90


def test_large_visual_change_triggers_ocr_at_the_change_frame():
    states = [200] * 37 + [30] * 53          # strong change at frame 37
    scanner, events, _ = run(states)
    first_new = min(e.frame['source_frame_index'] for e in events if e.results == [('TEXT-30', 0.92)])
    assert first_new == 37
    assert scanner.stats.by_reason.get('change') == 1


def test_subtle_text_change_is_located_exactly_by_bisection():
    states = [200] * 37 + [205] * 53         # below change threshold, different text
    scanner, events, _ = run(states)
    readings = {e.frame['source_frame_index']: e for e in events}
    boundary = min(i for i, e in readings.items() if e.results and e.results[0][0] == 'TEXT-205')
    assert boundary == 37
    owner_before = max(i for i, e in readings.items() if i < 37)
    assert readings[owner_before].visible_until == round(36 / FPS, 3)
    assert scanner.stats.boundary_searches >= 1
    assert scanner.stats.snapshot(scanner.config, FPS)['all_frames_accounted']


def test_short_flash_is_caught_by_change_check_between_grid_points():
    states = [90] * 70 + [255] * 4 + [90] * 46   # text visible 4 frames (0.13 s)
    _, events, _ = run(states)
    assert any(e.results and e.results[0][0] == 'TEXT-255' for e in events)


def test_constant_motion_is_rate_limited_not_exhaustive():
    scanner, _, ocr = run([200] * 90, noise=True)
    # min gap 0.2 s => at most ~5 OCR/s instead of 30
    assert len(ocr.calls) <= 90 // 6 + 2
    assert scanner.stats.snapshot(scanner.config, FPS)['all_frames_accounted']


def test_numeric_text_is_reread_once_at_full_resolution():
    scanner, events, ocr = run([200] * 90, digits=True, full=True)
    assert scanner.stats.fullres_calls == 1
    assert scanner.stats.fullres_improved == 1
    assert events[0].fullres_used is True and events[0].results[0][1] == 0.97
    assert len(ocr.calls) == scanner.stats.ocr_frames + 1


def test_signature_tolerates_ocr_jitter_but_not_a_different_price():
    a = signature([('Giá 149.000đ', .9)], 'ok')
    assert same_text(a, signature([('Gia 149.000đ', .9)], 'ok'))
    # 91% similar strings, but a different price: must be a different text state.
    assert not same_text(a, signature([('Giá 199.000đ', .9)], 'ok'))
    assert not same_text(signature([('149000', .9)], 'ok'), signature([('99000', .9)], 'ok'))
    assert not same_text(a, signature([], 'ok'))


def test_tile_change_detects_local_change_on_static_background():
    base = np.full((180, 320, 3), 90, dtype=np.uint8)
    changed = base.copy(); changed[10:40, 10:80] = 255
    assert tile_change(thumbnail(base), thumbnail(base)) == 0
    assert tile_change(thumbnail(base), thumbnail(changed)) > 12


def test_invalid_configuration_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        AdaptiveOCRConfig(max_gap_seconds=0)
    with pytest.raises(ValueError):
        AdaptiveOCRConfig(max_gap_seconds=0.5, min_gap_seconds=1)


def test_adaptive_is_default_in_real_job_and_frames_are_served(tmp_path, monkeypatch):
    import backend
    monkeypatch.setattr(backend, 'DB', tmp_path / 'verifai.sqlite3')
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    monkeypatch.setattr(backend, 'UPLOAD', tmp_path / 'uploads')
    monkeypatch.setattr(backend, 'FRAMES', tmp_path / 'frames')
    monkeypatch.setattr(backend, 'OCR_SCAN_MODE', 'adaptive')
    monkeypatch.setenv('OCR_ENABLED', '1')
    monkeypatch.setenv('ASR_ENABLED', '0')
    backend.UPLOAD.mkdir(); backend.FRAMES.mkdir()
    backend.init()
    ocr = FakeOCR()
    monkeypatch.setattr(backend, 'frame_ocr', ocr)
    video = tmp_path / 'v.mp4'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), FPS, (320, 180))
    for frame in frames_from([200] * 45 + [30] * 45):
        writer.write(frame['image'])
    writer.release()
    client = TestClient(backend.app)
    pid = client.post('/api/products', json={'sku': 'A1', 'name': 'x', 'brand': 'b', 'price': 1000,
                                             'claims': [], 'banned': []}).json()['id']
    with video.open('rb') as stream:
        jid = client.post('/api/jobs', data={'product_id': pid, 'rights': 'self_created'},
                          files={'file': ('v.mp4', stream, 'video/mp4')}).json()['id']
    for _ in range(300):
        job = client.get('/api/jobs/' + jid).json()
        if job['status'] in ('completed', 'failed'):
            break
        time.sleep(.025)
    assert job['status'] == 'completed', job['details']
    quality = job['details']['perception_quality']['ocr']
    assert quality['scan_mode'] == 'adaptive'
    assert quality['complete_video_scan'] is True
    assert quality['adaptive']['decoded_frames'] == 90
    assert quality['adaptive']['ocr_frames'] < 20
    ocr_evidence = [e for e in job['evidence'] if e['kind'] == 'ocr']
    assert ocr_evidence and all(e['end_timestamp'] >= e['timestamp'] for e in ocr_evidence)
    assert any(e['end_timestamp'] > e['timestamp'] for e in ocr_evidence)
    assert client.get(f'/api/jobs/{jid}/frames/{ocr_evidence[0]["frame"]}').status_code == 200
