/* Alfred orb — the interface itself is the face: rings, arcs, ticks and a voice waveform.
   Same API as the old face:  appear() · vanish() · holoMode() · setState(s) · upd(level, lookX, lookY)
   States: idle · listening · thinking · speaking · paused · starting                                  */
(function () {
  const TAU = Math.PI * 2, clamp = (x, a, b) => Math.max(a, Math.min(b, x)), lerp = (a, b, t) => a + (b - a) * t;
  const host = document.getElementById("holo") || document.body;
  const cv = document.createElement("canvas"); cv.style.width = "100%"; cv.style.height = "100%";
  host.appendChild(cv);
  const x = cv.getContext("2d");
  let W = 0, H = 0, DPR = 1;
  function resize() { DPR = Math.min(devicePixelRatio || 1, 2); W = cv.width = (host.clientWidth || 280) * DPR; H = cv.height = (host.clientHeight || 280) * DPR; }
  addEventListener("resize", resize); resize();

  const PAL = {            // rgb, glow strength, spin speed
    starting:  [[125, 160, 255], 1.0, 1.0],
    idle:      [[70, 200, 255], 0.75, 0.35],
    listening: [[120, 240, 255], 1.15, 0.8],
    thinking:  [[255, 176, 70], 1.0, 2.6],
    speaking:  [[90, 220, 255], 1.1, 0.6],
    paused:    [[110, 125, 150], 0.45, 0.1],
  };
  let state = "starting", level = 0, lv = 0, look = { x: 0, y: 0 }, lk = { x: 0, y: 0 };
  let rgb = PAL.starting[0].slice(), glow = 1, spin = 1, flash = 1, mode = "appearing", mt = 0;
  const hist = new Array(96).fill(0);           // waveform history around the core
  const rot = [0, 0, 0, 0, 0];

  window.setState = s => { if (PAL[s] && s !== state) { state = s; flash = 0.8; } };
  window.upd = (l, lx, ly) => { level = clamp(+l || 0, 0, 1); if (lx !== undefined) { look.x = clamp(lx, -1, 1); look.y = clamp(ly, -1, 1); } };
  window.appear = () => { if (mode === "shown" || mode === "appearing") return; mode = "appearing"; mt = 0; flash = 1; };
  window.vanish = () => { if (window.clearPanels) clearPanels(); if (mode === "hidden" || mode === "vanishing") return; mode = "vanishing"; mt = 0; };
  window.holoMode = () => mode;
  window.orbStill = s => { state = s; mode = "shown"; rgb = PAL[s][0].slice(); glow = PAL[s][1]; spin = PAL[s][2]; flash = 0; lv = s === "speaking" ? 0.6 : 0; for (let i = 0; i < hist.length; i++) hist[i] = s === "speaking" ? 0.25 + 0.6 * Math.abs(Math.sin(i * 1.7)) : 0; };  // for tutorial pictures

  const col = (a, k = 1) => `rgba(${Math.round(rgb[0] * k)},${Math.round(rgb[1] * k)},${Math.round(rgb[2] * k)},${clamp(a, 0, 1)})`;
  function arc(r, w, a0, len, a) { x.beginPath(); x.lineWidth = w; x.strokeStyle = col(a); x.arc(0, 0, r, a0, a0 + len); x.stroke(); }
  function ticks(r, n, len, r0, a, every) {
    x.strokeStyle = col(a); x.lineWidth = 1.2 * DPR; x.beginPath();
    for (let i = 0; i < n; i++) { const L = every && i % every === 0 ? len * 2 : len, q = r0 + i * TAU / n;
      x.moveTo(Math.cos(q) * r, Math.sin(q) * r); x.lineTo(Math.cos(q) * (r + L), Math.sin(q) * (r + L)); }
    x.stroke();
  }

  let last = performance.now(), t = 0;
  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min((now - last) / 1000, 0.05); last = now; t += dt;
    if (mode === "hidden") { x.clearRect(0, 0, W, H); return; }
    mt += dt;
    const P = PAL[state];
    for (let i = 0; i < 3; i++) rgb[i] = lerp(rgb[i], P[0][i], 0.08);
    glow = lerp(glow, P[1], 0.06); spin = lerp(spin, P[2], 0.05); flash = Math.max(0, flash - dt * 1.8);
    const live = state === "speaking" || state === "listening" ? level : 0;
    lv = lerp(lv, live, live > lv ? 0.5 : 0.15);
    hist.push(lv * (0.6 + 0.4 * Math.random())); hist.shift();
    lk.x = lerp(lk.x, look.x, 0.06); lk.y = lerp(lk.y, look.y, 0.06);

    let s = 1, a = 1;                                     // appear / vanish envelope
    if (mode === "appearing") { const k = clamp(mt / 0.9, 0, 1); s = 1 + 2.7 * Math.pow(k - 1, 3) + 1.7 * Math.pow(k - 1, 2); a = clamp(mt / 0.35, 0, 1); if (k >= 1) mode = "shown"; }
    else if (mode === "vanishing") { const k = clamp(mt / 0.7, 0, 1); s = 1 - k * 0.85; a = 1 - k; if (k >= 1) mode = "hidden"; }

    x.clearRect(0, 0, W, H);
    const R = Math.min(W, H) * 0.42 * Math.max(0.05, s);
    x.save(); x.translate(W / 2 + lk.x * 6 * DPR, H / 2 + lk.y * 6 * DPR); x.globalAlpha = a;
    x.globalCompositeOperation = "lighter";

    // core glow
    const cr = R * (0.2 + lv * 0.12 + flash * 0.1);
    const g = x.createRadialGradient(0, 0, 0, 0, 0, cr * 2.6);
    g.addColorStop(0, `rgba(235,252,255,${0.85 * glow})`); g.addColorStop(0.18, col(0.75 * glow));
    g.addColorStop(0.55, col(0.18 * glow)); g.addColorStop(1, col(0));
    x.fillStyle = g; x.beginPath(); x.arc(0, 0, cr * 2.6, 0, TAU); x.fill();
    arc(cr * 1.05, 1.6 * DPR, 0, TAU, 0.9);

    // voice waveform ring (bars radiating from the core)
    const wr = R * 0.36, n = hist.length;
    x.lineWidth = 2 * DPR; x.strokeStyle = col(0.85); x.beginPath();
    for (let i = 0; i < n; i++) {
      const q = i * TAU / n - Math.PI / 2, v = hist[(i * 7) % n] * 0.9 + 0.03 + (state === "idle" ? 0.02 * Math.sin(t * 2 + i) : 0);
      const l = R * 0.28 * v;
      x.moveTo(Math.cos(q) * wr, Math.sin(q) * wr); x.lineTo(Math.cos(q) * (wr + l), Math.sin(q) * (wr + l));
    }
    x.stroke();

    // rotating rings
    for (let i = 0; i < rot.length; i++) rot[i] += dt * spin * [0.6, -0.35, 0.9, -1.4, 0.2][i];
    arc(R * 0.62, 1 * DPR, 0, TAU, 0.35);
    for (let k = 0; k < 3; k++) arc(R * 0.70, 5 * DPR, rot[0] + k * TAU / 3, TAU / 3 * 0.62, 0.55 * glow);
    ticks(R * 0.78, 90, 4 * DPR, rot[1], 0.45, 5);
    arc(R * 0.88, 2 * DPR, rot[2], TAU * 0.72, 0.5);
    arc(R * 0.88, 2 * DPR, rot[2] + TAU * 0.78, TAU * 0.12, 0.8);
    for (let k = 0; k < 6; k++) arc(R * 0.96, 1.2 * DPR, rot[4] + k * TAU / 6, TAU / 6 * 0.8, 0.25);

    // thinking: orbiting nodes on a fast amber ring
    const th = state === "thinking" ? 1 : 0;
    if (th) for (let k = 0; k < 3; k++) { const q = rot[3] * 1.5 + k * TAU / 3, r = R * 0.53;
      x.fillStyle = col(0.95); x.beginPath(); x.arc(Math.cos(q) * r, Math.sin(q) * r, 3.2 * DPR, 0, TAU); x.fill(); arc(r, 1.5 * DPR, q - 0.8, 0.8, 0.6); }

    // listening: expanding pulse rings
    if (state === "listening") for (let k = 0; k < 2; k++) { const p = ((t * 0.8 + k * 0.5) % 1); arc(R * (0.45 + p * 0.55), 1.5 * DPR, 0, TAU, (1 - p) * 0.5); }

    // flash on state change / appear
    if (flash > 0) arc(R * (1 - flash * 0.4), 3 * DPR, 0, TAU, flash * 0.8);
    x.restore();
  }
  requestAnimationFrame(frame);
})();
