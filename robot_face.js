/* Alfred — голограмма на основе картинок лица (window.FACE: closed / open / think).
   API:  setState('idle'|'listening'|'thinking'|'speaking'|'paused'|'starting')
         upd(level 0..1, lookX -1..1, lookY -1..1)                                    */
(function () {
  const TAU = Math.PI * 2;
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const lerp = (a, b, t) => a + (b - a) * t;
  const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t); };

  // кадрирование картинки (доли, y сверху вниз) и положение черт лица
  const X0 = 0.13, X1 = 0.87, Y0 = 0.07, Y1 = 0.99;   // область картинки на экране
  const HEAD_Y = 0.47;                                // центр головы по высоте
  const S = 4.0;                                      // доля картинки -> единицы сцены

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, premultipliedAlpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  const host = document.getElementById("holo") || document.body;
  host.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 60);
  camera.position.set(0, 0, 9.0);
  function resize() {
    const w = host.clientWidth || innerWidth, h = host.clientHeight || innerHeight;
    renderer.setSize(w, h, false);
    renderer.domElement.style.width = "100%"; renderer.domElement.style.height = "100%";
    camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  addEventListener("resize", resize);

  const dot = (() => {
    const c = document.createElement("canvas"); c.width = c.height = 64;
    const x = c.getContext("2d"), g = x.createRadialGradient(32, 32, 0, 32, 32, 32);
    g.addColorStop(0, "rgba(255,255,255,1)"); g.addColorStop(.2, "rgba(255,255,255,.8)");
    g.addColorStop(.5, "rgba(255,255,255,.2)"); g.addColorStop(1, "rgba(255,255,255,0)");
    x.fillStyle = g; x.fillRect(0, 0, 64, 64); return new THREE.CanvasTexture(c);
  })();

  const loadTex = src => { const t = new THREE.TextureLoader().load(src); t.minFilter = THREE.LinearFilter; t.generateMipmaps = false; return t; };
  const F = window.FACE || {};
  const texC = loadTex(F.closed), texO = loadTex(F.open || F.closed), texT = loadTex(F.think || F.closed);

  /* ---------- лицо ---------- */
  const rig = new THREE.Group(); scene.add(rig);
  const W = (X1 - X0) * S, H = (Y1 - Y0) * S;
  const faceU = {
    tC: { value: texC }, tO: { value: texO }, tT: { value: texT },
    uOpen: { value: 0 }, uThink: { value: 0 }, uBlink: { value: 0 }, uTime: { value: 0 }, uLevel: { value: 0 },
    uGlitch: { value: 0 }, uOpacity: { value: 1 }, uReveal: { value: 0 }, uGray: { value: 0 }, uBright: { value: 1 }, uDissolve: { value: 0 },
    uLook: { value: new THREE.Vector2() },
  };
  const faceMat = new THREE.ShaderMaterial({
    uniforms: faceU, transparent: true, depthWrite: false, premultipliedAlpha: true,
    vertexShader: `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
    fragmentShader: `
      uniform sampler2D tC, tO, tT;
      uniform float uOpen, uThink, uBlink, uTime, uLevel, uGlitch, uOpacity, uReveal, uGray, uBright, uDissolve;
      uniform vec2 uLook;
      varying vec2 vUv;
      const vec2 EL = vec2(0.405, 0.534), ER = vec2(0.600, 0.534), ES = vec2(0.047, 0.023);
      float rnd(float x){ return fract(sin(x * 91.17) * 43758.5453); }
      float h2(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
      float vn(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
        return mix(mix(h2(i), h2(i + vec2(1, 0)), f.x), mix(h2(i + vec2(0, 1)), h2(i + vec2(1, 1)), f.x), f.y); }
      vec3 samp(vec2 tc){
        vec3 a = texture2D(tC, tc).rgb, b = texture2D(tO, tc).rgb;
        float m = 1.0 - smoothstep(0.55, 1.0, length((tc - vec2(0.5, 0.29)) / vec2(0.22, 0.16)));
        vec3 c = mix(a, b, uOpen * m);
        return mix(c, texture2D(tT, tc).rgb, uThink);
      }
      void main(){
        vec2 tc = vec2(mix(${X0.toFixed(3)}, ${X1.toFixed(3)}, vUv.x), mix(${(1 - Y1).toFixed(3)}, ${(1 - Y0).toFixed(3)}, vUv.y));
        // глитч-срезы
        float row = floor(tc.y * 80.0);
        float g = step(0.93, rnd(row + floor(uTime * 14.0))) * uGlitch;
        tc.x += (rnd(row * 3.1 + floor(uTime * 23.0)) - 0.5) * 0.035 * g;
        // параллакс по глубине головы
        vec2 hc = (tc - vec2(0.5, 0.53)) / vec2(0.28, 0.37);
        float depth = sqrt(max(0.0, 1.0 - dot(hc, hc)));
        tc -= uLook * vec2(0.014, 0.010) * depth;
        // глаза следят
        vec2 dl = (tc - EL) / ES, dr = (tc - ER) / ES;
        float inL = 1.0 - smoothstep(0.55, 1.05, length(dl)), inR = 1.0 - smoothstep(0.55, 1.05, length(dr));
        vec2 stc = tc - uLook * vec2(0.011, 0.006) * max(inL, inR);
        // хроматическая аберрация
        float ca = 0.0012 + uLevel * 0.0045 + g * 0.006;
        vec3 col = vec3(samp(stc + vec2(ca, 0.0)).r, samp(stc).g, samp(stc - vec2(ca, 0.0)).b);
        // моргание: веко из кожи над глазом
        for (int i = 0; i < 2; i++) {
          vec2 d = i == 0 ? dl : dr; vec2 c0 = i == 0 ? EL : ER;
          float inside = 1.0 - smoothstep(0.85, 1.05, length(d));
          float cov = inside * smoothstep(1.0 - uBlink - 0.12, 1.0 - uBlink, abs(d.y));
          vec3 lid = samp(c0 + vec2(d.x * ES.x, ES.y * 2.6));
          col = mix(col, lid, cov);
          col += vec3(0.35, 0.9, 1.0) * inside * smoothstep(0.55, 1.0, uBlink) * exp(-pow(d.y * 9.0, 2.0)) * 0.6;
        }
        // голографические эффекты
        col *= 0.88 + 0.12 * sin(gl_FragCoord.y * 1.7 + uTime * 6.0);
        col += col * 0.45 * exp(-pow((tc.y - (1.0 - fract(uTime * 0.13))) * 22.0, 2.0));
        col *= 0.95 + 0.05 * sin(uTime * 53.0) * rnd(floor(uTime * 9.0));
        col *= uBright * (1.0 + uLevel * 0.2);
        float lum = dot(col, vec3(0.3, 0.59, 0.11));
        col = mix(col, vec3(lum) * vec3(0.6, 0.7, 0.85), uGray) * mix(1.0, 0.5, uGray);
        // появление сверху вниз со светящейся кромкой
        float edge = (1.0 - vUv.y) - uReveal;
        float vis = 1.0 - smoothstep(-0.02, 0.0, edge);
        col = col * vis + vec3(0.5, 0.95, 1.0) * exp(-pow(edge * 60.0, 2.0)) * step(uReveal, 1.0) * 1.3;
        // испарение: лицо рассыпается снизу вверх со светящейся кромкой
        if (uDissolve > 0.0) {
          float n = vn(vUv * 70.0) * 0.35 + vn(vUv * 22.0) * 0.35 + vn(vUv * 7.0 + uTime * 0.3) * 0.3;
          float v = n * 0.42 + vUv.y * 0.58, thr = uDissolve * 1.25 - 0.12;
          float keep = smoothstep(thr, thr + 0.025, v);
          float rim = exp(-pow((v - thr) * 38.0, 2.0)) * step(0.001, uDissolve) * (1.0 - smoothstep(0.85, 1.0, uDissolve));
          col = col * keep + vec3(0.55, 0.95, 1.0) * rim * 1.1;
        }
        // плавно гасим шею снизу и края
        col *= smoothstep(0.0, 0.2, vUv.y) * smoothstep(0.0, 0.04, vUv.x) * smoothstep(1.0, 0.96, vUv.x);
        float a = clamp(max(col.r, max(col.g, col.b)), 0.0, 1.0);
        gl_FragColor = vec4(col * uOpacity, a * uOpacity);
      }`,
  });
  const face = new THREE.Mesh(new THREE.PlaneGeometry(W, H), faceMat);
  face.position.y = ((Y0 + Y1) / 2 - HEAD_Y) * -S;  // центр головы в начале координат
  rig.add(face);

  /* ---------- частицы по светящимся линиям лица ---------- */
  const pU = {
    uTime: { value: 0 }, uLevel: { value: 0 }, uAssemble: { value: 0 }, uOpacity: { value: 1 }, uVanish: { value: 0 },
    uPix: { value: renderer.getPixelRatio() }, uColor: { value: new THREE.Color("#5fe6ff") }, uTex: { value: dot },
  };
  const pMat = new THREE.ShaderMaterial({
    uniforms: pU, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `
      attribute float aSeed; attribute float aB; attribute vec3 aScatter;
      uniform float uTime, uLevel, uAssemble, uPix, uVanish; varying float vA;
      void main(){
        vec3 p = position;
        float tr = 0.004 + uLevel * 0.05 * fract(aSeed * 7.31);
        p += vec3(sin(uTime * 21.0 + aSeed * 50.0), cos(uTime * 17.0 + aSeed * 33.0), sin(uTime * 13.0 + aSeed * 71.0)) * tr;
        float k = smoothstep(0.0, 1.0, clamp(uAssemble * 1.4 - fract(aSeed * 3.7) * 0.4, 0.0, 1.0));
        // при появлении частицы слетаются по спирали
        float sw = (1.0 - k) * 2.2; float cs = cos(sw), sn = sin(sw);
        vec3 sc = vec3(aScatter.x * cs - aScatter.z * sn, aScatter.y, aScatter.x * sn + aScatter.z * cs);
        p = mix(sc, p, k);
        // при исчезновении частицы испаряются вверх вслед за кромкой
        float h = (position.y + 2.08) / 3.68;
        float thr = uVanish * 1.25 - 0.12;
        float rel = clamp((thr - (h * 0.58 + fract(aSeed * 5.3) * 0.42)) * 2.6, 0.0, 1.0);
        p += vec3(sin(aSeed * 40.0 + uTime * 2.0) * 0.55 * rel + (position.x) * 0.5 * rel,
                  rel * rel * (1.6 + fract(aSeed * 9.1) * 2.2),
                  cos(aSeed * 23.0 + uTime * 1.7) * 0.5 * rel);
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_Position = projectionMatrix * mv;
        float tw = 0.45 + 0.55 * pow(0.5 + 0.5 * sin(uTime * (1.5 + aSeed * 3.0) + aSeed * 40.0), 3.0);
        vA = aB * tw * mix(1.0, 0.55, k * (1.0 - uLevel));
        vA *= (1.0 + rel * (1.0 - rel) * 9.0) * (1.0 - rel) * (1.0 - smoothstep(0.95, 1.0, uVanish));
        gl_PointSize = (1.3 + aB * 1.8) * (1.0 + uLevel * 1.2) * uPix * (9.0 / -mv.z) * (1.0 + (1.0 - k) * 1.5);
      }`,
    fragmentShader: `
      uniform sampler2D uTex; uniform vec3 uColor; uniform float uOpacity; varying float vA;
      void main(){ float a = texture2D(uTex, gl_PointCoord).a; gl_FragColor = vec4(mix(uColor, vec3(1.0), 0.35), a * vA * uOpacity); }`,
  });
  (function buildParticles() {
    const img = new Image();
    img.onload = () => {
      const N = 220, c = document.createElement("canvas"); c.width = c.height = N;
      const x = c.getContext("2d"); x.drawImage(img, 0, 0, N, N);
      const d = x.getImageData(0, 0, N, N).data;
      const pos = [], seed = [], br = [], sc = [];
      for (let tries = 0; tries < 90000 && pos.length < 5200 * 3; tries++) {
        const u = X0 + Math.random() * (X1 - X0), v = Y0 + Math.random() * (Y1 - Y0 - 0.12);
        const i = (Math.floor(v * N) * N + Math.floor(u * N)) * 4;
        const lum = (d[i] * 0.3 + d[i + 1] * 0.59 + d[i + 2] * 0.11) / 255;
        if (lum < 0.18 || Math.random() > lum * lum * 1.6) continue;
        const hx = (u - 0.5) / 0.28, hy = (v - 0.53) / 0.37, depth = Math.sqrt(Math.max(0, 1 - hx * hx - hy * hy));
        pos.push((u - 0.5) * S, (HEAD_Y - v) * S, depth * 0.55 + 0.05);
        seed.push(Math.random()); br.push(Math.min(1, lum * 1.15));
        const r = 1.7 + Math.random() * 1.5, th = Math.random() * TAU, ph = Math.acos(Math.random() * 2 - 1);
        sc.push(r * Math.sin(ph) * Math.cos(th), r * Math.cos(ph), r * Math.sin(ph) * Math.sin(th));
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
      g.setAttribute("aSeed", new THREE.Float32BufferAttribute(seed, 1));
      g.setAttribute("aB", new THREE.Float32BufferAttribute(br, 1));
      g.setAttribute("aScatter", new THREE.Float32BufferAttribute(sc, 3));
      rig.add(new THREE.Points(g, pMat));
    };
    img.src = F.closed;
  })();

  /* ---------- HUD-кольца ---------- */
  function sprite(size, opacity) {
    const m = new THREE.SpriteMaterial({ map: dot, color: 0xffffff, transparent: true, opacity, depthWrite: false, blending: THREE.AdditiveBlending });
    const s = new THREE.Sprite(m); s.scale.set(size, size, 1); return s;
  }
  const hud = new THREE.Group(); hud.position.z = -0.6; scene.add(hud);
  const hudMats = [];
  function hudLine(points, opacity, loop) {
    const m = new THREE.LineBasicMaterial({ color: 0x4fe3ff, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false });
    m.userData.base = opacity; hudMats.push(m);
    const g = new THREE.BufferGeometry().setFromPoints(points);
    return loop ? new THREE.LineLoop(g, m) : new THREE.LineSegments(g, m);
  }
  const circle = (r, n = 180) => { const p = []; for (let i = 0; i < n; i++) { const a = (i / n) * TAU; p.push(new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r, 0)); } return p; };
  const arcSegs = (r, segs, fill) => { const p = []; for (let s = 0; s < segs; s++) { const a0 = (s / segs) * TAU, a1 = a0 + (TAU / segs) * fill; for (let k = 0; k < 8; k++) { const a = lerp(a0, a1, k / 8), b = lerp(a0, a1, (k + 1) / 8); p.push(new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r, 0), new THREE.Vector3(Math.cos(b) * r, Math.sin(b) * r, 0)); } } return p; };
  const ticks = (r, n, len, every) => { const p = []; for (let i = 0; i < n; i++) { const a = (i / n) * TAU, l = i % every === 0 ? len * 2.2 : len; p.push(new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r, 0), new THREE.Vector3(Math.cos(a) * (r + l), Math.sin(a) * (r + l), 0)); } return p; };
  const R = 1.95;
  const ring1 = hudLine(circle(R * 0.93), 0.3, true);
  const ring2 = hudLine(arcSegs(R * 1.0, 28, 0.6), 0.5);
  const ring3 = hudLine(ticks(R * 1.06, 160, 0.035, 8), 0.4);
  const ring4 = hudLine(arcSegs(R * 1.14, 3, 0.17), 0.85);
  const ring5 = hudLine(arcSegs(R * 0.97, 6, 0.07), 0.9);
  hud.add(ring1, ring2, ring3, ring4, ring5);
  const orbit = new THREE.Group(); orbit.rotation.x = 1.25; orbit.rotation.y = 0.32; hud.add(orbit);
  orbit.add(hudLine(circle(R * 1.08, 220), 0.25, true));
  const orbDot = sprite(0.24, 1.0); orbit.add(orbDot);
  const EQ = 140, eqPos = new Float32Array(EQ * 6), eqVals = new Float32Array(EQ);
  const eqGeo = new THREE.BufferGeometry(); eqGeo.setAttribute("position", new THREE.BufferAttribute(eqPos, 3));
  const eqMat = new THREE.LineBasicMaterial({ color: 0x9ff0ff, transparent: true, opacity: 0.8, blending: THREE.AdditiveBlending, depthWrite: false });
  hud.add(new THREE.LineSegments(eqGeo, eqMat));
  const dust = (() => {
    const pts = []; for (let i = 0; i < 420; i++) { const r = 1.2 + Math.random() * 1.6, a = Math.random() * TAU, h = (Math.random() - .5) * 3.6; pts.push(new THREE.Vector3(Math.cos(a) * r, h, Math.sin(a) * r - 0.5)); }
    const m = new THREE.PointsMaterial({ size: 0.026, map: dot, color: 0x6fe6ff, transparent: true, opacity: 0.45, depthWrite: false, blending: THREE.AdditiveBlending });
    const p = new THREE.Points(new THREE.BufferGeometry().setFromPoints(pts), m); scene.add(p); return p;
  })();

  /* ---------- вспышки появления / исчезновения ---------- */
  const burstMat = new THREE.LineBasicMaterial({ color: 0x9ff4ff, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false });
  const burst = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(circle(1, 200)), burstMat); scene.add(burst);
  const burst2 = new THREE.LineLoop(burst.geometry, burstMat.clone()); scene.add(burst2);
  const core = sprite(1, 0); scene.add(core);
  const beamMat = new THREE.SpriteMaterial({ map: dot, color: 0xbff6ff, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending });
  const beam = new THREE.Sprite(beamMat); scene.add(beam);

  /* ---------- появление / исчезновение ---------- */
  // mode: appearing → shown → vanishing → hidden
  let mode = "appearing", mt = 0;
  const APPEAR = 1.5, VANISH = 1.9;
  window.appear = () => {
    if (mode === "shown" || mode === "appearing") return;
    mode = "appearing"; mt = 0; pU.uAssemble.value = 0; faceU.uReveal.value = 0; flash = 1;
  };
  window.vanish = () => {
    if (window.clearPanels) clearPanels();
    if (mode === "hidden" || mode === "vanishing") return; mode = "vanishing"; mt = 0;
  };
  window.holoMode = () => mode;
  const easeOutBack = x => 1 + 2.7 * Math.pow(x - 1, 3) + 1.7 * Math.pow(x - 1, 2);

  /* ---------- состояния ---------- */
  const PAL = {
    idle:      ["#2fd0ff", 0.92, 1.0],
    listening: ["#5ef2ff", 1.0, 1.15],
    thinking:  ["#ffae3d", 1.0, 1.05],
    speaking:  ["#3ad8ff", 1.0, 1.0],
    paused:    ["#6a7690", 0.5, 0.7],
    starting:  ["#7d8cff", 1.0, 1.0],
  };
  let state = "starting", level = 0, lvlS = 0, look = { x: 0, y: 0 }, lookS = { x: 0, y: 0 };
  let col = new THREE.Color(PAL.starting[0]), op = 1, bright = 1, flash = 0, blinkT = 3, blink = 0, openS = 0, think = 0, gray = 0;
  window.setState = s => { if (PAL[s] && s !== state) { state = s; flash = 1; } };
  window.upd = (l, lx, ly) => { level = clamp(+l || 0, 0, 1); if (lx !== undefined) { look.x = clamp(lx, -1, 1); look.y = clamp(ly, -1, 1); } };

  const clock = new THREE.Clock(); let t = 0, sacc = { x: 0, y: 0 }, saccT = 0, glitchT = 0;
  function frame() {
    requestAnimationFrame(frame);
    const dt = Math.min(clock.getDelta(), 0.05); t += dt;
    if (mode === "hidden") return;  // невидим — не тратим процессор
    mt += dt;
    const P = PAL[state];
    col.lerp(new THREE.Color(P[0]), 0.08); op = lerp(op, P[1], 0.06); bright = lerp(bright, P[2], 0.06);
    flash = Math.max(0, flash - dt * 2.5);
    const live = state === "speaking" || state === "listening" ? level : 0;
    lvlS = lerp(lvlS, live, live > lvlS ? 0.55 : 0.2);
    openS = lerp(openS, state === "speaking" ? clamp(lvlS * 1.5, 0, 1) : 0, 0.5);
    think = lerp(think, state === "thinking" ? 1 : 0, 0.06);
    gray = lerp(gray, state === "paused" ? 1 : 0, 0.06);

    // появление: вспышка в центре → кольцо-ударная волна → частицы слетаются по спирали → лицо проявляется лучом
    let hudK = 1, coreA = 0, coreS = 0.1, bA = 0, bS = 1, b2A = 0, b2S = 1, beamA = 0, rigS = 1;
    if (mode === "appearing") {
      const k = mt / APPEAR;
      pU.uAssemble.value = clamp((mt - 0.1) / 0.85, 0, 1);
      faceU.uReveal.value = clamp((mt - 0.55) / 0.7, 0, 1.2);
      coreA = Math.sin(clamp(mt / 0.45, 0, 1) * Math.PI) * 1.0; coreS = 0.2 + clamp(mt / 0.45, 0, 1) * 1.6;
      bS = 0.1 + clamp(mt / 0.7, 0, 1) * 3.2; bA = (1 - clamp(mt / 0.7, 0, 1)) * 0.9;
      b2S = 0.1 + clamp((mt - 0.15) / 0.8, 0, 1) * 2.4; b2A = (1 - clamp((mt - 0.15) / 0.8, 0, 1)) * 0.6 * (mt > 0.15 ? 1 : 0);
      hudK = easeOutBack(clamp((mt - 0.2) / 0.9, 0, 1));
      beamA = mt > 0.55 && mt < 1.3 ? 0.9 * Math.sin(clamp((mt - 0.55) / 0.75, 0, 1) * Math.PI) : 0;
      rigS = 0.86 + 0.14 * clamp(mt / 1.1, 0, 1);
      faceU.uDissolve.value = 0; pU.uVanish.value = 0;
      if (k >= 1) { mode = "shown"; }
    } else if (mode === "shown") {
      pU.uAssemble.value = 1; faceU.uReveal.value = 1.2; faceU.uDissolve.value = 0; pU.uVanish.value = 0;
    } else if (mode === "vanishing") {
      // испарение: глитч → лицо рассыпается снизу вверх, частицы улетают паром, кольца схлопываются в точку
      const v = clamp(mt / (VANISH - 0.4), 0, 1);
      faceU.uDissolve.value = v; pU.uVanish.value = v;
      hudK = 1 - Math.pow(clamp((mt - 0.35) / 0.95, 0, 1), 2);
      rigS = 1 + v * 0.05;
      const end = clamp((mt - (VANISH - 0.45)) / 0.45, 0, 1);
      coreA = Math.sin(end * Math.PI) * 0.9; coreS = 1.2 - end * 1.1;
      bS = 2.6 - clamp((mt - 0.3) / 0.9, 0, 1) * 2.5; bA = clamp((mt - 0.3) / 0.3, 0, 1) * (1 - end) * 0.7;
      if (mt < 0.25) glitchT = 0.1;
      if (mt >= VANISH) { mode = "hidden"; renderer.clear(); return; }
    }

    // глитч на пиках голоса и при смене состояния
    glitchT -= dt;
    if ((state === "speaking" && lvlS > 0.8 && Math.random() < 0.08) || flash > 0.9) glitchT = 0.12;
    faceU.uGlitch.value = glitchT > 0 ? 1 : (Math.random() < 0.004 ? 1 : 0);

    // взгляд
    saccT -= dt; if (saccT < 0) { saccT = 0.7 + Math.random() * 2.4; sacc.x = (Math.random() - .5) * 0.3; sacc.y = (Math.random() - .5) * 0.2; }
    let tx = look.x + sacc.x, ty = look.y + sacc.y;
    if (state === "thinking") { tx = 0.6 + Math.sin(t * 1.8) * 0.25; ty = 0.5; }
    lookS.x = lerp(lookS.x, tx, 0.09); lookS.y = lerp(lookS.y, ty, 0.09);
    faceU.uLook.value.set(lookS.x, lookS.y);
    rig.rotation.y = lookS.x * 0.16 + Math.sin(t * 0.37) * 0.035;
    rig.rotation.x = -lookS.y * 0.09 + (state === "paused" ? 0.1 : 0);
    rig.rotation.z = state === "listening" ? -0.035 : 0;
    rig.position.y = Math.sin(t * 1.05) * 0.04;

    // моргание
    blinkT -= dt; if (blinkT < 0) { blink = 1; blinkT = 2.6 + Math.random() * 4.5; }
    blink = Math.max(0, blink - dt * 6.5);
    faceU.uBlink.value = state === "paused" ? 1 : Math.sin(blink * Math.PI);

    faceU.uTime.value = t; faceU.uLevel.value = lvlS; faceU.uOpen.value = openS; faceU.uThink.value = think;
    faceU.uGray.value = gray; faceU.uOpacity.value = op; faceU.uBright.value = bright + flash * 0.25;
    pU.uTime.value = t; pU.uLevel.value = lvlS + flash * 0.2; pU.uColor.value.copy(col); pU.uOpacity.value = op;

    // HUD
    const spin = state === "thinking" ? 3.2 : state === "listening" ? 1.7 : 1.0;
    ring2.rotation.z += dt * 0.12 * spin; ring3.rotation.z -= dt * 0.05 * spin;
    ring4.rotation.z -= dt * 0.5 * spin; ring5.rotation.z += dt * 0.85 * spin; orbit.rotation.z += dt * 0.55 * spin;
    orbDot.position.set(Math.cos(t * 1.3 * spin) * R * 1.08, Math.sin(t * 1.3 * spin) * R * 1.08, 0);
    orbDot.material.color.copy(col);
    hud.scale.setScalar(Math.max(0.001, hudK) * (1 + lvlS * 0.03 + flash * 0.03));
    hud.rotation.z = (1 - clamp(hudK, 0, 1)) * (mode === "vanishing" ? 2.4 : -1.6);
    rig.scale.setScalar(rigS);
    burstMat.opacity = bA; burstMat.color.copy(col); burst.scale.setScalar(bS);
    burst2.material.opacity = b2A; burst2.material.color.copy(col); burst2.scale.setScalar(b2S);
    core.material.opacity = coreA; core.scale.set(coreS, coreS, 1); core.material.color.copy(col).lerp(new THREE.Color(1, 1, 1), 0.5);
    beamMat.opacity = beamA; beam.scale.set(4.2, 0.09, 1);
    beam.position.y = rig.position.y + 1.6 - clamp((mt - 0.55) / 0.7, 0, 1) * 3.6;
    const hudOp = mode === "vanishing" ? clamp(hudK, 0, 1) : 1;
    hudMats.forEach(m => { m.color.copy(col); m.opacity = m.userData.base * op * hudOp * (0.85 + flash * 0.6); });
    for (let i = 0; i < EQ; i++) {
      const a = (i / EQ) * TAU;
      const target = live * (0.3 + 0.7 * Math.abs(Math.sin(a * 3 + t * 5.0) * Math.cos(a * 5 - t * 3.3))) + 0.012;
      eqVals[i] = lerp(eqVals[i], target, 0.35);
      const r0 = R * 0.9, r1 = r0 - eqVals[i] * 0.3;
      eqPos.set([Math.cos(a) * r0, Math.sin(a) * r0, 0, Math.cos(a) * r1, Math.sin(a) * r1, 0], i * 6);
    }
    eqGeo.attributes.position.needsUpdate = true; eqMat.color.copy(col); eqMat.opacity = (0.15 + live) * op * hudOp;
    const spinBoost = mode === "vanishing" ? 1 + mt * 6 : mode === "appearing" ? 1 + (1 - clamp(mt / APPEAR, 0, 1)) * 5 : 1;
    ring4.rotation.z -= dt * 0.5 * (spinBoost - 1); ring5.rotation.z += dt * 0.8 * (spinBoost - 1);
    dust.rotation.y += dt * 0.03 * spin * spinBoost; dust.material.color.copy(col);
    dust.material.opacity = 0.4 * op * (mode === "appearing" ? clamp(mt / APPEAR, 0, 1) : mode === "vanishing" ? 1 - clamp(mt / VANISH, 0, 1) : 1);

    renderer.render(scene, camera);
  }
  resize();
  requestAnimationFrame(frame);
})();
