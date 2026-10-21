"""Measure local OCR/ASR latency on a real video; never uploads content.

Example:
  python scripts/benchmark_perception.py --video "C:\\Videos\\VID_LOI01.mp4" --ocr-frames 12 --output benchmark.json

First run includes lazy model loading/downloads; warm run reuses model memory.
Tests remain fast and do not run this script automatically.
"""
from __future__ import annotations
import argparse
import json
import platform
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verifai_core.perception import ASRService, OCRService


def sample_video(path: Path, count: int):
    import cv2
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError('OpenCV could not open video')
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    indices = [round(i * max(0, total - 1) / max(1, count - 1)) for i in range(min(count,total))] if total > 0 else []
    frames=[]
    for idx in dict.fromkeys(indices):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue
        scale=min(1.0, 800/max(frame.shape[:2]))
        frame=cv2.resize(frame,(max(1,int(frame.shape[1]*scale)),max(1,int(frame.shape[0]*scale))))
        frames.append((round(idx/fps,2),frame))
    cap.release()
    return frames, {'fps':round(float(fps),2),'duration_seconds':round(total/fps,2) if fps else None,'frames_total':total}


def summarize(times: list[float]) -> dict:
    values=sorted(times)
    return {'samples':len(values),'total_seconds':round(sum(values),3),
            'avg_seconds':round(sum(values)/len(values),3) if values else None,
            'median_seconds':round(values[len(values)//2],3) if values else None,
            'max_seconds':round(max(values),3) if values else None}


def run(video: Path, ocr_frames: int=12, warm_runs: int=1, ocr: bool=True, asr: bool=True) -> dict:
    if not video.is_file():
        raise FileNotFoundError(video)
    if not ocr and not asr:
        raise ValueError('Both OCR and ASR are disabled')
    result={'file':video.name,'size_mb':round(video.stat().st_size/(1024*1024),2),
            'system':{'python':platform.python_version(),'os':platform.system(),'processor':platform.processor()},
            'ocr':None,'asr':None}
    frames=[]
    if ocr:
        start=time.perf_counter()
        frames,metadata=sample_video(video,ocr_frames)
        result['video']=metadata
        result['decode_seconds']=round(time.perf_counter()-start,3)
        if not frames:
            raise RuntimeError('No frames decoded')
        service=OCRService()
        for repetition in range(1+warm_runs):
            durations=[];lines=0;state='not_started'
            for at,frame in frames:
                start=time.perf_counter()
                extracted,state=service.extract(frame)
                durations.append(time.perf_counter()-start)
                lines+=len(extracted)
                if state!='ok':break
            report={'run':'cold' if repetition==0 else f'warm_{repetition}',
                    'status':state,'text_lines':lines,**summarize(durations)}
            if result['ocr'] is None:result['ocr']=[]
            result['ocr'].append(report)
            print('OCR:',json.dumps(report,ensure_ascii=False),flush=True)
            if state!='ok':break
    if asr:
        service=ASRService()
        for repetition in range(1+warm_runs):
            start=time.perf_counter()
            segments,state=service.extract(video)
            report={'run':'cold' if repetition==0 else f'warm_{repetition}',
                    'status':state,'segments':len(segments),
                    'seconds':round(time.perf_counter()-start,3)}
            if result['asr'] is None:result['asr']=[]
            result['asr'].append(report)
            print('ASR:',json.dumps(report,ensure_ascii=False),flush=True)
            if state!='ok':break
    return result


def main(argv=None):
    ap=argparse.ArgumentParser(description='Measure local video OCR/ASR cold/warm speed')
    ap.add_argument('--video',type=Path,required=True)
    ap.add_argument('--ocr-frames',type=int,default=12)
    ap.add_argument('--warm-runs',type=int,default=1)
    ap.add_argument('--ocr-only',action='store_true')
    ap.add_argument('--asr-only',action='store_true')
    ap.add_argument('--output',type=Path,default=None)
    args=ap.parse_args(argv)
    if not 1<=args.ocr_frames<=60 or not 0<=args.warm_runs<=3:
        ap.error('--ocr-frames must be 1..60 and --warm-runs must be 0..3')
    if args.ocr_only and args.asr_only:
        ap.error('--ocr-only and --asr-only are mutually exclusive')
    print('Model weights may download on first use. Video is processed locally.',flush=True)
    try:
        report=run(args.video,args.ocr_frames,args.warm_runs,not args.asr_only,not args.ocr_only)
    except Exception as exc:
        print('Benchmark failed:',exc,file=sys.stderr)
        return 1
    if args.output:
        args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        print('Saved:',args.output,flush=True)
    print('RESULT:',json.dumps(report,ensure_ascii=False),flush=True)
    return 0 if all(item['status']=='ok' for key in ('ocr','asr') for item in (report[key] or [])) else 1


if __name__=='__main__':raise SystemExit(main())
