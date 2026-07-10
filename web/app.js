"use strict";

// ---- world -> canvas transform (map coords come from the Python maps) ----
const OFFX = 40, OFFY = 0;
const canvas = document.getElementById("board");
const ctx = canvas.getContext("2d");
const DPR = window.devicePixelRatio || 1;
const CW = 820, CH = 620;
canvas.width = CW * DPR; canvas.height = CH * DPR;
ctx.scale(DPR, DPR);                       // crisp on hi-DPI displays
const sx = (x) => x + OFFX, sy = (y) => y + OFFY;
const rgb = (c) => `rgb(${c[0]},${c[1]},${c[2]})`;
if (!CanvasRenderingContext2D.prototype.roundRect) {   // older mobile browsers
  CanvasRenderingContext2D.prototype.roundRect = function (x, y, w, h) {
    this.rect(x, y, w, h); return this;
  };
}

const el = (id) => document.getElementById(id);
let G = null;                              // Python bridge function handles
let cm = null;                             // CodeMirror editor instance
let running = false, over = false;
let selectedGun = null;                    // gun chosen in the palette (click to place)
let deviceMode = null;                     // "gate" | "limiter" placement mode
let selectedModule = null;                 // module chosen to equip on a tapped turret
let buildMode = false, edgeSrc = null;     // topology editing state
let mouseW = [0, 0];                       // last mouse position in world coords
let drag = null;                           // dragging a placed item: {fromX,fromY,curX,curY,moved}
let helpData = null;                       // {glossary, hud}
let lastTut = "", lastLes = "";            // panel-state caches (avoid re-rendering every frame)
let snap = null;                           // latest snapshot (for hover tooltips)
let speed = 1;                             // sim speed multiplier
let frameN = 0;                            // frame counter (throttle live metrics)
let lastLeaks = 0;                         // for auto-pause-on-leak
let last = performance.now();

const DEFAULT_LOADOUT = `# The board starts empty (you have full credits).
# Place turrets by clicking a gun in the palette, then a node on the board —
# or build in code here and Run (Ctrl+Enter). No imports needed:
#   Turret(x, y, gun=...), make_gun("name").
# Guns: sieve(auth,dns)  scatter(ids,firewall)  relay(dns,email)  auditor(cloudtrail) ...
# Devices: place gate/limiter from the palette, or define build_gates(unlocked, slots),
# build_limiters(...), build_parsers(...) returning Gate/Limiter/Parser objects.
def build_loadout(unlocked, slots):
    # Example — uncomment to deploy two turrets:
    #   return [
    #       Turret(*slots[0], gun=make_gun("sieve")),     # covers auth, dns
    #       Turret(*slots[1], gun=make_gun("scatter")),   # covers ids, firewall
    #   ]
    return []
`;

async function boot() {
  const sub = el("boot-sub");
  sub.textContent = "starting Pyodide…";
  const pyodide = await loadPyodide();
  sub.textContent = "loading the game core…";
  const zipBuf = await (await fetch("chokepoint.zip")).arrayBuffer();
  await pyodide.unpackArchive(zipBuf, "zip");        // -> chokepoint/ on sys.path
  const bridge = await (await fetch("webgame.py")).text();
  pyodide.runPython(bridge);
  G = {
    new_game: pyodide.globals.get("new_game"),
    load_loadout: pyodide.globals.get("load_loadout"),
    step: pyodide.globals.get("step"),
    begin: pyodide.globals.get("begin"),
    set_paused: pyodide.globals.get("set_paused"),
    snapshot_json: pyodide.globals.get("snapshot_json"),
    palette_json: pyodide.globals.get("palette_json"),
    select_gun: pyodide.globals.get("select_gun"),
    select_device: pyodide.globals.get("select_device"),
    select_module: pyodide.globals.get("select_module"),
    place_at: pyodide.globals.get("place_at"),
    move_at: pyodide.globals.get("move_at"),
    remove_at: pyodide.globals.get("remove_at"),
    node_at: pyodide.globals.get("node_at"),
    edge_at: pyodide.globals.get("edge_at"),
    add_node: pyodide.globals.get("add_node"),
    add_edge: pyodide.globals.get("add_edge"),
    remove_node: pyodide.globals.get("remove_node"),
    remove_edge: pyodide.globals.get("remove_edge"),
    help_json: pyodide.globals.get("help_json"),
    tutorial_state: pyodide.globals.get("tutorial_state"),
    tutorial_next: pyodide.globals.get("tutorial_next"),
    tutorial_skip: pyodide.globals.get("tutorial_skip"),
    tutorial_signal: pyodide.globals.get("tutorial_signal"),
    tutorial_skip_step: pyodide.globals.get("tutorial_skip_step"),
    lessons_state: pyodide.globals.get("lessons_state"),
    lessons_next: pyodide.globals.get("lessons_next"),
    lessons_skip: pyodide.globals.get("lessons_skip"),
    lessons_start: pyodide.globals.get("lessons_start"),
    grant_sandbox_credits: pyodide.globals.get("grant_sandbox_credits"),
    metrics_json: pyodide.globals.get("metrics_json"),
    undo: pyodide.globals.get("undo"),
    walkthroughs_json: pyodide.globals.get("walkthroughs_json"),
    start_walkthrough: pyodide.globals.get("start_walkthrough"),
  };

  const fresh = localStorage.getItem(SK("ver")) === SAVE_VERSION;   // ignore pre-clean-start saves
  const savedMap = fresh ? localStorage.getItem(SK("map")) : null;
  const savedDiff = fresh ? localStorage.getItem(SK("diff")) : null;
  const savedCode = fresh ? localStorage.getItem(SK("loadout")) : null;
  const meta = JSON.parse(G.new_game(savedMap || "trunk", savedDiff || "easy"));
  fillSelect(el("mapSel"), meta.maps, savedMap || "trunk");
  fillSelect(el("diffSel"), meta.difficulties, savedDiff || "easy");
  el("code").value = savedCode || DEFAULT_LOADOUT;
  cm = CodeMirror.fromTextArea(el("code"), {
    mode: "python", theme: "material-darker", lineNumbers: true,
    indentUnit: 4, matchBrackets: true, autofocus: false,
    extraKeys: { "Ctrl-Enter": applyLoadout, "Cmd-Enter": applyLoadout },
  });
  let hlTimer = null;                      // re-highlight TODOs as the code changes
  cm.on("change", () => {
    clearTimeout(hlTimer);
    hlTimer = setTimeout(() => { highlightTodos(); }, 300);
  });
  highlightTodos();
  applyLoadout();
  refreshPalette();
  helpData = JSON.parse(G.help_json());
  buildGlossary();

  wireUI();
  el("boot").classList.add("hidden");
  requestAnimationFrame(frame);
}

function fillSelect(sel, items, current) {
  sel.innerHTML = "";
  for (const it of items) {
    const o = document.createElement("option");
    o.value = o.textContent = it;
    if (it === current) o.selected = true;
    sel.appendChild(o);
  }
}

function newGame() {
  running = false; over = false;
  G.new_game(el("mapSel").value, el("diffSel").value);
  applyLoadout();
  refreshPalette();
  el("startBtn").textContent = "▶ Start";
}

function applyLoadout() {
  const src = cm ? cm.getValue() : el("code").value;
  const res = JSON.parse(G.load_loadout(src));
  const s = el("codeStatus");
  if (res.ok) {
    s.textContent = `deployed ${res.turrets} turret(s)` + (res.dropped ? ` (${res.dropped} over budget)` : "");
    s.className = "code-status ok";
    clearErrLine();
  } else {
    s.textContent = res.error; s.className = "code-status err";
    markErrorLine(res.line);               // jump the editor to the offending line
  }
  refreshPalette();
  autoSave();
}

// ------------------------------------------------------------- persistence
const SK = (k) => "chokepoint." + k;
const SAVE_VERSION = "2";                   // bump to invalidate older auto-saves

function autoSave() {
  try {
    localStorage.setItem(SK("ver"), SAVE_VERSION);
    localStorage.setItem(SK("loadout"), cm ? cm.getValue() : el("code").value);
    localStorage.setItem(SK("map"), el("mapSel").value);
    localStorage.setItem(SK("diff"), el("diffSel").value);
  } catch (e) { /* storage disabled/full — ignore */ }
}

function setStatus(msg, ok) {
  const s = el("codeStatus"); s.textContent = msg; s.className = "code-status " + (ok ? "ok" : "err");
}
function setSelect(id, val) {
  const s = el(id); if ([...s.options].some((o) => o.value === val)) s.value = val;
}

function exportSaveCode() {
  const save = { v: 1, code: cm.getValue(), map: el("mapSel").value, diff: el("diffSel").value };
  const codeStr = btoa(unescape(encodeURIComponent(JSON.stringify(save))));
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(codeStr)
      .then(() => setStatus("save-code copied to clipboard", true))
      .catch(() => window.prompt("Copy your save-code:", codeStr));
  } else {
    window.prompt("Copy your save-code:", codeStr);
  }
}

function importSaveCode() {
  const codeStr = window.prompt("Paste a save-code:");
  if (!codeStr) return;
  let save;
  try { save = JSON.parse(decodeURIComponent(escape(atob(codeStr.trim())))); }
  catch (e) { setStatus("invalid save-code", false); return; }
  if (save.map) setSelect("mapSel", save.map);
  if (save.diff) setSelect("diffSel", save.diff);
  // fresh world on the chosen map/difficulty; load the code but DO NOT run it —
  // the player reviews shared code and clicks Run themselves (the sandbox still applies).
  running = false; over = false;
  G.new_game(el("mapSel").value, el("diffSel").value);
  cm.setValue(save.code || "");
  refreshPalette();
  el("startBtn").textContent = "▶ Start";
  setStatus("loaded save-code — review the code, then click Run", true);
}

let lastPal = null;                        // cached palette (coach "show me" targeting)
function refreshPalette() {
  const pal = JSON.parse(G.palette_json());
  lastPal = pal;
  selectedGun = (pal.guns.find((g) => g.selected) || {}).name || null;
  deviceMode = (pal.devices.find((d) => d.selected) || {}).kind || null;
  selectedModule = (pal.modules.find((m) => m.selected) || {}).name || null;
  const gunHtml = pal.guns.map((g) => `
    <button class="gun ${g.selected ? "sel" : ""} ${g.afford ? "" : "poor"}" data-gun="${g.name}">
      <span class="gun-name">${g.name}</span><span class="gun-cost">${g.cost}cr</span>
      <span class="gun-kinds">${g.accepts.map((k, i) =>
        `<span class="sw" style="background:${rgb(g.colors[i])}"></span>${k}`).join(" ")}</span>
    </button>`).join("");
  const devHtml = pal.devices.map((d) => `
    <button class="gun dev ${d.selected ? "sel" : ""} ${d.afford ? "" : "poor"}" data-dev="${d.kind}">
      <span class="gun-name">${d.kind}</span><span class="gun-cost">${d.cost}cr</span>
      <span class="gun-kinds">${d.desc}</span>
    </button>`).join("");
  const modHtml = (pal.modules || []).map((m) => `
    <button class="gun mod ${m.selected ? "sel" : ""} ${m.afford ? "" : "poor"}" data-mod="${m.name}">
      <span class="gun-name">${m.name}</span><span class="gun-cost">${m.cost}cr</span>
      <span class="gun-kinds">${m.desc}</span>
    </button>`).join("");
  el("palette").innerHTML =
    `<div class="palette-head">Tap a GUN or DEVICE, then tap the board to place (snaps to the line). Drag a placed item to move it; tap it (nothing selected) to remove.</div>` +
    gunHtml +
    `<div class="palette-sub">FLOW DEVICES — parsers are code-only (build_parsers)</div>` +
    devHtml +
    (modHtml ? `<div class="palette-sub">MODULES — tap one, then tap a turret to equip</div>${modHtml}` : "");
  el("palette").querySelectorAll("button.gun[data-gun]").forEach((b) => {
    b.onclick = () => { G.select_gun(b.dataset.gun); refreshPalette(); };
  });
  el("palette").querySelectorAll("button.gun[data-dev]").forEach((b) => {
    b.onclick = () => { G.select_device(b.dataset.dev); refreshPalette(); };
  });
  el("palette").querySelectorAll("button.gun[data-mod]").forEach((b) => {
    b.onclick = () => { G.select_module(b.dataset.mod); refreshPalette(); };
  });
}

function eventToWorld(e) {
  const r = canvas.getBoundingClientRect();
  return [(e.clientX - r.left) * (CW / r.width) - OFFX,
          (e.clientY - r.top) * (CH / r.height) - OFFY];
}

function inEditor() {
  const a = document.activeElement;
  return a && a.closest && a.closest(".CodeMirror");   // let CodeMirror keep its own Ctrl+Z
}

// ---- targeted code highlighting: TODO task lines + the line an error points at ----
let errLine = null, todoLines = [];
function markErrorLine(line) {
  clearErrLine();
  if (!line || !cm) return;
  errLine = line - 1;
  cm.addLineClass(errLine, "background", "cm-error-line");
  cm.scrollIntoView({ line: errLine, ch: 0 }, 60);
}
function clearErrLine() {
  if (errLine !== null && cm) cm.removeLineClass(errLine, "background", "cm-error-line");
  errLine = null;
}
function highlightTodos() {
  if (!cm) return;
  todoLines.forEach((l) => cm.removeLineClass(l, "background", "cm-todo-line"));
  todoLines = [];
  for (let l = 0; l < cm.lineCount(); l++) {
    if (/#\s*TODO/i.test(cm.getLine(l))) {
      cm.addLineClass(l, "background", "cm-todo-line");
      todoLines.push(l);
    }
  }
}

function itemNear(x, y) {
  if (!snap) return false;
  const near = (o) => (o.x - x) ** 2 + (o.y - y) ** 2 <= 18 * 18;
  return snap.turrets.some(near) || (snap.gates || []).some(near) || (snap.limiters || []).some(near);
}

function drawDragGhost() {
  if (!snap) return;                       // show where the dragged item will snap (nearest node)
  let best = null, bd = 1e9;
  for (const n of snap.nodes) { const d = (n.x - drag.curX) ** 2 + (n.y - drag.curY) ** 2; if (d < bd) { bd = d; best = n; } }
  if (!best) return;
  ctx.strokeStyle = "#38e1b0"; ctx.lineWidth = 2; ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.arc(sx(best.x), sy(best.y), 16, 0, 7); ctx.stroke(); ctx.setLineDash([]);
}
function doUndo() {
  if (JSON.parse(G.undo()).ok) { refreshPalette(); showPlace("undone", true); }
  else showPlace("nothing to undo", false);
}

let placeTimer = null;
function showPlace(msg, ok) {
  const m = el("placeMsg");
  m.textContent = msg;
  m.style.color = ok ? "var(--phos)" : "var(--danger)";
  clearTimeout(placeTimer);
  placeTimer = setTimeout(() => { m.textContent = ""; }, 2500);
}

function wireUI() {
  el("startBtn").onclick = () => {
    if (over) return;
    running = !running;
    if (running) { G.begin(); el("startBtn").textContent = "❚❚ Pause"; }
    else { G.set_paused(true); el("startBtn").textContent = "▶ Start"; }
  };
  el("helpBtn").onclick = () => el("glossary").classList.toggle("hidden");
  el("glossClose").onclick = () => el("glossary").classList.add("hidden");
  el("metricsBtn").onclick = () => { el("metrics").classList.toggle("hidden"); renderMetrics(); };
  el("metricsClose").onclick = () => el("metrics").classList.add("hidden");
  el("learnBtn").onclick = () => { el("walkthroughs").classList.toggle("hidden"); renderWalkthroughs(); };
  el("wtClose").onclick = () => el("walkthroughs").classList.add("hidden");
  // coach "show me": pulse the palette card / editor the fix refers to
  el("hud").addEventListener("click", (e) => {
    const b = e.target.closest(".coach-show");
    if (!b) return;
    if (b.dataset.editor) {
      const ed = document.querySelector(".editor-wrap");
      ed.scrollIntoView({ behavior: "smooth", block: "center" }); pulse(ed);
      return;
    }
    const t = document.querySelector(b.dataset.sel);
    if (t) { t.scrollIntoView({ behavior: "smooth", block: "center" }); pulse(t); }
  });
  el("copyBtn").onclick = exportSaveCode;
  el("loadBtn").onclick = importSaveCode;
  el("stepBtn").onclick = () => { if (!over) G.step(1 / 60); };
  document.querySelectorAll("button.spd").forEach((b) => {
    if (+b.dataset.spd === speed) b.classList.add("primary");
    b.onclick = () => {
      speed = +b.dataset.spd;
      document.querySelectorAll("button.spd").forEach((x) => x.classList.toggle("primary", x === b));
    };
  });
  el("resetBtn").onclick = newGame;
  el("undoBtn").onclick = doUndo;
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "z" && !inEditor()) { e.preventDefault(); doUndo(); }
  });
  el("mapSel").onchange = newGame;
  el("diffSel").onchange = newGame;
  el("runBtn").onclick = applyLoadout;   // CodeMirror handles Ctrl/Cmd-Enter + Tab
  el("buildBtn").onclick = () => {
    buildMode = !buildMode; edgeSrc = null;
    el("buildBtn").classList.toggle("primary", buildMode);
  };

  // Pointer events unify mouse + touch; touch-action:none (CSS) stops the tap
  // from scrolling/zooming so it registers on the board (fixes mobile placement).
  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  canvas.addEventListener("pointermove", (e) => {
    mouseW = eventToWorld(e);
    if (drag) {
      [drag.curX, drag.curY] = mouseW;
      if (Math.hypot(drag.curX - drag.fromX, drag.curY - drag.fromY) > 6) drag.moved = true;
      el("boardTip").classList.add("hidden");
    } else updateBoardTip(e);
  });
  canvas.addEventListener("pointerleave", () => el("boardTip").classList.add("hidden"));
  canvas.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    mouseW = eventToWorld(e);
    const [x, y] = mouseW;
    if (buildMode) return onBuildClick(e.button, x, y);
    if (e.button === 2) { G.remove_at(x, y); refreshPalette(); return; }  // right-click: remove
    if (selectedGun || deviceMode || selectedModule) {                   // place a gun/device or equip
      const r = JSON.parse(G.place_at(x, y));
      if (r.ok) showPlace("placed ✓", true);
      else showPlace(r.reason || "pick a gun or device first", false);
      refreshPalette();
      return;
    }
    if (itemNear(x, y)) {                                                 // grab a placed item to drag
      drag = { fromX: x, fromY: y, curX: x, curY: y, moved: false };
      try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* older browsers */ }
    }
  });
  canvas.addEventListener("pointerup", (e) => {
    if (!drag) return;
    const [x, y] = eventToWorld(e);
    if (drag.moved) { G.move_at(drag.fromX, drag.fromY, x, y); showPlace("moved ✓", true); }
    else G.remove_at(drag.fromX, drag.fromY);                            // a tap on an item removes it
    drag = null; refreshPalette();
  });
}

function onBuildClick(button, x, y) {
  const node = G.node_at(x, y);
  if (button === 2) {                       // right-click: cancel / remove
    if (edgeSrc) { edgeSrc = null; return; }
    if (node) { G.remove_node(node); return; }
    const edge = G.edge_at(x, y);
    if (edge) G.remove_edge(...edge.split(","));
    return;
  }
  if (!node) { G.add_node(x, y); return; }   // empty space: new node
  if (!edgeSrc) { edgeSrc = node; }          // first node of an edge
  else { if (edgeSrc !== node) G.add_edge(edgeSrc, node); edgeSrc = null; }
}

function frame(now) {
  const dt = Math.min((now - last) / 1000, 0.05);
  last = now;
  if (running && !over) { for (let i = 0; i < speed; i++) G.step(dt); }
  const s = JSON.parse(G.snapshot_json());
  snap = s;
  over = s.over;
  if (running && el("autoPause").checked && s.leaks > lastLeaks && !s.over) {  // pause on a fresh leak
    running = false; G.set_paused(true); el("startBtn").textContent = "▶ Start";
    showPlace("a leak got through — paused. Check the coach, then Start.", false);
  }
  lastLeaks = s.leaks;
  if (over && running) { running = false; el("startBtn").textContent = "▶ Start"; }
  render(s);
  if ((selectedGun || deviceMode) && !buildMode) drawPlacePreview(s);
  if (drag && drag.moved) drawDragGhost();
  if (buildMode) drawBuildOverlay(s);
  updateHUD(s);
  renderOverlay(s);
  tickPanels();
  frameN++;
  if (frameN % 15 === 0 && !el("metrics").classList.contains("hidden")) renderMetrics();  // live
  requestAnimationFrame(frame);
}

function renderMetrics() {
  const m = JSON.parse(G.metrics_json());
  const kindRows = Object.entries(m.kinds).map(([k, v]) =>
    `<tr><td><span class="sw" style="background:${rgb(v.color)}"></span>${k}</td>
     <td>${v.in}</td><td>${v.ok}</td><td>${v.leak}</td><td>${v.peak}</td><td>${v.p50}s</td><td>${v.p95}s</td></tr>`).join("");
  const nodeRows = Object.entries(m.nodes).map(([n, v]) =>
    `<tr><td>${n}</td><td>${v.peak}</td><td>${v.drops}</td><td>${Math.round(v.load * 100)}%</td></tr>`).join("");
  const empty = (c) => `<tr><td colspan="${c}" style="color:var(--muted)">no data yet — run a wave</td></tr>`;
  el("metricsBody").innerHTML = `
    <div class="m-kpi">cost / handled: <b>${m.cost_per_handled}cr</b>
      <span>(fleet ${m.deployed_cost}cr · ${m.handled} handled — the over-provisioning KPI)</span></div>
    <canvas id="trendCanvas" width="600" height="90"></canvas>
    <h4>By kind</h4>
    <table class="kinds"><tr><th>kind</th><th>in</th><th>ok</th><th>leak</th><th>peak</th><th>p50</th><th>p95</th></tr>${kindRows || empty(7)}</table>
    <h4>By node — peak queue / overflow drops / time busy</h4>
    <table class="kinds"><tr><th>node</th><th>peak</th><th>drops</th><th>load</th></tr>${nodeRows || empty(4)}</table>`;
  drawTrend(m.trend, m.max_health);
}

function drawTrend(trend, maxH) {
  const c = el("trendCanvas"); if (!c) return;
  const g = c.getContext("2d"); g.clearRect(0, 0, c.width, c.height);
  g.fillStyle = "#93a6b8"; g.font = "11px monospace"; g.fillText("health over time", 6, 12);
  if (trend.length < 2) return;
  g.strokeStyle = "#38e1b0"; g.lineWidth = 2; g.beginPath();
  trend.forEach((p, i) => {
    const x = i / (trend.length - 1) * c.width;
    const y = c.height - (p.health / maxH) * (c.height - 16) - 4;
    i ? g.lineTo(x, y) : g.moveTo(x, y);
  });
  g.stroke();
}

function diamond(cx, cy, r) {
  ctx.beginPath(); ctx.moveTo(cx, cy - r); ctx.lineTo(cx + r, cy);
  ctx.lineTo(cx, cy + r); ctx.lineTo(cx - r, cy); ctx.closePath();
}
function hexagon(cx, cy, r) {
  ctx.beginPath();
  for (let i = 0; i < 6; i++) {
    const a = Math.PI / 3 * i, x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  }
  ctx.closePath();
}

function drawPlacePreview(s) {
  let best = null, bd = 1e9;
  for (const n of s.nodes) { const d = (n.x - mouseW[0]) ** 2 + (n.y - mouseW[1]) ** 2; if (d < bd) { bd = d; best = n; } }
  if (!best || bd > 60 * 60) return;
  ctx.strokeStyle = "#38e1b0"; ctx.lineWidth = 2; ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.arc(sx(best.x), sy(best.y), 15, 0, 7); ctx.stroke(); ctx.setLineDash([]);
}

function renderOverlay(s) {
  const box = el("boardOverlay");
  if (!s.over) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  let html = `<h2 class="${s.won ? "won" : "lost"}">${s.won ? "PIPELINE HELD ✓" : "PIPELINE OVERWHELMED ✕"}</h2>`;
  html += `<div class="ov-sub">waves cleared ${Math.max(0, s.wave - 1)} · leaks ${s.leaks}/${s.max_leaks}</div>`;
  if (s.debrief) {
    html += `<div class="ov-cause">${s.debrief.cause}</div>`;
    html += `<div class="ov-lines">${s.debrief.lines.slice(0, 6).map((l) => `<div>• ${l}</div>`).join("")}</div>`;
  }
  html += `<button id="ovRetry" class="primary">Retry</button>`;
  box.innerHTML = html;
  el("ovRetry").onclick = () => { box.classList.add("hidden"); newGame(); };
}

// board hover tooltips (node / turret) — a key training aid
function updateBoardTip(e) {
  const box = el("boardTip");
  if (!snap || buildMode) { box.classList.add("hidden"); return; }
  const [x, y] = mouseW;
  let tip = null;
  const near = (o) => (o.x - x) ** 2 + (o.y - y) ** 2 <= 16 * 16;
  for (const t of snap.turrets) if (near(t)) { tip = turretTip(t); break; }
  if (!tip) for (const g of (snap.gates || [])) if (near(g)) {
    const rts = g.branches.map((b) => `→ ${b.to}: ${b.kinds.join(", ") || "(none)"}`).join("<br>");
    tip = `<b>${g.id}: gate</b><br>routes kinds at the fork<br>${rts}`; break;
  }
  if (!tip) for (const lm of (snap.limiters || [])) if (near(lm)) {
    tip = `<b>${lm.id}: quelimiter</b><br>release ${lm.rate}/s<br>buffered ${lm.buffered}/${lm.cap}`; break;
  }
  if (!tip) for (const ps of (snap.parsers || [])) if (near(ps)) {
    tip = `<b>${ps.id}: parser</b><br>decodes raw → ${ps.handles.join(", ")}`; break;
  }
  if (!tip) for (const n of snap.nodes) if (near(n)) { tip = nodeTip(n); break; }
  if (!tip) { box.classList.add("hidden"); return; }
  box.innerHTML = tip;
  box.classList.remove("hidden");
  const r = canvas.getBoundingClientRect();
  box.style.left = (e.clientX - r.left + 14) + "px";
  box.style.top = (e.clientY - r.top + 14) + "px";
}
function turretTip(t) {
  const mods = t.modules && t.modules.length ? `<br>modules: ${t.modules.join(", ")}` : "";
  return `<b>${t.id}: ${t.gun}</b><br>${t.desc}<br>accepts: ${t.accepts.join(", ")}<br>throughput ${t.dps}/s${mods}`;
}
function nodeTip(n) {
  const role = n.source ? "source" : n.sink ? "sink" : "node";
  let s = `<b>${role} ${n.id}</b><br>queue ${n.queue}/${n.cap}`;
  s += `<br>serves: ${n.served.length ? n.served.join(", ") : "(pass-through)"}`;
  if (n.queue) s += `<br>oldest wait ${n.oldest}s / grace ${n.grace}s${n.oldest > n.grace ? " — BLEEDING" : ""}`;
  return s;
}

// ------------------------------------------------- tutorial + lessons panels
function tickPanels() {
  const tj = G.tutorial_state();
  if (tj !== lastTut) { lastTut = tj; renderTutorial(JSON.parse(tj)); }
  const lj = G.lessons_state();
  if (lj !== lastLes) { lastLes = lj; renderLessons(JSON.parse(lj)); }
}

function renderWalkthroughs() {
  const list = JSON.parse(G.walkthroughs_json());
  el("wtBody").innerHTML =
    `<div class="wt-intro">Short, hands-on guides. Each step waits for you to actually do it.</div>` +
    list.map((w) => `
      <div class="wt-item">
        <b>${w.title}</b><span>${w.desc} <em>(${w.n} steps)</em></span>
        <button class="primary wt-start" data-wt="${w.id}">${w.active ? "Restart" : "Start"}</button>
      </div>`).join("");
  el("wtBody").querySelectorAll(".wt-start").forEach((b) => {
    b.onclick = () => {
      G.start_walkthrough(b.dataset.wt);
      el("walkthroughs").classList.add("hidden");
      lastTut = "";
    };
  });
}

function pulse(elm) {
  elm.classList.remove("pulse");
  void elm.offsetWidth;                   // restart the animation
  elm.classList.add("pulse");
  setTimeout(() => elm.classList.remove("pulse"), 2000);
}

function renderTutorial(s) {
  const box = el("tutorial");
  if (!s.active) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  box.innerHTML = `
    <div class="tut-head"><b>${s.title}</b><span>${s.name ? s.name + " · " : ""}Step ${s.i + 1}/${s.n}</span></div>
    ${s.body.map((b) => `<div>${b}</div>`).join("")}
    <div class="tut-btns">
      <button id="tutSkip">Skip tutorial</button>
      ${s.manual
        ? `<button id="tutNext" class="primary">${s.button} ▸</button>`
        : `<span class="tut-hint">do the action above, or</span><button id="tutSkipStep">skip step ▸</button>`}
    </div>`;
  el("tutSkip").onclick = () => { G.tutorial_skip(); lastTut = ""; };
  if (s.manual) el("tutNext").onclick = () => { G.tutorial_next(); lastTut = ""; };
  else el("tutSkipStep").onclick = () => { G.tutorial_skip_step(); lastTut = ""; };
}

function renderLessons(s) {
  const box = el("lessons");
  if (!s.active) {
    box.innerHTML = `<button id="lesStart">📘 Python lessons</button>`;
    el("lesStart").onclick = () => { const st = JSON.parse(G.lessons_start()); enterLesson(st); lastLes = ""; };
    return;
  }
  box.innerHTML = `
    <div class="les-head"><b>${s.title}</b><span>lesson ${s.i + 1}/${s.n}</span></div>
    ${s.teach.map((t) => `<div class="les-teach">${t}</div>`).join("")}
    <div class="les-task"><b>TASK</b> ${s.task}</div>
    ${s.concept ? `<div class="les-concept">concept: ${s.concept}</div>` : ""}
    ${s.hands_on ? `<div class="les-status ${s.passed ? "ok" : ""}">${s.passed ? "done ✓" : "edit the code, then Run to check"}</div>` : ""}
    <div class="les-btns">
      <button id="lesSkip">Skip lessons</button>
      ${s.can_advance ? `<button id="lesNext" class="primary">${s.i + 1 === s.n ? "Finish" : "Next"} ▸</button>` : ""}
    </div>`;
  el("lesSkip").onclick = () => { G.lessons_skip(); lastLes = ""; };
  if (s.can_advance) el("lesNext").onclick = () => { const st = JSON.parse(G.lessons_next()); enterLesson(st); lastLes = ""; };
}

function enterLesson(s) {
  if (s.active && s.hands_on && s.starter && cm) cm.setValue(s.starter);
  if (s.active && s.sandbox) G.grant_sandbox_credits();
}

function buildGlossary() {
  el("glossBody").innerHTML = helpData.glossary.map(
    ([term, def]) => `<div class="gl-item"><b>${term}</b><span>${def}</span></div>`).join("");
}

function drawBuildOverlay(s) {
  ctx.fillStyle = "#38e1b0"; ctx.font = "13px monospace";
  ctx.fillText("BUILD: click empty = node · click node then node = edge · RMB node/edge = remove", 10, 16);
  if (edgeSrc) {
    const n = s.nodes.find((nn) => nn.id === edgeSrc);
    if (n) {
      ctx.strokeStyle = "#38e1b0"; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(sx(n.x), sy(n.y), 18, 0, 7); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(sx(n.x), sy(n.y)); ctx.lineTo(sx(mouseW[0]), sy(mouseW[1])); ctx.stroke();
    }
  }
}

// ---------------------------------------------------------------- rendering
function render(s) {
  ctx.clearRect(0, 0, CW, CH);
  // faint dot grid so the space reads as a surface, not a void
  ctx.fillStyle = "rgba(230, 238, 246, 0.045)";
  for (let gx = 20; gx < CW; gx += 40)
    for (let gy = 20; gy < CH; gy += 40) ctx.fillRect(gx, gy, 1.5, 1.5);

  // edges: dark rail + lighter core (reads as a pipe)
  ctx.lineCap = "round";
  for (const e of s.edges) {
    ctx.strokeStyle = "#1d3049"; ctx.lineWidth = 8;
    ctx.beginPath(); ctx.moveTo(sx(e.ax), sy(e.ay)); ctx.lineTo(sx(e.bx), sy(e.by)); ctx.stroke();
    ctx.strokeStyle = "#33506e"; ctx.lineWidth = 2.5;
    ctx.beginPath(); ctx.moveTo(sx(e.ax), sy(e.ay)); ctx.lineTo(sx(e.bx), sy(e.by)); ctx.stroke();
    // direction arrow at 65%
    const t = 0.65, mx = e.ax + (e.bx - e.ax) * t, my = e.ay + (e.by - e.ay) * t;
    const ang = Math.atan2(e.by - e.ay, e.bx - e.ax);
    ctx.fillStyle = "#5a7c9d";
    ctx.beginPath();
    ctx.moveTo(sx(mx) + Math.cos(ang) * 7, sy(my) + Math.sin(ang) * 7);
    ctx.lineTo(sx(mx) + Math.cos(ang + 2.6) * 7, sy(my) + Math.sin(ang + 2.6) * 7);
    ctx.lineTo(sx(mx) + Math.cos(ang - 2.6) * 7, sy(my) + Math.sin(ang - 2.6) * 7);
    ctx.closePath(); ctx.fill();
  }

  // turret tethers UNDER nodes/turrets: show exactly which node each turret serves
  const nodeById = {};
  for (const n of s.nodes) nodeById[n.id] = n;
  for (const t of s.turrets) {
    const n = nodeById[t.node];
    if (!n) continue;
    ctx.strokeStyle = "rgba(56, 225, 176, 0.4)"; ctx.lineWidth = 1.5; ctx.setLineDash([3, 3]);
    ctx.beginPath(); ctx.moveTo(sx(t.x), sy(t.y)); ctx.lineTo(sx(n.x), sy(n.y)); ctx.stroke();
    ctx.setLineDash([]);
  }

  // nodes: load halo + core + queue badge; source/sink get labeled markers
  for (const n of s.nodes) {
    const frac = Math.min(n.queue, 8) / 8;
    const col = frac < 0.34 ? "#38e1b0" : frac < 0.67 ? "#f2c85a" : "#e5556e";
    if (n.queue) {                        // translucent halo scales with queue depth
      ctx.globalAlpha = 0.22;
      ctx.fillStyle = col;
      ctx.beginPath(); ctx.arc(sx(n.x), sy(n.y), 8 + Math.min(n.queue, 10) * 1.6, 0, 7); ctx.fill();
      ctx.globalAlpha = 1;
    }
    ctx.fillStyle = "#0b1320";
    ctx.beginPath(); ctx.arc(sx(n.x), sy(n.y), 7, 0, 7); ctx.fill();
    ctx.strokeStyle = col; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(sx(n.x), sy(n.y), 7, 0, 7); ctx.stroke();
    ctx.fillStyle = col;
    ctx.beginPath(); ctx.arc(sx(n.x), sy(n.y), 2.5, 0, 7); ctx.fill();
    if (n.source) {
      ctx.fillStyle = "#8fa3b6"; ctx.font = "bold 11px monospace";
      ctx.fillText("IN ▶", sx(n.x) - 14, sy(n.y) - 14);
    }
    if (n.sink) {
      ctx.fillStyle = "rgba(229, 85, 110, 0.25)"; ctx.fillRect(sx(n.x) - 3, sy(n.y) - 22, 12, 44);
      ctx.fillStyle = "#e5556e"; ctx.fillRect(sx(n.x) + 6, sy(n.y) - 22, 3, 44);
      ctx.font = "bold 11px monospace"; ctx.fillText("EXIT", sx(n.x) - 10, sy(n.y) + 36);
    }
    if (n.queue) {                        // queue-count badge
      const label = String(n.queue), w = 10 + label.length * 7;
      ctx.fillStyle = "rgba(11, 19, 32, 0.9)";
      ctx.beginPath(); ctx.roundRect(sx(n.x) + 10, sy(n.y) - 20, w, 15, 7); ctx.fill();
      ctx.strokeStyle = col; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.roundRect(sx(n.x) + 10, sy(n.y) - 20, w, 15, 7); ctx.stroke();
      ctx.fillStyle = col; ctx.font = "11px monospace";
      ctx.fillText(label, sx(n.x) + 15, sy(n.y) - 9);
    }
  }

  // packets: soft glow + bright core, so traffic is alive and readable
  for (const p of s.packets) {
    ctx.globalAlpha = 0.3;
    ctx.fillStyle = rgb(p.color);
    ctx.beginPath(); ctx.arc(sx(p.x), sy(p.y), 7.5, 0, 7); ctx.fill();
    ctx.globalAlpha = 1;
    ctx.beginPath(); ctx.arc(sx(p.x), sy(p.y), 3.5, 0, 7); ctx.fill();
  }

  // turrets
  for (const t of s.turrets) {
    ctx.fillStyle = "#0d1826"; ctx.beginPath(); ctx.arc(sx(t.x), sy(t.y), 12, 0, 7); ctx.fill();
    ctx.strokeStyle = "#38e1b0"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(sx(t.x), sy(t.y), 12, 0, 7); ctx.stroke();
    ctx.strokeStyle = "rgba(56, 225, 176, 0.25)";
    ctx.beginPath(); ctx.arc(sx(t.x), sy(t.y), 15, 0, 7); ctx.stroke();
    ctx.fillStyle = "#38e1b0"; ctx.font = "bold 11px monospace";
    ctx.fillText(t.id, sx(t.x) - 8, sy(t.y) - 19);
    t.colors.forEach((c, i) => { ctx.fillStyle = rgb(c); ctx.fillRect(sx(t.x) - 12 + i * 6, sy(t.y) + 17, 5, 5); });
  }
  // flow devices: gates (diamond @ fork), limiters (valve), parsers (hexagon)
  for (const g of s.gates || []) {
    const X = sx(g.x), Y = sy(g.y);
    diamond(X, Y, 13); ctx.fillStyle = "#0b1320"; ctx.fill();
    diamond(X, Y, 13); ctx.strokeStyle = "#f0c878"; ctx.lineWidth = 2; ctx.stroke();
    ctx.fillStyle = "#f0c878"; ctx.font = "11px monospace"; ctx.fillText(g.id, X - 8, Y - 20);
  }
  for (const lm of s.limiters || []) {
    const X = sx(lm.x), Y = sy(lm.y);
    ctx.fillStyle = "#0b1320"; ctx.fillRect(X - 9, Y - 9, 18, 18);
    ctx.strokeStyle = "#f2c85a"; ctx.lineWidth = 2; ctx.strokeRect(X - 9, Y - 9, 18, 18);
    ctx.beginPath(); ctx.moveTo(X, Y - 9); ctx.lineTo(X, Y + 9); ctx.stroke();
    ctx.fillStyle = "#f2c85a"; ctx.font = "11px monospace"; ctx.fillText(lm.id, X - 8, Y - 14);
  }
  for (const ps of s.parsers || []) {
    const X = sx(ps.x), Y = sy(ps.y);
    hexagon(X, Y, 11); ctx.fillStyle = "#0b1320"; ctx.fill();
    hexagon(X, Y, 11); ctx.strokeStyle = "#be96ff"; ctx.lineWidth = 2; ctx.stroke();
    ctx.fillStyle = "#be96ff"; ctx.font = "11px monospace"; ctx.fillText(ps.id, X - 8, Y - 16);
    (ps.colors || []).forEach((c, i) => { ctx.fillStyle = rgb(c); ctx.fillRect(X - 12 + i * 5, Y + 13, 4, 4); });
  }
  // bottleneck callout: ring + label the most backed-up node when it's serious
  let worst = null;
  for (const n of s.nodes) if (!worst || n.queue > worst.queue) worst = n;
  if (worst && worst.queue > worst.cap - 2) {
    ctx.strokeStyle = "#e5556e"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(sx(worst.x), sy(worst.y), 22, 0, 7); ctx.stroke();
    ctx.fillStyle = "#e5556e"; ctx.font = "12px monospace";
    ctx.fillText("BOTTLENECK", sx(worst.x) - 34, sy(worst.y) + 40);
    ctx.fillStyle = "#f2c85a";
    ctx.fillText("add a turret, a limiter, or a parallel branch", sx(worst.x) - 130, sy(worst.y) + 56);
  }
}

// ---------------------------------------------------------------- HUD (crisp DOM)
function updateHUD(s) {
  const hpFrac = Math.max(0, s.health / s.max_health);
  const hpCol = hpFrac < 0.34 ? "var(--danger)" : hpFrac < 0.67 ? "var(--ink)" : "var(--phos)";
  const cov = s.coverage_gaps.length
    ? `<span class="cov-gap">COVERAGE GAP: ${s.coverage_gaps.join(", ")}</span>`
    : `<span class="cov-ok">coverage: all seen kinds handled</span>`;

  let rows = "";
  for (const [k, v] of Object.entries(s.stats)) {
    rows += `<tr class="${v.gap ? "gap" : ""}">
      <td><span class="sw" style="background:${rgb(v.color)}"></span>${v.gap ? "!" : ""}${k}</td>
      <td>${v.in}</td><td>${v.ok}</td><td>${v.leak}</td><td>${v.now}</td></tr>`;
  }

  const leakCol = s.leaks >= s.max_leaks - 3 ? "var(--danger)" : "var(--ink)";
  el("hud").innerHTML = `
    <div class="stats">
      <div class="stat"><span>wave</span><b>${s.wave}</b></div>
      <div class="stat hoverable" title="Your latency budget. Alerts queued too long drain it; at 0 the pipeline goes down.">
        <span>health</span><b style="color:${hpCol}">${s.health}</b>
        <span class="bar"><i style="width:${hpFrac * 100}%;background:${hpCol}"></i></span>
      </div>
      <div class="stat hoverable" title="Alerts lost (unhandled at the exit, or overflowed a full queue). Hit the cap and the run ends.">
        <span>leaks</span><b style="color:${leakCol}">${s.leaks}<small style="color:var(--muted)">/${s.max_leaks}</small></b>
      </div>
      <div class="stat hoverable" title="Your budget. Grows each wave; spend on turrets, removing refunds.">
        <span>credits</span><b style="color:var(--phos)">${s.credits}</b>
      </div>
    </div>
    <div class="cov">${cov}</div>
    <table class="kinds">
      <tr><th>kind</th><th>in</th><th>ok</th><th>leak</th><th>now</th></tr>
      ${rows || `<tr><td colspan="5" style="color:var(--muted)">no traffic yet</td></tr>`}
    </table>
    ${coachHtml(s)}`;

  // wave / start prompt over the board
  const msg = el("waveMsg");
  if (s.over) { msg.textContent = s.won ? "PIPELINE HELD ✓" : "PIPELINE OVERWHELMED ✕"; }
  else if (!running && s.upcoming.length) {
    // proactive coverage check: flag incoming kinds you can't handle yet, before they leak
    const covered = new Set();
    s.turrets.forEach((t) => t.accepts.forEach((k) => covered.add(k)));
    const up = s.upcoming.map((u) => {
      if (u.kind === "raw") return `<span style="color:var(--muted)">raw×${u.n}</span>`;
      const ok = covered.has(u.kind);
      return `<span style="color:${ok ? "var(--phos)" : "var(--danger)"}">${ok ? "✓" : "✗"} ${u.kind}×${u.n}</span>`;
    }).join("  ");
    msg.innerHTML = `Wave ${s.wave} — press Start.  incoming: ${up}`;
  } else msg.textContent = "";
}

// map a coach fix to the UI element that carries it out ("show me")
function findCoachTarget(fix) {
  if (!fix || !lastPal) return null;
  for (const g of lastPal.guns)
    if (new RegExp(`\\b${g.name}\\b`).test(fix)) return { sel: `[data-gun="${g.name}"]` };
  for (const m of (lastPal.modules || []))
    if (fix.includes(`'${m.name}'`) || fix.includes(m.name)) return { sel: `[data-mod="${m.name}"]` };
  if (/quelimiter|limiter/i.test(fix)) return { sel: `[data-dev="limiter"]` };
  if (/\bgate\b/i.test(fix)) return { sel: `[data-dev="gate"]` };
  if (/parser|build_parsers|loadout\.py/i.test(fix)) return { editor: true };
  return null;
}

function coachHtml(s) {
  if (!s.coach || !s.coach.length) return "";
  const h = s.coach[0];
  const lc = { danger: "var(--danger)", warn: "var(--amber)", tip: "var(--phos)", ok: "var(--phos)" }[h.level] || "var(--ink)";
  if (h.level === "ok") return `<div class="coach ok">COACH: ${h.text}</div>`;
  const target = findCoachTarget(h.fix);
  const showBtn = target
    ? `<button class="coach-show" ${target.editor ? 'data-editor="1"' : `data-sel='${target.sel}'`}>⌖ show me</button>`
    : "";
  return `<div class="coach" style="border-color:${lc}">
    <div class="coach-head" style="color:${lc}">COACH ▸ ${h.text}</div>
    ${h.why ? `<div class="coach-line"><b>WHY</b> ${h.why}</div>` : ""}
    ${h.fix ? `<div class="coach-line coach-fix"><b>FIX</b> ${h.fix}</div>` : ""}
    <div class="coach-foot">
      ${h.concept ? `<span class="coach-concept">concept: ${h.concept}</span>` : "<span></span>"}
      ${showBtn}
    </div>
  </div>`;
}

boot().catch((e) => { el("boot-sub").textContent = "error: " + e; console.error(e); });
