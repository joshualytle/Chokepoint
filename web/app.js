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

const el = (id) => document.getElementById(id);
let G = null;                              // Python bridge function handles
let cm = null;                             // CodeMirror editor instance
let running = false, over = false;
let selectedGun = null;                    // gun chosen in the palette (click to place)
let buildMode = false, edgeSrc = null;     // topology editing state
let mouseW = [0, 0];                       // last mouse position in world coords
let helpData = null;                       // {glossary, hud}
let lastTut = "", lastLes = "";            // panel-state caches (avoid re-rendering every frame)
let last = performance.now();

const DEFAULT_LOADOUT = `# Edit build_loadout, then Run (Ctrl+Enter).
# Available without imports: Turret(x, y, gun=...), make_gun("name").
# Guns: sieve(auth,dns)  scatter(ids,firewall)  relay(dns,email)
#       auditor(cloudtrail)  lance(endpoint)  quarantine(email) ...
def build_loadout(unlocked, slots):
    return [
        Turret(*slots[0], gun=make_gun("sieve")),     # covers auth, dns
        Turret(*slots[1], gun=make_gun("scatter")),   # covers ids, firewall
    ]
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
    place_at: pyodide.globals.get("place_at"),
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
    lessons_state: pyodide.globals.get("lessons_state"),
    lessons_next: pyodide.globals.get("lessons_next"),
    lessons_skip: pyodide.globals.get("lessons_skip"),
    lessons_start: pyodide.globals.get("lessons_start"),
    grant_sandbox_credits: pyodide.globals.get("grant_sandbox_credits"),
  };

  const savedMap = localStorage.getItem(SK("map"));
  const savedDiff = localStorage.getItem(SK("diff"));
  const savedCode = localStorage.getItem(SK("loadout"));
  const meta = JSON.parse(G.new_game(savedMap || "trunk", savedDiff || "easy"));
  fillSelect(el("mapSel"), meta.maps, savedMap || "trunk");
  fillSelect(el("diffSel"), meta.difficulties, savedDiff || "easy");
  el("code").value = savedCode || DEFAULT_LOADOUT;
  cm = CodeMirror.fromTextArea(el("code"), {
    mode: "python", theme: "material-darker", lineNumbers: true,
    indentUnit: 4, matchBrackets: true, autofocus: false,
    extraKeys: { "Ctrl-Enter": applyLoadout, "Cmd-Enter": applyLoadout },
  });
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
  } else { s.textContent = res.error; s.className = "code-status err"; }
  refreshPalette();
  G.tutorial_signal("run"); lastTut = ""; lastLes = "";
  autoSave();
}

// ------------------------------------------------------------- persistence
const SK = (k) => "chokepoint." + k;

function autoSave() {
  try {
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

function refreshPalette() {
  const items = JSON.parse(G.palette_json());
  selectedGun = (items.find((g) => g.selected) || {}).name || null;
  el("palette").innerHTML =
    `<div class="palette-head">GUNS — click one, then click a node on the board (right-click a turret to remove)</div>` +
    items.map((g) => `
      <button class="gun ${g.selected ? "sel" : ""} ${g.afford ? "" : "poor"}" data-gun="${g.name}">
        <span class="gun-name">${g.name}</span><span class="gun-cost">${g.cost}cr</span>
        <span class="gun-kinds">${g.accepts.map((k, i) =>
          `<span class="sw" style="background:${rgb(g.colors[i])}"></span>${k}`).join(" ")}</span>
      </button>`).join("");
  el("palette").querySelectorAll("button.gun").forEach((b) => {
    b.onclick = () => { G.select_gun(b.dataset.gun); refreshPalette(); };
  });
}

function eventToWorld(e) {
  const r = canvas.getBoundingClientRect();
  return [(e.clientX - r.left) * (CW / r.width) - OFFX,
          (e.clientY - r.top) * (CH / r.height) - OFFY];
}

function wireUI() {
  el("startBtn").onclick = () => {
    if (over) return;
    running = !running;
    if (running) { G.begin(); el("startBtn").textContent = "❚❚ Pause"; G.tutorial_signal("start"); lastTut = ""; }
    else { G.set_paused(true); el("startBtn").textContent = "▶ Start"; }
  };
  el("helpBtn").onclick = () => el("glossary").classList.toggle("hidden");
  el("glossClose").onclick = () => el("glossary").classList.add("hidden");
  el("copyBtn").onclick = exportSaveCode;
  el("loadBtn").onclick = importSaveCode;
  el("resetBtn").onclick = newGame;
  el("mapSel").onchange = newGame;
  el("diffSel").onchange = newGame;
  el("runBtn").onclick = applyLoadout;   // CodeMirror handles Ctrl/Cmd-Enter + Tab
  el("buildBtn").onclick = () => {
    buildMode = !buildMode; edgeSrc = null;
    el("buildBtn").classList.toggle("primary", buildMode);
  };

  canvas.addEventListener("contextmenu", (e) => e.preventDefault());
  canvas.addEventListener("mousemove", (e) => { mouseW = eventToWorld(e); });
  canvas.addEventListener("mousedown", (e) => {
    const [x, y] = eventToWorld(e);
    if (buildMode) return onBuildClick(e.button, x, y);
    if (e.button === 2) { G.remove_at(x, y); refreshPalette(); }        // right-click: remove
    else if (selectedGun) {                                            // left-click: place
      if (JSON.parse(G.place_at(x, y)).ok) { G.tutorial_signal("place"); lastTut = ""; }
      refreshPalette();
    }
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
  if (running && !over) G.step(dt);
  const s = JSON.parse(G.snapshot_json());
  over = s.over;
  if (over && running) { running = false; el("startBtn").textContent = "▶ Start"; }
  render(s);
  if (buildMode) drawBuildOverlay(s);
  updateHUD(s);
  tickPanels();
  requestAnimationFrame(frame);
}

// ------------------------------------------------- tutorial + lessons panels
function tickPanels() {
  const tj = G.tutorial_state();
  if (tj !== lastTut) { lastTut = tj; renderTutorial(JSON.parse(tj)); }
  const lj = G.lessons_state();
  if (lj !== lastLes) { lastLes = lj; renderLessons(JSON.parse(lj)); }
}

function renderTutorial(s) {
  const box = el("tutorial");
  if (!s.active) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  box.innerHTML = `
    <div class="tut-head"><b>${s.title}</b><span>Step ${s.i + 1}/${s.n}</span></div>
    ${s.body.map((b) => `<div>${b}</div>`).join("")}
    <div class="tut-btns">
      <button id="tutSkip">Skip</button>
      ${s.manual ? `<button id="tutNext" class="primary">${s.button} ▸</button>`
                 : `<span class="tut-hint">(do the action above to continue)</span>`}
    </div>`;
  el("tutSkip").onclick = () => { G.tutorial_skip(); lastTut = ""; };
  if (s.manual) el("tutNext").onclick = () => { G.tutorial_next(); lastTut = ""; };
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
  // edges
  ctx.strokeStyle = "#2b4460"; ctx.lineWidth = 6; ctx.lineCap = "round";
  for (const e of s.edges) {
    ctx.beginPath(); ctx.moveTo(sx(e.ax), sy(e.ay)); ctx.lineTo(sx(e.bx), sy(e.by)); ctx.stroke();
    // direction arrow at 65%
    const t = 0.65, mx = e.ax + (e.bx - e.ax) * t, my = e.ay + (e.by - e.ay) * t;
    const ang = Math.atan2(e.by - e.ay, e.bx - e.ax);
    ctx.fillStyle = "#46647d";
    ctx.beginPath();
    ctx.moveTo(sx(mx) + Math.cos(ang) * 7, sy(my) + Math.sin(ang) * 7);
    ctx.lineTo(sx(mx) + Math.cos(ang + 2.6) * 7, sy(my) + Math.sin(ang + 2.6) * 7);
    ctx.lineTo(sx(mx) + Math.cos(ang - 2.6) * 7, sy(my) + Math.sin(ang - 2.6) * 7);
    ctx.closePath(); ctx.fill();
  }
  // nodes
  for (const n of s.nodes) {
    const frac = Math.min(n.queue, 8) / 8;
    const col = frac < 0.34 ? "#38e1b0" : frac < 0.67 ? "#f2c85a" : "#e5556e";
    if (n.sink) { ctx.fillStyle = "#e5556e"; ctx.fillRect(sx(n.x) - 4, sy(n.y) - 18, 7, 36); }
    ctx.fillStyle = col;
    ctx.beginPath(); ctx.arc(sx(n.x), sy(n.y), 5 + Math.min(n.queue, 8), 0, 7); ctx.fill();
    if (n.queue) { ctx.fillStyle = col; ctx.font = "12px monospace"; ctx.fillText(n.queue, sx(n.x) + 10, sy(n.y) - 8); }
  }
  // packets
  for (const p of s.packets) {
    ctx.fillStyle = rgb(p.color);
    ctx.beginPath(); ctx.arc(sx(p.x), sy(p.y), 4, 0, 7); ctx.fill();
  }
  // turrets
  for (const t of s.turrets) {
    ctx.fillStyle = "#0b1320"; ctx.beginPath(); ctx.arc(sx(t.x), sy(t.y), 12, 0, 7); ctx.fill();
    ctx.strokeStyle = "#38e1b0"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(sx(t.x), sy(t.y), 12, 0, 7); ctx.stroke();
    ctx.fillStyle = "#38e1b0"; ctx.font = "12px monospace"; ctx.fillText(t.id, sx(t.x) - 8, sy(t.y) - 18);
    t.colors.forEach((c, i) => { ctx.fillStyle = rgb(c); ctx.fillRect(sx(t.x) - 12 + i * 6, sy(t.y) + 14, 5, 5); });
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

  el("hud").innerHTML = `
    <div class="row">
      <span class="stat">wave <b>${s.wave}</b></span>
      <span class="stat hoverable" title="Alerts lost (unhandled at the exit, or overflowed a full queue). Hit the cap and the run ends.">leaks <b>${s.leaks}/${s.max_leaks}</b></span>
      <span class="stat hoverable" title="Your budget. Grows each wave; spend on turrets, removing refunds.">cr <b>${s.credits}</b></span>
    </div>
    <div class="row" style="margin-top:6px">
      <span class="stat hoverable" title="Your latency budget. Alerts queued too long drain it; at 0 the pipeline goes down.">health <b style="color:${hpCol}">${s.health}</b></span>
      <span class="bar"><i style="width:${hpFrac * 100}%;background:${hpCol}"></i></span>
    </div>
    <div class="row" style="margin-top:6px">${cov}</div>
    <table class="kinds">
      <tr><th>KIND</th><th>in</th><th>ok</th><th>leak</th><th>now</th></tr>
      ${rows || `<tr><td colspan="5" style="color:var(--muted)">no traffic yet</td></tr>`}
    </table>
    ${coachHtml(s)}`;

  // wave / start prompt over the board
  const msg = el("waveMsg");
  if (s.over) msg.textContent = s.won ? "PIPELINE HELD ✓" : "PIPELINE OVERWHELMED ✕";
  else if (!running) {
    const up = s.upcoming.map((u) => `${u.kind}×${u.n}`).join("  ");
    msg.textContent = `Wave ${s.wave} ready — press Start.  incoming: ${up}`;
  } else msg.textContent = "";
}

function coachHtml(s) {
  if (!s.coach || !s.coach.length) return "";
  const h = s.coach[0];
  const lc = { danger: "var(--danger)", warn: "var(--amber)", tip: "var(--phos)", ok: "var(--phos)" }[h.level] || "var(--ink)";
  if (h.level === "ok") return `<div class="coach ok">COACH: ${h.text}</div>`;
  return `<div class="coach" style="border-color:${lc}">
    <div class="coach-head" style="color:${lc}">COACH ▸ ${h.text}</div>
    ${h.why ? `<div class="coach-line"><b>WHY</b> ${h.why}</div>` : ""}
    ${h.fix ? `<div class="coach-line coach-fix"><b>FIX</b> ${h.fix}</div>` : ""}
    ${h.concept ? `<div class="coach-concept">concept: ${h.concept}</div>` : ""}
  </div>`;
}

boot().catch((e) => { el("boot-sub").textContent = "error: " + e; console.error(e); });
