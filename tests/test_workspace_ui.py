"""Lightweight contract checks for the operational workspace.

These guard the API-wired UI against accidental ID/interaction regressions.
Browser layout and keyboard testing must still be performed before release.
"""
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "static" / "index.html"
STYLES = ROOT / "static" / "workspace.css"


class WorkspaceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.forms = []
        self.details = []
        self.sections = []
        self.links = []
        self.buttons = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get('id'):
            self.ids.append(a['id'])
            if tag == 'section':
                self.sections.append(a['id'])
        if tag == 'form':
            self.forms.append(a.get('id'))
        if tag == 'details':
            self.details.append(a.get('id'))
        if tag == 'link':
            self.links.append(a.get('href'))
        if tag == 'button':
            self.buttons.append(a)


def parse_workspace():
    p = WorkspaceParser()
    p.feed(HTML.read_text(encoding="utf-8"))
    return p


def test_task_first_navigation_and_real_forms():
    p = parse_workspace()
    assert len(p.ids) == len(set(p.ids)), "Duplicate DOM IDs cause wrong interactions"
    assert {'queue','analyze','overview','products','dataset','evaluation'} <= set(p.sections)
    assert {'uploadForm','productForm','datasetForm'} <= set(p.forms)
    assert '/static/workspace.css' in p.links
    assert {'analysisAdvanced','reviewEvidenceDetails','newProductDetails'} <= set(p.details)
    assert {'uploadProduct','videoFile','findings','player','reviewer',
            'jobDetail','queueStatus','queueTable','datasetTable',
            'officialEvaluation','metricCards','coverage','audits',
            'datasetDetail','datasetForm','evidenceFilter'} <= set(p.ids)


def test_required_inputs_and_hidden_diagnostics():
    html = HTML.read_text(encoding="utf-8")
    assert 'id="videoFile"' in html and 'type="file"' in html
    assert 'id="uploadProduct" required' in html
    assert 'id="analysisAdvanced"' in html
    assert 'id="reviewEvidenceDetails"' in html
    assert '<details class="detail-disclosure"><summary>Chi tiết kỹ thuật' in html
    assert '<section id="queue" class="section active"' in html
    assert 'id="jobDetail" class="hidden"' in html
    assert '<div class="hero">' not in html
    assert 'id="pipeline"' not in html
    assert 'window.addEventListener(\'popstate\'' in html
    assert 'function renderQueue()' in html
    assert "if(mode==='pending')" in html
    assert 'function submitReview(decision)' in html
    assert 'window.confirm(' not in html  # confirmation uses native confirm via real events


def test_accessibility_and_reduced_motion():
    p = parse_workspace()
    css = STYLES.read_text(encoding="utf-8")
    assert 'aria-label="Các khu vực làm việc"' in HTML.read_text(encoding="utf-8")
    assert 'aria-live="polite"' in HTML.read_text(encoding="utf-8")
    assert ':focus-visible' in css
    assert 'prefers-reduced-motion:reduce' in css
    assert '@media(max-width:560px)' in css
    assert all('data-target' in b or 'onclick' in b or 'type' in b for b in p.buttons)


def test_no_fake_interactions():
    html = HTML.read_text(encoding="utf-8")
    for endpoint in ('/api/jobs','/api/products','/api/dataset/import','/api/dataset/cases'):
        assert endpoint in html
    assert 'function flag(id,state)' in html
    assert 'function exportEvidence()' in html
    assert 'function selectDatasetCase(' in html
