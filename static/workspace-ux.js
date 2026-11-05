/* VerifAI workspace UX layer.
   Loaded before the main inline script: it only defines helpers and wires
   DOM listeners. It reads the main script's globals (jobs, products, selected,
   currentJob, poll, openTab, showJob, refreshAll, submitReview, seek, ...)
   at call time, never at load time. */
(() => {
  const q = id => document.getElementById(id);
  const html = document.documentElement;
  const mobile = () => matchMedia('(max-width:870px)').matches;
  const store = {
    get(k) { try { return localStorage.getItem(k) || ''; } catch (_) { return ''; } },
    set(k, v) { try { v ? localStorage.setItem(k, v) : localStorage.removeItem(k); } catch (_) {} }
  };
  const norm = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd').replace(/Đ/g, 'D').toLowerCase();
  const isMac = /Mac|iPhone|iPad/i.test(navigator.platform || navigator.userAgent);
  document.querySelectorAll('.modkey').forEach(el => { el.textContent = isMac ? '⌘K' : 'Ctrl K'; });

  /* ---------- Sidebar: collapse (desktop) / drawer (mobile) ---------- */
  function syncToggle() {
    const c = html.classList.contains('side-collapsed');
    const b = q('sideToggle');
    if (!b) return;
    const label = c ? 'Mở rộng menu' : 'Thu gọn menu';
    b.setAttribute('aria-expanded', String(!c));
    b.setAttribute('aria-label', label);
    b.title = label + ' ( [ )';
  }
  function setCollapsed(c) {
    html.classList.toggle('side-collapsed', c);
    store.set('vfSide', c ? 'collapsed' : 'open');
    syncToggle();
  }
  function drawer(open) {
    html.classList.toggle('drawer-open', open);
    q('sideScrim').hidden = !open;
    q('menuOpen')?.setAttribute('aria-expanded', String(open));
    if (open) requestAnimationFrame(() => document.querySelector('#nav button.active, #nav button')?.focus());
  }
  window.toggleSide = () => mobile() ? drawer(!html.classList.contains('drawer-open')) : setCollapsed(!html.classList.contains('side-collapsed'));
  window.openDrawer = () => drawer(true);
  window.closeDrawer = () => drawer(false);
  document.querySelectorAll('#nav button[data-target]').forEach(b => b.addEventListener('click', () => { if (mobile()) drawer(false); }));
  addEventListener('resize', () => { if (!mobile() && html.classList.contains('drawer-open')) drawer(false); });
  syncToggle();

  /* ---------- Light / dark theme (remembered on this device) ---------- */
  const themeBtn = q('themeToggle');
  const syncTheme = () => {
    const dark = html.dataset.theme === 'dark';
    if (themeBtn) { themeBtn.textContent = dark ? '☀' : '☾'; themeBtn.title = dark ? 'Chuyển sang chế độ sáng' : 'Chuyển sang chế độ tối'; themeBtn.setAttribute('aria-pressed', String(dark)); }
  };
  window.toggleTheme = () => {
    const dark = html.dataset.theme !== 'dark';
    if (dark) html.dataset.theme = 'dark'; else delete html.dataset.theme;
    store.set('vfTheme', dark ? 'dark' : '');
    syncTheme();
  };
  syncTheme();

  /* ---------- Reviewer identity (remembered on this device) ---------- */
  const initials = n => n.trim().split(/\s+/).filter(Boolean).map(w => w[0]).filter((_, i, a) => i === 0 || i === a.length - 1).join('').toUpperCase();
  function renderChip() {
    const n = store.get('vfReviewer');
    q('reviewerChipName').textContent = n || 'Chưa đặt tên';
    q('reviewerAvatar').textContent = n ? initials(n) : '?';
    q('reviewerChip').dataset.tip = n ? 'Người duyệt: ' + n : 'Đặt tên người duyệt';
    if (q('dbWhoName')) { q('dbWhoName').textContent = n || 'Chưa đặt tên'; q('dbAvatar').textContent = n ? initials(n) : '?'; }
  }
  function setReviewer(name) {
    name = String(name || '').trim().slice(0, 80);
    store.set('vfReviewer', name);
    if (q('reviewer')) q('reviewer').value = name;
    renderChip();
  }
  window.currentReviewerName = () => store.get('vfReviewer');
  let afterName = null;
  window.openReviewerDialog = then => {
    afterName = typeof then === 'function' ? then : null;
    q('whoName').value = store.get('vfReviewer') || q('reviewer')?.value || '';
    q('whoDialog').showModal();
    requestAnimationFrame(() => q('whoName').select());
  };
  q('whoForm').addEventListener('submit', e => {
    e.preventDefault();
    const n = q('whoName').value.trim();
    if (!n) { q('whoName').focus(); return; }
    setReviewer(n);
    q('whoDialog').close();
    const fn = afterName; afterName = null;
    if (fn) fn();
  });
  q('whoDialog').addEventListener('close', () => { afterName = null; });
  // Returns the reviewer name, or opens the name dialog and retries `then` afterwards.
  window.ensureReviewer = then => {
    const n = (q('reviewer')?.value || '').trim() || store.get('vfReviewer');
    if (n) { if (q('reviewer') && !q('reviewer').value.trim()) q('reviewer').value = n; return n; }
    openReviewerDialog(then);
    return '';
  };
  q('reviewer')?.addEventListener('change', e => { if (e.target.value.trim()) setReviewer(e.target.value); });
  if (q('reviewer') && !q('reviewer').value) q('reviewer').value = store.get('vfReviewer');
  renderChip();

  /* ---------- Note indicator on the decision bar ---------- */
  const noteBox = q('reviewNote');
  const syncNote = () => noteBox?.closest('.db-note')?.classList.toggle('has-note', !!noteBox.value.trim());
  noteBox?.addEventListener('input', syncNote);
  window.syncNoteIndicator = syncNote;

  /* ---------- Queue chrome: tabs, counts, badge, order ---------- */
  window.queueOrder = [];
  window.updateQueueChrome = (counts, mode) => {
    document.querySelectorAll('#queue .qtabs button').forEach(b => {
      const on = b.dataset.mode === mode;
      b.classList.toggle('active', on);
      b.setAttribute('aria-selected', String(on));
      // Hide empty filters (except the default, "all" and the active one) to keep the bar short.
      b.hidden = !on && !['pending', 'all'].includes(b.dataset.mode) && !(counts[b.dataset.mode] > 0);
    });
    document.querySelectorAll('#queue .qcount').forEach(el => { el.textContent = counts[el.dataset.count] ?? 0; });
    const badge = q('navBadgeQueue');
    if (badge) { badge.textContent = counts.pending; badge.hidden = !counts.pending; }
    if (focusJob) { const row = document.querySelector(`#queueTable .rowlink[data-job="${CSS.escape(focusJob)}"]`); if (row && document.activeElement === document.body) row.focus({ preventScroll: true }); }
  };
  document.querySelectorAll('#queue .qtabs button').forEach(b => b.addEventListener('click', () => {
    q('queueStatus').value = b.dataset.mode;
    renderQueue();
  }));
  let focusJob = null;
  function moveRow(dir) {
    const rows = [...document.querySelectorAll('#queueTable .rowlink')];
    if (!rows.length) return;
    let i = rows.indexOf(document.activeElement);
    if (i < 0) { const at = rows.findIndex(r => r.classList.contains('sel')); i = at < 0 ? (dir > 0 ? 0 : rows.length - 1) : Math.min(rows.length - 1, Math.max(0, at + dir)); }
    else i = Math.min(rows.length - 1, Math.max(0, i + dir));
    rows[i].focus();
    rows[i].scrollIntoView({ block: 'nearest' });
    focusJob = rows[i].dataset.job;
  }

  /* ---------- Live refresh while something is processing ---------- */
  let liveTimer = null;
  window.scheduleLivePoll = () => {
    clearTimeout(liveTimer);
    if (!jobs.some(j => j.status === 'queued' || j.status === 'processing')) return;
    liveTimer = setTimeout(() => { if (document.hidden) scheduleLivePoll(); else refreshAll(); }, 4000);
  };

  /* ---------- Drag a video onto the queue to start an analysis ---------- */
  const panel = document.querySelector('#queue > .panel');
  const hint = q('queueDrop');
  let depth = 0;
  const hasFiles = e => [...(e.dataTransfer?.types || [])].includes('Files');
  panel?.addEventListener('dragenter', e => { if (!hasFiles(e)) return; e.preventDefault(); depth++; hint.hidden = false; });
  panel?.addEventListener('dragover', e => { if (hasFiles(e)) e.preventDefault(); });
  panel?.addEventListener('dragleave', () => { if (--depth <= 0) { depth = 0; hint.hidden = true; } });
  panel?.addEventListener('drop', e => {
    if (!hasFiles(e)) return;
    e.preventDefault(); depth = 0; hint.hidden = true;
    const files = e.dataTransfer.files;
    if (!files?.length) return;
    if (!/^video\//.test(files[0].type) && !/\.(mp4|mov|mkv|webm)$/i.test(files[0].name)) { toast('Chỉ nhận tệp video MP4, MOV, MKV hoặc WEBM'); return; }
    q('videoFile').files = files;
    q('fileLabel').textContent = files[0].name;
    openTab('analyze');
    q('videoFile').dispatchEvent(new Event('change'));
    toast('Đã chọn ' + files[0].name + '. Chọn sản phẩm tham chiếu để bắt đầu.');
  });

  /* ---------- Review view helpers ---------- */
  window.closeReview = () => {
    const jid = selected;
    const v = q('player'); if (v && !v.paused) v.pause();
    if (poll) clearInterval(poll);
    selected = null; currentJob = null;
    q('queue').classList.remove('reviewing');
    q('jobDetail').classList.add('hidden');
    if (location.hash !== '#queue') history.pushState({ tab: 'queue' }, '', location.pathname + location.search + '#queue');
    openTab('queue', { skipHistory: true });
    focusJob = jid;
    if (jid) { window.inboxForget?.(jid); window.inboxSelect?.(jid); }
    requestAnimationFrame(() => {
      const row = jid && document.querySelector(`#queueTable .rowlink[data-job="${CSS.escape(jid)}"]`);
      if (row) { row.focus({ preventScroll: true }); row.scrollIntoView({ block: 'center' }); }
    });
  };
  function reviewOrder() {
    const order = (window.queueOrder || []).slice();
    if (selected && !order.includes(selected)) return jobs.map(j => j.id);
    return order.length ? order : jobs.map(j => j.id);
  }
  window.updateReviewNav = () => {
    const order = reviewOrder(), i = order.indexOf(selected);
    q('reviewPos').textContent = i >= 0 ? `${i + 1} / ${order.length}` : '';
    q('prevJob').disabled = i <= 0;
    q('nextJob').disabled = i < 0 || i >= order.length - 1;
  };
  window.stepJob = dir => {
    const order = reviewOrder(), i = order.indexOf(selected), next = order[i + dir];
    if (!next) { toast(dir > 0 ? 'Đây là video cuối trong danh sách' : 'Đây là video đầu trong danh sách'); return; }
    showJob(next);
  };

  // Finding markers on the video timeline
  const sevName = { high: 'Cao', medium: 'Trung bình', low: 'Thấp' };
  window.renderFindingTrack = d => {
    const track = q('findingTrack'), labels = q('findingTrackLabels');
    const v = q('player');
    const dur = Number(d.details?.duration) || (isFinite(v.duration) ? v.duration : 0) || Math.max(1, ...d.findings.map(f => Number(f.timestamp) || 0));
    labels.innerHTML = `<span>0s</span><span>${dur ? dur.toFixed(1) + 's' : ''}</span>`;
    if (d.status !== 'completed' || !d.findings.length) {
      track.innerHTML = `<i class="fplay"></i><span class="ftrack-empty">${d.status !== 'completed' ? 'Đang phân tích' : 'Không có cảnh báo trên dòng thời gian'}</span>`;
      return;
    }
    track.innerHTML = '<i class="fplay"></i>' + d.findings.map(f => {
      const t = Number(f.timestamp) || 0, pct = Math.min(100, Math.max(0, t / dur * 100));
      const name = findingNames[f.code] || f.code;
      return `<button type="button" class="fm ${esc(f.severity)} ${esc(f.flag_review)}" style="left:${pct}%" data-fid="${Number(f.id)}" data-t="${t}" aria-label="${esc(name)} tại ${t.toFixed(1)} giây, mức ${esc(sevName[f.severity] || f.severity)}" title="${esc(name)} · ${t.toFixed(1)}s"></button>`;
    }).join('');
  };
  q('findingTrack')?.addEventListener('click', e => {
    const m = e.target.closest('.fm');
    if (m) {
      seek(Number(m.dataset.t));
      const card = q('finding-' + m.dataset.fid);
      if (card) { card.classList.remove('flash'); void card.offsetWidth; card.classList.add('flash'); card.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
      return;
    }
    const v = q('player'), r = e.currentTarget.getBoundingClientRect();
    if (isFinite(v.duration) && v.duration > 0) v.currentTime = (e.clientX - r.left) / r.width * v.duration;
  });
  q('player')?.addEventListener('timeupdate', e => {
    const v = e.target, bar = document.querySelector('#findingTrack .fplay');
    if (bar && isFinite(v.duration) && v.duration > 0) bar.style.width = (v.currentTime / v.duration * 100) + '%';
  });
  q('player')?.addEventListener('loadedmetadata', () => { if (currentJob && !Number(currentJob.details?.duration)) renderFindingTrack(currentJob); });

  window.renderFindingProgress = d => {
    const box = q('findingProgress');
    if (d.status !== 'completed' || !d.findings.length) { box.innerHTML = ''; return; }
    const done = d.findings.filter(f => f.flag_review !== 'unreviewed').length, total = d.findings.length;
    box.innerHTML = `<span>Đã xác minh <b>${done}/${total}</b> cảnh báo</span><span class="bar"><i style="width:${total ? done / total * 100 : 0}%"></i></span>`;
  };

  /* ---------- Review side panel: tabs, finding focus, decision bar ---------- */
  const RTABS = ['findings', 'evidence', 'more'];
  window.setReviewTab = name => {
    if (!RTABS.includes(name)) name = 'findings';
    RTABS.forEach(t => {
      const on = t === name, tab = q('rtab-' + t), pane = q('rpane-' + t);
      if (!tab || !pane) return;
      tab.setAttribute('aria-selected', String(on));
      tab.tabIndex = on ? 0 : -1;
      pane.hidden = !on;
    });
  };
  document.querySelectorAll('.rtabs [data-rtab]').forEach(b => {
    b.addEventListener('click', () => setReviewTab(b.dataset.rtab));
    b.addEventListener('keydown', e => {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      e.preventDefault();
      const i = RTABS.indexOf(b.dataset.rtab), next = RTABS[(i + (e.key === 'ArrowRight' ? 1 : -1) + RTABS.length) % RTABS.length];
      setReviewTab(next); q('rtab-' + next).focus();
    });
  });
  // Unverified findings start open, verified ones start collapsed; the header toggles either way.
  window.toggleFinding = id => {
    const card = q('finding-' + id); if (!card) return;
    const pendingCard = card.classList.contains('f-unreviewed');
    const isOpen = pendingCard ? !card.classList.contains('collapsed') : card.classList.contains('expanded');
    card.classList.toggle(pendingCard ? 'collapsed' : 'expanded', pendingCard ? isOpen : !isOpen);
    card.querySelector('.ftoggle')?.setAttribute('aria-expanded', String(!isOpen));
  };
  window.focusNextFinding = () => {
    const next = document.querySelector('#findings .finding.f-unreviewed');
    if (!next) return;
    next.classList.remove('flash'); void next.offsetWidth; next.classList.add('flash');
    next.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  };
  window.showCoverageDetails = () => {
    setReviewTab('evidence');
    const d = q('coverage')?.closest('details');
    if (d) { d.open = true; requestAnimationFrame(() => d.scrollIntoView({ behavior: 'smooth', block: 'nearest' })); }
  };
  window.copyJobId = () => {
    if (!selected) return;
    const done = () => toast('Đã sao chép mã video ' + selected);
    navigator.clipboard?.writeText(selected).then(done, () => toast('Mã video: ' + selected)) ?? toast('Mã video: ' + selected);
  };
  // Measure the sticky header and where the review view starts, for the fixed review layout.
  const measureReview = () => {
    const hdr = document.querySelector('.workspace-header'), jd = q('jobDetail');
    const sticky = hdr && getComputedStyle(hdr).position === 'sticky';
    html.style.setProperty('--hdr-h', (sticky ? hdr.offsetHeight : 0) + 'px');
    if (jd && !jd.classList.contains('hidden')) { let y = 0; for (let e = jd; e; e = e.offsetParent) y += e.offsetTop; html.style.setProperty('--rv-top', y + 'px'); }
  };
  addEventListener('resize', () => requestAnimationFrame(measureReview));
  window.renderReviewChrome = d => {
    requestAnimationFrame(measureReview);
    const ready = d.status === 'completed';
    const pending = ready ? d.findings.filter(f => f.flag_review === 'unreviewed').length : 0;
    const fc = q('rtabFindingsCount'), ec = q('rtabEvidenceCount');
    fc.textContent = ready && d.findings.length ? (pending ? pending : '✓') : '';
    fc.classList.toggle('is-todo', pending > 0);
    ec.textContent = d.evidence?.length || '';
    const rec = ready ? (d.ai_recommendation || d.details?.ai_recommendation) : null;
    document.querySelectorAll('#decisionBar [data-decision]').forEach(b => {
      b.classList.toggle('ai-pick', !!rec && rec.decision === b.dataset.decision);
      b.title = rec && rec.decision === b.dataset.decision ? 'AI đề xuất lựa chọn này' : '';
      b.setAttribute('aria-pressed', String(d.review_decision === b.dataset.decision));
      b.disabled = !ready;
    });
    const st = q('dbStatus');
    st.className = 'db-status';
    if (!ready) { st.textContent = d.status === 'failed' ? 'Phân tích lỗi' : 'Đang phân tích…'; }
    else if (d.review_decision) { st.textContent = 'Đã duyệt: ' + (decisionText[d.review_decision] || d.review_decision); st.classList.add('is-ok'); }
    else if (pending) { st.textContent = `Còn ${pending} cảnh báo chưa xác minh`; st.classList.add('is-todo'); }
    else { st.textContent = d.findings.length ? 'Đã xác minh hết cảnh báo' : 'Sẵn sàng quyết định'; st.classList.add('is-ok'); }
  };

  /* ---------- Quick search (command palette) ---------- */
  const pal = q('cmdk'), input = q('cmdkInput'), list = q('cmdkList');
  let items = [], sel = 0;
  const PAGES = [['queue', 'Danh sách duyệt', '☰'], ['analyze', 'Phân tích video', '▶'], ['overview', 'Tổng quan', '◔'], ['products', 'Sản phẩm tham chiếu', '◇'], ['dataset', 'Bộ kiểm thử', '▦'], ['evaluation', 'Đánh giá thực tế', '◎']];
  function build(text) {
    const n = norm(text), hit = s => !n || norm(s).includes(n);
    const out = [];
    const statusVi = { queued: 'Trong hàng đợi', processing: 'Đang phân tích', completed: 'Đã phân tích', failed: 'Lỗi xử lý' };
    jobs.filter(j => hit([j.filename, j.sku, j.product_name, j.case_code].join(' '))).slice(0, n ? 8 : 5)
      .forEach(j => out.push({ group: 'Video', icon: '▶', label: j.filename, sub: `${j.sku} · ${j.review_decision ? 'Đã duyệt' : statusVi[j.status] || j.status}`, run: () => showJob(j.id) }));
    PAGES.filter(p => hit(p[1])).forEach(p => out.push({ group: 'Đi tới trang', icon: p[2], label: p[1], run: () => openTab(p[0]) }));
    [
      { label: 'Phân tích video mới', icon: '+', key: 'N', run: () => openTab('analyze') },
      { label: 'Xuất toàn bộ phiên (ZIP)', icon: '↓', run: () => { location.href = '/api/sessions/export'; } },
      { label: 'Làm mới dữ liệu', icon: '↻', run: () => { refreshAll(); toast('Đã làm mới dữ liệu'); } },
      { label: 'Bật / tắt menu', icon: '⇤', key: '[', run: () => toggleSide() },
      { label: 'Đổi tên người duyệt', icon: '☺', run: () => openReviewerDialog() },
      { label: 'Xem phím tắt', icon: '?', key: '?', run: () => openHelp() }
    ].filter(a => hit(a.label)).forEach(a => out.push({ group: 'Thao tác', ...a }));
    if (n) products.filter(p => hit([p.sku, p.name, p.brand].join(' '))).slice(0, 5)
      .forEach(p => out.push({ group: 'Sản phẩm', icon: '◇', label: p.name, sub: p.sku, run: () => { openTab('products'); startProductEdit(p.id); } }));
    return out;
  }
  function render() {
    items = build(input.value);
    sel = Math.min(sel, Math.max(0, items.length - 1));
    if (!items.length) { list.innerHTML = '<div class="cmdk-empty">Không tìm thấy kết quả phù hợp</div>'; return; }
    let last = '', h = '';
    items.forEach((it, i) => {
      if (it.group !== last) { h += `<div class="cmdk-group">${esc(it.group)}</div>`; last = it.group; }
      h += `<button type="button" role="option" class="cmdk-item${i === sel ? ' sel' : ''}" data-i="${i}" aria-selected="${i === sel}"><span class="ci">${esc(it.icon || '•')}</span><span class="ct"><b>${esc(it.label)}</b>${it.sub ? `<small>${esc(it.sub)}</small>` : ''}</span>${it.key ? `<kbd>${esc(it.key)}</kbd>` : ''}</button>`;
    });
    list.innerHTML = h;
    list.querySelector('.sel')?.scrollIntoView({ block: 'nearest' });
  }
  function runItem(i) { const it = items[i]; if (!it) return; pal.close(); it.run(); }
  window.openPalette = () => {
    if (pal.open) return;
    if (mobile()) drawer(false);
    input.value = ''; sel = 0; render();
    pal.showModal();
    input.focus();
  };
  input.addEventListener('input', () => { sel = 0; render(); });
  input.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); sel = (sel + 1) % Math.max(1, items.length); render(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sel = (sel - 1 + items.length) % Math.max(1, items.length); render(); }
    else if (e.key === 'Enter') { e.preventDefault(); runItem(sel); }
  });
  list.addEventListener('click', e => { const b = e.target.closest('.cmdk-item'); if (b) runItem(+b.dataset.i); });
  list.addEventListener('mousemove', e => { const b = e.target.closest('.cmdk-item'); if (b && +b.dataset.i !== sel) { sel = +b.dataset.i; list.querySelectorAll('.cmdk-item').forEach((x, i) => { x.classList.toggle('sel', i === sel); x.setAttribute('aria-selected', String(i === sel)); }); } });
  [pal, q('kbdHelp'), q('whoDialog')].forEach(d => d.addEventListener('click', e => { if (e.target === d) d.close(); }));

  window.openHelp = () => { if (!q('kbdHelp').open) q('kbdHelp').showModal(); };

  /* ---------- Keyboard shortcuts ---------- */
  document.addEventListener('keydown', e => {
    const k = e.key;
    if ((e.metaKey || e.ctrlKey) && !e.altKey && k.toLowerCase() === 'k') { e.preventDefault(); pal.open ? pal.close() : openPalette(); return; }
    if (e.metaKey || e.ctrlKey || e.altKey || e.defaultPrevented) return;
    if (document.querySelector('dialog[open]') || html.classList.contains('drawer-lock')) return;
    const t = e.target;
    if (t.closest && t.closest('input,textarea,select,[contenteditable="true"]')) { if (k === 'Escape') t.blur(); return; }
    if (k === 'Escape' && html.classList.contains('drawer-open')) { drawer(false); return; }
    if (k === '?') { e.preventDefault(); openHelp(); return; }
    if (k === '[') { e.preventDefault(); toggleSide(); return; }
    if (k === '/') { e.preventDefault(); openPalette(); return; }
    const onQueue = q('queue').classList.contains('active');
    const reviewing = onQueue && q('queue').classList.contains('reviewing');
    if (reviewing) {
      if (k === '1' || k === '2' || k === '3') { e.preventDefault(); submitReview(['Pass', 'Needs Review', 'Regenerate'][+k - 1]); return; }
      if (k === 'j' || k === 'J') { e.preventDefault(); stepJob(1); return; }
      if (k === 'k' || k === 'K') { e.preventDefault(); stepJob(-1); return; }
      if (k === 'Escape') { e.preventDefault(); closeReview(); return; }
      return;
    }
    if (onQueue && (k === 'j' || k === 'J')) { e.preventDefault(); moveRow(1); return; }
    if (onQueue && (k === 'k' || k === 'K')) { e.preventDefault(); moveRow(-1); return; }
    if (onQueue && k === 'Enter' && window.inboxSelected?.()) { e.preventDefault(); showJob(window.inboxSelected()); return; }
    if (k === 'n' || k === 'N') { e.preventDefault(); openTab('analyze'); }
  });
})();
