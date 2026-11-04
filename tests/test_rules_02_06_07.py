"""RULE02 (infant nutrition), RULE06 (garbled text), RULE07 (mirror, pixelation),
and the RULE01-10 registry (04/11/2026)."""
import json
import time

import cv2
import numpy as np
from fastapi.testclient import TestClient

from verifai_core.color_consistency import parse_text_issues
from verifai_core.frame_anomaly import detect_mirror, detect_pixelation
from verifai_core.infant_nutrition import (advertising_restriction, breastmilk_comparison,
                                           has_age_information, max_age_months)
from verifai_core.rule_registry import RULES, rule_for


# --- RULE07 -------------------------------------------------------------------
def _asymmetric_video(path, frames=40, mirror_from=24):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 8, (160, 240))
    for i in range(frames):
        img = np.full((240, 160, 3), 60, dtype=np.uint8)
        img[20:120, 10:70] = 230                      # bright block on the LEFT
        writer.write(cv2.flip(img, 1) if i >= mirror_from else img)
    writer.release()


class OrientationOCR:
    """Reads the brand only when the bright block is on the left (normal orientation)."""
    def __init__(self):
        self.calls = 0

    def __call__(self, image):
        self.calls += 1
        h, w = image.shape[:2]
        left = image[: h // 2, : w // 2].mean()
        right = image[: h // 2, w // 2:].mean()
        return ([('BabySkin', 0.99)] if left > right else [('nikSybaB', 0.6)]), 'ok'


def test_mirror_detected_only_where_brand_reads_after_flipping(tmp_path):
    video = tmp_path / 'mirror.mp4'
    _asymmetric_video(video)
    result = detect_mirror(video, OrientationOCR(), 'BabySkin')
    assert result['flagged'] is True
    assert result['first_at'] >= 2.9  # mirrored from frame 24 / 8 fps = 3.0 s
    normal = tmp_path / 'normal.mp4'
    _asymmetric_video(normal, mirror_from=10_000)
    assert detect_mirror(normal, OrientationOCR(), 'BabySkin')['flagged'] is False


def test_brand_readable_both_ways_is_not_a_mirror(tmp_path):
    video = tmp_path / 'v.mp4'
    _asymmetric_video(video)
    always = lambda image: ([('BabySkin', 0.99)], 'ok')  # noqa: E731
    assert detect_mirror(video, always, 'BabySkin')['flagged'] is False


def _texture_video(path, frames=40, pixelate_from=None):
    rng = np.random.default_rng(0)
    base = cv2.GaussianBlur(rng.integers(0, 255, (640, 360, 3), dtype=np.uint8), (3, 3), 0)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 10, (360, 640))
    for i in range(frames):
        img = np.roll(base, i, axis=1)
        if pixelate_from is not None and i >= pixelate_from:
            small = cv2.resize(img, (36, 64), interpolation=cv2.INTER_AREA)
            img = cv2.resize(small, (360, 640), interpolation=cv2.INTER_NEAREST)
        writer.write(img)
    writer.release()


def test_pixelation_detected_with_start_time(tmp_path):
    video = tmp_path / 'pix.mp4'
    _texture_video(video, pixelate_from=28)
    result = detect_pixelation(video)
    assert result['flagged'] is True and 2.5 <= result['first_at'] <= 3.2
    clean = tmp_path / 'clean.mp4'
    _texture_video(clean)
    assert detect_pixelation(clean)['flagged'] is False


# --- RULE02 -------------------------------------------------------------------
def test_infant_restriction_by_category_and_age():
    assert max_age_months('Hộp 900g, 0-6 tháng') == 6 and max_age_months('1-3 tuổi') == 36
    assert advertising_restriction('infant_formula', '0-6 tháng')['reason'] == 'infant_formula_under_24m'
    assert advertising_restriction('infant_formula', '')['reason'] == 'infant_formula_age_unknown'
    assert advertising_restriction('infant_formula', '3-6 tuổi') is None
    assert advertising_restriction('feeding_bottle_teat', '')['reason'] == 'feeding_bottle_teat'
    assert advertising_restriction('general', '') is None


def test_breastmilk_comparison_on_real_and_lossy_text():
    assert breastmilk_comparison('Giống hệt ti mẹ 100%') == 'gionghettime'
    assert breastmilk_comparison('Ging ht ti m 100%') == 'gionghettime'      # VID_LOI20 OCR
    assert breastmilk_comparison('Thay thế sữa mẹ hoàn hảo') == 'thaythesuame'
    for clean in ('Không thay thế sữa mẹ', 'Núm ti mềm, chống sặc', 'Sữa mẹ là thức ăn tốt nhất cho trẻ',
                  'Bình sữa mềm mại', 'Sữa tắm gội toàn thân'):
        assert breastmilk_comparison(clean) is None, clean
    assert has_age_information(['Hp 900g, 0-6 tháng']) and not has_age_information(['Sa bt', '450.000d'])


# --- RULE06 parsing -----------------------------------------------------------------
def test_text_issues_drop_self_contradicting_orientation_and_weak_items():
    raw = json.dumps({'text_issues': [
        {'text': 'Comable Bomonlas', 'frame': 2, 'problem': 'ký tự lộn xộn, vô nghĩa', 'confidence': 0.95},
        {'text': "Lavin'skin", 'frame': 1, 'problem': 'chữ in rõ, ổn định, không lỗi', 'confidence': 0.95},
        {'text': 'PureSoft', 'frame': 3, 'problem': 'bị ngược khi mở nắp', 'confidence': 0.95},
        {'text': 'Natual', 'frame': 1, 'problem': 'sai chính tả', 'confidence': 0.85},
        {'text': 'Comable Bomonlas', 'frame': 4, 'problem': 'lặp lại', 'confidence': 0.95}]})
    found = parse_text_issues(raw, [0.5, 2.0, 4.0, 6.0, 7.5])
    assert [(f['text'], f['timestamp']) for f in found] == [('Comable Bomonlas', 2.0)]


# --- registry + API -----------------------------------------------------------------
def test_registry_maps_codes_and_marks_legal_review():
    assert rule_for('PRICE-01')['rule_id'] == 'RULE03'
    assert rule_for('INFANT-01')['review_priority'] == 'Rất cao'
    assert rule_for('VIS-04')['rule_id'] == 'RULE07' and rule_for('TEXT-03')['rule_id'] == 'RULE06'
    assert rule_for('VIS-SCREEN') is None
    assert all(rule_for(c)['legal_review_required'] for c in ('CLAIM-01', 'AI-LABEL-01'))
    assert set(RULES) == {f'RULE{i:02d}' for i in range(1, 11)}


def test_infant_product_flagged_with_rule_and_category_persisted(tmp_path, monkeypatch):
    import backend
    monkeypatch.setattr(backend, 'DB', tmp_path / 'verifai.sqlite3')
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    monkeypatch.setattr(backend, 'UPLOAD', tmp_path / 'uploads')
    monkeypatch.setattr(backend, 'FRAMES', tmp_path / 'frames')
    monkeypatch.setattr(backend, 'OCR_SCAN_MODE', 'adaptive')
    monkeypatch.setenv('OCR_ENABLED', '1')
    backend.UPLOAD.mkdir(); backend.FRAMES.mkdir(); backend.init()
    monkeypatch.setattr(backend, 'frame_ocr', lambda frame: ([('NutriGrow', 0.99), ('Ging ht ti m 100%', 0.97)], 'ok'))
    monkeypatch.setattr(backend, 'transcribe', lambda path: ([], 'ok'))
    client = TestClient(backend.app)
    r = client.post('/api/products', json={'sku': 'MILK', 'name': 'Sữa bột', 'brand': 'NutriGrow', 'price': 450000,
                                          'claims': [], 'banned': [], 'category': 'infant_formula',
                                          'target_age': '0-6 tháng', 'reference_status': 'test_reference_approved',
                                          'reference_note': 'test'})
    assert r.status_code == 200, r.text
    pid = r.json()['id']
    assert client.get(f'/api/products/{pid}').json()['category'] == 'infant_formula'
    assert client.post('/api/products', json={'sku': 'BAD', 'name': 'x', 'category': 'drink'}).status_code == 422
    video = tmp_path / 'v.mp4'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), 10, (128, 80))
    for _ in range(20):
        writer.write(np.full((80, 128, 3), 120, dtype=np.uint8))
    writer.release()
    with video.open('rb') as stream:
        jid = client.post('/api/jobs', data={'product_id': pid, 'rights': 'self_created'},
                          files={'file': ('v.mp4', stream, 'video/mp4')}).json()['id']
    for _ in range(300):
        job = client.get('/api/jobs/' + jid).json()
        if job['status'] in ('completed', 'failed'):
            break
        time.sleep(.025)
    assert job['status'] == 'completed', job['details']
    codes = {f['code']: f for f in job['findings']}
    assert codes['INFANT-01']['rule']['rule_id'] == 'RULE02'
    assert codes['INFANT-02']['severity'] == 'high'           # strong OCR evidence
    assert 'INFANT-03' in codes                                # no age shown in the video
    assert job['details']['product_truth_snapshot']['category'] == 'infant_formula'
    assert client.get('/api/rules').json()['rules']['RULE02']['review_priority'] == 'Rất cao'
