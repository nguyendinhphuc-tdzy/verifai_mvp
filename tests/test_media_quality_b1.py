"""Deterministic Sprint B1 media/coverage tests: no OCR/ASR downloads."""
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from verifai_core.media_quality import (
    SAMPLING_VERSION, OCRCoverage, select_ocr_frames, video_stride,
)
from verifai_core.perception import unpack_asr_segments
from verifai_core.evidence import RawEvidence, normalize_evidence


@pytest.mark.parametrize(('fps', 'duration', 'expected'), [
    (25., 30., 25),
    (25., 180., 75),
    (30., 90., 45),
    (30., 0., 30),
    (1., 10., 1),
])
def test_video_stride_targets_denser_short_clips(fps, duration, expected):
    assert video_stride(fps, duration) == expected


@pytest.mark.parametrize('fps', [0, -2, float('inf'), float('nan')])
def test_stride_rejects_invalid_fps(fps):
    with pytest.raises(ValueError):
        video_stride(fps, 60)


def _frames(n=20, changed_at=None):
    frames = []
    for i in range(n):
        intensity = 180 if changed_at is not None and i == changed_at else 30
        frames.append({'at':float(i), 'frame':f'{i:03d}.jpg',
                       'image':np.full((80,128,3),intensity,dtype=np.uint8),
                       'blur':100})
    return frames


def test_uniform_sampler_preserves_endpoints_and_temporal_order():
    frames=_frames()
    out=select_ocr_frames(frames, 6, 'uniform')
    assert out[0] is frames[0] and out[-1] is frames[-1]
    assert len(out)==6
    assert [x['at'] for x in out] == sorted(x['at'] for x in out)
    assert not (set(map(id,out)) - set(map(id,frames)))


def test_hybrid_includes_novel_frame_while_preserving_anchors():
    frames=_frames(changed_at=7)
    selected=select_ocr_frames(frames,6,'hybrid')
    indices=[frames.index(x) if False else int(x['at']) for x in selected]
    assert 7 in indices
    assert indices[0]==0 and indices[-1]==19
    assert indices==sorted(indices) and len(set(indices))==6


def test_hybrid_keeps_uniform_distribution_on_static_clips():
    frames=_frames()
    assert [f['at'] for f in select_ocr_frames(frames,6,'hybrid')] == [
        f['at'] for f in select_ocr_frames(frames,6,'uniform')]


def test_sampler_handles_budget_and_invalid_mode():
    frames=_frames(3)
    assert select_ocr_frames(frames,0)==[]
    assert len(select_ocr_frames(frames,12))==3
    assert select_ocr_frames([],5)==[]
    assert len(select_ocr_frames(frames,1))==1
    with pytest.raises(ValueError):
        select_ocr_frames(frames,2,'random')


@pytest.mark.parametrize(('statuses','counts','expected'), [
    ([],[], 'skipped'),
    (['ok'],[0],'ok'),
    (['ok','ok'],[0,2],'ok'),
    (['ok','error: timeout'],[2,0],'partial'),
    (['not_installed','not_installed'],[0,0],'not_installed'),
    (['error: runtime'],[0],'error'),
    (['not_installed','error: runtime'],[0,0],'error'),
])
def test_ocr_coverage_is_truthful(statuses,counts,expected):
    meter=OCRCoverage()
    for status,count in zip(statuses,counts):
        meter.observe(status,count)
    snap=meter.snapshot()
    assert snap['status']==expected
    assert snap['attempted_frames']==len(statuses)
    assert snap['successful_frames']==statuses.count('ok')
    assert snap['text_lines']==sum(counts[i] for i,s in enumerate(statuses) if s=='ok')
    assert snap['text_observed']==(snap['text_lines']>0)
    assert len(snap['errors'])<=5


def test_coverage_errors_are_bounded_and_deduplicated():
    meter=OCRCoverage()
    for i in range(30):
        meter.observe('error: '+str(i%8),0)
    snap=meter.snapshot()
    assert snap['status']=='error'
    assert len(snap['errors'])==5
    assert snap['failed_frames']==30


def test_unpack_whisper_segments_with_end_and_noise():
    segments=[
        SimpleNamespace(start=1.1,end=3.4,text='  Giá  149k  '),
        SimpleNamespace(start=4.0,text=' Không được quảng cáo  '),
        SimpleNamespace(start=8,end=6,text='Bad end'),
        SimpleNamespace(start=-1,end=1,text='Impossible'),
        SimpleNamespace(start=float('nan'),text='Invalid'),
        SimpleNamespace(start=6,text='  '),
    ]
    result=unpack_asr_segments(iter(segments))
    assert result==[
        {'at':1.1,'end':3.4,'text':'Giá 149k','score':None},
        {'at':4.0,'text':'Không được quảng cáo','score':None},
        {'at':8.,'text':'Bad end','score':None},
    ]


def test_asr_evidence_preserves_segment_end_seconds():
    segments=[
        RawEvidence('wh0','asr',1.1,'Giá 149k',None,source_model='faster-whisper',
                    metadata={'segment_end_seconds':3.4}),
    ]
    result,_=normalize_evidence(segments)
    assert result[0].timestamp==1.1
    assert result[0].end_timestamp==3.4
    assert result[0].metadata['segment_end_seconds']==3.4


def test_invalid_segment_end_does_not_break_evidence():
    segments=[
        RawEvidence('wh0','asr',1.1,'Giá 149k',None,source_model='faster-whisper',
                    metadata={'segment_end_seconds':float('nan')}),
    ]
    result,_=normalize_evidence(segments)
    assert result[0].end_timestamp==1.1


def test_sampling_version_is_auditable():
    assert SAMPLING_VERSION.startswith('media-sampling-b1.')
