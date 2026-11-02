"""Videos without an audio track: ASR is complete with zero speech, not an error."""
import cv2
import numpy as np

from verifai_core import perception


def _silent_video(path):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), 10, (64, 48))
    for _ in range(10):
        writer.write(np.zeros((48, 64, 3), dtype=np.uint8))
    writer.release()


def test_video_without_audio_track_is_detected(tmp_path):
    video = tmp_path / 'silent.mp4'
    _silent_video(video)
    assert perception.has_audio_stream(video) in (False, None)  # None only if PyAV missing


def test_asr_returns_ok_without_calling_whisper_when_no_audio(tmp_path, monkeypatch):
    monkeypatch.setattr(perception, 'asr_installed', lambda: True)
    monkeypatch.setattr(perception, 'has_audio_stream', lambda path: False)
    service = perception.ASRService()
    assert service.extract(tmp_path / 'x.mp4') == ([], 'ok')
    assert service.model is None
