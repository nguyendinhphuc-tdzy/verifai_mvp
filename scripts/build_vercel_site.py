"""Build the static team website for Vercel from the app's home page.

    python scripts/build_vercel_site.py

Reads static/home.html and static/one-pager.html, inlines every local asset
(images as data URIs, sfx.js and leaves.js as inline scripts) and writes
site/index.html + site/one-pager.html. Each page is a single self-contained
file. Links to the local app (/app) become "Xem video demo"; documents that
the team website must list come from site/links.json (empty = "Đang cập nhật").
Re-run after editing home.html, one-pager.html or links.json.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'static'
SITE = ROOT / 'site'

# (section no. in the team sheet, title, description, [(target, label)]).
# target "link:<key>" = external URL from links.json; anything else = page anchor.
HS = 'ho-so.html'
DOC_CARDS = [
    ('07', 'Video demo', 'Video minh họa VerifAI kiểm tra một video quảng cáo, từ lúc tải lên đến quyết định của người duyệt.',
     [('link:demo_video', 'Xem video demo'), (HS + '#demo', 'Chức năng prototype')]),
    ('06', 'Mã nguồn', 'Repository của prototype, cấu trúc mã nguồn và các thành phần AI.',
     [('link:repository', 'Mở repository'), (HS + '#ma-nguon', 'Kiến trúc kỹ thuật')]),
    ('04', 'Định hướng sản phẩm', 'Product Vision, người dùng mục tiêu, điểm khác biệt và kịch bản demo kiểm tra video.',
     [(HS + '#dinh-huong', 'Xem chi tiết')]),
    ('05', 'Quản lý dự án', 'Sprint plan, mốc thời gian, Product Backlog, ma trận RACI và lịch họp nhóm.',
     [(HS + '#quan-ly', 'Xem chi tiết')]),
    ('08', 'Tài liệu AI', 'Các biểu mẫu AI bản cuối kỳ, thống nhất với kết quả đánh giá trên 80 video.',
     [(HS + '#ai-canvas', 'AI Canvas'), (HS + '#project-charter', 'Project Charter'), (HS + '#data-audit', 'Data Audit'),
      (HS + '#danh-gia', 'Kết quả đánh giá'), (HS + '#risk-register', 'AI Risk Register'), (HS + '#system-card', 'AI System Card')]),
    ('03', 'Thỏa thuận nhóm', 'Thỏa thuận thành lập nhóm và các nguyên tắc làm việc đã thống nhất.',
     [(HS + '#thoa-thuan', 'Xem chi tiết')]),
]

DOC_ICON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
            'stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/>'
            '<path d="M14 3v5h5M9 13h6M9 17h4"/></svg>')

DOCS_CSS = """<style>
.doclinks{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}
.doclinks a{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;border-radius:999px;border:1.5px solid currentColor;font-size:.85rem;font-weight:700;color:var(--label,#1f7a67);text-decoration:none}
.doclinks a:hover{background:rgba(232,182,74,.18)}
.doclinks a.pending{border-style:dashed;opacity:.6;pointer-events:none}
.doc-no{display:block;font-size:.72rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;opacity:.7;margin-bottom:4px}
</style>"""

# Fills [data-link] anchors from window.VF_LINKS; empty links stay on the page as "Đang cập nhật".
LINKS_JS = """<script>
(() => {
  const L = window.VF_LINKS || {};
  document.querySelectorAll('[data-link]').forEach(a => {
    const url = (L[a.dataset.link] || '').trim();
    if (url) { a.href = url; a.target = '_blank'; a.rel = 'noopener'; a.classList.remove('pending'); a.removeAttribute('aria-disabled'); }
    else {
      a.title = 'Đang cập nhật';
      const chip = a.closest('.doclinks'), btn = a.classList.contains('btn');
      if (chip || btn) { a.classList.add(chip ? 'pending' : 'pending-link'); a.setAttribute('aria-disabled', 'true'); a.removeAttribute('href'); a.textContent = a.textContent.replace(/\s*→\s*$/, '') + ' (đang cập nhật)'; }
    }
  });
})();
</script>"""


def replace(text: str, old: str, new: str, count: int | None = 1) -> str:
    found = text.count(old)
    if (count is None and found == 0) or (count is not None and found != count):
        raise SystemExit(f'Expected {count or ">=1"} x {old[:70]!r}, found {found}. home.html changed: update the build script.')
    return text.replace(old, new)


def data_uri(path: Path) -> str:
    return 'data:image/webp;base64,' + base64.b64encode(path.read_bytes()).decode('ascii')


def inline_assets(html: str) -> str:
    for img in sorted((STATIC / 'home').glob('*.webp')):
        html = html.replace(f'/static/home/{img.name}', data_uri(img))
    for js in ('sfx.js', 'leaves.js'):
        tag = f'<script src="/static/{js}"></script>'
        if tag in html:
            code = (STATIC / js).read_text(encoding='utf-8')
            assert '</script' not in code.lower(), js
            html = html.replace(tag, f'<script>\n{code}\n</script>')
    assert '/static/' not in html, 'unhandled /static/ reference'
    return html


def esc(s: str) -> str:
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def docs_section() -> str:
    cards = []
    for i, (no, title, desc, links) in enumerate(DOC_CARDS):
        a = ''.join(f'<a data-link="{t[5:]}" href="#ho-so">{esc(label)}</a>' if t.startswith('link:')
                    else f'<a href="{t}">{esc(label)}</a>' for t, label in links)
        cards.append(f'<article class="card spot reveal" style="--d:{i % 3 * .08:.2f}s"><div class="ic">{DOC_ICON}</div>'
                     f'<span class="doc-no">Mục {no}</span><h3>{esc(title)}</h3><p>{esc(desc)}</p>'
                     f'<div class="doclinks">{a}</div></article>')
    return f"""  <!-- PROJECT DOCUMENTS (website only) -->
  <section class="section" id="ho-so">
    <div class="wrap">
      <div class="head reveal">
        <span class="eyebrow">06 · Hồ sơ dự án</span>
        <h2>Tài liệu <span class="grad">dự án.</span></h2>
        <p>Video demo, mã nguồn, tài liệu quản lý dự án và tài liệu AI của nhóm. Xem toàn bộ tại <a href="ho-so.html" style="color:inherit;font-weight:700">trang Hồ sơ dự án</a>, hoặc bản <a href="one-pager.html" style="color:inherit;font-weight:700">one-pager</a>.</p>
      </div>
      <div class="bento">
        {''.join(cards)}
      </div>
    </div>
  </section>

"""


def links_script(links: dict) -> str:
    clean = {k: v for k, v in links.items() if not k.startswith('_')}
    return '<script>window.VF_LINKS=' + json.dumps(clean, ensure_ascii=False) + ';</script>\n' + LINKS_JS


def build_home(links: dict) -> str:
    h = (STATIC / 'home.html').read_text(encoding='utf-8')
    # Entry points into the local app become the demo video.
    h = replace(h, '<a class="only-mobile" href="/app" data-enter>Vào ứng dụng →</a>',
                '<a class="only-mobile" data-link="demo_video" href="#ho-so">Xem video demo →</a>')
    h = replace(h, 'href="/app" data-enter>Vào ứng dụng\n', 'data-link="demo_video" href="#ho-so">Xem video demo\n')
    h = replace(h, 'href="/app" data-enter>Bắt đầu kiểm duyệt', 'data-link="demo_video" href="#ho-so">Xem video demo')
    h = replace(h, '<h3>Dùng thử với video của bạn</h3>', '<h3>Xem VerifAI hoạt động</h3>')
    h = replace(h, '<p>Tải một video lên để xem các điểm VerifAI đánh dấu cần kiểm tra.</p>',
                '<p>Video demo minh họa cách VerifAI đánh dấu các điểm cần kiểm tra trong một video quảng cáo.</p>')
    h = replace(h, 'href="/app" data-enter>Phân tích video', 'data-link="demo_video" href="#ho-so">Xem video demo')
    h = replace(h, '<a href="/app" data-enter>Vào ứng dụng</a>', '<a data-link="demo_video" href="#ho-so">Video demo</a>')
    assert 'href="/app"' not in h, 'a link to /app is left'
    # The illustrated app window shows a local address; neutral label on the public site.
    h = replace(h, '<div class="addr">127.0.0.1:8000/app</div>', '<div class="addr">VerifAI · Duyệt video</div>')
    h = replace(h, 'href="/one-pager"', 'href="one-pager.html"', count=None)
    # Documents section before the team, listed in the nav; team becomes section 07.
    h = replace(h, '      <a href="#nhom">Nhóm</a>', '      <a href="#ho-so">Hồ sơ</a>\n      <a href="#nhom">Nhóm</a>')
    h = replace(h, '  <!-- TEAM -->', docs_section() + '  <!-- TEAM -->')
    h = replace(h, '<span class="eyebrow">06 · Nhóm</span>', '<span class="eyebrow">07 · Nhóm</span>')
    h = replace(h, '</head>', DOCS_CSS + '\n</head>')
    h = inline_assets(h)
    return replace(h, '</body>', links_script(links) + '\n</body>')


def build_one_pager(links: dict) -> str:
    p = (STATIC / 'one-pager.html').read_text(encoding='utf-8')
    p = replace(p, '<a class="back" href="/">', '<a class="back" href="index.html">')
    p = replace(p, '<a class="go" href="/app">Vào ứng dụng →</a>', '<a class="go" data-link="demo_video" href="index.html#ho-so">Xem video demo →</a>')
    assert 'href="/app"' not in p
    p = inline_assets(p)
    return replace(p, '</body>', links_script(links) + '\n</body>')


def build_dossier(links: dict) -> str:
    d = (ROOT / 'site_src' / 'ho-so.html').read_text(encoding='utf-8')
    d = inline_assets(d)
    return replace(d, '</body>', links_script(links) + '\n</body>')


def main():
    links = json.loads((SITE / 'links.json').read_text(encoding='utf-8'))
    unknown = {t[5:] for _, _, _, ls in DOC_CARDS for t, _ in ls if t.startswith('link:')} - set(links)
    if unknown:
        raise SystemExit(f'links.json is missing keys: {sorted(unknown)}')
    for name, html in (('index.html', build_home(links)), ('one-pager.html', build_one_pager(links)),
                       ('ho-so.html', build_dossier(links))):
        (SITE / name).write_text(html, encoding='utf-8', newline='\n')
        print(f'site/{name}: {len(html.encode("utf-8")) / 1024:.0f} KB')
    empty = [k for k, v in links.items() if not k.startswith('_') and not v.strip()]
    print(f'Links still empty ({len(empty)}): {", ".join(empty) or "none"}')


if __name__ == '__main__':
    main()
