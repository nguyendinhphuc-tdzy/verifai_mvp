"""Gemini multi-frame colour-consistency check (VID_LOI31/34, 04/11/2026)."""
import json

import cv2
import numpy as np

from verifai_core.color_consistency import parse_inconsistencies, sample_frames


def test_parse_keeps_confident_changes_and_maps_frame_to_time():
    times = [0.6, 2.4, 4.1, 5.8, 7.5]
    raw = json.dumps({'inconsistencies': [
        {'object': 'sữa tắm', 'from_frame': 1, 'to_frame': 5, 'from_color': 'trắng',
         'to_color': 'xanh dương', 'visible_basis': 'dòng sữa trên tay màu xanh', 'confidence': 0.95},
        {'object': 'nền', 'from_frame': 1, 'to_frame': 2, 'from_color': 'xám',
         'to_color': 'trắng', 'visible_basis': 'ánh sáng', 'confidence': 0.4},
        {'object': 'hộp', 'to_frame': 99, 'from_color': 'xanh', 'to_color': 'hồng',
         'visible_basis': 'thân hộp', 'confidence': 2},
        'garbage']})
    found = parse_inconsistencies(raw, times)
    assert [(f['object'], f['timestamp'], f['confidence']) for f in found] == \
        [('sữa tắm', 7.5, 0.95), ('hộp', 7.5, 1.0)]


def test_sample_frames_spreads_over_video(tmp_path):
    path = tmp_path / 'v.mp4'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 10, (320, 180))
    for _ in range(64):  # 6.4 s, like VID_GOC05 (a fixed 7 s frame would not exist)
        writer.write(np.full((180, 320, 3), 100, dtype=np.uint8))
    writer.release()
    images, times = sample_frames(path, 5)
    assert len(images) == 5 and times[0] < 1 and 5.5 < times[-1] < 6.4


def test_color_change_becomes_vis02_reviewer_candidate(tmp_path, monkeypatch):
    import test_unknown_frame_count as helper
    import backend
    monkeypatch.setenv('VLM_COLOR_CHECK', '1')
    calls = []

    def fake_check(client, model, path):
        calls.append(str(path))
        return {'status': 'ok', 'times': [0.2, 1.0, 1.8, 2.6],
                'issues': [{'object': 'sữa tắm', 'from_color': 'trắng', 'to_color': 'xanh dương',
                            'visible_basis': 'dòng sữa trên tay', 'confidence': 0.95, 'timestamp': 2.6}]}
    monkeypatch.setattr(backend, 'check_color_consistency', fake_check)

    class Client:
        model = 'gemini-test'
    monkeypatch.setattr(backend._ProductionGeminiVLM, '_get_client', lambda self: Client(), raising=False)
    job = helper._run(tmp_path, monkeypatch)
    assert job['status'] == 'completed', job['details']
    assert len(calls) == 1
    vis = [f for f in job['findings'] if f['code'] == 'VIS-02']
    assert len(vis) == 1 and vis[0]['severity'] == 'medium' and vis[0]['source'] == 'vlm_color_check'
    assert job['details']['vlm']['color_check']['status'] == 'ok'
    assert job['decision'] != 'Regenerate'  # Gemini-only finding never forces Regenerate
    assert 'Không nhất quán hình ảnh' in job['label_suggestion']['error_types']


def test_color_check_failure_is_recorded_not_fatal(tmp_path, monkeypatch):
    import test_unknown_frame_count as helper
    import backend
    monkeypatch.setenv('VLM_COLOR_CHECK', '1')

    def boom(client, model, path):
        raise RuntimeError('503 UNAVAILABLE')
    monkeypatch.setattr(backend, 'check_color_consistency', boom)
    monkeypatch.setattr(backend._ProductionGeminiVLM, '_get_client', lambda self: object(), raising=False)
    job = helper._run(tmp_path, monkeypatch)
    assert job['status'] == 'completed'
    assert job['details']['vlm']['color_check']['status'] == 'error'
    assert job['details']['coverage']['vlm'] == 'ok'
