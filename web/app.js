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
let running = false, over = false;
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
  };

  const meta = JSON.parse(G.new_game("trunk", "easy"));
  fillSelect(el("mapSel"), meta.maps, "trunk");
  fillSelect(el("diffSel"), meta.difficulties, "easy");
  el("code").value = DEFAULT_LOADOUT;
  applyLoadout();

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
  el("startBtn").textContent = "▶ Start";
}

function applyLoadout() {
  const res = JSON.parse(G.load_loadout(el("code").value));
  const s = el("codeStatus");
  if (res.ok) { s.textContent = `deployed ${res.turrets} turret(s)`; s.className = "code-status ok"; }
  else { s.textContent = res.error; s.className = "code-status err"; }
}

function wireUI() {
  el("startBtn").onclick = () => {
    if (over) return;
    running = !running;
    if (running) { G.begin(); el("startBtn").textContent = "❚❚ Pause"; }
    else { G.set_paused(true); el("startBtn").textContent = "▶ Start"; }
  };
  el("resetBtn").onclick = newGame;
  el("mapSel").onchange = newGame;
  el("diffSel").onchange = newGame;
  el("runBtn").onclick = applyLoadout;
  el("code").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); applyLoadout(); }
    if (e.key === "Tab") { e.preventDefault(); insertAtCursor(el("code"), "    "); }
  });
}

function insertAtCursor(ta, text) {
  const s = ta.selectionStart, e = ta.selectionEnd;
  ta.value = ta.value.slice(0, s) + text + ta.value.slice(e);
  ta.selectionStart = ta.selectionEnd = s + text.length;
}

function frame(now) {
  const dt = Math.min((now - last) / 1000, 0.05);
  last = now;
  if (running && !over) G.step(dt);
  const s = JSON.parse(G.snapshot_json());
  over = s.over;
  if (over && running) { running = false; el("startBtn").textContent = "▶ Start"; }
  render(s);
  updateHUD(s);
  requestAnimationFrame(frame);
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
    </table>`;

  // wave / start prompt over the board
  const msg = el("waveMsg");
  if (s.over) msg.textContent = s.won ? "PIPELINE HELD ✓" : "PIPELINE OVERWHELMED ✕";
  else if (!running) {
    const up = s.upcoming.map((u) => `${u.kind}×${u.n}`).join("  ");
    msg.textContent = `Wave ${s.wave} ready — press Start.  incoming: ${up}`;
  } else msg.textContent = "";
}

boot().catch((e) => { el("boot-sub").textContent = "error: " + e; console.error(e); });
