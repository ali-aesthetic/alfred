/* Alfred face, look C in 3D: a gyroscope of precise gold HUD rings.
   Same API as the other faces: appear() · vanish() · holoMode() · setState(s) · upd(level, lookX, lookY) · orbStill(s)
   idle: rings tilted like a slow gyroscope · listening: rings swing flat to face you and brighten
   thinking: rings spin fast at steep angles · speaking: rings pulse outward in a wave with the voice           */
(function () {
  const TAU = Math.PI * 2, clamp = (x, a, b) => Math.max(a, Math.min(b, x)), lerp = (a, b, t) => a + (b - a) * t;
  const host = document.getElementById("holo") || document.body;
  if (!window.THREE) { console.error("three.js missing"); return; }

  const GOLD = new THREE.Color("#ffe0a8"), AMBER = new THREE.Color("#ffa63d"), HOT = new THREE.Color("#fff4e0");
  const LOOK = {  // tilt = how far layers lean (1 = full gyroscope), spin, glow
    starting:  { tilt: 1.0, spin: 1.0, glow: 1.0 },
    idle:      { tilt: 0.75, spin: 0.35, glow: 0.7 },
    listening: { tilt: 0.12, spin: 0.5, glow: 1.15 },
    thinking:  { tilt: 1.25, spin: 2.6, glow: 1.0 },
    speaking:  { tilt: 0.35, spin: 0.6, glow: 1.1 },
    paused:    { tilt: 0.9, spin: 0.06, glow: 0.35 },
  };
  let state = "starting", level = 0, lv = 0, look = { x: 0, y: 0 }, lk = { x: 0, y: 0 };
  let mode = "appearing", mt = 0, flash = 1, still = false;
  const cur = { tilt: 1, spin: 1, glow: 1 };
  window.setState = s => { if (LOOK[s] && s !== state) { state = s; flash = Math.max(flash, 0.5); } };
  window.upd = (l, lx, ly) => { level = clamp(+l || 0, 0, 1); if (lx !== undefined) { look.x = clamp(lx, -1, 1); look.y = clamp(ly, -1, 1); } };
  window.appear = () => { if (mode === "shown" || mode === "appearing") return; mode = "appearing"; mt = 0; flash = 1; };
  window.vanish = () => { if (window.clearPanels) clearPanels(); if (mode === "hidden" || mode === "vanishing") return; mode = "vanishing"; mt = 0; };
  window.holoMode = () => mode;

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, premultipliedAlpha: true });
  renderer.setClearColor(0x000000, 0);
  renderer.domElement.style.width = "100%"; renderer.domElement.style.height = "100%";
  host.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const cam = new THREE.PerspectiveCamera(32, 1, 0.1, 50); cam.position.set(0, 0, 7.2);
  function resize() { const w = host.clientWidth || 280, h = host.clientHeight || 280; renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2)); renderer.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix(); }
  addEventListener("resize", resize); resize();

  const mats = [];
  const lineMat = (c, a) => { const m = new THREE.LineBasicMaterial({ color: c, transparent: true, opacity: a, blending: THREE.AdditiveBlending, depthWrite: false }); m.userData.a = a; mats.push(m); return m; };
  const meshMat = (c, a) => { const m = new THREE.MeshBasicMaterial({ color: c, transparent: true, opacity: a, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }); m.userData.a = a; mats.push(m); return m; };
  const circle = (r, a0 = 0, len = TAU, n = 200) => { const p = []; const k = Math.max(8, Math.round(n * len / TAU)); for (let i = 0; i <= k; i++) { const q = a0 + len * i / k; p.push(new THREE.Vector3(Math.cos(q) * r, Math.sin(q) * r, 0)); } return new THREE.BufferGeometry().setFromPoints(p); };
  const ring = (r, c, a) => new THREE.Line(circle(r), lineMat(c, a));
  const dashed = (r, c, a, n, fill) => { const g = new THREE.Group(); for (let i = 0; i < n; i++) g.add(new THREE.Line(circle(r, i / n * TAU, TAU / n * fill, 60), lineMat(c, a))); return g; };
  const band = (r, w, a0, len, c, a) => glowBand(r, w, a0, len, c, a) || new THREE.Mesh(new THREE.RingGeometry(r - w / 2, r + w / 2, Math.max(16, Math.round(160 * len / TAU)), 1, a0, len), meshMat(c, a));
  const ticks = (r, n, l, c, a, every = 5) => { const p = []; for (let i = 0; i < n; i++) { const q = i / n * TAU, L = i % every ? l : l * 2.2; p.push(new THREE.Vector3(Math.cos(q) * r, Math.sin(q) * r, 0), new THREE.Vector3(Math.cos(q) * (r + L), Math.sin(q) * (r + L), 0)); } return new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(p), lineMat(c, a)); };
  const glyphs = (r, n, c, a) => { const g = new THREE.Group(); for (let i = 0; i < n; i++) { if (Math.random() < 0.35) continue; const q = i / n * TAU, w = 0.02 + Math.random() * 0.05; const m = new THREE.Mesh(new THREE.PlaneGeometry(w, 0.03), meshMat(c, a * (0.5 + Math.random() * 0.5))); m.position.set(Math.cos(q) * r, Math.sin(q) * r, 0); m.rotation.z = q + Math.PI / 2; g.add(m); } return g; };
  const brackets = (r, c, a) => { const g = new THREE.Group(); for (let k = 0; k < 4; k++) { const q = k * TAU / 4 + TAU / 8; const l = new THREE.Line(circle(r, q - 0.09, 0.18, 12), lineMat(c, a)); g.add(l); const p = [new THREE.Vector3(Math.cos(q - 0.09) * r, Math.sin(q - 0.09) * r, 0), new THREE.Vector3(Math.cos(q - 0.09) * (r - 0.08), Math.sin(q - 0.09) * (r - 0.08), 0)]; g.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(p), lineMat(c, a))); } return g; };

  // bands get a soft wide glow copy behind them
  function glowBand(r, w, a0, len, c, a) {
    const g = new THREE.Group(), n = Math.max(16, Math.round(160 * len / TAU));
    g.add(new THREE.Mesh(new THREE.RingGeometry(r - w / 2, r + w / 2, n, 1, a0, len), meshMat(c, a)));
    g.add(new THREE.Mesh(new THREE.RingGeometry(r - w * 1.6, r + w * 1.6, n, 1, a0, len), meshMat(c, a * 0.18)));
    return g;
  }
  // layers: [radius, builder, base tilt x, base tilt y, spin speed]
  const root = new THREE.Group(); scene.add(root);
  const L = [];
  function layer(r, parts, tx, ty, sp) { const g = new THREE.Group(); parts.forEach(p => g.add(p)); const pivot = new THREE.Group(); pivot.add(g); root.add(pivot); L.push({ r, g, pivot, tx, ty, sp, ph: Math.random() * TAU }); }
  layer(0.32, [ring(0.32, HOT, 0.9), ticks(0.36, 36, 0.035, GOLD, 0.6, 3)], 0.2, -0.3, 1.4);
  layer(0.58, [ring(0.58, GOLD, 0.75), dashed(0.64, AMBER, 0.6, 24, 0.55)], -0.9, 0.4, -0.9);
  layer(0.86, [band(0.86, 0.07, 0.2, 1.3, AMBER, 0.55), band(0.86, 0.07, 2.4, 0.8, AMBER, 0.55), band(0.86, 0.07, 3.9, 1.6, AMBER, 0.55), ring(0.93, GOLD, 0.45)], 1.1, 0.7, 0.55);
  layer(1.12, [ring(1.12, GOLD, 0.6), glyphs(1.2, 140, GOLD, 0.7), ticks(1.04, 120, 0.03, GOLD, 0.35)], -0.45, -1.0, -0.35);
  layer(1.38, [ring(1.38, GOLD, 0.5), ticks(1.40, 180, 0.04, GOLD, 0.45, 10), band(1.47, 0.025, 0, TAU * 0.7, AMBER, 0.4)], 0.65, -0.55, 0.25);
  layer(1.62, [band(1.62, 0.09, 0.6, 0.9, AMBER, 0.5), band(1.62, 0.09, 3.6, 1.2, AMBER, 0.5), dashed(1.7, GOLD, 0.45, 60, 0.4)], -1.2, 0.25, -0.5);
  layer(1.88, [ring(1.88, GOLD, 0.35), brackets(1.95, HOT, 0.8), ticks(1.8, 72, 0.05, GOLD, 0.3, 6)], 0.3, 1.25, 0.15);

  // center light + halo
  const dot = (() => { const c = document.createElement("canvas"); c.width = c.height = 64; const x = c.getContext("2d"), g = x.createRadialGradient(32, 32, 0, 32, 32, 32);
    g.addColorStop(0, "rgba(255,255,255,1)"); g.addColorStop(.2, "rgba(255,240,215,.8)"); g.addColorStop(.55, "rgba(255,170,70,.2)"); g.addColorStop(1, "rgba(255,150,40,0)"); x.fillStyle = g; x.fillRect(0, 0, 64, 64); return new THREE.CanvasTexture(c); })();
  const core = new THREE.Sprite(new THREE.SpriteMaterial({ map: dot, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false })); scene.add(core);
  const haze = new THREE.Sprite(new THREE.SpriteMaterial({ map: dot, color: 0xff9a2e, transparent: true, opacity: 0.12, blending: THREE.AdditiveBlending, depthWrite: false })); haze.scale.setScalar(5.2); scene.add(haze);
  const halo = new THREE.Sprite(new THREE.SpriteMaterial({ map: dot, color: 0xffa63d, transparent: true, opacity: 0.25, blending: THREE.AdditiveBlending, depthWrite: false })); scene.add(halo);
  // dust: tiny sparks drifting in the gyroscope
  const DN = 260, dp = new Float32Array(DN * 3); for (let i = 0; i < DN; i++) { const u = Math.random() * 2 - 1, th = Math.random() * TAU, r = 0.4 + Math.random() * 1.7, s = Math.sqrt(1 - u * u); dp.set([s * Math.cos(th) * r, u * r, s * Math.sin(th) * r], i * 3); }
  const dg = new THREE.BufferGeometry(); dg.setAttribute("position", new THREE.BufferAttribute(dp, 3));
  const dust = new THREE.Points(dg, new THREE.PointsMaterial({ map: dot, size: 0.05, color: 0xffd08a, transparent: true, opacity: 0.6, blending: THREE.AdditiveBlending, depthWrite: false })); scene.add(dust);

  window.orbStill = s => { still = true; state = s; mode = "shown"; Object.assign(cur, LOOK[s]); flash = 0; lv = s === "speaking" ? 0.6 : 0; };

  let last = performance.now(), t = 0;
  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min((now - last) / 1000, 0.05); last = now; t += dt;
    if (mode === "hidden") { renderer.clear(); return; }
    mt += dt;
    const T = LOOK[state];
    cur.tilt = lerp(cur.tilt, T.tilt, 0.035); cur.spin = lerp(cur.spin, T.spin, 0.04); cur.glow = lerp(cur.glow, T.glow, 0.05);
    flash = Math.max(0, flash - dt * 1.3);
    const live = state === "speaking" || state === "listening" ? level : 0;
    if (!still) lv = lerp(lv, live, live > lv ? 0.45 : 0.12);
    lk.x = lerp(lk.x, look.x, 0.05); lk.y = lerp(lk.y, look.y, 0.05);
    let s = 1, a = 1;
    if (mode === "appearing") { const k = clamp(mt / 1.2, 0, 1); s = 0.3 + 0.7 * (1 - Math.pow(1 - k, 3)); a = clamp(mt / 0.4, 0, 1); if (k >= 1) mode = "shown"; }
    else if (mode === "vanishing") { const k = clamp(mt / 0.8, 0, 1); s = 1 + k * 0.3; a = 1 - k; if (k >= 1) mode = "hidden"; }

    L.forEach((o, i) => {
      // appear: rings unfold one after another from flat
      const unfold = mode === "appearing" ? clamp(mt * 1.6 - i * 0.12, 0, 1) : 1;
      o.pivot.rotation.x = lerp(o.pivot.rotation.x, o.tx * cur.tilt * unfold + Math.sin(t * 0.3 + o.ph) * 0.08 * cur.tilt, 0.08);
      o.pivot.rotation.y = lerp(o.pivot.rotation.y, o.ty * cur.tilt * unfold + Math.cos(t * 0.25 + o.ph) * 0.08 * cur.tilt, 0.08);
      o.g.rotation.z += dt * o.sp * cur.spin;
      // voice: a wave travels outward through the rings
      const wave = lv * Math.max(0, Math.sin(t * 10 - i * 0.9)) * 0.09;
      o.pivot.scale.setScalar(s * (1 + wave + (state === "listening" ? Math.sin(t * 2.4 - i * 0.5) * 0.012 : 0)));
    });
    root.rotation.y = lk.x * 0.25 + Math.sin(t * 0.17) * 0.12 * cur.tilt;
    root.rotation.x = -lk.y * 0.2;
    const g = cur.glow * a * (1 + flash * 0.6 + lv * 0.35);
    mats.forEach(m => { m.opacity = clamp(m.userData.a * g * 1.75, 0, 1); });
    core.scale.setScalar((0.55 + lv * 0.45 + Math.sin(t * 3) * 0.03) * s); core.material.opacity = a;
    halo.scale.setScalar((2.2 + lv * 0.8) * s); halo.material.opacity = 0.3 * g; haze.material.opacity = 0.13 * g * a;
    dust.rotation.y += dt * 0.05 * cur.spin; dust.material.opacity = 0.5 * a * cur.glow;
    renderer.render(scene, cam);
  }
  requestAnimationFrame(frame);
})();
