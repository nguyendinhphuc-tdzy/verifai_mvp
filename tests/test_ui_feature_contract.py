"""The workspace UI must keep every backend feature reachable (merge of PR #29, 04/11/2026).

A UI redesign built on an older branch once dropped these controls without any
test failing. Each entry is a backend capability and the markup/JS that uses it.
"""
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / 'static'
INDEX = (STATIC / 'index.html').read_text(encoding='utf-8')

FEATURES = {
    'upload declares usage rights (Gemini gate)': ['id="rights"', "form.append('rights'"],
    'upload declares AI-generated (AI-LABEL-01)': ['id="aiGenerated"', "form.append('ai_generated'"],
    'product category and target age (RULE02)': ['id="productCategory"', 'name="target_age"',
                                                  "category:String(f.get('category')"],
    'change SKU after analysis': ['id="jobProductSelect"', 'async function changeJobProduct(',
                                  '/product`', 'renderJobProduct(d)'],
    'AI-suggested label, reviewer confirms': ['id="labelSuggestion"', 'id="acceptSuggestionBtn"',
                                              'function renderLabelSuggestion(', 'error_types:types'],
    'rule basis on each finding (RULE01-10)': ['f.rule.rule_id', 'f.rule.legal_basis'],
    'reviewer decision buttons': ["submitReview('Pass')", "submitReview('Needs Review')",
                                  "submitReview('Regenerate')"],
}


@pytest.mark.parametrize('feature', sorted(FEATURES))
def test_workspace_keeps_feature(feature):
    missing = [needle for needle in FEATURES[feature] if needle not in INDEX]
    assert not missing, f'{feature}: missing {missing}'


def test_rights_and_ai_flag_are_required_before_upload():
    submit = INDEX[INDEX.index("$('uploadForm').onsubmit"):]
    submit = submit[:submit.index("x.send(form)")]
    assert "if(!$('rights').value)" in submit and "if(!$('aiGenerated').value)" in submit


def test_home_and_workspace_routes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import backend
    client = TestClient(backend.app)
    home = client.get('/')
    assert home.status_code == 200 and 'href="/app"' in home.text
    app_page = client.get('/app')
    assert app_page.status_code == 200 and 'id="jobProductSelect"' in app_page.text
    assert client.get('/healthz').json() == {'ok': True}
    assert client.get('/api/rules').status_code == 200
