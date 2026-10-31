"""No-network tests for full-frame OCR and native Gemini video understanding."""
import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from verifai_core.video_ocr import iter_all_video_frames
from verifai_core.video_understanding import (
    VideoUnderstandingResult, analyze_native_video, video_prompt,
)


def _video(path, frame_count=18, fps=6):
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),
                           fps,(160,96))
    assert writer.isOpened(), 'Test OpenCV video encoder unavailable'
    for i in range(frame_count):
        frame=np.full((96,160,3),i*10%255,dtype=np.uint8)
        writer.write(frame)
    writer.release()


def test_full_frame_ocr_decoder_does_not_truncate_to_four_or_sixty(tmp_path):
    path=tmp_path/'all.avi'
    _video(path,frame_count=72,fps=12)
    frames=list(iter_all_video_frames(path))
    assert len(frames)==72
    assert frames[0]['source_frame_index']==0
    assert frames[-1]['source_frame_index']==71
    assert frames[-1]['at']==round(71/12,3)
    assert frames[-1]['frame']=='ocr-00000071.jpg'
    assert all(f['image'].shape==(96,160,3) for f in frames)


def test_frames_are_resized_and_timestamps_from_video_fps(tmp_path):
    path=tmp_path/'resized.avi'
    _video(path,frame_count=6,fps=3)
    frames=list(iter_all_video_frames(path,long_edge=80))
    assert len(frames)==6
    assert max(frames[0]['image'].shape[:2])<=80
    assert frames[3]['at']==1.0


def test_video_prompt_includes_timeline_and_no_fake_product_certification():
    prompt=video_prompt({
        'sku':'SKU001','name':'BabyGentle','brand':'BabyGentle',
        'variant':'200ml','reference_status':'unverified',
        'claims':['Dịu nhẹ'],'banned':[],
    })
    assert 'VIDEO QUẢNG CÁO LIÊN TỤC' in prompt
    assert 'timestamp_seconds' in prompt
    assert 'reference_status' in prompt
    assert 'unverified' in prompt
    assert 'không phải bằng chứng' in prompt.lower()
    assert 'timeline_summary' in prompt


def test_native_video_uses_original_video_waits_for_processing_and_deletes(tmp_path,monkeypatch):
    pytest.importorskip('google.genai')
    path=tmp_path/'clip.mp4'
    path.write_bytes(b'fixture-video-for-fake-client')
    calls=[]
    pending=SimpleNamespace(name='files/clip123',state=SimpleNamespace(name='PROCESSING'),
                            uri='https://files.fake/clip123',mime_type='video/mp4')
    ready=SimpleNamespace(name='files/clip123',state=SimpleNamespace(name='ACTIVE'),
                          uri='https://files.fake/clip123',mime_type='video/mp4')
    class Files:
        def upload(self,**kwargs):
            calls.append(('upload',kwargs))
            return pending
        def get(self,**kwargs):
            calls.append(('get',kwargs))
            return ready
        def delete(self,**kwargs):
            calls.append(('delete',kwargs))
    class Models:
        def generate_content(self,**kwargs):
            calls.append(('infer',kwargs))
            return SimpleNamespace(text=json.dumps({
                'summary':'Video có chuyển cảnh', 'timeline_summary':'0s: chai; 2s: chữ 99.000đ',
                'observations':[{
                    'timestamp_seconds':2.0, 'description':'Overlay giá 99.000đ',
                    'category':'visible_text','confidence':0.92,
                }],
                'issues':[{
                    'timestamp_seconds':2.0,'code':'SKU-01',
                    'description':'Tên thương hiệu lệch trên bao bì',
                    'visible_basis':'Tên in rõ khác với brand tham chiếu',
                    'confidence':0.8,
                }],
            },ensure_ascii=False))
    fake=SimpleNamespace(files=Files(),models=Models())
    adapter=SimpleNamespace(_get_client=lambda:fake,model='gemini-3.5-flash-lite')
    monkeypatch.setattr('verifai_core.video_understanding.time.sleep',lambda _:None)
    result=analyze_native_video(adapter,path,{'sku':'SKU001','brand':'BabyGentle'})
    assert isinstance(result,VideoUnderstandingResult)
    assert result.observations[0].timestamp_seconds==2.0
    assert result.issues[0].code=='SKU-01'
    assert [x[0] for x in calls]==['upload','get','infer','delete']
    assert calls[0][1]['file']==str(path)
    assert calls[2][1]['contents'][0].name=='files/clip123'
    assert 'timeline_summary' in calls[2][1]['contents'][1]


def test_native_video_cleans_up_failed_request(tmp_path,monkeypatch):
    pytest.importorskip('google.genai')
    from verifai_core.vlm import VLMError
    path=tmp_path/'fail.mp4'
    path.write_bytes(b'demo')
    touched=[]
    uploaded=SimpleNamespace(name='files/fail123',state=SimpleNamespace(name='ACTIVE'))
    class F:
        def upload(self,**kwargs):return uploaded
        def delete(self,**kwargs):touched.append(kwargs['name'])
    class M:
        def generate_content(self,**kwargs):raise RuntimeError('model unavailable')
    obj=SimpleNamespace(files=F(),models=M())
    adapter=SimpleNamespace(_get_client=lambda:obj,model='gemini-3.5-flash-lite')
    with pytest.raises(VLMError,match='Gemini video'):
        analyze_native_video(adapter,path,{})
    assert touched==['files/fail123']


def test_backend_routes_new_modes_and_keeps_video_evidence_separate():
    from pathlib import Path
    backend=(Path(__file__).resolve().parents[1]/'backend.py').read_text(encoding='utf-8')
    assert "OCR_SCAN_MODE=os.environ.get('OCR_SCAN_MODE','all')" in backend
    assert 'iter_all_video_frames(path)' in backend
    assert "VLM_INPUT_MODE','video'" in backend
    assert 'analyze_native_video(client,path,p)' in backend
    assert "'timestamp_source':'model_reported'" in backend
    assert "('vlm_observation','vlm_video_observation')" in backend
