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
    <button class="btn" onclick="fetchLogs()">↻ Atualizar agora</button>
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
