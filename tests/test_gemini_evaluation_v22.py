"""Offline tests: no Gemini API key and no video upload required."""
from types import SimpleNamespace
import json
from pathlib import Path
from verifai_core.evaluation import (
    calculate_metrics, predicted_error, sufficient_coverage, independent_consensus)
from verifai_core.gemini import GeminiVLM


def test_shared_metrics_and_excluded_findings():
    assert not predicted_error([{'code':'COVERAGE','severity':'medium'}])
    assert not predicted_error([{'code':'VIS-SCREEN','severity':'low'}])
    assert predicted_error([{'code':'PRICE-01','severity':'medium'}])
    assert sufficient_coverage({'vlm':'partial'})
    assert not sufficient_coverage({'ocr':'disabled','vlm':'error','asr':'disabled'})
    result = calculate_metrics([(True,True),(True,False),(False,True),(False,False)])
    assert (result['tp'],result['fp'],result['fn'],result['tn']) == (1,1,1,1)
    assert result['precision']==.5 and result['recall']==.5 and result['f1']==.5


def test_ground_truth_requires_distinct_annotators():
    assert independent_consensus([{'annotator':'A','label':'error'}]) is None
    assert independent_consensus([{'annotator':'A','label':'error'},{'annotator':'A','label':'error'}]) is None
    assert independent_consensus([{'annotator':'A','label':'error'},{'annotator':'B','label':'clean'}]) is None
    assert independent_consensus([{'annotator':'A','label':'error'},{'annotator':'B','label':'error'}]) == 'error'


def test_gemini_adapter_schema_and_pair_constraints(tmp_path, monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','test-not-real')
    frame=tmp_path/'000.jpg'
    frame.write_bytes(b'fake-image')
    response=SimpleNamespace(text=json.dumps({
        'summary':'demo', 'observations':[{'description':'Visible label Baby',
        'category':'visible_text','confidence':0.8,'frame_index':0}],
        'issues':[{'code':'VIS-02','description':'Change between frames',
        'visible_basis':'Same product label changed','confidence':0.9,'frame_index':0}]
    }))
    calls=[]
    class FakeModels:
        def generate_content(self,**kwargs):
            calls.append(kwargs)
            return response
    client=SimpleNamespace(models=FakeModels())
    vlm=GeminiVLM(client=client)
    product={'sku':'A','name':'Baby','brand':'B','claims':[],'banned':[]}
    out=vlm.analyze([frame],product,'single')
    assert len(calls)==1 and calls[0]['model']=='gemini-3.8-flash'
    assert out.issues==[]  # temporal issue cannot come from single frame
    assert out.observations[0].description=='Visible label Baby'
