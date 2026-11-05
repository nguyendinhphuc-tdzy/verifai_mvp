"""Gemini rejects constrained response schemas (400); replies are clamped locally."""
import json

import pytest

from verifai_core.video_understanding import VideoUnderstandingWire, to_strict


def _schema_has_constraints(schema):
    text = json.dumps(schema)
    return any(k in text for k in ('"minLength"', '"maxLength"', '"maxItems"', '"minimum"', '"maximum"'))


def test_wire_schema_sent_to_gemini_has_no_constraints():
    assert not _schema_has_constraints(VideoUnderstandingWire.model_json_schema())


def test_reply_is_clamped_and_weak_issues_dropped():
    raw = json.dumps({
        'summary': 'x' * 1500, 'timeline_summary': '',
        'observations': [
            {'timestamp_seconds': -2, 'description': 'Chai sữa tắm', 'category': 'product', 'confidence': 1.4},
            {'timestamp_seconds': 1, 'description': 'ab', 'category': 'scene', 'confidence': .5}],
        'issues': [
            {'timestamp_seconds': 3.2, 'code': 'VIS-03', 'description': 'Logo bị méo',
             'visible_basis': 'Chữ MinniFeed trên thân bình giây 3', 'confidence': .8},
            {'timestamp_seconds': 4, 'code': 'VIS-01', 'description': 'Lạ', 'visible_basis': '', 'confidence': .9}],
    })
    result = to_strict(raw)
    assert len(result.summary) == 1000
    assert [o.timestamp_seconds for o in result.observations] == [0]
    assert result.observations[0].confidence == 1
    assert [i.code for i in result.issues] == ['VIS-03']


def test_invalid_reply_raises_value_error():
    with pytest.raises(ValueError):
        to_strict('[]')
