# server/api.py
# Issue #3 - REST endpoints
# Issue #4 - WebSocket real-time stream
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from contextlib import asynccontextmanager
import asyncio
import json
import logging
import time

from server.models import AircraftState
from server import state as shared

log = logging.getLogger("iox-api")

# ----------------------------------------------------------------
# WebSocket connection manager
# ----------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)
        log.info(f"WS client connected. Total: {len(self.active)}")

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)
        log.info(f"WS client disconnected. Total: {len(self.active)}")

    async def broadcast(self, data: str):
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)


manager = ConnectionManager()


# ----------------------------------------------------------------
# Background task: broadcast state to WS clients at 30Hz
# ----------------------------------------------------------------
async def broadcast_loop():
    log.info("WebSocket broadcast loop started")
    while True:
        await asyncio.sleep(1 / 30)  # 30Hz
        if shared.latest_state and manager.active:
            payload = shared.latest_state.model_dump_json()
            await manager.broadcast(payload)


# ----------------------------------------------------------------
# App lifespan
# ----------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(broadcast_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


# ----------------------------------------------------------------
# FastAPI app
# ----------------------------------------------------------------
app = FastAPI(
    title="dcs-iox-api",
    description="DCS World IOX API — Export.lua bridge + REST/WebSocket server",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------
# REST endpoints
# ----------------------------------------------------------------
@app.get("/health", tags=["System"])
async def health():
    """Server health check."""
    return {
        "status": "ok",
        "uptime": time.time() - shared.start_time,
        "packets_received": shared.packet_count,
        "dcs_connected": shared.latest_state is not None,
    }


@app.get("/logs", tags=["System"])
async def get_logs(n: int = 50):
    """Returns the last N server log entries (default 50, max 200)."""
    entries = list(shared.log_buffer)
    return {
        "count": len(entries),
        "logs": entries[-min(n, 200):],
    }


@app.get("/logs/view", response_class=HTMLResponse, tags=["System"], include_in_schema=False)
async def logs_view():
    """Live log dashboard — auto-refreshes every 10 seconds."""
    html = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>dcs-iox-api | Logs</title>
  <style>
    :root {
      --bg: #171614;
      --surface: #1c1b19;
      --border: #393836;
      --text: #cdccca;
      --text-muted: #797876;
      --primary: #4f98a3;
      --radius: 6px;
      --font: 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: var(--font);
      font-size: 13px;
      min-height: 100vh;
      padding: 24px;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 20px;
      flex-wrap: wrap;
      gap: 12px;
    }
    .logo {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .logo svg { color: var(--primary); }
    .logo h1 { font-size: 16px; font-weight: 600; letter-spacing: 0.05em; color: var(--primary); }
    .logo span { font-size: 12px; color: var(--text-muted); }
    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 12px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      font-size: 12px;
      color: var(--text-muted);
    }
    .dot {
      width: 8px; height: 8px;
      border-radius: 50%;
      background: var(--primary);
      animation: pulse 2s ease-in-out infinite;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.3; }
    }
    .toolbar {
      display: flex;
      gap: 8px;
      margin-bottom: 12px;
      flex-wrap: wrap;
      align-items: center;
    }
    .toolbar label { color: var(--text-muted); font-size: 12px; }
    select, input[type=number] {
      background: var(--surface);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 4px 8px;
      border-radius: var(--radius);
      font-family: var(--font);
      font-size: 12px;
    }
    .btn {
      padding: 4px 12px;
      background: var(--primary);
      color: #171614;
      border: none;
      border-radius: var(--radius);
      cursor: pointer;
      font-size: 12px;
      font-weight: 600;
      font-family: var(--font);
      transition: opacity 0.15s;
    }
    .btn:hover { opacity: 0.85; }
    #log-box {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px;
      height: calc(100vh - 180px);
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 2px;
    }
    .log-line {
      display: grid;
      grid-template-columns: 70px 70px 1fr;
      gap: 12px;
      padding: 3px 0;
      border-bottom: 1px solid rgba(255,255,255,0.03);
      line-height: 1.5;
    }
    .log-line:last-child { border-bottom: none; }
    .ts { color: var(--text-muted); }
    .lvl { font-weight: 700; }
    .msg { word-break: break-all; }
    .empty {
      color: var(--text-muted);
      text-align: center;
      padding: 40px;
      font-style: italic;
    }
    #countdown {
      font-size: 11px;
      color: var(--text-muted);
    }
  </style>
</head>
<body>
  <header>
    <div class="logo">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 2L2 7l10 5 10-5-10-5z"/>
        <path d="M2 17l10 5 10-5"/>
        <path d="M2 12l10 5 10-5"/>
      </svg>
      <div>
        <h1>dcs-iox-api</h1>
        <span>Live Server Logs</span>
      </div>
    </div>
    <div style="display:flex;gap:8px;align-items:center;">
      <div class="badge"><div class="dot"></div><span id="status-text">conectando...</span></div>
      <span id="countdown" class="badge">next refresh: 10s</span>
    </div>
  </header>

  <div class="toolbar">
    <label>Linhas:</label>
    <input type="number" id="n-lines" value="50" min="10" max="200" style="width:70px">
    <label>Filtro:</label>
    <select id="filter-level">
      <option value="ALL">Todos</option>
      <option value="INFO">INFO</option>
      <option value="WARNING">WARNING</option>
      <option value="ERROR">ERROR</option>
      <option value="DEBUG">DEBUG</option>
    </select>
    <button class="btn" onclick="fetchLogs()">&#8635; Atualizar agora</button>
    <button class="btn" onclick="clearView()" style="background:#393836;color:var(--text)">Limpar view</button>
  </div>

  <div id="log-box"><div class="empty">Aguardando logs...</div></div>

<script>
  let countdown = 10;
  let timer;

  async function fetchLogs() {
    const n = document.getElementById('n-lines').value || 50;
    const level = document.getElementById('filter-level').value;
    try {
      const res = await fetch(`/logs?n=${n}`);
      const data = await res.json();
      renderLogs(data.logs, level);
      document.getElementById('status-text').textContent =
        `${data.count} entradas | upd: ${new Date().toLocaleTimeString('pt-BR')}`;
    } catch(e) {
      document.getElementById('status-text').textContent = 'erro ao buscar logs';
    }
    resetCountdown();
  }

  function renderLogs(logs, level) {
    const box = document.getElementById('log-box');
    const filtered = level === 'ALL' ? logs : logs.filter(l => l.level === level);
    if (!filtered.length) {
      box.innerHTML = '<div class="empty">Nenhum log encontrado para este filtro.</div>';
      return;
    }
    box.innerHTML = filtered.map(l => `
      <div class="log-line">
        <span class="ts">${l.ts}</span>
        <span class="lvl" style="color:${l.color}">${l.level}</span>
        <span class="msg">${escHtml(l.message)}</span>
      </div>`).join('');
    box.scrollTop = box.scrollHeight;
  }

  function escHtml(s) {
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function clearView() {
    document.getElementById('log-box').innerHTML = '<div class="empty">View limpa. Próximo refresh em ' + countdown + 's</div>';
  }

  function resetCountdown() {
    clearInterval(timer);
    countdown = 10;
    document.getElementById('countdown').textContent = `next refresh: ${countdown}s`;
    timer = setInterval(() => {
      countdown--;
      document.getElementById('countdown').textContent = `next refresh: ${countdown}s`;
      if (countdown <= 0) fetchLogs();
    }, 1000);
  }

  fetchLogs();
</script>
</body>
</html>
    """
    return HTMLResponse(content=html)


@app.get("/state", response_model=AircraftState, tags=["Telemetry"])
async def get_state():
    """Full aircraft state (latest frame from DCS)."""
    if shared.latest_state is None:
        raise HTTPException(status_code=503, detail="No data from DCS yet. Is Export.lua running?")
    return shared.latest_state


@app.get("/telemetry", tags=["Telemetry"])
async def get_telemetry():
    """Concise flight parameters — position, speed, attitude."""
    if shared.latest_state is None:
        raise HTTPException(status_code=503, detail="No data from DCS yet. Is Export.lua running?")
    s = shared.latest_state
    return {
        "aircraft": s.aircraft,
        "timestamp": s.timestamp,
        "position": {
            "lat": s.lat,
            "lon": s.lon,
            "alt_msl_m": s.alt_msl_m,
            "alt_agl_m": s.alt_agl_m,
        },
        "speed": {
            "ias_ms": s.ias_ms,
            "ias_kts": round(s.ias_ms * 1.944, 1),
            "tas_ms": s.tas_ms,
            "mach": s.mach,
            "vvi_ms": s.vvi_ms,
        },
        "attitude": {
            "heading_deg": s.heading_deg,
            "pitch_deg": s.pitch_deg,
            "bank_deg": s.bank_deg,
            "aoa_deg": s.aoa_deg,
        },
    }


# ----------------------------------------------------------------
# Dashboard — Live Cockpit HUD
# ----------------------------------------------------------------
@app.get("/dashboard", response_class=HTMLResponse, tags=["System"], include_in_schema=False)
async def dashboard():
    """Live cockpit HUD — WebSocket powered, 30Hz update."""
    html = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DCS IOX — Live HUD</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@400;700&display=swap');

  :root {
    --bg:      #0a0c0a;
    --panel:   #0d110d;
    --border:  #1a2a1a;
    --green:   #39ff6e;
    --green-dim:#1a7a35;
    --amber:   #ffb830;
    --red:     #ff4040;
    --blue:    #40c8ff;
    --text:    #c8e8c8;
    --muted:   #4a6a4a;
    --font-mono: 'Share Tech Mono', monospace;
    --font-hud:  'Orbitron', sans-serif;
    --glow: 0 0 8px rgba(57,255,110,0.35);
  }

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-mono);
    font-size: 13px;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    overflow-x: hidden;
  }

  /* ── Top bar ── */
  #topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 20px;
    border-bottom: 1px solid var(--border);
    background: var(--panel);
    flex-shrink: 0;
  }
  #topbar .logo {
    font-family: var(--font-hud);
    font-size: 14px;
    font-weight: 700;
    color: var(--green);
    letter-spacing: 0.15em;
    text-shadow: var(--glow);
  }
  #topbar .logo span { color: var(--muted); font-weight: 400; font-size: 11px; margin-left: 8px; }
  #ws-status {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 11px;
    color: var(--muted);
  }
  #ws-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    background: var(--muted);
    transition: background 0.3s;
  }
  #ws-dot.live { background: var(--green); box-shadow: var(--glow); animation: blink 2s infinite; }
  #ws-dot.error { background: var(--red); }
  @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.4} }

  #aircraft-id {
    font-family: var(--font-hud);
    font-size: 12px;
    color: var(--amber);
    letter-spacing: 0.1em;
  }

  /* ── Main grid ── */
  #main {
    flex: 1;
    display: grid;
    grid-template-columns: 200px 1fr 200px;
    grid-template-rows: 1fr auto;
    gap: 1px;
    background: var(--border);
    min-height: 0;
  }

  .panel {
    background: var(--panel);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 16px 12px;
    gap: 16px;
  }

  /* ── Center: ADI canvas ── */
  #center-panel {
    background: var(--bg);
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 20px;
    padding: 20px;
  }

  canvas {
    display: block;
  }

  /* ── Gauge block ── */
  .gauge-block {
    width: 100%;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }
  .gauge-label {
    font-size: 10px;
    color: var(--muted);
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }
  .gauge-value {
    font-family: var(--font-hud);
    font-size: 22px;
    font-weight: 700;
    color: var(--green);
    text-shadow: var(--glow);
    line-height: 1;
    transition: color 0.2s;
  }
  .gauge-unit {
    font-size: 10px;
    color: var(--muted);
  }
  .gauge-bar {
    width: 100%;
    height: 4px;
    background: var(--border);
    border-radius: 2px;
    overflow: hidden;
  }
  .gauge-bar-fill {
    height: 100%;
    background: var(--green);
    border-radius: 2px;
    transition: width 0.1s linear, background 0.2s;
  }

  /* ── Heading tape ── */
  #heading-tape-wrap {
    width: 300px;
    height: 36px;
    background: #0a140a;
    border: 1px solid var(--border);
    border-radius: 4px;
    overflow: hidden;
    position: relative;
  }
  #heading-tape-canvas { display: block; }
  #hdg-bug {
    position: absolute;
    top: 0; left: 50%;
    transform: translateX(-50%);
    width: 2px; height: 36px;
    background: var(--amber);
    pointer-events: none;
  }
  #hdg-bug::after {
    content: '';
    position: absolute;
    top: 0; left: 50%;
    transform: translateX(-50%);
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 8px solid var(--amber);
    margin-left: -4px;
  }

  /* ── VSI ── */
  #vsi-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
  }
  #vsi-arrow {
    font-size: 20px;
    line-height: 1;
    transition: transform 0.15s, color 0.15s;
  }

  /* ── Bottom bar ── */
  #bottombar {
    grid-column: 1 / -1;
    background: var(--panel);
    border-top: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 0;
    padding: 0;
    height: 40px;
    overflow: hidden;
  }
  .stat-cell {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    padding: 0 12px;
    border-right: 1px solid var(--border);
    height: 100%;
  }
  .stat-cell:last-child { border-right: none; }
  .stat-lbl { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; }
  .stat-val { font-family: var(--font-hud); font-size: 13px; color: var(--green); }

  /* ── Divider ── */
  .divider {
    width: 80%;
    height: 1px;
    background: var(--border);
  }

  /* ── Offline overlay ── */
  #offline {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(10,12,10,0.88);
    z-index: 100;
    align-items: center;
    justify-content: center;
    flex-direction: column;
    gap: 16px;
    font-family: var(--font-hud);
    color: var(--red);
    font-size: 18px;
    letter-spacing: 0.1em;
    text-align: center;
  }
  #offline.show { display: flex; }
  #offline small { font-family: var(--font-mono); font-size: 12px; color: var(--muted); }
  #retry-btn {
    margin-top: 8px;
    padding: 8px 24px;
    background: none;
    border: 1px solid var(--red);
    color: var(--red);
    font-family: var(--font-hud);
    font-size: 12px;
    cursor: pointer;
    letter-spacing: 0.1em;
    transition: background 0.2s;
  }
  #retry-btn:hover { background: rgba(255,64,64,0.15); }
</style>
</head>
<body>

<!-- Offline overlay -->
<div id="offline">
  <div>&#9888; NO DCS SIGNAL</div>
  <small id="offline-msg">WebSocket disconnected</small>
  <button id="retry-btn" onclick="initWS()">RECONNECT</button>
</div>

<!-- Top bar -->
<div id="topbar">
  <div class="logo">DCS IOX<span>LIVE HUD v0.1</span></div>
  <div id="aircraft-id">—</div>
  <div id="ws-status">
    <div id="ws-dot"></div>
    <span id="ws-label">OFFLINE</span>
  </div>
</div>

<!-- Main grid -->
<div id="main">

  <!-- LEFT PANEL: Airspeed + AoA + G -->
  <div class="panel" id="left-panel">
    <div class="gauge-block">
      <div class="gauge-label">IAS</div>
      <div class="gauge-value" id="ias-val">0</div>
      <div class="gauge-unit">knots</div>
      <div class="gauge-bar"><div class="gauge-bar-fill" id="ias-bar" style="width:0%"></div></div>
    </div>
    <div class="divider"></div>
    <div class="gauge-block">
      <div class="gauge-label">MACH</div>
      <div class="gauge-value" id="mach-val">0.00</div>
      <div class="gauge-unit"></div>
    </div>
    <div class="divider"></div>
    <div class="gauge-block">
      <div class="gauge-label">AoA</div>
      <div class="gauge-value" id="aoa-val">0.0</div>
      <div class="gauge-unit">deg</div>
    </div>
    <div class="divider"></div>
    <div class="gauge-block">
      <div class="gauge-label">G-FORCE</div>
      <div class="gauge-value" id="g-val">1.0</div>
      <div class="gauge-unit">g</div>
    </div>
  </div>

  <!-- CENTER PANEL: ADI + Heading tape -->
  <div id="center-panel">
    <canvas id="adi-canvas" width="260" height="260"></canvas>
    <div id="heading-tape-wrap">
      <canvas id="heading-tape-canvas" width="300" height="36"></canvas>
      <div id="hdg-bug"></div>
    </div>
    <div id="vsi-wrap">
      <div class="gauge-label">VERTICAL SPEED</div>
      <div id="vsi-arrow" style="color:var(--green)">&#9654;</div>
      <div class="gauge-value" id="vsi-val" style="font-size:18px">+0</div>
      <div class="gauge-unit">ft/min</div>
    </div>
  </div>

  <!-- RIGHT PANEL: Altitude + Fuel + Engine -->
  <div class="panel" id="right-panel">
    <div class="gauge-block">
      <div class="gauge-label">ALT MSL</div>
      <div class="gauge-value" id="alt-val">0</div>
      <div class="gauge-unit">feet</div>
      <div class="gauge-bar"><div class="gauge-bar-fill" id="alt-bar" style="width:0%"></div></div>
    </div>
    <div class="divider"></div>
    <div class="gauge-block">
      <div class="gauge-label">ALT AGL</div>
      <div class="gauge-value" id="agl-val">0</div>
      <div class="gauge-unit">feet</div>
    </div>
    <div class="divider"></div>
    <div class="gauge-block">
      <div class="gauge-label">FUEL</div>
      <div class="gauge-value" id="fuel-val">—</div>
      <div class="gauge-unit">kg</div>
      <div class="gauge-bar"><div class="gauge-bar-fill" id="fuel-bar" style="width:0%"></div></div>
    </div>
    <div class="divider"></div>
    <div class="gauge-block">
      <div class="gauge-label">ENGINE RPM</div>
      <div class="gauge-value" id="rpm-val">—</div>
      <div class="gauge-unit">%</div>
    </div>
  </div>

  <!-- BOTTOM BAR -->
  <div id="bottombar">
    <div class="stat-cell"><span class="stat-lbl">HDG</span><span class="stat-val" id="hdg-val">---°</span></div>
    <div class="stat-cell"><span class="stat-lbl">PITCH</span><span class="stat-val" id="pitch-val">---°</span></div>
    <div class="stat-cell"><span class="stat-lbl">BANK</span><span class="stat-val" id="bank-val">---°</span></div>
    <div class="stat-cell"><span class="stat-lbl">LAT</span><span class="stat-val" id="lat-val">---.----</span></div>
    <div class="stat-cell"><span class="stat-lbl">LON</span><span class="stat-val" id="lon-val">---.----</span></div>
    <div class="stat-cell"><span class="stat-lbl">PACKETS</span><span class="stat-val" id="pkt-val">0</span></div>
    <div class="stat-cell"><span class="stat-lbl">FPS</span><span class="stat-val" id="fps-val">--</span></div>
  </div>

</div><!-- /main -->

<script>
"use strict";

// ── State ──────────────────────────────────────────────────────
let state = null;
let ws = null;
let reconnectTimer = null;
let packetCount = 0;
let fpsCount = 0;
let lastFpsTime = performance.now();

// ── ADI Canvas ────────────────────────────────────────────────
const adiCanvas = document.getElementById('adi-canvas');
const adiCtx = adiCanvas.getContext('2d');
const ADI_CX = 130, ADI_CY = 130, ADI_R = 120;

function drawADI(pitch, bank) {
  const ctx = adiCtx;
  ctx.clearRect(0, 0, 260, 260);

  ctx.save();
  ctx.translate(ADI_CX, ADI_CY);
  ctx.rotate(bank * Math.PI / 180);

  // Clip to circle
  ctx.beginPath();
  ctx.arc(0, 0, ADI_R, 0, Math.PI * 2);
  ctx.clip();

  // Sky
  const pitchPx = pitch * 3.5;
  const skyGrad = ctx.createLinearGradient(0, -ADI_R + pitchPx, 0, pitchPx);
  skyGrad.addColorStop(0, '#0a1a2e');
  skyGrad.addColorStop(1, '#0d2a4a');
  ctx.fillStyle = skyGrad;
  ctx.fillRect(-ADI_R, -ADI_R + pitchPx, ADI_R * 2, ADI_R * 2);

  // Ground
  const gndGrad = ctx.createLinearGradient(0, pitchPx, 0, ADI_R + pitchPx);
  gndGrad.addColorStop(0, '#2a1a08');
  gndGrad.addColorStop(1, '#1a0e04');
  ctx.fillStyle = gndGrad;
  ctx.fillRect(-ADI_R, pitchPx, ADI_R * 2, ADI_R * 2);

  // Horizon line
  ctx.strokeStyle = '#ffffff';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(-ADI_R, pitchPx);
  ctx.lineTo(ADI_R, pitchPx);
  ctx.stroke();

  // Pitch ladder
  ctx.strokeStyle = 'rgba(255,255,255,0.7)';
  ctx.fillStyle = 'rgba(255,255,255,0.7)';
  ctx.font = '10px Share Tech Mono';
  ctx.textAlign = 'right';
  ctx.lineWidth = 1;
  for (let p = -30; p <= 30; p += 5) {
    if (p === 0) continue;
    const y = pitchPx - p * 3.5;
    const w = (Math.abs(p) % 10 === 0) ? 40 : 20;
    ctx.beginPath();
    ctx.moveTo(-w, y); ctx.lineTo(w, y);
    ctx.stroke();
    if (Math.abs(p) % 10 === 0) {
      ctx.fillText(p.toString(), -w - 4, y + 4);
    }
  }

  ctx.restore();

  // Circle border
  ctx.beginPath();
  ctx.arc(ADI_CX, ADI_CY, ADI_R, 0, Math.PI * 2);
  ctx.strokeStyle = '#1a3a1a';
  ctx.lineWidth = 3;
  ctx.stroke();

  // Bank arc
  ctx.save();
  ctx.translate(ADI_CX, ADI_CY);
  ctx.strokeStyle = 'rgba(57,255,110,0.3)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(0, 0, ADI_R - 8, Math.PI * 1.2, Math.PI * 1.8);
  ctx.stroke();

  // Bank tick marks
  ctx.strokeStyle = '#4a6a4a';
  ctx.lineWidth = 1;
  for (const angle of [-60, -45, -30, -20, -10, 0, 10, 20, 30, 45, 60]) {
    const rad = (angle - 90) * Math.PI / 180;
    const inner = ADI_R - 14;
    const outer = ADI_R - 6;
    ctx.beginPath();
    ctx.moveTo(Math.cos(rad) * inner, Math.sin(rad) * inner);
    ctx.lineTo(Math.cos(rad) * outer, Math.sin(rad) * outer);
    ctx.stroke();
  }

  // Bank pointer (rotates with bank)
  ctx.rotate(bank * Math.PI / 180);
  ctx.fillStyle = '#39ff6e';
  ctx.beginPath();
  ctx.moveTo(0, -(ADI_R - 14));
  ctx.lineTo(-5, -(ADI_R - 4));
  ctx.lineTo(5, -(ADI_R - 4));
  ctx.closePath();
  ctx.fill();
  ctx.restore();

  // Fixed aircraft symbol
  ctx.save();
  ctx.translate(ADI_CX, ADI_CY);
  ctx.strokeStyle = '#ffb830';
  ctx.lineWidth = 2.5;
  ctx.lineCap = 'round';
  // Wings
  ctx.beginPath();
  ctx.moveTo(-50, 0); ctx.lineTo(-10, 0);
  ctx.moveTo(10, 0);  ctx.lineTo(50, 0);
  ctx.stroke();
  // Fuselage
  ctx.beginPath();
  ctx.moveTo(0, -6); ctx.lineTo(0, 6);
  ctx.stroke();
  // Wing tips
  ctx.beginPath();
  ctx.moveTo(-50, 0); ctx.lineTo(-45, -6);
  ctx.moveTo(50, 0);  ctx.lineTo(45, -6);
  ctx.stroke();
  ctx.restore();
}

// ── Heading Tape ──────────────────────────────────────────────
const hdgCanvas = document.getElementById('heading-tape-canvas');
const hdgCtx = hdgCanvas.getContext('2d');

function drawHeadingTape(hdg) {
  const ctx = hdgCtx;
  const W = 300, H = 36;
  ctx.clearRect(0, 0, W, H);

  ctx.fillStyle = '#0a140a';
  ctx.fillRect(0, 0, W, H);

  const pxPerDeg = 5;
  const halfW = W / 2;

  ctx.font = '10px Share Tech Mono';
  ctx.textAlign = 'center';

  for (let d = -30; d <= 30; d++) {
    const deg = ((hdg + d) % 360 + 360) % 360;
    const x = halfW + d * pxPerDeg;

    if (deg % 10 === 0) {
      ctx.fillStyle = '#4a6a4a';
      ctx.fillRect(x - 0.5, 0, 1, 12);

      const label = deg === 0 ? 'N' : deg === 90 ? 'E' : deg === 180 ? 'S' : deg === 270 ? 'W' : deg.toString();
      ctx.fillStyle = (deg % 90 === 0) ? '#39ff6e' : '#6a9a6a';
      ctx.fillText(label, x, 26);
    } else if (deg % 5 === 0) {
      ctx.fillStyle = '#2a3a2a';
      ctx.fillRect(x - 0.5, 0, 1, 6);
    }
  }

  // Center line (current heading marker)
  ctx.fillStyle = '#ffb830';
  ctx.fillRect(halfW - 1, 0, 2, H);
}

// ── DOM refs ──────────────────────────────────────────────────
const $ = id => document.getElementById(id);

function setVal(id, v) { const el = $(id); if (el) el.textContent = v; }
function setBar(id, pct, warn, danger) {
  const el = $(id);
  if (!el) return;
  const p = Math.min(100, Math.max(0, pct));
  el.style.width = p + '%';
  el.style.background = p >= danger ? 'var(--red)' : p >= warn ? 'var(--amber)' : 'var(--green)';
}
function setColor(id, color) {
  const el = $(id);
  if (el) el.style.color = color;
}

// ── FPS counter ───────────────────────────────────────────────
function updateFPS() {
  fpsCount++;
  const now = performance.now();
  if (now - lastFpsTime >= 1000) {
    setVal('fps-val', fpsCount.toString());
    fpsCount = 0;
    lastFpsTime = now;
  }
}

// ── Update HUD ────────────────────────────────────────────────
function updateHUD(s) {
  // Aircraft ID
  $('aircraft-id').textContent = (s.aircraft || 'UNKNOWN').toUpperCase();

  // IAS
  const ias = Math.round((s.ias_ms || 0) * 1.944);
  setVal('ias-val', ias);
  setBar('ias-bar', ias / 600 * 100, 70, 90);
  setColor('ias-val', ias > 540 ? 'var(--red)' : ias > 450 ? 'var(--amber)' : 'var(--green)');

  // MACH
  setVal('mach-val', (s.mach || 0).toFixed(2));
  setColor('mach-val', (s.mach || 0) > 1.0 ? 'var(--amber)' : 'var(--green)');

  // AoA
  const aoa = (s.aoa_deg || 0).toFixed(1);
  setVal('aoa-val', aoa);
  setColor('aoa-val', Math.abs(s.aoa_deg || 0) > 20 ? 'var(--red)' : 'var(--green)');

  // G
  const g = s.g_force != null ? s.g_force.toFixed(1) : '—';
  setVal('g-val', g);
  if (s.g_force != null) {
    setColor('g-val', s.g_force > 7 ? 'var(--red)' : s.g_force > 5 ? 'var(--amber)' : 'var(--green)');
  }

  // Altitude
  const altFt = Math.round((s.alt_msl_m || 0) * 3.28084);
  const aglFt = Math.round((s.alt_agl_m || 0) * 3.28084);
  setVal('alt-val', altFt.toLocaleString());
  setVal('agl-val', aglFt.toLocaleString());
  setBar('alt-bar', altFt / 50000 * 100, 70, 90);
  setColor('alt-val', aglFt < 500 ? 'var(--red)' : aglFt < 1000 ? 'var(--amber)' : 'var(--green)');

  // Fuel
  if (s.fuel_kg != null) {
    setVal('fuel-val', Math.round(s.fuel_kg).toLocaleString());
    const fuelPct = s.fuel_max_kg ? s.fuel_kg / s.fuel_max_kg * 100 : 50;
    setBar('fuel-bar', fuelPct, 30, 15);
    setColor('fuel-val', fuelPct < 15 ? 'var(--red)' : fuelPct < 30 ? 'var(--amber)' : 'var(--green)');
  }

  // RPM
  if (s.engine_rpm_pct != null) {
    setVal('rpm-val', s.engine_rpm_pct.toFixed(0));
  }

  // VSI
  const vviMs = s.vvi_ms || 0;
  const vsiFpm = Math.round(vviMs * 196.85);
  setVal('vsi-val', (vsiFpm >= 0 ? '+' : '') + vsiFpm.toLocaleString());
  const vsiEl = $('vsi-arrow');
  if (vsiFpm > 50) {
    vsiEl.textContent = '▲'; vsiEl.style.color = 'var(--green)';
  } else if (vsiFpm < -50) {
    vsiEl.textContent = '▼'; vsiEl.style.color = 'var(--red)';
  } else {
    vsiEl.textContent = '▶'; vsiEl.style.color = 'var(--muted)';
  }

  // Bottom bar
  const hdg = s.heading_deg || 0;
  setVal('hdg-val', Math.round(hdg) + '°');
  setVal('pitch-val', (s.pitch_deg || 0).toFixed(1) + '°');
  setVal('bank-val',  (s.bank_deg  || 0).toFixed(1) + '°');
  setVal('lat-val',   (s.lat || 0).toFixed(4));
  setVal('lon-val',   (s.lon || 0).toFixed(4));
  setVal('pkt-val',   packetCount.toLocaleString());

  // ADI
  drawADI(s.pitch_deg || 0, s.bank_deg || 0);

  // Heading tape
  drawHeadingTape(hdg);

  updateFPS();
}

// ── WebSocket ─────────────────────────────────────────────────
function setWsStatus(status) {
  const dot = $('ws-dot');
  const lbl = $('ws-label');
  dot.className = '';
  if (status === 'live') {
    dot.classList.add('live');
    lbl.textContent = 'LIVE';
    lbl.style.color = 'var(--green)';
    $('offline').classList.remove('show');
  } else if (status === 'connecting') {
    lbl.textContent = 'CONNECTING';
    lbl.style.color = 'var(--amber)';
  } else {
    dot.classList.add('error');
    lbl.textContent = 'OFFLINE';
    lbl.style.color = 'var(--red)';
    $('offline').classList.add('show');
  }
}

function initWS() {
  clearTimeout(reconnectTimer);
  if (ws) { try { ws.close(); } catch(e){} ws = null; }

  setWsStatus('connecting');
  $('offline-msg').textContent = 'Connecting to WebSocket...';

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws/telemetry`);

  ws.onopen = () => {
    setWsStatus('live');
  };

  ws.onmessage = (evt) => {
    try {
      const s = JSON.parse(evt.data);
      packetCount++;
      updateHUD(s);
    } catch(e) {}
  };

  ws.onerror = () => {};

  ws.onclose = (evt) => {
    setWsStatus('offline');
    $('offline-msg').textContent = `Disconnected (code ${evt.code}). Retrying in 3s...`;
    reconnectTimer = setTimeout(initWS, 3000);
  };
}

// ── Init ──────────────────────────────────────────────────────
drawADI(0, 0);
drawHeadingTape(0);
initWS();
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


# ----------------------------------------------------------------
# WebSocket endpoint
# ----------------------------------------------------------------
@app.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket):
    """Real-time telemetry stream at ~30Hz."""
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
