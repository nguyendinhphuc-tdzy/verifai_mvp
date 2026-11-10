"""Print OCR/ASR installation status; --live initializes local OCR/Whisper models.

The live test may download pretrained model weights on first execution.
No result here constitutes an evaluation of error-detection performance.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verifai_core.envfile import load_env_file
# Same configuration as the app: read ./.env (variables already set in the shell win).
load_env_file(Path(__file__).resolve().parents[1] / '.env')
from verifai_core.perception import ASRService, OCRService, asr_installed, ocr_installed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--live', action='store_true', help='load OCR and ASR models (may download weights)')
    ap.add_argument('--video', type=Path, help='video or audio path to transcribe when --live')
    args = ap.parse_args(argv)
    for name in ('paddlepaddle', 'paddleocr', 'faster-whisper'):
        try:
            print(f'{name}: {importlib.metadata.version(name)}')
        except importlib.metadata.PackageNotFoundError:
            print(f'{name}: NOT INSTALLED')
    print('OCR installed:', ocr_installed())
    print('ASR installed:', asr_installed())
    if not args.live:
        return 0
    import cv2
    import numpy as np
    frame = np.full((180, 600, 3), 255, dtype=np.uint8)
    cv2.putText(frame, 'Gia 149.000 VND', (20, 100), cv2.FONT_HERSHEY_SIMPLEX,
                1.3, (0, 0, 0), 3, cv2.LINE_AA)
    lines, status = OCRService().extract(frame)
    print('OCR live:', status, lines[:10])
    if args.video:
        if not args.video.is_file():
            print('Video/audio not found:', args.video)
            return 2
        segments, state = ASRService().extract(args.video)
        print('ASR live:', state, segments[:8])
        return 0 if status == 'ok' and state == 'ok' else 1
    print('ASR live test skipped. Use --video path/to/video.mp4 to run transcription.')
    return 0 if status == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
