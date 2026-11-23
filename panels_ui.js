/* Голографические панели Alfred: text · list · table · chart · image · video · stat.
   API: setPanels([{id,type,title,...}]) — показать (по id: новые влетают, исчезнувшие сворачиваются)
        clearPanels()                      — убрать все                                              */
(function () {
  const css = `
  #panels{display:flex;flex-direction:column;justify-content:flex-end;gap:10px;pointer-events:auto;
    font-family:"SF Pro Text","Helvetica Neue",system-ui,sans-serif;color:#d6f4ff}
  .pnl{position:relative;flex:0 1 auto;min-height:0;display:flex;flex-direction:column;overflow:hidden;
    background:linear-gradient(180deg,rgba(8,34,52,.88),rgba(3,13,24,.9));border:1px solid rgba(90,225,255,.5);
    border-radius:3px;padding:10px 14px 12px;box-shadow:0 0 22px rgba(63,216,255,.28),inset 0 0 28px rgba(63,216,255,.08);
    transform-origin:100% 50%;animation:pnlIn .6s cubic-bezier(.2,.9,.25,1) both}
  .pnl.out{animation:pnlOut .45s cubic-bezier(.6,0,.8,.3) both}
  .pnl::before,.pnl::after{content:"";position:absolute;width:12px;height:12px;border:2px solid #7ff0ff;pointer-events:none;
    filter:drop-shadow(0 0 4px #4fe3ff)}
  .pnl::before{left:-1px;top:-1px;border-right:0;border-bottom:0}
  .pnl::after{right:-1px;bottom:-1px;border-left:0;border-top:0}
  .pnl .scan{position:absolute;inset:0;pointer-events:none;
    background:repeating-linear-gradient(0deg,rgba(120,230,255,.05) 0 1px,transparent 1px 3px)}
  .pnl .sweep{position:absolute;left:0;right:0;height:40%;top:-40%;pointer-events:none;
    background:linear-gradient(180deg,transparent,rgba(120,235,255,.16),transparent);animation:sweep 1.1s .25s ease-out both}
  .pnl .beam{position:absolute;right:-1px;top:50%;width:3px;height:30%;transform:translateY(-50%);
    background:#9ff4ff;box-shadow:0 0 10px #4fe3ff,0 0 20px #4fe3ff;opacity:.8}
  .pnl h3{margin:0 0 8px;font:600 11px/1.2 "SF Pro Display","Helvetica Neue",sans-serif;letter-spacing:.2em;
    text-transform:uppercase;color:#6fe6ff;display:flex;gap:8px;align-items:center;flex:none;text-shadow:0 0 8px rgba(80,220,255,.6)}
  .pnl h3 .n{color:#2f9fc0}
  .pnl h3 .u{margin-left:auto;color:#5aa9c4;letter-spacing:.08em;text-transform:none}
  .pnl .body{position:relative;min-height:0;overflow:hidden;flex:0 1 auto}
  .pnl .body > *{animation:fadeUp .5s .3s both}
  .pnl p{margin:0 0 6px;font-size:13.5px;line-height:1.42}
  .pnl b{color:#fff;font-weight:600}
  .pnl ul{margin:0;padding:0;list-style:none}
  .pnl li{position:relative;padding:3px 0 3px 18px;font-size:13.5px;line-height:1.35;animation:fadeUp .4s both}
  .pnl li::before{content:"";position:absolute;left:2px;top:9px;width:6px;height:6px;transform:rotate(45deg);
    background:#4fe3ff;box-shadow:0 0 6px #4fe3ff}
  .pnl table{border-collapse:collapse;width:100%;font-size:12.5px;font-variant-numeric:tabular-nums}
  .pnl th{position:sticky;top:0;background:rgba(6,30,46,.97);color:#7fe9ff;font-weight:600;text-align:left;
    padding:4px 8px;border-bottom:1px solid rgba(90,225,255,.45);white-space:nowrap}
  .pnl td{padding:4px 8px;border-bottom:1px solid rgba(90,225,255,.12);white-space:nowrap}
  .pnl tr{animation:fadeUp .35s both}
  .pnl td.num,.pnl th.num{text-align:right}
  .pnl .stat{font:300 38px/1.05 "SF Pro Display","Helvetica Neue",sans-serif;color:#fff;letter-spacing:.01em;
    text-shadow:0 0 18px rgba(80,220,255,.7)}
  .pnl .note{margin-top:6px;color:#8fc9dd;font-size:13px}
  .pnl .media{display:block;max-width:100%;max-height:280px;margin:0 auto;border:1px solid rgba(90,225,255,.3)}
  .pnl .err{color:#ffb36b;font-size:13px}
  .pnl svg{display:block;width:100%;height:auto;overflow:visible}
  .pnl .body.ch{flex:1 1 auto;display:flex;flex-direction:column}
  .pnl .body.ch svg{flex:1 1 auto;min-height:80px;max-height:240px;height:100%}
  .pnl .body.md{flex:1 1 auto;display:flex;min-height:60px;max-height:230px}
  .pnl .body.md .media{max-height:100%;max-width:100%;object-fit:contain}
  .pnl svg text{fill:#8fd6ec;font-size:11px;font-family:"SF Pro Text","Helvetica Neue",sans-serif}
  .pnl svg .grid{stroke:rgba(90,225,255,.13)}
  .pnl svg .bar{transform-box:fill-box;transform-origin:50% 100%;animation:grow .8s cubic-bezier(.2,.9,.3,1) both}
  .pnl svg .line{stroke-dasharray:2000;stroke-dashoffset:2000;animation:draw 1.3s .3s ease-out forwards}
  .pnl .legend{display:flex;gap:12px;flex-wrap:wrap;margin-top:6px;font-size:11.5px;color:#9fd8ea}
  .pnl .legend i{display:inline-block;width:9px;height:9px;margin-right:5px;vertical-align:-1px}
  @keyframes pnlIn{0%{opacity:0;transform:scaleX(.04) scaleY(.02);filter:brightness(3)}
    35%{opacity:1;transform:scaleX(1) scaleY(.02);filter:brightness(2.2)}100%{opacity:1;transform:none;filter:none}}
  @keyframes pnlOut{0%{opacity:1;transform:none}45%{opacity:1;transform:scaleY(.02);filter:brightness(2.5)}
    100%{opacity:0;transform:scaleX(.02) scaleY(.02)}}
  @keyframes sweep{to{top:110%}}
  @keyframes fadeUp{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
  @keyframes grow{from{transform:scaleY(0)}to{transform:scaleY(1)}}
  @keyframes draw{to{stroke-dashoffset:0}}`;
  const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);

  let box = document.getElementById("panels");
  if (!box) { box = document.createElement("div"); box.id = "panels"; document.body.appendChild(box); }

  const COLORS = ["#4fe3ff", "#ffae3d", "#b08cff", "#5dffb0", "#ff6b9a"];
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  const isNum = s => /^[\s+\-−]?[\d\s.,]+(%|[a-zа-я$€₽]{0,4})?\s*$/i.test(String(s)) && /\d/.test(String(s));
  const fmt = v => {
    const a = Math.abs(v);
    if (a >= 1e9) return (v / 1e9).toFixed(a >= 1e10 ? 0 : 1).replace(".", ",") + " млрд";
    if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 0 : 1).replace(".", ",") + " млн";
    if (a >= 1e4) return Math.round(v / 1e3) + " тыс";
    return (Math.round(v * 100) / 100).toString().replace(".", ",");
  };

  function textBody(s) {
    const lines = String(s.text || "").split(/\n/);
    let html = "", inList = false;
    for (const ln of lines) {
      const m = ln.match(/^\s*[-•*]\s+(.*)/);
      if (m) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${inline(m[1])}</li>`; continue; }
      if (inList) { html += "</ul>"; inList = false; }
      if (ln.trim()) html += `<p>${inline(ln)}</p>`;
    }
    return html + (inList ? "</ul>" : "");
  }
  function listBody(s) {
    return "<ul>" + (s.items || []).map((x, i) => `<li style="animation-delay:${0.25 + i * 0.07}s">${inline(x)}</li>`).join("") + "</ul>";
  }
  function tableBody(s) {
    const rows = s.rows || [], cols = s.columns || [];
    const numCol = cols.map((_, j) => rows.length && rows.every(r => r[j] === undefined || r[j] === "" || isNum(r[j])));
    let h = "<table>";
    if (cols.length) h += "<thead><tr>" + cols.map((c, j) => `<th class="${numCol[j] ? "num" : ""}">${esc(c)}</th>`).join("") + "</tr></thead>";
    h += "<tbody>" + rows.map((r, i) => `<tr style="animation-delay:${0.3 + Math.min(i, 14) * 0.045}s">` +
      r.map((c, j) => `<td class="${numCol[j] ? "num" : ""}">${inline(c)}</td>`).join("") + "</tr>").join("") + "</tbody></table>";
    return h;
  }
  function chartBody(s) {
    const labels = s.labels || [], series = (s.series || []).filter(x => x && x.values);
    const n = Math.max(labels.length, ...series.map(x => x.values.length), 1);
    const all = series.flatMap(x => x.values);
    let lo = Math.min(0, ...all), hi = Math.max(0, ...all); if (hi === lo) hi = lo + 1;
    const raw = (hi - lo) / 4, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const stp = [1, 2, 2.5, 5, 10].map(k => k * mag).find(k => k >= raw);
    lo = Math.floor(lo / stp) * stp; hi = Math.ceil(hi / stp) * stp;
    const ticksN = Math.round((hi - lo) / stp);
    const W = 520, H = 220, L = 46, B = 30, T = 14, pw = W - L - 8, ph = H - B - T;
    const y = v => T + ph - ((v - lo) / (hi - lo)) * ph;
    let g = "";
    for (let k = 0; k <= ticksN; k++) { const v = lo + stp * k, yy = y(v); g += `<line class="grid" x1="${L}" x2="${W - 8}" y1="${yy}" y2="${yy}"/><text x="${L - 6}" y="${yy + 4}" text-anchor="end">${fmt(v)}</text>`; }
    const step = pw / n, every = Math.ceil(n / 9);
    labels.forEach((lb, i) => { if (i % every === 0) g += `<text x="${L + step * (i + .5)}" y="${H - 10}" text-anchor="middle">${esc(String(lb).slice(0, 10))}</text>`; });
    if (s.kind === "line") {
      series.forEach((ser, si) => {
        const c = COLORS[si % COLORS.length];
        const pts = ser.values.map((v, i) => `${L + step * (i + .5)},${y(v)}`).join(" ");
        g += `<polyline class="line" points="${pts}" fill="none" stroke="${c}" stroke-width="2.2" style="filter:drop-shadow(0 0 4px ${c})"/>`;
        ser.values.forEach((v, i) => { g += `<circle cx="${L + step * (i + .5)}" cy="${y(v)}" r="3" fill="${c}" style="animation:fadeUp .3s ${0.4 + i * 0.05}s both"/>`; });
      });
    } else {
      const m = series.length || 1, bw = Math.max(3, step * 0.72 / m);
      series.forEach((ser, si) => {
        const c = COLORS[si % COLORS.length];
        ser.values.forEach((v, i) => {
          const x = L + step * i + step * 0.14 + bw * si, y0 = y(Math.max(0, v)), y1 = y(Math.min(0, v));
          g += `<rect class="bar" x="${x}" y="${y0}" width="${bw - 1}" height="${Math.max(1, y1 - y0)}" fill="${c}" opacity=".85" style="animation-delay:${0.25 + i * 0.05}s;filter:drop-shadow(0 0 5px ${c})"/>`;
          if (n <= 12 && m === 1) g += `<text x="${x + bw / 2}" y="${y0 - 4}" text-anchor="middle" style="fill:#e6faff;animation:fadeUp .3s ${0.6 + i * 0.05}s both">${fmt(v)}</text>`;
        });
      });
    }
    let leg = "";
    if (series.length > 1) leg = `<div class="legend">${series.map((x, i) => `<span><i style="background:${COLORS[i % COLORS.length]}"></i>${esc(x.name)}</span>`).join("")}</div>`;
    return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${g}</svg>${leg}`;
  }
  function mediaBody(s) {
    const src = esc(s.src || "");
    if (s.type === "video") return `<video class="media" src="${src}" autoplay muted loop playsinline></video>`;
    return `<img class="media" src="${src}" alt="">`;
  }
  function statBody(s) {
    return `<div class="stat">${esc(s.value)}</div>` + (s.note ? `<div class="note">${inline(s.note)}</div>` : "");
  }
  const BODY = { text: textBody, list: listBody, table: tableBody, chart: chartBody, image: mediaBody, video: mediaBody, stat: statBody };

  // длинное содержимое плавно прокручивается само
  function autoscroll(el) {
    let dir = 1, wait = 90;
    const iv = setInterval(() => {
      if (!el.isConnected) return clearInterval(iv);
      if (el.scrollHeight <= el.clientHeight + 2) return;
      if (wait > 0) { wait--; return; }
      el.scrollTop += dir * 0.6;
      if (el.scrollTop + el.clientHeight >= el.scrollHeight - 1) { dir = -6; wait = 90; }
      else if (el.scrollTop <= 0 && dir < 0) { dir = 1; wait = 90; }
    }, 33);
  }

  function make(s, idx) {
    const el = document.createElement("div");
    el.className = "pnl"; el.dataset.id = s.id || "";
    const unit = s.unit ? `<span class="u">${esc(s.unit)}</span>` : "";
    let body;
    try { body = (BODY[s.type] || textBody)(s); } catch (e) { body = `<div class="err">Не удалось показать: ${esc(e.message)}</div>`; }
    el.innerHTML = `<div class="scan"></div><div class="sweep"></div><div class="beam"></div>` +
      `<h3><span class="n">${String(idx + 1).padStart(2, "0")}</span>${esc(s.title || "")}${unit}</h3>` +
      `<div class="body ${s.type === "chart" ? "ch" : (s.type === "image" || s.type === "video") ? "md" : ""}">${body}</div>`;
    const media = el.querySelector(".media");
    if (media) {
      media.addEventListener("error", () => { media.outerHTML = `<div class="err">Не удалось загрузить файл.</div>`; });
      if (media.tagName === "VIDEO") media.addEventListener("click", () => { media.muted = !media.muted; });
    }
    autoscroll(el.querySelector(".body"));
    return el;
  }

  function remove(el) {
    if (el.classList.contains("out")) return;
    el.classList.add("out"); el.style.animationDelay = "0s";
    el.querySelectorAll("video").forEach(v => v.pause());
    setTimeout(() => el.remove(), 460);
  }

  window.setPanels = list => {
    list = Array.isArray(list) ? list.slice(-3) : [];
    const want = new Set(list.map(s => s.id || ""));
    [...box.children].forEach(el => { if (!want.has(el.dataset.id)) remove(el); });
    list.forEach((s, i) => {
      if (![...box.children].some(el => el.dataset.id === (s.id || "") && !el.classList.contains("out"))) {
        const el = make(s, i); el.style.animationDelay = (i * 0.12) + "s"; box.appendChild(el);
      }
    });
    [...box.children].filter(el => !el.classList.contains("out")).forEach((el, i) => {
      const n = el.querySelector("h3 .n"); if (n) n.textContent = String(i + 1).padStart(2, "0");
    });
  };
  window.clearPanels = () => [...box.children].forEach(remove);
})();
