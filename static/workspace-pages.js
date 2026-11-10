/* VerifAI page layer (part D): analyze wizard, products slide-over and
   filters, actionable overview. Loaded before the main inline script and,
   like workspace-ux.js, only reads the main script's globals at call time. */
(() => {
  const q = id => document.getElementById(id);
  const html = document.documentElement;
  const norm = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd').replace(/Đ/g, 'D').toLowerCase();
  const vnd = n => n === null || n === undefined ? 'Chưa nhập giá' : Number(n).toLocaleString('vi-VN') + ' VND';
  const mb = b => (b / 1048576).toFixed(b < 10485760 ? 1 : 0) + ' MB';
  const REF = {
    unverified: ['ref-unverified', 'Chưa xem xét nguồn'],
    reviewed: ['ref-reviewed', 'Đã xem xét nguồn thực tế'],
    test_reference_approved: ['ref-test', 'Chuẩn kiểm thử']
  };
  window.refBadge = s => { const r = REF[s] || REF.unverified; return `<span class="pill ${r[0]}">${r[1]}</span>`; };

  /* =================== Analyze wizard =================== */
  const MAX_BYTES = 150 * 1024 * 1024, MAX_SEC = 180;
  let step = 1, previewURL = null, videoSec = null;
  const file = () => q('videoFile').files?.[0] || null;
  const product = () => products.find(p => p.id === q('uploadProduct').value) || null;
  const ok = n => n === 1 ? true : n === 2 ? !!file() && file().size <= MAX_BYTES : !!file() && file().size <= MAX_BYTES && !!product();

  function goStep(n, { focus = true } = {}) {
    if (!ok(n)) n = !file() || file().size > MAX_BYTES ? 1 : 2;
    step = n;
    document.querySelectorAll('#uploadForm .wstep').forEach(s => { s.hidden = Number(s.dataset.step) !== n; });
    document.querySelectorAll('#stepper button').forEach(b => {
      const k = Number(b.dataset.step);
      b.classList.toggle('current', k === n);
      b.classList.toggle('done', k < n || (k === 1 && !!file()) || (k === 2 && !!product()));
      b.disabled = !ok(k);
      if (k === n) b.setAttribute('aria-current', 'step'); else b.removeAttribute('aria-current');
    });
    q('wBack').hidden = n === 1;
    q('wNext').hidden = n === 3;
    q('wNext').disabled = !ok(n + 1);
    q('wHint').textContent = n === 1 ? (file() ? '' : 'Kéo thả hoặc chọn một video để tiếp tục') : n === 2 ? (product() ? '' : 'Chọn một sản phẩm để tiếp tục') : '';
    if (n === 2) renderPicker();
    if (n === 3) renderConfirm();
    if (focus) requestAnimationFrame(() => {
      const el = n === 1 ? (file() ? q('wNext') : q('dropzone')) : n === 2 ? q('productPick') : q('uploadBtn');
      el?.focus({ preventScroll: true });
    });
  }
  function summaries() {
    const f = file(), p = product();
    q('stepSum1').textContent = f ? f.name : 'Chưa chọn';
    q('stepSum2').textContent = p ? p.sku + ' · ' + p.name : 'Chưa chọn';
  }
  window.syncAnalyze = () => {
    summaries();
    const target = !file() || file().size > MAX_BYTES ? 1 : !product() ? 2 : 3;
    goStep(ok(step) ? step : target, { focus: false });
  };

  function showPreview() {
    const f = file(), box = q('videoPreview'), v = q('previewPlayer');
    if (previewURL) { URL.revokeObjectURL(previewURL); previewURL = null; }
    videoSec = null;
    if (!f) { box.classList.add('hidden'); q('dropzone').classList.remove('hidden'); v.removeAttribute('src'); v.load(); return; }
    previewURL = URL.createObjectURL(f);
    v.src = previewURL;
    q('vpName').textContent = f.name;
    q('vpMeta').textContent = mb(f.size);
    const warn = q('vpWarn');
    warn.hidden = f.size <= MAX_BYTES;
    warn.textContent = f.size > MAX_BYTES ? 'Video vượt giới hạn 150MB. Hãy chọn video nhỏ hơn.' : '';
    box.classList.remove('hidden');
    q('dropzone').classList.add('hidden');
  }
  q('previewPlayer').addEventListener('loadedmetadata', e => {
    videoSec = e.target.duration;
    const f = file(); if (!f || !isFinite(videoSec)) return;
    q('vpMeta').textContent = `${mb(f.size)} · ${videoSec.toFixed(1)} giây`;
    if (videoSec > MAX_SEC) { q('vpWarn').hidden = false; q('vpWarn').textContent = `Video dài hơn ${MAX_SEC} giây; hệ thống có thể từ chối hoặc chỉ xử lý một phần.`; }
    if (step === 3) renderConfirm();
  });
  q('videoFile').addEventListener('change', () => {
    showPreview(); summaries();
    if (file() && file().size <= MAX_BYTES) goStep(product() ? 3 : 2); else goStep(1);
  });
  window.pickVideoAgain = () => q('videoFile').click();

  function renderPicker() {
    const list = q('productPickList'), text = norm(q('productPick').value), sel = q('uploadProduct').value;
    const items = products.filter(p => !text || norm([p.sku, p.name, p.brand].join(' ')).includes(text));
    if (!products.length) { list.innerHTML = '<div class="pp-empty">Chưa có sản phẩm tham chiếu nào. Hãy tạo sản phẩm đầu tiên.</div>'; return; }
    if (!items.length) { list.innerHTML = '<div class="pp-empty">Không tìm thấy sản phẩm phù hợp.</div>'; return; }
    list.innerHTML = items.map(p => `<button type="button" role="option" class="pp-item${p.id === sel ? ' sel' : ''}" aria-selected="${p.id === sel}" data-pid="${esc(p.id)}">
      <span class="pp-radio" aria-hidden="true"></span>
      <span class="pp-main"><b>${esc(p.name)}</b><small>${esc(p.sku)}${p.brand ? ' · ' + esc(p.brand) : ''} · ${esc(vnd(p.price))}</small></span>
      ${refBadge(p.reference_status)}</button>`).join('');
  }
  q('productPick').addEventListener('input', renderPicker);
  q('productPick').addEventListener('keydown', e => {
    const items = [...q('productPickList').querySelectorAll('.pp-item')];
    if (e.key === 'ArrowDown' && items.length) { e.preventDefault(); items[0].focus(); }
    if (e.key === 'Enter') { e.preventDefault(); if (items.length === 1) items[0].click(); }
  });
  q('productPickList').addEventListener('keydown', e => {
    const items = [...q('productPickList').querySelectorAll('.pp-item')], i = items.indexOf(document.activeElement);
    if (e.key === 'ArrowDown' && i < items.length - 1) { e.preventDefault(); items[i + 1].focus(); }
    if (e.key === 'ArrowUp') { e.preventDefault(); (i > 0 ? items[i - 1] : q('productPick')).focus(); }
  });
  q('productPickList').addEventListener('click', e => {
    const b = e.target.closest('.pp-item'); if (!b) return;
    q('uploadProduct').value = b.dataset.pid;
    q('uploadProduct').dispatchEvent(new Event('change'));
    summaries(); renderPicker();
    goStep(3);
  });
  q('uploadProduct').addEventListener('change', () => { summaries(); if (step === 2) renderPicker(); });

  function renderConfirm() {
    const f = file(), p = product();
    if (!f || !p) return;
    q('confirmVideo').innerHTML = `<small>Video</small><b>${esc(f.name)}</b><span>${mb(f.size)}${videoSec && isFinite(videoSec) ? ' · ' + videoSec.toFixed(1) + ' giây' : ''}</span>`;
    q('confirmProduct').innerHTML = `<small>Sản phẩm tham chiếu</small><b>${esc(p.name)}</b><span>${esc(p.sku)} · ${esc(vnd(p.price))} · ${p.claims.length} claim được phép</span>${refBadge(p.reference_status)}`;
    const unverified = !['reviewed', 'test_reference_approved'].includes(p.reference_status);
    q('confirmWarn').innerHTML = unverified ? '<p class="notice">Nguồn của sản phẩm này chưa được xem xét. Bạn vẫn phân tích được, nhưng nên xác minh thông tin sản phẩm trước khi chấp thuận video.</p>' : '';
  }
  document.querySelectorAll('[data-edit-step]').forEach(b => b.addEventListener('click', () => goStep(Number(b.dataset.editStep))));
  q('stepper').addEventListener('click', e => { const b = e.target.closest('button[data-step]'); if (b && !b.disabled) goStep(Number(b.dataset.step)); });
  q('wNext').addEventListener('click', () => goStep(step + 1));
  q('wBack').addEventListener('click', () => goStep(step - 1));

  window.setUploadProgress = frac => {
    const pct = Math.round(frac * 100);
    q('uploadBar').style.width = pct + '%';
    q('uploadPct').textContent = pct < 100 ? `Đang tải video lên… ${pct}%` : 'Đã tải xong, đang đưa vào hàng đợi…';
  };
  window.resetAnalyzeWizard = () => {
    q('uploadForm').reset();
    q('analysisAdvanced').open = false;
    q('fileLabel').textContent = 'Nhấn để chọn hoặc kéo video vào đây';
    q('productPick').value = '';
    showPreview(); summaries(); step = 1; goStep(1, { focus: false });
  };
  window.analyzeWithProduct = id => {
    q('uploadProduct').value = id;
    q('uploadProduct').dispatchEvent(new Event('change'));
    openTab('analyze');
    toast('Đã chọn sản phẩm. Hãy chọn video để phân tích.');
  };
  window.highlightJob = id => {
    requestAnimationFrame(() => {
      const row = document.querySelector(`#queueTable .rowlink[data-job="${CSS.escape(id)}"]`);
      if (!row) return;
      row.classList.remove('just-added'); void row.offsetWidth; row.classList.add('just-added');
      row.scrollIntoView({ block: 'center', behavior: 'smooth' });
      row.focus({ preventScroll: true });
    });
  };

  /* =================== Products =================== */
  const view = { text: '', status: 'all' };
  window.productListView = () => {
    const t = norm(view.text);
    return products.filter(p => (view.status === 'all' || (p.reference_status || 'unverified') === view.status) && (!t || norm([p.sku, p.name, p.brand, p.variant].join(' ')).includes(t)));
  };
  window.updateProductChrome = () => {
    const c = { all: products.length, unverified: 0, reviewed: 0, test_reference_approved: 0 };
    products.forEach(p => { c[p.reference_status || 'unverified'] = (c[p.reference_status || 'unverified'] || 0) + 1; });
    document.querySelectorAll('#productTabs button').forEach(b => {
      b.classList.toggle('active', b.dataset.status === view.status);
      b.setAttribute('aria-selected', String(b.dataset.status === view.status));
      const n = b.querySelector('.qcount'); if (n) n.textContent = c[b.dataset.status] || 0;
    });
    q('productShown').textContent = `${productListView().length} / ${products.length} sản phẩm`;
  };
  window.setProductFilter = status => { view.status = status; renderProducts(); };
  document.querySelectorAll('#productTabs button').forEach(b => b.addEventListener('click', () => setProductFilter(b.dataset.status)));
  q('productSearch').addEventListener('input', e => { view.text = e.target.value; renderProducts(); });

  // Slide-over editor: the <details id="newProductDetails"> element is styled as a drawer.
  const drawer = q('newProductDetails');
  let dirty = false, returnToAnalyze = false;
  q('productForm').addEventListener('input', () => { dirty = true; });
  drawer.addEventListener('toggle', () => {
    const open = drawer.open;
    html.classList.toggle('drawer-lock', open);
    q('productScrim').hidden = !open;
    if (open) { dirty = false; requestAnimationFrame(() => q('newSKU').focus()); }
  });
  window.openProductCreate = ({ fromAnalyze = false } = {}) => {
    if (typeof editingProductId !== 'undefined' && editingProductId) cancelProductEdit();
    q('productDrawerTitle').textContent = 'Tạo sản phẩm tham chiếu';
    q('productDrawerEyebrow').textContent = 'Product Truth mới';
    drawer.open = true;
    returnToAnalyze = fromAnalyze;
  };
  window.requestCloseProductDrawer = () => {
    if (dirty && !confirm('Bỏ các thay đổi chưa lưu?')) return;
    dirty = false; returnToAnalyze = false;
    cancelProductEdit();
  };
  window.afterProductSaved = id => {
    dirty = false;
    if (returnToAnalyze && id) {
      q('uploadProduct').value = id;
      q('uploadProduct').dispatchEvent(new Event('change'));
      summaries(); goStep(3);
    }
    returnToAnalyze = false;
  };

  // "⋯" overflow menus
  window.toggleMenu = id => {
    const m = q(id), btn = document.querySelector(`[aria-controls="${id}"]`);
    const open = m.hidden;
    document.querySelectorAll('.menu').forEach(x => { x.hidden = true; });
    document.querySelectorAll('[aria-haspopup="menu"]').forEach(x => x.setAttribute('aria-expanded', 'false'));
    m.hidden = !open;
    btn?.setAttribute('aria-expanded', String(open));
    if (open) requestAnimationFrame(() => m.querySelector('button')?.focus());
  };
  document.addEventListener('click', e => {
    if (e.target.closest('.more')) return;
    document.querySelectorAll('.menu').forEach(x => { x.hidden = true; });
    document.querySelectorAll('[aria-haspopup="menu"]').forEach(x => x.setAttribute('aria-expanded', 'false'));
  });
  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    const openMenu = [...document.querySelectorAll('.menu')].find(m => !m.hidden);
    if (openMenu) { openMenu.hidden = true; document.querySelector(`[aria-controls="${openMenu.id}"]`)?.focus(); return; }
    if (drawer.open && !document.querySelector('dialog[open]')) { e.preventDefault(); requestCloseProductDrawer(); }
  });

  /* =================== Overview =================== */
  window.openQueueFilter = mode => { q('queueStatus').value = mode; openTab('queue'); };
  window.renderOverviewExtras = () => {
    const c = { pending: 0, processing: 0, reviewed: 0, failed: 0 };
    jobs.forEach(j => {
      if (!j.review_decision && j.status !== 'failed') c.pending++;
      if (j.status === 'queued' || j.status === 'processing') c.processing++;
      if (j.review_decision) c.reviewed++;
      if (j.status === 'failed') c.failed++;
    });
    q('stat-pending').textContent = c.pending;
    q('stat-processing').textContent = c.processing;
    const ready = jobs.filter(j => !j.review_decision && j.status === 'completed'), firstReady = ready[0];
    const unverified = products.filter(p => !['reviewed', 'test_reference_approved'].includes(p.reference_status)).length;
    const todo = [];
    if (!products.length) todo.push(['◇', 'Chưa có sản phẩm tham chiếu', 'Tạo sản phẩm để có dữ liệu đối chiếu khi phân tích video.', 'Tạo sản phẩm', 'openProductCreate()']);
    if (!jobs.length) todo.push(['▶', 'Chưa có video nào', 'Tải video đầu tiên lên để bắt đầu kiểm duyệt.', 'Phân tích video', "openTab('analyze')"]);
    if (firstReady) todo.push(['✓', `${ready.length} video đã phân tích xong, chờ duyệt`, '', 'Duyệt ngay', `showJob('${esc(firstReady.id)}')`]);
    if (c.processing) todo.push(['◔', `${c.processing} video đang được phân tích`, '', 'Xem tiến độ', "openQueueFilter('processing')"]);
    if (c.failed) todo.push(['!', `${c.failed} video bị lỗi xử lý`, '', 'Xem video lỗi', "openQueueFilter('failed')"]);
    if (unverified) todo.push(['◇', `${unverified} sản phẩm chưa xem xét nguồn`, 'AI sẽ không đề xuất Chấp thuận khi nguồn sản phẩm chưa được xác minh.', 'Xem sản phẩm', "openTab('products');setProductFilter('unverified')"]);
    q('overviewTodo').innerHTML = `<div class="review-subhead"><h3>Việc cần làm</h3></div>` + (todo.length
      ? todo.map(t => `<div class="todo-item"><span class="todo-ic" aria-hidden="true">${t[0]}</span><div><b>${esc(t[1])}</b>${t[2] ? `<small>${esc(t[2])}</small>` : ''}</div><button type="button" class="mini" onclick="${t[4]}">${esc(t[3])} →</button></div>`).join('')
      : '<div class="todo-done">Không còn việc tồn đọng. Mọi video đã được duyệt.</div>');
  };
})();

/* ---------- UX polish after the sprint1 merge ---------- */
(() => {
  const q = id => document.getElementById(id);
  const store = {
    get(k) { try { return localStorage.getItem(k) || ''; } catch (_) { return ''; } },
    set(k, v) { try { v ? localStorage.setItem(k, v) : localStorage.removeItem(k); } catch (_) {} }
  };

  // Change-product dialog for the review view (replaces the always-visible select).
  const syncApply = () => {
    const same = !currentJob || q('jobProductSelect').value === currentJob.product_id;
    q('jobProductApply').disabled = same || q('jobProductSelect').disabled;
  };
  window.openJobProductDialog = () => {
    if (!currentJob) return;
    if (['queued', 'processing'].includes(currentJob.status)) { toast('Chờ phân tích xong rồi mới đổi sản phẩm'); return; }
    renderJobProduct(currentJob);
    const p = currentJob.product || {};
    q('jobProductCurrent').textContent = `Đang gắn: ${p.sku || '-'} · ${p.name || ''}`;
    syncApply();
    q('jobProductDialog').showModal();
    requestAnimationFrame(() => q('jobProductSelect').focus());
  };
  q('jobProductSelect').addEventListener('change', syncApply);
  q('jobProductDialog').addEventListener('click', e => { if (e.target === q('jobProductDialog')) q('jobProductDialog').close(); });

  // Inline error under a form field; returns undefined so callers can `return fieldError(...)`.
  window.fieldError = (id, msg) => {
    const el = q(id), field = el.closest('.field') || el.parentElement;
    field.classList.add('invalid');
    let note = field.querySelector('.field-error');
    if (!note) { note = document.createElement('small'); note.className = 'field-error'; note.setAttribute('role', 'alert'); field.appendChild(note); }
    note.textContent = msg;
    el.setAttribute('aria-invalid', 'true');
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    el.focus({ preventScroll: true });
  };
  const clearError = id => {
    const el = q(id), field = el.closest('.field') || el.parentElement;
    field.classList.remove('invalid');
    field.querySelector('.field-error')?.remove();
    el.removeAttribute('aria-invalid');
  };
  ['rights', 'aiGenerated'].forEach(id => q(id)?.addEventListener('change', () => clearError(id)));

  // Remember the usage-rights choice on this device (the AI-generated answer is per video, so it is not remembered).
  const restoreRights = () => {
    const saved = store.get('vfRights'), sel = q('rights');
    if (saved && sel && !sel.value && [...sel.options].some(o => o.value === saved && !o.disabled)) sel.value = saved;
  };
  q('rights')?.addEventListener('change', e => store.set('vfRights', e.target.value));
  const baseReset = window.resetAnalyzeWizard;
  window.resetAnalyzeWizard = () => { baseReset(); restoreRights(); clearError('rights'); clearError('aiGenerated'); };
  restoreRights();
})();

/* ---------- Inbox (Danh sách duyệt): grouped video list + AI/human preview pane ---------- */
(() => {
  const q = id => document.getElementById(id);
  const mobile = () => matchMedia('(max-width:870px)').matches;
  const pad = n => String(n).padStart(2, '0');
  const when = iso => {
    const d = new Date(iso); if (isNaN(d)) return '';
    const now = new Date(), sameDay = d.toDateString() === now.toDateString();
    const y = new Date(now); y.setDate(now.getDate() - 1);
    const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    return sameDay ? hm : d.toDateString() === y.toDateString() ? `${hm} hôm qua` : `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${hm}`;
  };
  const shortWhen = iso => { const d = new Date(iso); if (isNaN(d)) return ''; return d.toDateString() === new Date().toDateString() ? `${pad(d.getHours())}:${pad(d.getMinutes())}` : `${pad(d.getDate())}/${pad(d.getMonth() + 1)}`; };
  const initials = n => String(n || '').trim().split(/\s+/).filter(Boolean).map(w => w[0]).filter((_, i, a) => i === 0 || i === a.length - 1).join('').toUpperCase() || '?';
  const groupOf = j => j.review_decision ? 'done' : j.status === 'failed' ? 'failed' : (j.status === 'queued' || j.status === 'processing') ? 'running' : 'todo';
  const GROUPS = [['todo', 'Chờ bạn duyệt'], ['running', 'AI đang phân tích'], ['failed', 'Lỗi xử lý'], ['done', 'Đã quyết định']];
  const decisionLabel = r => r ? (r.reference_scope === 'test' && r.decision === 'Pass' ? 'Pass (kiểm thử)' : decisionText[r.decision] || r.decision) : '';
  // One renderer for status labels (filled "pill" badges, same classes as the rest of the app).
  window.statusMark = (key, label) => `<span class="pill ${esc(key || '')}">${esc(label)}</span>`;
  let sel = null;
  const cache = new Map();

  window.inboxList = (list, mode) => {
    const byGroup = Object.fromEntries(GROUPS.map(([g]) => [g, []]));
    list.forEach(j => byGroup[groupOf(j)].push(j));
    window.queueOrder = GROUPS.flatMap(([g]) => byGroup[g].map(j => j.id));
    if (!window.queueOrder.includes(sel)) sel = window.queueOrder[0] || null;
    if (!list.length) {
      const empty = !jobs.length
        ? '<b>Chưa có video nào</b><span>Tải video đầu tiên lên, AI sẽ phân tích rồi chuyển vào đây cho bạn duyệt.</span><button type="button" class="button" onclick="openTab(\'analyze\')">+ Phân tích video</button>'
        : q('queueSearch').value.trim() ? '<b>Không tìm thấy video phù hợp</b><span>Thử từ khóa khác hoặc chọn "Tất cả".</span>'
        : mode === 'pending' ? '<b>Đã duyệt toàn bộ video</b><span>Không còn video chờ duyệt. Video mới sẽ xuất hiện ở đây khi AI phân tích xong.</span>'
        : '<b>Chưa có video ở mục này</b><span>Chọn "Tất cả" để xem toàn bộ video.</span>';
      return `<div class="inbox-empty">${empty}</div>`;
    }
    const shown = GROUPS.filter(([g]) => byGroup[g].length);
    return shown.map(([g, label]) => (shown.length > 1 ? `<div class="igroup"><span>${label}</span><span>${byGroup[g].length}</span></div>` : '') + byGroup[g].map(j => {
      const tag = g === 'todo' ? (j.ai_recommendation ? statusMark(j.ai_recommendation.decision, 'AI: ' + decisionLabel(j.ai_recommendation)) : '')
        : g === 'running' ? statusMark('processing', 'Đang phân tích')
        : g === 'failed' ? statusMark('failed', 'Phân tích lỗi')
        : statusMark(j.review_decision, decisionText[j.review_decision] || j.review_decision);
      return `<div class="rowlink inbox-item g-${g}${j.id === sel ? ' sel' : ''}" tabindex="0" role="button" data-job="${esc(j.id)}" aria-current="${j.id === sel}"><span class="ii-main"><b>${esc(j.filename)}</b><small>${esc(j.sku)} · ${esc(j.product_name)}</small><span class="ii-tags">${tag}</span></span><span class="ii-time">${esc(shortWhen(j.created_at))}</span></div>`;
    }).join('')).join('');
  };

  const pick = (id, { focus = false } = {}) => {
    if (!id) return;
    sel = id;
    document.querySelectorAll('#queueTable .inbox-item').forEach(el => { const on = el.dataset.job === id; el.classList.toggle('sel', on); el.setAttribute('aria-current', String(on)); if (on && focus) el.focus(); });
    renderInboxDetail();
  };
  window.inboxSelect = pick;
  window.inboxSelected = () => sel;
  window.inboxForget = id => cache.delete(id);
  const list = q('queueTable');
  list?.addEventListener('click', e => { const it = e.target.closest('.inbox-item'); if (!it) return; mobile() ? showJob(it.dataset.job) : pick(it.dataset.job); });
  list?.addEventListener('dblclick', e => { const it = e.target.closest('.inbox-item'); if (it) showJob(it.dataset.job); });
  list?.addEventListener('focusin', e => { const it = e.target.closest('.inbox-item'); if (it && it.dataset.job !== sel) pick(it.dataset.job); });
  list?.addEventListener('keydown', e => { const it = e.target.closest('.inbox-item'); if (it && e.key === 'Enter') { e.preventDefault(); showJob(it.dataset.job); } });

  const ACTIONS = {
    uploaded: () => 'Video được tải lên',
    analysis_completed: p => 'AI phân tích xong' + (p.decision ? ', đề xuất ' + (decisionText[p.decision] || p.decision) : ''),
    analysis_failed: () => 'AI phân tích không thành công',
    reanalyze_requested: () => 'yêu cầu phân tích lại',
    product_changed: () => 'đổi sản phẩm tham chiếu',
    flag_review: p => p.state === 'confirmed' ? 'xác nhận một cảnh báo là lỗi' : p.state === 'rejected' ? 'bác bỏ một cảnh báo' : 'bỏ đánh dấu một cảnh báo',
    review_decision: p => 'quyết định: ' + (decisionText[p.decision] || p.decision || ''),
    ground_truth_label: () => 'gán nhãn đánh giá',
    job_recovered: () => 'Phiên phân tích được khôi phục',
    recovery_failed: () => 'Khôi phục phiên phân tích không thành công'
  };
  const feed = audits => {
    const rows = (audits || []).slice(0, 6).map(a => {
      let p = {}; try { p = typeof a.payload === 'string' ? JSON.parse(a.payload) : (a.payload || {}); } catch (_) {}
      const sys = a.actor === 'system', fn = ACTIONS[a.action];
      const text = fn ? fn(p) : a.action;
      const who = sys ? '' : `<b>${esc(a.actor)}</b> `;
      const av = sys ? (a.action === 'uploaded' ? '<span class="av up" aria-hidden="true">↑</span>' : '<span class="av ai" aria-hidden="true">AI</span>') : `<span class="av h" aria-hidden="true">${esc(initials(a.actor))}</span>`;
      return `<div class="ev">${av}<div><p>${who}${esc(text)}</p><small>${esc(when(a.created_at))}</small></div></div>`;
    }).join('');
    return rows ? `<div class="ifeed"><h4>Hoạt động</h4>${rows}</div>` : '';
  };

  const detailHtml = d => {
    const g = groupOf(d), rec = d.status === 'completed' ? (d.ai_recommendation || d.details?.ai_recommendation) : null;
    const frame = (d.details?.frame_timeline || [])[0]?.frame || d.evidence?.find(e => e.frame)?.frame;
    const dur = Number(d.details?.duration);
    const meta = [d.product?.sku, d.product?.name, dur ? dur.toLocaleString('vi-VN', { maximumFractionDigits: 1 }) + ' giây' : '', 'tải lên ' + when(d.created_at)].filter(Boolean).map(esc).join(' · ');
    const state = { todo: ['Chờ bạn duyệt', 'Needs Review'], running: ['AI đang phân tích', 'processing'], failed: ['Phân tích lỗi', 'failed'], done: ['Đã quyết định', d.review_decision] }[g];
    const findings = d.findings || [], pending = findings.filter(f => f.flag_review === 'unreviewed').length;
    let ai;
    if (g === 'running') ai = esc(progressText(d) || 'Đang phân tích video…');
    else if (d.status === 'failed') ai = `Chưa phân tích được video này${d.details?.error ? ': ' + esc(d.details.error) : '.'}`;
    else {
      const sev = { high: 0, medium: 0, low: 0 }; findings.forEach(f => { sev[f.severity] = (sev[f.severity] || 0) + 1; });
      const sevText = [['high', 'cao'], ['medium', 'trung bình'], ['low', 'thấp']].filter(([k]) => sev[k]).map(([k, n]) => `${sev[k]} mức ${n}`).join(', ');
      const names = findings.slice(0, 3).map(f => '"' + esc(findingNames[f.code] || f.code) + '"').join(', ');
      ai = (rec ? `Đề xuất ${statusMark(rec.decision, decisionLabel(rec))}` : 'Chưa có đề xuất.')
        + (findings.length ? `<span class="bub-line">${findings.length} cảnh báo (${sevText}): ${names}${findings.length > 3 ? ` và ${findings.length - 3} cảnh báo khác` : ''}.</span>` : `<span class="bub-line">${esc(rec?.explanation || 'Không thấy cảnh báo trong các phần đã kiểm tra.')}</span>`);
    }
    const c = d.details?.coverage || {}, truth = d.details?.product_truth_snapshot || {};
    const tasks = [];
    if (d.status === 'completed') {
      if (findings.length) tasks.push([`Xác nhận ${findings.length} cảnh báo` + (pending && pending < findings.length ? ` (còn ${pending})` : ''), !pending]);
      if (!['reviewed', 'test_reference_approved'].includes(truth.reference_status)) tasks.push([`Kiểm tra sản phẩm ${d.product?.sku || ''}`.trim(), false]);
      if (['ocr', 'asr', 'vlm'].some(k => c[k] !== 'ok')) tasks.push(['Xem lại thủ công (một số nguồn AI chưa chạy)', false]);
      tasks.push(['Chọn quyết định', !!d.review_decision]);
    }
    const me = currentReviewerName();
    const human = d.review_decision
      ? `<div class="msg me"><span class="av h" aria-hidden="true">${esc(initials(d.reviewer || me))}</span><div class="bub">Đã quyết định ${statusMark(d.review_decision, decisionText[d.review_decision] || d.review_decision)}${d.reviewer ? ' · ' + esc(d.reviewer) : ''}${d.review_note ? `<span class="bub-note">Ghi chú: ${esc(d.review_note)}</span>` : ''}</div></div>`
      : tasks.length ? `<div class="msg me"><span class="av h" aria-hidden="true">${esc(initials(me))}</span><div class="bub"><b>Việc của bạn</b><ul class="chk">${tasks.map(([t, done]) => `<li class="${done ? 'done' : ''}">${esc(t)}</li>`).join('')}</ul></div></div>` : '';
    const jid = esc(d.id);
    const cta = g === 'todo' ? `<button type="button" class="button" onclick="showJob('${jid}')">Bắt đầu duyệt <kbd>Enter</kbd></button>`
      : g === 'done' ? `<button type="button" class="button secondary" onclick="showJob('${jid}')">Xem lại video</button>`
      : g === 'running' ? `<button type="button" class="button secondary" onclick="showJob('${jid}')">Mở theo dõi</button>`
      : `<button type="button" class="button" onclick="inboxReanalyze('${jid}')">↻ Phân tích lại</button><button type="button" class="button secondary" onclick="showJob('${jid}')">Xem chi tiết lỗi</button>`;
    const coverageOk = ['ocr', 'asr', 'vlm'].every(k => c[k] === 'ok');
    const truthOk = ['reviewed', 'test_reference_approved'].includes(truth.reference_status);
    const keys = d.status === 'completed' ? `<div class="ikeys">${[
      ['!', findings.length ? `${findings.length} cảnh báo` : 'Không có cảnh báo', findings.length ? (pending ? `còn ${pending} chưa xác minh` : 'đã xác minh hết') : 'trong phần đã kiểm tra'],
      ['◇', 'Sản phẩm', truthOk ? 'đã xác minh' : 'chưa xác minh'],
      ['↻', 'Nguồn AI', coverageOk ? 'chạy đủ' : 'một số chưa chạy']
    ].map(([i, b, s]) => `<div class="ikey"><span class="ic" aria-hidden="true">${i}</span><div><b>${esc(b)}</b><small>${esc(s)}</small></div></div>`).join('')}</div>` : '';
    const order = window.queueOrder || [], i = order.indexOf(d.id);
    const nextBtn = order.length > 1 ? `<button type="button" class="button ghost" onclick="inboxStep(1)">Video sau <kbd>J</kbd></button>` : '';
    return `<div class="idh"><div><h3>${esc(d.filename)}</h3><p>${meta}</p></div>${statusMark(state[1], state[0])}</div>
      <div class="idp"><button type="button" class="ithumb" onclick="showJob('${jid}')" aria-label="Mở video ${esc(d.filename)}"${frame ? ` style="background-image:url('/api/jobs/${jid}/frames/${esc(frame)}')"` : ''}><span aria-hidden="true">▶</span></button>
      <div class="iconv"><div class="msg"><span class="av ai" aria-hidden="true">AI</span><div class="bub">${ai}</div></div>${human}<div class="cta">${cta}${nextBtn}</div>${keys}</div></div>${feed(d.audits)}`;
  };

  window.renderInboxDetail = async () => {
    const box = q('inboxDetail'); if (!box) return;
    if (!sel) {
      box.innerHTML = jobs.length ? '<div class="idempty"><b>Chọn một video</b><span>Tóm tắt của AI và việc bạn cần làm sẽ hiện ở đây.</span></div>'
        : '<div class="idempty"><b>Danh sách duyệt đang trống</b><span>Khi bạn tải video lên, AI sẽ phân tích trước rồi chuyển vào đây để bạn xác minh và quyết định.</span></div>';
      return;
    }
    const id = sel, j = jobs.find(x => x.id === id);
    const key = j ? [j.status, j.review_decision].join('|') : '';
    const hit = cache.get(id);
    if (hit && hit.key === key && Date.now() - hit.at < 15000) { box.innerHTML = detailHtml(hit.d); return; }
    if (!hit) box.innerHTML = '<div class="skeleton"><i></i><i></i><i></i></div>';
    try {
      const d = await api('/api/jobs/' + id);
      cache.set(id, { d, key, at: Date.now() });
      if (sel === id) box.innerHTML = detailHtml(d);
    } catch (e) { if (sel === id) box.innerHTML = `<div class="idempty"><b>Không tải được video</b><span>${esc(e.message)}</span></div>`; }
  };
  window.heroStart = () => {
    const first = (window.queueOrder || []).find(id => { const j = jobs.find(x => x.id === id); return j && groupOf(j) === 'todo'; })
      || jobs.find(j => groupOf(j) === 'todo')?.id;
    first ? showJob(first) : openTab('analyze');
  };
  // Shrink the illustration while the list or the preview is scrolled.
  const heroScroll = () => {
    const y = Math.max(q('queueTable')?.scrollTop || 0, q('inboxDetail')?.scrollTop || 0);
    q('queue').classList.toggle('hero-min', y > 24);
  };
  q('queueTable')?.addEventListener('scroll', heroScroll, { passive: true });
  q('inboxDetail')?.addEventListener('scroll', heroScroll, { passive: true });
  window.inboxStep = dir => {
    const order = window.queueOrder || [], i = order.indexOf(sel), next = order[i + dir];
    if (next) pick(next, { focus: true });
  };
  window.inboxReanalyze = async id => {
    if (!confirm('Chạy lại phân tích cho video này?')) return;
    try { await api(`/api/jobs/${id}/reanalyze`, { method: 'POST' }); cache.delete(id); toast('Đã yêu cầu phân tích lại'); await refreshAll(); } catch (e) { toast(e.message); }
  };
  window.inboxLead = () => {
    const todo = jobs.filter(j => groupOf(j) === 'todo').length, run = jobs.filter(j => groupOf(j) === 'running').length;
    const unverified = products.filter(p => !['reviewed', 'test_reference_approved'].includes(p.reference_status)).length;
    const me = currentReviewerName();
    q('queueHeading').textContent = me ? 'Danh sách duyệt của ' + me.trim().split(/\s+/).pop() : 'Danh sách duyệt';
    if (q('queue').classList.contains('active') && !q('queue').classList.contains('reviewing')) q('currentSectionLabel').textContent = tabNames.queue;
    const parts = [todo ? `${todo} video chờ bạn duyệt` : 'Không có video nào chờ bạn', run ? `AI đang phân tích ${run} video` : '', unverified ? `${unverified} sản phẩm cần xác minh` : ''].filter(Boolean);
    if (q('inboxLead')) q('inboxLead').textContent = parts.join(' · ');
    if (q('heroTitle')) {
      q('heroTitle').textContent = todo ? `${todo} video chờ duyệt` : run ? `AI đang phân tích ${run} video` : jobs.length ? 'Đã duyệt toàn bộ video' : 'Chưa có video cần duyệt';
      q('heroCta').textContent = todo ? 'Bắt đầu duyệt →' : 'Phân tích video mới →';
    }
  };
})();
