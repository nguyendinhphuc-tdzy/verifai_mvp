/* VerifAI leaves.
   - vfDropLeaf(art, tree): one leaf drifts down from a tree crown (idle, Home hero).
   - vfLeafGust({origins}): the single exit gust. Leaves tear off the given tree
     crowns and blow left to right across the screen; without visible origins
     they enter from the left edge. Both respect reduced motion. */
(() => {
  // Palette sampled from the painted tree crowns.
  const COLORS = ['#217542', '#388a4a', '#539d4f', '#6fae4a', '#92c246', '#a2cd6e', '#c6df8a'];
  const SHAPES = [
    'M0 -13 C8 -8 9 4 0 13 C-9 4 -8 -8 0 -13Z',
    'M0 -15 C11 -6 8 9 0 15 C-5 6 -7 -7 0 -15Z',
    'M0 -12 C5 -12 10 -4 0 12 C-10 -4 -5 -12 0 -12Z',
    'M-2 -14 C9 -10 10 6 1 14 C-6 8 -9 -6 -2 -14Z'
  ];
  const NS = 'http://www.w3.org/2000/svg';
  const rnd = (a, b) => a + Math.random() * (b - a);
  const pick = a => a[Math.floor(Math.random() * a.length)];
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

  function leaf(size) {
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '-16 -16 32 32');
    svg.setAttribute('width', size); svg.setAttribute('height', size);
    const body = document.createElementNS(NS, 'path');
    body.setAttribute('d', pick(SHAPES)); body.setAttribute('fill', pick(COLORS));
    const vein = document.createElementNS(NS, 'path');
    vein.setAttribute('d', 'M0 -10 C1 -2 1 5 0 12');
    vein.setAttribute('stroke', 'rgba(255,253,230,.55)'); vein.setAttribute('stroke-width', '1.2');
    vein.setAttribute('stroke-linecap', 'round'); vein.setAttribute('fill', 'none');
    svg.append(body, vein);
    return svg;
  }
  // A point inside the upper (leafy) part of a tree element.
  function crownPoint(el, rect) {
    const r = rect || el.getBoundingClientRect();
    return { x: r.left + r.width * rnd(.12, .88), y: r.top + r.height * rnd(.05, .62) };
  }

  window.vfDropLeaf = (art, tree) => {
    if (reduced() || !art || !tree) return;
    const a = art.getBoundingClientRect(), p = crownPoint(tree);
    const size = rnd(14, 26) * (a.width / 1470);
    const el = leaf(Math.max(10, size)); el.classList.add('leaf-fall');
    art.appendChild(el);
    const x0 = p.x - a.left, y0 = p.y - a.top, fall = a.height * rnd(.32, .55), drift = rnd(40, 160);
    const r0 = rnd(0, 360), spin = rnd(160, 420) * (Math.random() < .5 ? -1 : 1), sway = rnd(18, 40);
    const at = (t, w) => `translate(${x0 + drift * t + w}px,${y0 + fall * t}px) rotate(${r0 + spin * t}deg)`;
    const anim = el.animate([
      { transform: at(0, 0), opacity: 0 },
      { transform: at(.1, sway * .3), opacity: 1, offset: .08 },
      { transform: at(.35, -sway), offset: .35 },
      { transform: at(.6, sway), offset: .6 },
      { transform: at(.85, -sway * .5), opacity: .9, offset: .85 },
      { transform: at(1, 0), opacity: 0 }
    ], { duration: rnd(4200, 6500), easing: 'linear', fill: 'both' });
    anim.onfinish = () => el.remove();
  };

  // The single exit gust, simulated: leaves detach one by one from the crowns,
  // each with its own weight and drag, and are carried by a rising, turbulent
  // wind (left to right) while tumbling. Returns the expected duration (ms).
  window.vfLeafGust = ({ count = 70, duration = 1600, origins = [] } = {}) => {
    if (reduced()) return 0;
    const W = innerWidth, H = innerHeight;
    const live = origins.map(o => ({ ...o, r: o.el?.getBoundingClientRect() }))
      .filter(o => o.r && o.r.bottom > 0 && o.r.top < H && o.r.right > 0 && o.r.left < W);
    const total = live.reduce((s, o) => s + (o.weight || 1), 0);
    const layer = document.createElement('div');
    layer.className = 'vf-gust'; layer.setAttribute('aria-hidden', 'true');
    layer.style.cssText = 'position:fixed;inset:0;z-index:10001;pointer-events:none;overflow:hidden';
    const windMax = W * rnd(1.45, 1.65);                 // px/s at full strength
    const leaves = [];
    for (let i = 0; i < count; i++) {
      let src = null;
      if (live.length) { let k = Math.random() * total; src = live.find(o => (k -= (o.weight || 1)) < 0) || live[0]; }
      const p = src ? crownPoint(null, src.r) : { x: -rnd(30, 160), y: rnd(.05, .95) * H };
      const size = rnd(14, 50) * (W < 600 ? .75 : 1);
      const el = leaf(size);
      el.style.cssText = 'position:absolute;left:0;top:0;opacity:0;filter:drop-shadow(0 5px 6px rgba(20,40,33,.18));will-change:transform,opacity';
      layer.appendChild(el);
      const light = 1 - (size - 14) / 36;            // small leaves are light and catch the wind fast
      leaves.push({
        el, half: size / 2, x: p.x, y: p.y,
        vx: rnd(-30, 30), vy: rnd(-40, 30),
        // detach times skew early but keep trickling: no single clump
        at: Math.pow(Math.random(), 1.4) * duration * .42,
        drag: rnd(2.4, 3.6) + light * 2.2,
        lane: rnd(-.5, .12) * H,                     // each leaf rides its own vertical current
        fall: rnd(120, 260) * (1.2 - light * .5),
        rot: rnd(0, 360), spin: rnd(90, 420) * (Math.random() < .5 ? -1 : 1),
        flip: rnd(0, 6.28), flipSpeed: rnd(4, 11), ph: rnd(0, 6.28), wob: rnd(30, 110),
        on: false, done: false
      });
    }
    document.body.appendChild(layer);
    const t0 = performance.now(); let last = t0, raf = 0;
    const ease = t => t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t);
    const frame = now => {
      const dt = Math.min(.05, (now - last) / 1000); last = now;
      const ms = now - t0, t = ms / 1000;
      let alive = 0;
      for (const L of leaves) {
        if (L.done) continue;
        alive++;
        if (ms < L.at) continue;
        const age = (ms - L.at) / 1000;
        if (!L.on) { L.on = true; L.el.style.opacity = '1'; }
        // wind builds up over ~0.7s, gusts vary with time and height
        const gust = 1 + .28 * Math.sin(t * 4.3 + L.y * .012) + .12 * Math.sin(t * 9.1 + L.ph);
        const wx = windMax * ease(t / .4 + .1) * gust * ease(age / .22 + .2);
        const wy = L.lane * ease(age / .35) + Math.sin(t * 3.1 + L.x * .007 + L.ph) * H * .12;
        L.vx += (wx - L.vx) * L.drag * dt;
        L.vy += ((wy - L.vy) * L.drag + L.fall) * dt;
        // flutter: a falling leaf rocks side to side as it tumbles
        L.flip += L.flipSpeed * dt;
        const flut = Math.sin(L.flip + L.ph) * L.wob;
        L.x += L.vx * dt; L.y += (L.vy + flut * .6) * dt;
        L.rot += (L.spin + L.vx * .08) * dt;
        const sy = Math.cos(L.flip), sc = .15 + .85 * Math.abs(sy);
        L.el.style.transform = `translate3d(${(L.x - L.half).toFixed(1)}px,${(L.y - L.half).toFixed(1)}px,0) rotate(${L.rot.toFixed(1)}deg) scale(1,${(sy < 0 ? -sc : sc).toFixed(3)})`;
        if (L.x > W + 120 || L.y > H + 120 || L.y < -220 || age > 4) { L.done = true; L.el.remove(); }
      }
      if (alive) raf = requestAnimationFrame(frame); else layer.remove();
    };
    raf = requestAnimationFrame(frame);
    setTimeout(() => { cancelAnimationFrame(raf); layer.remove(); }, 6000);
    return duration + 900;
  };
})();
