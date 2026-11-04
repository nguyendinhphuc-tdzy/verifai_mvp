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
      const row = document.querySelector(`#queueTable tr[data-job="${CSS.escape(id)}"]`);
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
    if (firstReady) todo.push(['✓', `${ready.length} video đã phân tích xong, đang chờ bạn duyệt`, 'Mở video đầu tiên, duyệt xong sẽ tự chuyển sang video tiếp theo.', 'Duyệt ngay', `showJob('${esc(firstReady.id)}')`]);
    if (c.processing) todo.push(['◔', `${c.processing} video đang được phân tích`, 'Hàng đợi tự cập nhật khi phân tích xong.', 'Xem tiến độ', "openQueueFilter('processing')"]);
    if (c.failed) todo.push(['!', `${c.failed} video bị lỗi xử lý`, 'Mở để xem lỗi và phân tích lại.', 'Xem video lỗi', "openQueueFilter('failed')"]);
    if (unverified) todo.push(['◇', `${unverified} sản phẩm chưa xem xét nguồn`, 'AI sẽ không đề xuất Chấp thuận khi nguồn sản phẩm chưa được xác minh.', 'Xem sản phẩm', "openTab('products');setProductFilter('unverified')"]);
    q('overviewTodo').innerHTML = `<div class="review-subhead"><h3>Việc cần làm</h3></div>` + (todo.length
      ? todo.map(t => `<div class="todo-item"><span class="todo-ic" aria-hidden="true">${t[0]}</span><div><b>${esc(t[1])}</b><small>${esc(t[2])}</small></div><button type="button" class="mini" onclick="${t[4]}">${esc(t[3])} →</button></div>`).join('')
      : '<div class="todo-done">Không còn việc tồn đọng. Mọi video đã được duyệt.</div>');
  };
})();
