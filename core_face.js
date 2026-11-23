/* Alfred living core — the face.
   Body: a looping core film (made with Higgsfield, black turned into light) + a real-time 3D particle shell
   that breathes, listens, thinks and talks with his voice.
   Same API as before: appear() · vanish() · holoMode() · setState(s) · upd(level, lookX, lookY) · orbStill(s)
   States: idle · listening · thinking · speaking · paused · starting                                        */
(function () {
  const TAU = Math.PI * 2, clamp = (x, a, b) => Math.max(a, Math.min(b, x)), lerp = (a, b, t) => a + (b - a) * t;
  const host = document.getElementById("holo") || document.body;

  // state look: tint (rgb gain), brightness, particle spin, film speed
  const LOOK = {
    starting:  { tint: [1.0, 0.92, 0.85], gain: 1.0, spin: 0.6, rate: 1.0, spread: 1.0 },
    idle:      { tint: [1.0, 0.88, 0.72], gain: 0.78, spin: 0.18, rate: 0.7, spread: 1.0 },
    listening: { tint: [1.05, 1.0, 0.92], gain: 1.15, spin: 0.35, rate: 1.0, spread: 0.92 },
    thinking:  { tint: [1.15, 1.08, 1.0], gain: 1.05, spin: 1.6, rate: 2.2, spread: 1.04 },
    speaking:  { tint: [1.1, 0.98, 0.86], gain: 1.1, spin: 0.4, rate: 1.15, spread: 1.0 },
    paused:    { tint: [0.55, 0.55, 0.6], gain: 0.45, spin: 0.05, rate: 0.25, spread: 1.0 },
  };
  let state = "starting", level = 0, lv = 0, look = { x: 0, y: 0 }, lk = { x: 0, y: 0 };
  let mode = "appearing", mt = 0, flash = 1, still = false;
  const cur = { tint: LOOK.starting.tint.slice(), gain: 1, spin: 0.6, rate: 1, spread: 1 };

  window.setState = s => { if (LOOK[s] && s !== state) { state = s; flash = Math.max(flash, 0.6); } };
  window.upd = (l, lx, ly) => { level = clamp(+l || 0, 0, 1); if (lx !== undefined) { look.x = clamp(lx, -1, 1); look.y = clamp(ly, -1, 1); } };
  window.appear = () => { if (mode === "shown" || mode === "appearing") return; mode = "appearing"; mt = 0; flash = 1; };
  window.vanish = () => { if (window.clearPanels) clearPanels(); if (mode === "hidden" || mode === "vanishing") return; mode = "vanishing"; mt = 0; };
  window.holoMode = () => mode;

  // ---------- film (blob URL keeps WebGL happy with local files) ----------
  const vid = document.createElement("video");
  vid.muted = true; vid.loop = true; vid.playsInline = true; vid.autoplay = true;
  vid.setAttribute("playsinline", ""); vid.setAttribute("muted", "");
  let filmOK = false;
  try {
    if (window.CORE_FILM_B64) {
      const bin = atob(window.CORE_FILM_B64), u8 = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
      vid.src = URL.createObjectURL(new Blob([u8], { type: "video/mp4" }));
      filmOK = true;
    }
  } catch (e) { console.error(e); }
  const tryPlay = () => { const p = vid.play(); if (p && p.catch) p.catch(() => {}); };
  tryPlay(); document.addEventListener("click", tryPlay);

  // ---------- three.js ----------
  if (!window.THREE) { console.error("three.js missing"); return; }
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, premultipliedAlpha: true });
  renderer.setClearColor(0x000000, 0);
  renderer.domElement.style.width = "100%"; renderer.domElement.style.height = "100%";
  host.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const cam = new THREE.PerspectiveCamera(30, 1, 0.1, 50); cam.position.set(0, 0, 7.6);
  function resize() {
    const w = host.clientWidth || 280, h = host.clientHeight || 280;
    renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2)); renderer.setSize(w, h, false);
    cam.aspect = w / h; cam.updateProjectionMatrix();
  }
  addEventListener("resize", resize); resize();

  const U = { uTex: { value: null }, uTint: { value: new THREE.Vector3(1, 1, 1) }, uGain: { value: 1 }, uLevel: { value: 0 },
              uTime: { value: 0 }, uAlpha: { value: 0 }, uFlash: { value: 0 }, uHas: { value: 0 } };
  if (filmOK) {
    const tex = new THREE.VideoTexture(vid); tex.minFilter = THREE.LinearFilter; tex.magFilter = THREE.LinearFilter;
    U.uTex.value = tex;
  }
  const filmMat = new THREE.ShaderMaterial({
    uniforms: U, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `uniform sampler2D uTex; uniform vec3 uTint; uniform float uGain, uLevel, uTime, uAlpha, uFlash, uHas; varying vec2 vUv;
      void main(){
        vec2 c = vUv - 0.5; float r = length(c);
        // voice ripple: rings wobble outward while he talks
        float rip = sin(r * 46.0 - uTime * 9.0) * 0.006 * uLevel;
        vec2 uv = 0.5 + c * (1.0 - rip / max(r, 0.05));
        vec3 col = uHas > 0.5 ? texture2D(uTex, uv).rgb : vec3(0.0);
        col = pow(col, vec3(1.15)) * uTint * uGain * (1.0 + uLevel * 0.55);
        // glowing core boost + flash ring
        col += vec3(1.0, 0.82, 0.55) * exp(-r * r * 90.0) * (0.25 + uLevel * 0.9);
        col += vec3(1.0, 0.85, 0.6) * exp(-pow((r - (0.5 - uFlash * 0.42)) * 34.0, 2.0)) * uFlash * 0.9;
        float edge = smoothstep(0.5, 0.43, r);
        col *= edge * uAlpha;
        gl_FragColor = vec4(col, clamp(max(col.r, max(col.g, col.b)), 0.0, 1.0));
      }`,
  });
  U.uHas.value = filmOK ? 1 : 0;
  const film = new THREE.Mesh(new THREE.PlaneGeometry(4.2, 4.2), filmMat);
  scene.add(film);

  // particle shell: fragments on a sphere, in 3D, reacting to the voice
  const dot = (() => { const c = document.createElement("canvas"); c.width = c.height = 32; const x = c.getContext("2d"), g = x.createRadialGradient(16, 16, 0, 16, 16, 16);
    g.addColorStop(0, "rgba(255,255,255,1)"); g.addColorStop(.35, "rgba(255,255,255,.55)"); g.addColorStop(1, "rgba(255,255,255,0)"); x.fillStyle = g; x.fillRect(0, 0, 32, 32); return new THREE.CanvasTexture(c); })();
  const N = 1400, pos = new Float32Array(N * 3), base = new Float32Array(N * 3), seed = new Float32Array(N), col = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {
    const u = Math.random() * 2 - 1, th = Math.random() * TAU, s = Math.sqrt(1 - u * u);
    const r = 1.55 + (Math.random() < 0.75 ? Math.random() * 0.12 : -Math.random() * 0.9);  // most on the shell, some inside
    base.set([s * Math.cos(th) * r, u * r, s * Math.sin(th) * r], i * 3); seed[i] = Math.random();
    const w = 0.6 + Math.random() * 0.4; col.set([1.0 * w, (0.62 + Math.random() * 0.25) * w, (0.25 + Math.random() * 0.2) * w], i * 3);
  }
  pos.set(base);
  const pg = new THREE.BufferGeometry(); pg.setAttribute("position", new THREE.BufferAttribute(pos, 3)); pg.setAttribute("color", new THREE.BufferAttribute(col, 3));
  const pmat = new THREE.PointsMaterial({ size: 0.055, map: dot, vertexColors: true, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending });
  const shell = new THREE.Points(pg, pmat); scene.add(shell);

  // thin orbit rings (thinking = nodes racing around)
  const ringMat = new THREE.LineBasicMaterial({ color: 0xffb04a, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false });
  const rings = new THREE.Group(); scene.add(rings);
  [[1.95, 0.25, 0.1], [2.05, -0.55, 0.9], [1.85, 1.2, -0.4]].forEach(([r, rx, rz]) => {
    const p = []; for (let i = 0; i <= 160; i++) { const q = i / 160 * TAU; if (i % 40 < 31) p.push(new THREE.Vector3(Math.cos(q) * r, Math.sin(q) * r, 0)); }
    const l = new THREE.Line(new THREE.BufferGeometry().setFromPoints(p), ringMat); l.rotation.set(rx, rz, 0); rings.add(l);
  });
  const nodes = [0, 1, 2].map(() => { const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: dot, color: 0xffe2b0, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false })); s.scale.setScalar(0.22); scene.add(s); return s; });

  window.orbStill = s => { still = true; state = s; mode = "shown"; const L = LOOK[s]; cur.tint = L.tint.slice(); cur.gain = L.gain; cur.spin = L.spin; flash = 0; lv = s === "speaking" ? 0.55 : 0; };

  let last = performance.now(), t = 0;
  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min((now - last) / 1000, 0.05); last = now; t += dt;
    if (mode === "hidden") { if (!vid.paused) try { vid.pause(); } catch (e) {} renderer.clear(); return; }
    if (filmOK && vid.paused && now - (window._lastPlay || 0) > 1000) { window._lastPlay = now; tryPlay(); }  // film runs only while the face is visible
    mt += dt;
    const L = LOOK[state];
    for (let i = 0; i < 3; i++) cur.tint[i] = lerp(cur.tint[i], L.tint[i], 0.06);
    cur.gain = lerp(cur.gain, L.gain, 0.06); cur.spin = lerp(cur.spin, L.spin, 0.04); cur.spread = lerp(cur.spread, L.spread, 0.05);
    cur.rate = lerp(cur.rate, L.rate, 0.05);
    try { if (filmOK && Math.abs(vid.playbackRate - cur.rate) > 0.03) vid.playbackRate = cur.rate; } catch (e) {}
    flash = Math.max(0, flash - dt * 1.4);
    const live = state === "speaking" || state === "listening" ? level : 0;
    if (!still) lv = lerp(lv, live, live > lv ? 0.45 : 0.12);
    lk.x = lerp(lk.x, look.x, 0.05); lk.y = lerp(lk.y, look.y, 0.05);

    let s = 1, a = 1;
    if (mode === "appearing") { const k = clamp(mt / 1.0, 0, 1); s = 0.2 + 0.8 * (1 - Math.pow(1 - k, 3)) + Math.sin(k * Math.PI) * 0.08; a = clamp(mt / 0.4, 0, 1); if (k >= 1) mode = "shown"; }
    else if (mode === "vanishing") { const k = clamp(mt / 0.8, 0, 1); s = 1 + k * 0.25; a = 1 - k; if (k >= 1) mode = "hidden"; }
    const breathe = 1 + Math.sin(t * (state === "listening" ? 2.4 : 1.1)) * 0.012;

    U.uTime.value = t; U.uLevel.value = lv; U.uAlpha.value = a; U.uFlash.value = flash;
    U.uTint.value.set(cur.tint[0], cur.tint[1], cur.tint[2]); U.uGain.value = cur.gain;
    film.scale.setScalar(s * breathe * (1 + lv * 0.05));
    film.position.set(lk.x * 0.08, -lk.y * 0.08, 0);

    // particles: spin in 3D, push out with the voice, pull in while listening
    shell.rotation.y += dt * cur.spin; shell.rotation.x = Math.sin(t * 0.21) * 0.35 + lk.y * 0.2; shell.rotation.z += dt * cur.spin * 0.3;
    const p = pg.attributes.position.array;
    for (let i = 0; i < N; i++) {
      const sd = seed[i], wob = 1 + Math.sin(t * (1.5 + sd * 3) + sd * 40) * 0.025;
      const push = 1 + lv * (0.12 + 0.35 * Math.max(0, Math.sin(t * 9 + sd * 25))) * (sd > 0.5 ? 1 : 0.5);
      const k2 = s * cur.spread * wob * push;
      p[i * 3] = base[i * 3] * k2; p[i * 3 + 1] = base[i * 3 + 1] * k2; p[i * 3 + 2] = base[i * 3 + 2] * k2;
    }
    pg.attributes.position.needsUpdate = true;
    pmat.opacity = a * (0.55 + cur.gain * 0.35 + lv * 0.4) * (state === "paused" ? 0.4 : 1);
    pmat.size = 0.05 + lv * 0.03;

    rings.rotation.y += dt * cur.spin * 0.6; rings.rotation.z += dt * 0.05;
    rings.scale.setScalar(s);
    const th = state === "thinking" ? 1 : 0;
    ringMat.opacity = a * (0.12 + th * 0.35 + flash * 0.3);
    nodes.forEach((n, k) => {
      const q = t * 2.6 + k * TAU / 3, r = 2.0 * s;
      n.position.set(Math.cos(q) * r, Math.sin(q * 0.7 + k) * 0.5, Math.sin(q) * r * 0.35);
      n.material.opacity = a * th * 0.95;
    });
    renderer.render(scene, cam);
  }
  requestAnimationFrame(frame);
})();
