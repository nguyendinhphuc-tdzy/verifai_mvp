/* VerifAI sound effects (Home + workspace).
   Every sound is synthesised with the Web Audio API: no audio files, nothing
   to download or license. The palette follows the art direction: wooden
   taps, paper, wind and soft bells, tuned to C major pentatonic so sounds
   that overlap never clash.
   - window.vfSfx.play(name)   play one sound (no-op when muted)
   - window.vfSfx.toggle()     mute / unmute, remembered in localStorage.vfSound
   - Buttons with [data-sound-toggle] show and switch the state; key M toggles.
   - The AudioContext starts on the first click or key press (browser policy). */
(() => {
  const KEY = 'vfSound';
  const store = {
    get() { try { return localStorage.getItem(KEY); } catch (e) { return null; } },
    set(v) { try { localStorage.setItem(KEY, v); } catch (e) { /* private mode */ } }
  };
  const AC = window.AudioContext || window.webkitAudioContext;
  let on = store.get() !== 'off';
  let ctx = null, master = null, noiseBuf = null;

  function ensure() {
    if (!AC) return null;
    if (!ctx) {
      ctx = new AC();
      master = ctx.createGain(); master.gain.value = .55;
      const comp = ctx.createDynamicsCompressor();
      comp.threshold.value = -18; comp.ratio.value = 4;
      master.connect(comp).connect(ctx.destination);
      noiseBuf = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
      const d = noiseBuf.getChannelData(0);
      for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    }
    if (ctx.state === 'suspended') ctx.resume().catch(() => {});
    return ctx;
  }
  const unlock = () => { if (on) ensure(); };
  addEventListener('pointerdown', unlock, { capture: true, passive: true });
  addEventListener('keydown', unlock, { capture: true });

  /* ---------- voices ---------- */
  function env(g, t, a, peak, dur) {
    g.gain.setValueAtTime(.0001, t);
    g.gain.exponentialRampToValueAtTime(peak, t + a);
    g.gain.exponentialRampToValueAtTime(.0001, t + Math.max(dur, a + .01));
  }
  function osc(freq, t, dur, { type = 'sine', vol = .2, a = .004, glide = 0 } = {}) {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = type; o.frequency.setValueAtTime(freq, t);
    if (glide) o.frequency.exponentialRampToValueAtTime(freq * glide, t + dur);
    env(g, t, a, vol, dur);
    o.connect(g).connect(master); o.start(t); o.stop(t + dur + .05);
  }
  // Wooden bar: fundamental plus a short inharmonic partial (marimba-like).
  function wood(freq, t, vol = .16, dur = .32) {
    osc(freq, t, dur, { vol, a: .003 });
    osc(freq * 3.93, t, dur * .16, { vol: vol * .32, a: .002 });
  }
  // Soft bell: partials at 1, 2.76 and 5.4.
  function bell(freq, t, vol = .1, dur = 1.1) {
    osc(freq, t, dur, { vol, a: .004 });
    osc(freq * 2.76, t, dur * .45, { vol: vol * .28, a: .003 });
    osc(freq * 5.4, t, dur * .18, { vol: vol * .1, a: .002 });
  }
  function noise(t, dur, { vol = .1, type = 'bandpass', f = 2000, f2 = 0, q = 1, a = .005 } = {}) {
    const s = ctx.createBufferSource(), fl = ctx.createBiquadFilter(), g = ctx.createGain();
    s.buffer = noiseBuf; s.loop = true;
    fl.type = type; fl.frequency.setValueAtTime(f, t);
    if (f2) fl.frequency.exponentialRampToValueAtTime(f2, t + dur);
    fl.Q.value = q;
    env(g, t, a, vol, dur);
    s.connect(fl).connect(g).connect(master);
    s.start(t, Math.random() * 1.5); s.stop(t + dur + .05);
  }

  const N = { D4: 293.66, E4: 329.63, G4: 392, A4: 440, C5: 523.25, D5: 587.33, E5: 659.25, G5: 783.99, A5: 880, C6: 1046.5, E6: 1318.51, G6: 1567.98 };
  const SOUNDS = {
    // UI feedback
    tick: t => { osc(2300, t, .03, { type: 'triangle', vol: .04, a: .001 }); noise(t, .02, { vol: .025, type: 'highpass', f: 4500, a: .001 }); },
    tap: t => wood(N.G5, t, .1, .22),
    tab: t => wood(N.E5, t, .08, .18),
    paper: t => noise(t, .14, { vol: .07, f: 2600, f2: 5200, q: .8 }),
    open: t => { noise(t, .16, { vol: .06, f: 1800, f2: 4200, q: .8 }); wood(N.C5, t + .04, .08, .22); },
    slide: t => noise(t, .24, { vol: .06, type: 'lowpass', f: 500, f2: 2400, q: .7, a: .04 }),
    switch: t => { osc(1500, t, .025, { type: 'triangle', vol: .05, a: .001 }); osc(950, t + .05, .03, { type: 'triangle', vol: .05, a: .001 }); },
    on: t => { wood(N.C5, t, .1); wood(N.G5, t + .08, .1); },
    // Findings
    confirm: t => { wood(N.A4, t, .15, .3); wood(N.E4, t + .07, .11, .34); },
    reject: t => { wood(N.E5, t, .11, .24); wood(N.G5, t + .07, .09, .28); },
    unflag: t => wood(N.C5, t, .08, .16),
    allDone: t => { bell(N.C6, t, .07, .9); bell(N.E6, t + .08, .06, .9); bell(N.G6, t + .16, .06, 1.2); },
    // Decisions
    approve: t => { wood(N.C5, t, .12); wood(N.G5, t + .09, .12); bell(N.C6, t + .18, .07, 1); },
    review: t => { wood(N.E5, t, .1, .22); wood(N.E5, t + .13, .08, .26); },
    redo: t => { wood(N.G4, t, .12, .28); wood(N.D4, t + .1, .11, .36); },
    // System
    notify: t => { bell(N.G5, t, .08, .9); bell(N.C6, t + .16, .08, 1.2); },
    error: t => { osc(220, t, .16, { type: 'triangle', vol: .11 }); osc(185, t + .14, .24, { type: 'triangle', vol: .1 }); },
    sent: t => { noise(t, .45, { vol: .07, f: 400, f2: 3200, q: 1.2, a: .14 }); wood(N.G5, t + .36, .08, .22); },
    // Home: the leaf gust that carries the page away
    gust: t => {
      const s = ctx.createBufferSource(), fl = ctx.createBiquadFilter(), g = ctx.createGain();
      s.buffer = noiseBuf; s.loop = true;
      fl.type = 'bandpass'; fl.Q.value = .6;
      fl.frequency.setValueAtTime(240, t);
      fl.frequency.exponentialRampToValueAtTime(950, t + .7);
      fl.frequency.exponentialRampToValueAtTime(520, t + 1.9);
      g.gain.setValueAtTime(.0001, t);
      g.gain.exponentialRampToValueAtTime(.17, t + .55);
      g.gain.setValueAtTime(.17, t + 1.05);
      g.gain.exponentialRampToValueAtTime(.0001, t + 2);
      s.connect(fl).connect(g).connect(master); s.start(t); s.stop(t + 2.05);
      noise(t + .25, 1.4, { vol: .035, f: 1400, f2: 2600, q: 4, a: .4 });   // faint whistle
      for (let i = 0; i < 28; i++) {                                          // leaves rustling
        noise(t + .15 + Math.random() * 1.45, .03 + Math.random() * .06,
          { vol: .015 + Math.random() * .035, type: 'highpass', f: 2800 + Math.random() * 3200, q: .5, a: .002 });
      }
    }
  };

  const last = {};
  function play(name) {
    if (!on || !SOUNDS[name]) return;
    const c = ensure();
    if (!c) return;
    const go = () => {
      const now = c.currentTime;
      if (last[name] && now - last[name] < .045) return;  // avoid stacking on double events
      last[name] = now;
      try { SOUNDS[name](now + .005); } catch (e) { /* never break the UI for a sound */ }
      document.dispatchEvent(new CustomEvent('vf-sfx', { detail: name }));   // for tests / analytics
    };
    if (c.state === 'running') go();
    // Just created inside this click: wait for the context to start. Without a
    // user gesture (e.g. a background notification) stay silent instead.
    else if (navigator.userActivation ? navigator.userActivation.isActive : true) c.resume().then(go, () => {});
  }

  /* ---------- mute toggle ---------- */
  const ICON_ON = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/></svg>';
  const ICON_OFF = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9.5h3.5L12 5.5v13l-4.5-4H4z"/><path d="m16 9.5 5 5M21 9.5l-5 5"/></svg>';
  function sync() {
    document.querySelectorAll('[data-sound-toggle]').forEach(b => {
      b.innerHTML = on ? ICON_ON : ICON_OFF;
      b.setAttribute('aria-pressed', String(on));
      b.title = on ? 'Tắt âm thanh (M)' : 'Bật âm thanh (M)';
      b.setAttribute('aria-label', on ? 'Tắt âm thanh' : 'Bật âm thanh');
    });
  }
  function toggle() {
    on = !on; store.set(on ? 'on' : 'off'); sync();
    if (on) { ensure(); setTimeout(() => play('on'), 30); }
  }

  /* ---------- automatic hooks ---------- */
  // First matching rule wins; null = handled elsewhere (sound plays on success).
  const RULES = [
    ['[data-sound-toggle], [data-decision], .fverdict button, [data-enter], .piano-box *', null],
    ['.side-toggle', 'slide'],
    ['#themeToggle', 'switch'],
    ['.nav button, .nav-links a', 'tap'],
    ['.rtabs button, .qtabs button, .tab, [role="tab"]', 'tab'],
    ['.ftoggle, summary', 'paper'],
    ['[onclick*="showJob"], [onclick*="heroStart"]', 'open'],
    ['#queueTable .rowlink', 'tap'],
    ['button, .button, .btn, .icon-btn, a.mini', 'tick']
  ];
  document.addEventListener('click', e => {
    if (!on) return;
    const el = e.target.closest?.('button, a, summary, [role="tab"], [role="button"], .rowlink');
    if (!el || el.disabled || el.getAttribute('aria-disabled') === 'true') return;
    for (const [sel, sound] of RULES) if (el.matches(sel)) { if (sound) play(sound); return; }
  }, true);

  const typing = t => t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
  document.addEventListener('keydown', e => {
    if (e.metaKey || e.ctrlKey || e.altKey || typing(e.target) || document.querySelector('dialog[open]')) return;
    if (e.key === 'm' || e.key === 'M') { toggle(); return; }
    if (['j', 'k', 'J', 'K', 'ArrowDown', 'ArrowUp'].includes(e.key) && document.querySelector('#queue.active')) play('tick');
  });

  // Workspace: a bell when a video finishes analysing, a low tone if it fails.
  // refreshAll is defined by the inline script, which runs before DOMContentLoaded.
  document.addEventListener('DOMContentLoaded', () => {
    sync();
    const orig = window.refreshAll;
    if (typeof orig !== 'function') return;
    let prev = null;
    window.refreshAll = async function (...args) {
      const result = await orig.apply(this, args);
      try {
        const list = typeof jobs !== 'undefined' && Array.isArray(jobs) ? jobs : [];
        const now = new Map(list.map(j => [j.id, j.status]));
        if (prev) {
          let done = 0, failed = 0;
          now.forEach((st, id) => {
            const was = prev.get(id);
            if (was === 'queued' || was === 'processing') { if (st === 'completed') done++; else if (st === 'failed') failed++; }
          });
          if (failed) play('error'); else if (done) play('notify');
        }
        prev = now;
      } catch (e) { /* ignore */ }
      return result;
    };
  });

  // Called from flag(): marks a finding, or chimes when the last one is verified.
  function finding(state, findings) {
    if (state === 'unreviewed') return play('unflag');
    const left = (findings || []).filter(f => f.flag_review === 'unreviewed').length;
    play(left ? (state === 'confirmed' ? 'confirm' : 'reject') : 'allDone');
  }
  const DECISION = { 'Pass': 'approve', 'Needs Review': 'review', 'Regenerate': 'redo' };
  const decision = d => play(DECISION[d] || 'tap');

  window.vfSfx = { play, toggle, sync, finding, decision, get enabled() { return on; } };
  sync();
})();
