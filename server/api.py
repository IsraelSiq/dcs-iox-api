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

from server.models import AircraftState, ContactsPacket
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
        if ws in self.active:
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
            if ws in self.active:
                self.active.remove(ws)


manager_telem  = ConnectionManager()  # /ws/telemetry
manager_radar  = ConnectionManager()  # /ws/radar


# ----------------------------------------------------------------
# Background broadcast loops
# ----------------------------------------------------------------
async def broadcast_telemetry():
    log.info("Telemetry WS broadcast loop started")
    while True:
        await asyncio.sleep(1 / 30)
        if shared.latest_state and manager_telem.active:
            await manager_telem.broadcast(shared.latest_state.model_dump_json())


async def broadcast_radar():
    """Broadcasts combined self+contacts frame at 10Hz to radar clients."""
    log.info("Radar WS broadcast loop started")
    while True:
        await asyncio.sleep(1 / 10)
        if not manager_radar.active:
            continue
        frame = {
            "self": shared.latest_state.model_dump() if shared.latest_state else None,
            "contacts": [c.model_dump() for c in shared.contacts.values()],
            "ts": time.time(),
        }
        await manager_radar.broadcast(json.dumps(frame))


# ----------------------------------------------------------------
# App lifespan
# ----------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    t1 = asyncio.create_task(broadcast_telemetry())
    t2 = asyncio.create_task(broadcast_radar())
    yield
    for t in (t1, t2):
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass


# ----------------------------------------------------------------
# FastAPI app
# ----------------------------------------------------------------
app = FastAPI(
    title="dcs-iox-api",
    description="DCS World IOX API — Export.lua bridge + REST/WebSocket server",
    version="0.2.0",
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
    return {
        "status": "ok",
        "uptime": time.time() - shared.start_time,
        "packets_received": shared.packet_count,
        "dcs_connected": shared.latest_state is not None,
        "contacts_count": len(shared.contacts),
    }


@app.get("/logs", tags=["System"])
async def get_logs(n: int = 50):
    entries = list(shared.log_buffer)
    return {"count": len(entries), "logs": entries[-min(n, 200):]}


@app.get("/state", response_model=AircraftState, tags=["Telemetry"])
async def get_state():
    if shared.latest_state is None:
        raise HTTPException(status_code=503, detail="No data from DCS yet.")
    return shared.latest_state


@app.get("/telemetry", tags=["Telemetry"])
async def get_telemetry():
    if shared.latest_state is None:
        raise HTTPException(status_code=503, detail="No data from DCS yet.")
    s = shared.latest_state
    return {
        "aircraft": s.aircraft,
        "timestamp": s.timestamp,
        "position": {"lat": s.lat, "lon": s.lon, "alt_msl_m": s.alt_msl_m, "alt_agl_m": s.alt_agl_m},
        "speed": {"ias_ms": s.ias_ms, "ias_kts": round(s.ias_ms * 1.944, 1), "tas_ms": s.tas_ms, "mach": s.mach, "vvi_ms": s.vvi_ms},
        "attitude": {"heading_deg": s.heading_deg, "pitch_deg": s.pitch_deg, "bank_deg": s.bank_deg, "aoa_deg": s.aoa_deg},
    }


@app.get("/contacts", tags=["Radar"])
async def get_contacts():
    """Current contacts within 100km, sorted by distance."""
    contacts = sorted(shared.contacts.values(), key=lambda c: c.dist_m)
    return {
        "count": len(contacts),
        "timestamp": shared.contacts_timestamp,
        "contacts": [c.model_dump() for c in contacts],
    }


# ----------------------------------------------------------------
# Logs view
# ----------------------------------------------------------------
@app.get("/logs/view", response_class=HTMLResponse, tags=["System"], include_in_schema=False)
async def logs_view():
    html = """
<!DOCTYPE html><html lang="pt-BR"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>dcs-iox-api | Logs</title>
<style>
  :root{--bg:#171614;--surface:#1c1b19;--border:#393836;--text:#cdccca;--text-muted:#797876;--primary:#4f98a3;--radius:6px;--font:'Fira Code','Cascadia Code','Consolas',monospace;}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:var(--font);font-size:13px;min-height:100vh;padding:24px}
  header{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;flex-wrap:wrap;gap:12px}
  .logo{display:flex;align-items:center;gap:10px}
  .logo h1{font-size:16px;font-weight:600;letter-spacing:.05em;color:var(--primary)}
  .logo span{font-size:12px;color:var(--text-muted)}
  .badge{display:inline-flex;align-items:center;gap:6px;padding:4px 12px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);font-size:12px;color:var(--text-muted)}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--primary);animation:pulse 2s ease-in-out infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
  .toolbar{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap;align-items:center}
  .toolbar label{color:var(--text-muted);font-size:12px}
  select,input[type=number]{background:var(--surface);border:1px solid var(--border);color:var(--text);padding:4px 8px;border-radius:var(--radius);font-family:var(--font);font-size:12px}
  .btn{padding:4px 12px;background:var(--primary);color:#171614;border:none;border-radius:var(--radius);cursor:pointer;font-size:12px;font-weight:600;font-family:var(--font);transition:opacity .15s}
  .btn:hover{opacity:.85}
  #log-box{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:16px;height:calc(100vh - 180px);overflow-y:auto;display:flex;flex-direction:column;gap:2px}
  .log-line{display:grid;grid-template-columns:70px 70px 1fr;gap:12px;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.03);line-height:1.5}
  .log-line:last-child{border-bottom:none}
  .ts{color:var(--text-muted)}.lvl{font-weight:700}.msg{word-break:break-all}
  .empty{color:var(--text-muted);text-align:center;padding:40px;font-style:italic}
</style></head><body>
<header>
  <div class="logo">
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--primary)"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
    <div><h1>dcs-iox-api</h1><span>Live Server Logs</span></div>
  </div>
  <div style="display:flex;gap:8px;align-items:center">
    <div class="badge"><div class="dot"></div><span id="status-text">conectando...</span></div>
    <span id="countdown" class="badge">next refresh: 10s</span>
  </div>
</header>
<div class="toolbar">
  <label>Linhas:</label><input type="number" id="n-lines" value="50" min="10" max="200" style="width:70px">
  <label>Filtro:</label>
  <select id="filter-level"><option value="ALL">Todos</option><option>INFO</option><option>WARNING</option><option>ERROR</option><option>DEBUG</option></select>
  <button class="btn" onclick="fetchLogs()">&#8635; Atualizar</button>
  <button class="btn" onclick="clearView()" style="background:#393836;color:var(--text)">Limpar</button>
</div>
<div id="log-box"><div class="empty">Aguardando logs...</div></div>
<script>
  let countdown=10,timer;
  async function fetchLogs(){
    const n=document.getElementById('n-lines').value||50;
    const level=document.getElementById('filter-level').value;
    try{
      const res=await fetch('/logs?n='+n);
      const data=await res.json();
      renderLogs(data.logs,level);
      document.getElementById('status-text').textContent=data.count+' entradas | '+new Date().toLocaleTimeString('pt-BR');
    }catch(e){document.getElementById('status-text').textContent='erro';}
    resetCountdown();
  }
  function renderLogs(logs,level){
    const box=document.getElementById('log-box');
    const f=level==='ALL'?logs:logs.filter(l=>l.level===level);
    if(!f.length){box.innerHTML='<div class="empty">Nenhum log.</div>';return;}
    box.innerHTML=f.map(l=>'<div class="log-line"><span class="ts">'+l.ts+'</span><span class="lvl" style="color:'+l.color+'">'+l.level+'</span><span class="msg">'+l.message.replace(/&/g,'&amp;').replace(/</g,'&lt;')+'</span></div>').join('');
    box.scrollTop=box.scrollHeight;
  }
  function clearView(){document.getElementById('log-box').innerHTML='<div class="empty">View limpa.</div>';}
  function resetCountdown(){
    clearInterval(timer);countdown=10;
    document.getElementById('countdown').textContent='next refresh: '+countdown+'s';
    timer=setInterval(()=>{countdown--;document.getElementById('countdown').textContent='next refresh: '+countdown+'s';if(countdown<=0)fetchLogs();},1000);
  }
  fetchLogs();
</script></body></html>
    """
    return HTMLResponse(content=html)


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
  :root{--bg:#0a0c0a;--panel:#0d110d;--border:#1a2a1a;--green:#39ff6e;--green-dim:#1a7a35;--amber:#ffb830;--red:#ff4040;--blue:#40c8ff;--text:#c8e8c8;--muted:#4a6a4a;--font-mono:'Share Tech Mono',monospace;--font-hud:'Orbitron',sans-serif;--glow:0 0 8px rgba(57,255,110,0.35);}
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:var(--font-mono);font-size:13px;min-height:100vh;display:flex;flex-direction:column;overflow-x:hidden}
  #topbar{display:flex;align-items:center;justify-content:space-between;padding:8px 20px;border-bottom:1px solid var(--border);background:var(--panel);flex-shrink:0}
  #topbar .logo{font-family:var(--font-hud);font-size:14px;font-weight:700;color:var(--green);letter-spacing:.15em;text-shadow:var(--glow)}
  #topbar .logo span{color:var(--muted);font-weight:400;font-size:11px;margin-left:8px}
  #ws-status{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--muted)}
  #ws-dot{width:8px;height:8px;border-radius:50%;background:var(--muted);transition:background .3s}
  #ws-dot.live{background:var(--green);box-shadow:var(--glow);animation:blink 2s infinite}
  #ws-dot.error{background:var(--red)}
  @keyframes blink{0%,100%{opacity:1}50%{opacity:.4}}
  #aircraft-id{font-family:var(--font-hud);font-size:12px;color:var(--amber);letter-spacing:.1em}
  #main{flex:1;display:grid;grid-template-columns:200px 1fr 200px;grid-template-rows:1fr auto;gap:1px;background:var(--border);min-height:0}
  .panel{background:var(--panel);display:flex;flex-direction:column;align-items:center;justify-content:center;padding:16px 12px;gap:16px}
  #center-panel{background:var(--bg);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:20px;padding:20px}
  canvas{display:block}
  .gauge-block{width:100%;display:flex;flex-direction:column;align-items:center;gap:4px}
  .gauge-label{font-size:10px;color:var(--muted);letter-spacing:.12em;text-transform:uppercase}
  .gauge-value{font-family:var(--font-hud);font-size:22px;font-weight:700;color:var(--green);text-shadow:var(--glow);line-height:1;transition:color .2s}
  .gauge-unit{font-size:10px;color:var(--muted)}
  .gauge-bar{width:100%;height:4px;background:var(--border);border-radius:2px;overflow:hidden}
  .gauge-bar-fill{height:100%;background:var(--green);border-radius:2px;transition:width .1s linear,background .2s}
  #heading-tape-wrap{width:300px;height:36px;background:#0a140a;border:1px solid var(--border);border-radius:4px;overflow:hidden;position:relative}
  #hdg-bug{position:absolute;top:0;left:50%;transform:translateX(-50%);width:2px;height:36px;background:var(--amber);pointer-events:none}
  #vsi-wrap{display:flex;flex-direction:column;align-items:center;gap:4px}
  #vsi-arrow{font-size:20px;line-height:1;transition:transform .15s,color .15s}
  #bottombar{grid-column:1/-1;background:var(--panel);border-top:1px solid var(--border);display:flex;align-items:center;height:40px;overflow:hidden}
  .stat-cell{flex:1;display:flex;align-items:center;justify-content:center;gap:6px;padding:0 12px;border-right:1px solid var(--border);height:100%}
  .stat-cell:last-child{border-right:none}
  .stat-lbl{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.1em}
  .stat-val{font-family:var(--font-hud);font-size:13px;color:var(--green)}
  .divider{width:80%;height:1px;background:var(--border)}
  #offline{display:none;position:fixed;inset:0;background:rgba(10,12,10,.88);z-index:100;align-items:center;justify-content:center;flex-direction:column;gap:16px;font-family:var(--font-hud);color:var(--red);font-size:18px;letter-spacing:.1em;text-align:center}
  #offline.show{display:flex}
  #offline small{font-family:var(--font-mono);font-size:12px;color:var(--muted)}
  #retry-btn{margin-top:8px;padding:8px 24px;background:none;border:1px solid var(--red);color:var(--red);font-family:var(--font-hud);font-size:12px;cursor:pointer;letter-spacing:.1em;transition:background .2s}
  #retry-btn:hover{background:rgba(255,64,64,.15)}
</style>
</head><body>
<div id="offline"><div>&#9888; NO DCS SIGNAL</div><small id="offline-msg">WebSocket disconnected</small><button id="retry-btn" onclick="initWS()">RECONNECT</button></div>
<div id="topbar"><div class="logo">DCS IOX<span>LIVE HUD v0.2</span></div><div id="aircraft-id">—</div><div id="ws-status"><div id="ws-dot"></div><span id="ws-label">OFFLINE</span></div></div>
<div id="main">
  <div class="panel">
    <div class="gauge-block"><div class="gauge-label">IAS</div><div class="gauge-value" id="ias-val">0</div><div class="gauge-unit">knots</div><div class="gauge-bar"><div class="gauge-bar-fill" id="ias-bar" style="width:0%"></div></div></div>
    <div class="divider"></div>
    <div class="gauge-block"><div class="gauge-label">MACH</div><div class="gauge-value" id="mach-val">0.00</div></div>
    <div class="divider"></div>
    <div class="gauge-block"><div class="gauge-label">AoA</div><div class="gauge-value" id="aoa-val">0.0</div><div class="gauge-unit">deg</div></div>
    <div class="divider"></div>
    <div class="gauge-block"><div class="gauge-label">G-FORCE</div><div class="gauge-value" id="g-val">1.0</div><div class="gauge-unit">g</div></div>
  </div>
  <div id="center-panel">
    <canvas id="adi-canvas" width="260" height="260"></canvas>
    <div id="heading-tape-wrap"><canvas id="heading-tape-canvas" width="300" height="36"></canvas><div id="hdg-bug"></div></div>
    <div id="vsi-wrap"><div class="gauge-label">VERTICAL SPEED</div><div id="vsi-arrow" style="color:var(--green)">&#9654;</div><div class="gauge-value" id="vsi-val" style="font-size:18px">+0</div><div class="gauge-unit">ft/min</div></div>
  </div>
  <div class="panel">
    <div class="gauge-block"><div class="gauge-label">ALT MSL</div><div class="gauge-value" id="alt-val">0</div><div class="gauge-unit">feet</div><div class="gauge-bar"><div class="gauge-bar-fill" id="alt-bar" style="width:0%"></div></div></div>
    <div class="divider"></div>
    <div class="gauge-block"><div class="gauge-label">ALT AGL</div><div class="gauge-value" id="agl-val">0</div><div class="gauge-unit">feet</div></div>
    <div class="divider"></div>
    <div class="gauge-block"><div class="gauge-label">FUEL</div><div class="gauge-value" id="fuel-val">—</div><div class="gauge-unit">kg</div><div class="gauge-bar"><div class="gauge-bar-fill" id="fuel-bar" style="width:0%"></div></div></div>
    <div class="divider"></div>
    <div class="gauge-block"><div class="gauge-label">ENGINE RPM</div><div class="gauge-value" id="rpm-val">—</div><div class="gauge-unit">%</div></div>
  </div>
  <div id="bottombar">
    <div class="stat-cell"><span class="stat-lbl">HDG</span><span class="stat-val" id="hdg-val">---°</span></div>
    <div class="stat-cell"><span class="stat-lbl">PITCH</span><span class="stat-val" id="pitch-val">---°</span></div>
    <div class="stat-cell"><span class="stat-lbl">BANK</span><span class="stat-val" id="bank-val">---°</span></div>
    <div class="stat-cell"><span class="stat-lbl">LAT</span><span class="stat-val" id="lat-val">---.----</span></div>
    <div class="stat-cell"><span class="stat-lbl">LON</span><span class="stat-val" id="lon-val">---.----</span></div>
    <div class="stat-cell"><span class="stat-lbl">PACKETS</span><span class="stat-val" id="pkt-val">0</span></div>
    <div class="stat-cell"><span class="stat-lbl">FPS</span><span class="stat-val" id="fps-val">--</span></div>
  </div>
</div>
<script>
"use strict";
let ws=null,reconnectTimer=null,packetCount=0,fpsCount=0,lastFpsTime=performance.now();
const adiCanvas=document.getElementById('adi-canvas'),adiCtx=adiCanvas.getContext('2d');
const ADI_CX=130,ADI_CY=130,ADI_R=120;
function drawADI(pitch,bank){
  const ctx=adiCtx;ctx.clearRect(0,0,260,260);
  ctx.save();ctx.translate(ADI_CX,ADI_CY);ctx.rotate(bank*Math.PI/180);
  ctx.beginPath();ctx.arc(0,0,ADI_R,0,Math.PI*2);ctx.clip();
  const pitchPx=pitch*3.5;
  const skyGrad=ctx.createLinearGradient(0,-ADI_R+pitchPx,0,pitchPx);
  skyGrad.addColorStop(0,'#0a1a2e');skyGrad.addColorStop(1,'#0d2a4a');
  ctx.fillStyle=skyGrad;ctx.fillRect(-ADI_R,-ADI_R+pitchPx,ADI_R*2,ADI_R*2);
  const gndGrad=ctx.createLinearGradient(0,pitchPx,0,ADI_R+pitchPx);
  gndGrad.addColorStop(0,'#2a1a08');gndGrad.addColorStop(1,'#1a0e04');
  ctx.fillStyle=gndGrad;ctx.fillRect(-ADI_R,pitchPx,ADI_R*2,ADI_R*2);
  ctx.strokeStyle='#ffffff';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(-ADI_R,pitchPx);ctx.lineTo(ADI_R,pitchPx);ctx.stroke();
  ctx.strokeStyle='rgba(255,255,255,.7)';ctx.fillStyle='rgba(255,255,255,.7)';ctx.font='10px Share Tech Mono';ctx.textAlign='right';ctx.lineWidth=1;
  for(let p=-30;p<=30;p+=5){if(p===0)continue;const y=pitchPx-p*3.5;const w=(Math.abs(p)%10===0)?40:20;ctx.beginPath();ctx.moveTo(-w,y);ctx.lineTo(w,y);ctx.stroke();if(Math.abs(p)%10===0)ctx.fillText(p.toString(),-w-4,y+4);}
  ctx.restore();
  ctx.beginPath();ctx.arc(ADI_CX,ADI_CY,ADI_R,0,Math.PI*2);ctx.strokeStyle='#1a3a1a';ctx.lineWidth=3;ctx.stroke();
  ctx.save();ctx.translate(ADI_CX,ADI_CY);
  ctx.strokeStyle='#4a6a4a';ctx.lineWidth=1;
  for(const a of[-60,-45,-30,-20,-10,0,10,20,30,45,60]){const r=(a-90)*Math.PI/180;ctx.beginPath();ctx.moveTo(Math.cos(r)*(ADI_R-14),Math.sin(r)*(ADI_R-14));ctx.lineTo(Math.cos(r)*(ADI_R-6),Math.sin(r)*(ADI_R-6));ctx.stroke();}
  ctx.rotate(bank*Math.PI/180);ctx.fillStyle='#39ff6e';ctx.beginPath();ctx.moveTo(0,-(ADI_R-14));ctx.lineTo(-5,-(ADI_R-4));ctx.lineTo(5,-(ADI_R-4));ctx.closePath();ctx.fill();
  ctx.restore();
  ctx.save();ctx.translate(ADI_CX,ADI_CY);ctx.strokeStyle='#ffb830';ctx.lineWidth=2.5;ctx.lineCap='round';
  ctx.beginPath();ctx.moveTo(-50,0);ctx.lineTo(-10,0);ctx.moveTo(10,0);ctx.lineTo(50,0);ctx.stroke();
  ctx.beginPath();ctx.moveTo(0,-6);ctx.lineTo(0,6);ctx.stroke();
  ctx.beginPath();ctx.moveTo(-50,0);ctx.lineTo(-45,-6);ctx.moveTo(50,0);ctx.lineTo(45,-6);ctx.stroke();
  ctx.restore();
}
const hdgCanvas=document.getElementById('heading-tape-canvas'),hdgCtx=hdgCanvas.getContext('2d');
function drawHeadingTape(hdg){
  const ctx=hdgCtx,W=300,H=36;ctx.clearRect(0,0,W,H);ctx.fillStyle='#0a140a';ctx.fillRect(0,0,W,H);
  const pxPerDeg=5,halfW=W/2;ctx.font='10px Share Tech Mono';ctx.textAlign='center';
  for(let d=-30;d<=30;d++){const deg=((hdg+d)%360+360)%360;const x=halfW+d*pxPerDeg;
    if(deg%10===0){ctx.fillStyle='#4a6a4a';ctx.fillRect(x-.5,0,1,12);const label=deg===0?'N':deg===90?'E':deg===180?'S':deg===270?'W':deg.toString();ctx.fillStyle=(deg%90===0)?'#39ff6e':'#6a9a6a';ctx.fillText(label,x,26);}
    else if(deg%5===0){ctx.fillStyle='#2a3a2a';ctx.fillRect(x-.5,0,1,6);}}
  ctx.fillStyle='#ffb830';ctx.fillRect(halfW-1,0,2,H);
}
const $=id=>document.getElementById(id);
function setVal(id,v){const el=$(id);if(el)el.textContent=v;}
function setBar(id,pct,warn,danger){const el=$(id);if(!el)return;const p=Math.min(100,Math.max(0,pct));el.style.width=p+'%';el.style.background=p>=danger?'var(--red)':p>=warn?'var(--amber)':'var(--green)';}
function setColor(id,c){const el=$(id);if(el)el.style.color=c;}
function updateFPS(){fpsCount++;const now=performance.now();if(now-lastFpsTime>=1000){setVal('fps-val',fpsCount.toString());fpsCount=0;lastFpsTime=now;}}
function updateHUD(s){
  $('aircraft-id').textContent=(s.aircraft||'UNKNOWN').toUpperCase();
  const ias=Math.round((s.ias_ms||0)*1.944);setVal('ias-val',ias);setBar('ias-bar',ias/600*100,70,90);setColor('ias-val',ias>540?'var(--red)':ias>450?'var(--amber)':'var(--green)');
  setVal('mach-val',(s.mach||0).toFixed(2));setColor('mach-val',(s.mach||0)>1.0?'var(--amber)':'var(--green)');
  setVal('aoa-val',(s.aoa_deg||0).toFixed(1));setColor('aoa-val',Math.abs(s.aoa_deg||0)>20?'var(--red)':'var(--green)');
  const g=s.g_force!=null?s.g_force.toFixed(1):'—';setVal('g-val',g);
  const altFt=Math.round((s.alt_msl_m||0)*3.28084);const aglFt=Math.round((s.alt_agl_m||0)*3.28084);
  setVal('alt-val',altFt.toLocaleString());setVal('agl-val',aglFt.toLocaleString());setBar('alt-bar',altFt/50000*100,70,90);
  setColor('alt-val',aglFt<500?'var(--red)':aglFt<1000?'var(--amber)':'var(--green)');
  if(s.fuel_kg!=null){setVal('fuel-val',Math.round(s.fuel_kg).toLocaleString());const fp=s.fuel_max_kg?s.fuel_kg/s.fuel_max_kg*100:50;setBar('fuel-bar',fp,30,15);setColor('fuel-val',fp<15?'var(--red)':fp<30?'var(--amber)':'var(--green)');}
  if(s.engine_rpm_pct!=null)setVal('rpm-val',s.engine_rpm_pct.toFixed(0));
  const vviMs=s.vvi_ms||0;const vsiFpm=Math.round(vviMs*196.85);
  setVal('vsi-val',(vsiFpm>=0?'+':'')+vsiFpm.toLocaleString());
  const vsiEl=$('vsi-arrow');if(vsiFpm>50){vsiEl.textContent='▲';vsiEl.style.color='var(--green)';}else if(vsiFpm<-50){vsiEl.textContent='▼';vsiEl.style.color='var(--red)';}else{vsiEl.textContent='▶';vsiEl.style.color='var(--muted)';}
  const hdg=s.heading_deg||0;
  setVal('hdg-val',Math.round(hdg)+'°');setVal('pitch-val',(s.pitch_deg||0).toFixed(1)+'°');setVal('bank-val',(s.bank_deg||0).toFixed(1)+'°');
  setVal('lat-val',(s.lat||0).toFixed(4));setVal('lon-val',(s.lon||0).toFixed(4));setVal('pkt-val',packetCount.toLocaleString());
  drawADI(s.pitch_deg||0,s.bank_deg||0);drawHeadingTape(hdg);updateFPS();
}
function setWsStatus(status){
  const dot=$('ws-dot'),lbl=$('ws-label');dot.className='';
  if(status==='live'){dot.classList.add('live');lbl.textContent='LIVE';lbl.style.color='var(--green)';$('offline').classList.remove('show');}
  else if(status==='connecting'){lbl.textContent='CONNECTING';lbl.style.color='var(--amber)';}
  else{dot.classList.add('error');lbl.textContent='OFFLINE';lbl.style.color='var(--red)';$('offline').classList.add('show');}
}
function initWS(){
  clearTimeout(reconnectTimer);if(ws){try{ws.close();}catch(e){}ws=null;}
  setWsStatus('connecting');$('offline-msg').textContent='Connecting...';
  const proto=location.protocol==='https:'?'wss:':'ws:';
  ws=new WebSocket(proto+'//'+location.host+'/ws/telemetry');
  ws.onopen=()=>setWsStatus('live');
  ws.onmessage=(evt)=>{try{const s=JSON.parse(evt.data);packetCount++;updateHUD(s);}catch(e){}};
  ws.onerror=()=>{};
  ws.onclose=(evt)=>{setWsStatus('offline');$('offline-msg').textContent='Disconnected ('+evt.code+'). Retry in 3s...';reconnectTimer=setTimeout(initWS,3000);};
}
drawADI(0,0);drawHeadingTape(0);initWS();
</script></body></html>"""
    return HTMLResponse(content=html)


# ----------------------------------------------------------------
# Radar — PPI Tactical Display
# ----------------------------------------------------------------
@app.get("/radar", response_class=HTMLResponse, tags=["Radar"], include_in_schema=False)
async def radar():
    """PPI Tactical Radar — 100km range, IFF colors, 10Hz WebSocket."""
    html = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DCS IOX — Radar PPI</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@400;700&display=swap');
  :root{
    --bg:#050a05;--panel:#080d08;--border:#0f1f0f;
    --green:#39ff6e;--green-dim:#0f3a1f;--green-mid:#1a7a35;
    --amber:#ffb830;--red:#ff4040;--blue:#40c8ff;
    --neutral:#aaaaaa;--text:#a0d0a0;--muted:#3a5a3a;
    --font:'Share Tech Mono',monospace;--hud:'Orbitron',sans-serif;
    --glow:0 0 10px rgba(57,255,110,0.4);
  }
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:var(--font);font-size:13px;min-height:100vh;display:flex;flex-direction:column}

  /* Top bar */
  #topbar{display:flex;align-items:center;justify-content:space-between;padding:8px 20px;border-bottom:1px solid var(--border);background:var(--panel);flex-shrink:0;gap:12px}
  .logo{font-family:var(--hud);font-size:13px;font-weight:700;color:var(--green);letter-spacing:.15em;text-shadow:var(--glow)}
  .logo span{color:var(--muted);font-weight:400;font-size:10px;margin-left:8px}
  #ws-dot{width:8px;height:8px;border-radius:50%;background:var(--muted);display:inline-block;margin-right:6px;vertical-align:middle}
  #ws-dot.live{background:var(--green);box-shadow:var(--glow);animation:blink 2s infinite}
  #ws-dot.err{background:var(--red)}
  @keyframes blink{0%,100%{opacity:1}50%{opacity:.3}}

  /* Main layout */
  #content{flex:1;display:grid;grid-template-columns:1fr 280px;gap:1px;background:var(--border);min-height:0}

  /* Radar area */
  #radar-wrap{background:var(--bg);display:flex;align-items:center;justify-content:center;padding:20px;overflow:hidden}
  #radar-canvas{border-radius:50%;cursor:crosshair}

  /* Sidebar */
  #sidebar{background:var(--panel);display:flex;flex-direction:column;padding:16px 14px;gap:0;overflow-y:auto}
  .side-section{margin-bottom:20px}
  .side-title{font-family:var(--hud);font-size:10px;letter-spacing:.15em;color:var(--muted);border-bottom:1px solid var(--border);padding-bottom:6px;margin-bottom:10px}
  .kv{display:flex;justify-content:space-between;align-items:baseline;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.03)}
  .kv:last-child{border-bottom:none}
  .kv-label{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
  .kv-value{font-family:var(--hud);font-size:13px;color:var(--green)}

  /* Contact list */
  #contact-list{display:flex;flex-direction:column;gap:2px;max-height:320px;overflow-y:auto}
  .contact-row{
    display:grid;grid-template-columns:12px 1fr 60px 50px;
    gap:6px;align-items:center;
    padding:4px 6px;
    border-radius:3px;
    border:1px solid transparent;
    cursor:pointer;
    transition:background .15s;
    font-size:11px;
  }
  .contact-row:hover{background:rgba(57,255,110,.06);border-color:var(--border)}
  .contact-row.selected{background:rgba(57,255,110,.1);border-color:var(--green-mid)}
  .iff-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
  .contact-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--text)}
  .contact-dist{text-align:right;color:var(--muted);font-size:10px}
  .contact-alt{text-align:right;color:var(--muted);font-size:10px}

  /* Legend */
  .legend{display:flex;flex-direction:column;gap:6px}
  .legend-item{display:flex;align-items:center;gap:8px;font-size:11px;color:var(--muted)}
  .legend-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}

  /* Range selector */
  .range-btns{display:flex;gap:6px;flex-wrap:wrap}
  .range-btn{
    padding:3px 10px;background:none;border:1px solid var(--border);
    color:var(--muted);font-family:var(--font);font-size:11px;
    border-radius:3px;cursor:pointer;transition:all .15s;
  }
  .range-btn:hover{border-color:var(--green-mid);color:var(--text)}
  .range-btn.active{border-color:var(--green);color:var(--green);background:rgba(57,255,110,.08)}

  /* Detail panel */
  #detail-panel{display:none;background:rgba(57,255,110,.04);border:1px solid var(--green-mid);border-radius:4px;padding:10px 12px;margin-top:8px}
  #detail-panel.show{display:block}
  #detail-panel .d-title{font-family:var(--hud);font-size:11px;color:var(--green);margin-bottom:8px;text-transform:uppercase;letter-spacing:.1em}

  /* Sweep line */
  .sweep-active #radar-canvas{box-shadow:0 0 30px rgba(57,255,110,.15);}

  #bottom-strip{background:var(--panel);border-top:1px solid var(--border);padding:6px 20px;display:flex;gap:20px;align-items:center;font-size:11px;color:var(--muted);flex-shrink:0}
  #bottom-strip span{color:var(--text)}
</style>
</head>
<body>
<div id="topbar">
  <div class="logo">DCS IOX <span>RADAR PPI v0.2</span></div>
  <div style="display:flex;align-items:center;gap:16px;font-size:11px">
    <div><span id="ws-dot"></span><span id="ws-lbl" style="color:var(--muted)">OFFLINE</span></div>
    <div id="self-aircraft" style="font-family:var(--hud);color:var(--amber);font-size:11px;letter-spacing:.1em">—</div>
    <div style="color:var(--muted)">RANGE: <span id="range-display" style="color:var(--green)">100 km</span></div>
    <div style="color:var(--muted)">CONTACTS: <span id="contact-count" style="color:var(--green)">0</span></div>
  </div>
</div>

<div id="content">
  <!-- Radar canvas -->
  <div id="radar-wrap">
    <canvas id="radar-canvas"></canvas>
  </div>

  <!-- Sidebar -->
  <div id="sidebar">

    <!-- Self data -->
    <div class="side-section">
      <div class="side-title">OWNSHIP</div>
      <div class="kv"><span class="kv-label">HDG</span><span class="kv-value" id="s-hdg">—°</span></div>
      <div class="kv"><span class="kv-label">IAS</span><span class="kv-value" id="s-ias">— kts</span></div>
      <div class="kv"><span class="kv-label">ALT MSL</span><span class="kv-value" id="s-alt">— ft</span></div>
      <div class="kv"><span class="kv-label">ALT AGL</span><span class="kv-value" id="s-agl">— ft</span></div>
    </div>

    <!-- Range selector -->
    <div class="side-section">
      <div class="side-title">RANGE</div>
      <div class="range-btns">
        <button class="range-btn" onclick="setRange(20)">20</button>
        <button class="range-btn" onclick="setRange(50)">50</button>
        <button class="range-btn active" onclick="setRange(100)">100</button>
        <button class="range-btn" onclick="setRange(200)">200</button>
        <span style="font-size:10px;color:var(--muted)">km</span>
      </div>
    </div>

    <!-- Contact detail -->
    <div id="detail-panel">
      <div class="d-title" id="d-title">SELECT CONTACT</div>
      <div class="kv"><span class="kv-label">TYPE</span><span class="kv-value" id="d-type">—</span></div>
      <div class="kv"><span class="kv-label">HDG</span><span class="kv-value" id="d-hdg">—°</span></div>
      <div class="kv"><span class="kv-label">SPEED</span><span class="kv-value" id="d-spd">— kts</span></div>
      <div class="kv"><span class="kv-label">ALT</span><span class="kv-value" id="d-alt">— ft</span></div>
      <div class="kv"><span class="kv-label">DIST</span><span class="kv-value" id="d-dist">— km</span></div>
      <div class="kv"><span class="kv-label">IFF</span><span class="kv-value" id="d-iff">—</span></div>
    </div>

    <!-- Contact list -->
    <div class="side-section">
      <div class="side-title">CONTACTS (<span id="list-count">0</span>)</div>
      <div id="contact-list"></div>
    </div>

    <!-- Legend -->
    <div class="side-section">
      <div class="side-title">IFF LEGEND</div>
      <div class="legend">
        <div class="legend-item"><div class="legend-dot" style="background:#40c8ff"></div>BLUE — Friendly</div>
        <div class="legend-item"><div class="legend-dot" style="background:#ff4040"></div>RED — Hostile</div>
        <div class="legend-item"><div class="legend-dot" style="background:#aaaaaa"></div>NEUTRAL / Unknown</div>
        <div class="legend-item"><div class="legend-dot" style="background:#39ff6e"></div>OWNSHIP</div>
      </div>
    </div>

  </div><!-- /sidebar -->
</div><!-- /content -->

<div id="bottom-strip">
  <div>PACKETS: <span id="pkt-count">0</span></div>
  <div>UPDATE: <span id="upd-time">—</span></div>
  <div>NORTH UP &nbsp;&#9650;</div>
</div>

<script>
"use strict";

// ── Config ──────────────────────────────────────────────────────
const RADAR_RANGE_KM_MAX = 100;  // server sends up to 100km
let   DISPLAY_RANGE_KM   = 100;  // what we render
const SWEEP_SPEED = 3;           // rotations per second
const FADE_TIME   = 4000;        // ms a blip stays bright

// ── State ────────────────────────────────────────────────────────
let selfState    = null;
let contacts     = [];
let selectedId   = null;
let packetCount  = 0;
let sweepAngle   = 0;
let lastSweepTs  = performance.now();
let blipTimestamps = {};  // id -> last seen timestamp

// ── Canvas setup ─────────────────────────────────────────────────
const canvas = document.getElementById('radar-canvas');
const ctx    = canvas.getContext('2d');
let CX, CY, R;

function resizeCanvas() {
  const wrap = document.getElementById('radar-wrap');
  const size = Math.min(wrap.clientWidth - 40, wrap.clientHeight - 40, 640);
  canvas.width  = size;
  canvas.height = size;
  CX = CY = size / 2;
  R  = size / 2 - 4;
}
window.addEventListener('resize', () => { resizeCanvas(); drawRadar(); });
resizeCanvas();

// ── IFF colors ───────────────────────────────────────────────────
function iffColor(coalition, alpha) {
  const a = alpha !== undefined ? alpha : 1;
  if (coalition === 2) return `rgba(64,200,255,${a})`;   // blue
  if (coalition === 1) return `rgba(255,64,64,${a})`;    // red
  return `rgba(170,170,170,${a})`;                        // neutral/unknown
}
function iffName(coalition) {
  if (coalition === 2) return 'FRIENDLY';
  if (coalition === 1) return 'HOSTILE';
  return 'NEUTRAL';
}

// ── Coordinate helpers ───────────────────────────────────────────
// Convert (lat/lon) offset from self to radar pixel (x,y)
// Uses equirectangular approximation — fine for 100km
function latLonToPixel(selfLat, selfLon, cLat, cLon) {
  const R_earth = 6371000;
  const dlat = (cLat - selfLat) * Math.PI / 180;
  const dlon = (cLon - selfLon) * Math.PI / 180;
  const dy = dlat * R_earth;               // north positive
  const dx = dlon * R_earth * Math.cos(selfLat * Math.PI / 180);  // east positive
  const range_m = DISPLAY_RANGE_KM * 1000;
  const px = CX + (dx / range_m) * R;
  const py = CY - (dy / range_m) * R;     // screen Y inverted
  return { px, py, dx, dy, dist: Math.sqrt(dx*dx + dy*dy) };
}

// ── Draw ─────────────────────────────────────────────────────────
function drawRadar() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Background circle
  ctx.beginPath();
  ctx.arc(CX, CY, R, 0, Math.PI * 2);
  ctx.fillStyle = '#030703';
  ctx.fill();

  // Range rings
  ctx.strokeStyle = 'rgba(15,40,15,0.8)';
  ctx.lineWidth = 1;
  ctx.font = '10px Share Tech Mono';
  ctx.fillStyle = 'rgba(57,255,110,0.25)';
  ctx.textAlign = 'left';
  const rings = 4;
  for (let i = 1; i <= rings; i++) {
    const rr = (R / rings) * i;
    ctx.beginPath();
    ctx.arc(CX, CY, rr, 0, Math.PI * 2);
    ctx.strokeStyle = i === rings ? 'rgba(30,70,30,0.9)' : 'rgba(15,40,15,0.8)';
    ctx.stroke();
    const km = Math.round(DISPLAY_RANGE_KM / rings * i);
    ctx.fillText(km + ' km', CX + rr + 3, CY - 3);
  }

  // Cardinal lines
  ctx.strokeStyle = 'rgba(15,40,15,0.6)';
  ctx.lineWidth = 1;
  ctx.setLineDash([4, 8]);
  for (const angle of [0, 90, 180, 270]) {
    const rad = (angle - 90) * Math.PI / 180;
    ctx.beginPath();
    ctx.moveTo(CX, CY);
    ctx.lineTo(CX + Math.cos(rad) * R, CY + Math.sin(rad) * R);
    ctx.stroke();
  }
  ctx.setLineDash([]);

  // Cardinal labels
  ctx.fillStyle = 'rgba(57,255,110,0.5)';
  ctx.font = '11px Orbitron, Share Tech Mono';
  ctx.textAlign = 'center';
  const lblOffset = R + 14;
  const cardinals = [{l:'N',a:270},{l:'E',a:0},{l:'S',a:90},{l:'W',a:180}];
  for (const c of cardinals) {
    const rad = (c.a - 90) * Math.PI / 180;
    ctx.fillText(c.l, CX + Math.cos(rad) * lblOffset, CY + Math.sin(rad) * lblOffset + 4);
  }

  // Sweep line
  const now = performance.now();
  const dt  = (now - lastSweepTs) / 1000;
  lastSweepTs = now;
  sweepAngle  = (sweepAngle + SWEEP_SPEED * dt * Math.PI * 2) % (Math.PI * 2);

  const sweepGrad = ctx.createConicalGradient
    ? ctx.createConicalGradient(CX, CY, sweepAngle)  // non-standard
    : null;

  // Sweep using arc sector fill
  const sweepLen = Math.PI / 6;  // 30-degree sweep sector
  const sweepGrad2 = ctx.createRadialGradient(CX, CY, 0, CX, CY, R);
  sweepGrad2.addColorStop(0,   'rgba(57,255,110,0.0)');
  sweepGrad2.addColorStop(0.6, 'rgba(57,255,110,0.05)');
  sweepGrad2.addColorStop(1,   'rgba(57,255,110,0.12)');
  ctx.beginPath();
  ctx.moveTo(CX, CY);
  ctx.arc(CX, CY, R, sweepAngle - sweepLen, sweepAngle);
  ctx.closePath();
  ctx.fillStyle = sweepGrad2;
  ctx.fill();

  // Sweep leading edge
  ctx.beginPath();
  ctx.moveTo(CX, CY);
  ctx.lineTo(CX + Math.cos(sweepAngle) * R, CY + Math.sin(sweepAngle) * R);
  ctx.strokeStyle = 'rgba(57,255,110,0.7)';
  ctx.lineWidth = 1.5;
  ctx.stroke();

  // Outer ring border
  ctx.beginPath();
  ctx.arc(CX, CY, R, 0, Math.PI * 2);
  ctx.strokeStyle = 'rgba(30,80,30,0.9)';
  ctx.lineWidth = 2;
  ctx.stroke();

  // ── Contacts ──────────────────────────────────────────────────
  if (selfState) {
    const sLat = selfState.lat;
    const sLon = selfState.lon;

    for (const c of contacts) {
      if (c.dist_m > DISPLAY_RANGE_KM * 1000) continue;
      const {px, py} = latLonToPixel(sLat, sLon, c.lat, c.lon);

      // Fade blips that haven't been refreshed recently
      const age = now - (blipTimestamps[c.id] || 0);
      const alpha = Math.max(0, 1 - age / FADE_TIME);
      if (alpha <= 0) continue;

      const color = iffColor(c.coalition, 1);
      const colorFaded = iffColor(c.coalition, alpha);

      // Blip trail (small fading circle)
      ctx.beginPath();
      ctx.arc(px, py, 7, 0, Math.PI * 2);
      ctx.fillStyle = iffColor(c.coalition, alpha * 0.15);
      ctx.fill();

      // Blip dot
      ctx.beginPath();
      ctx.arc(px, py, 4, 0, Math.PI * 2);
      ctx.fillStyle = colorFaded;
      if (c.id === selectedId) {
        ctx.shadowColor = color;
        ctx.shadowBlur  = 10;
      }
      ctx.fill();
      ctx.shadowBlur = 0;

      // Heading tick
      if (c.speed_ms > 5) {
        const hdgRad = (c.heading_deg - 90) * Math.PI / 180;
        const tickLen = 12;
        ctx.beginPath();
        ctx.moveTo(px, py);
        ctx.lineTo(px + Math.cos(hdgRad) * tickLen, py + Math.sin(hdgRad) * tickLen);
        ctx.strokeStyle = colorFaded;
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      // Label
      ctx.font = '10px Share Tech Mono';
      ctx.fillStyle = colorFaded;
      ctx.textAlign = 'left';
      const label = (c.name || c.type || '???').substring(0, 8);
      const altKft = Math.round((c.alt_msl_m || 0) * 3.28084 / 1000);
      ctx.fillText(label, px + 6, py - 4);
      ctx.fillText(altKft + 'k ft', px + 6, py + 8);

      // Selection ring
      if (c.id === selectedId) {
        ctx.beginPath();
        ctx.arc(px, py, 10, 0, Math.PI * 2);
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    }
  }

  // ── Ownship ────────────────────────────────────────────────────
  if (selfState) {
    const hdgRad = ((selfState.heading_deg || 0) - 90) * Math.PI / 180;

    // Heading vector
    ctx.beginPath();
    ctx.moveTo(CX, CY);
    ctx.lineTo(CX + Math.cos(hdgRad) * 28, CY + Math.sin(hdgRad) * 28);
    ctx.strokeStyle = 'rgba(57,255,110,0.8)';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Aircraft symbol
    ctx.save();
    ctx.translate(CX, CY);
    ctx.rotate(hdgRad + Math.PI / 2);
    ctx.strokeStyle = '#39ff6e';
    ctx.lineWidth = 2;
    ctx.lineCap = 'round';
    // Fuselage
    ctx.beginPath();
    ctx.moveTo(0, -10); ctx.lineTo(0, 10); ctx.stroke();
    // Wings
    ctx.beginPath();
    ctx.moveTo(-12, 2); ctx.lineTo(12, 2); ctx.stroke();
    // Tail
    ctx.beginPath();
    ctx.moveTo(-6, 8); ctx.lineTo(6, 8); ctx.stroke();
    ctx.restore();

    // Center glow
    ctx.beginPath();
    ctx.arc(CX, CY, 14, 0, Math.PI * 2);
    ctx.strokeStyle = 'rgba(57,255,110,0.15)';
    ctx.lineWidth = 1;
    ctx.stroke();
  } else {
    // No signal indicator
    ctx.font = '12px Orbitron';
    ctx.fillStyle = 'rgba(255,64,64,0.6)';
    ctx.textAlign = 'center';
    ctx.fillText('NO DCS SIGNAL', CX, CY - 10);
    ctx.fillText('Waiting for Export.lua...', CX, CY + 10);
  }
}

// ── Animation loop ───────────────────────────────────────────────
function animate() {
  drawRadar();
  requestAnimationFrame(animate);
}

// ── UI updates ───────────────────────────────────────────────────
function updateSidebar() {
  if (selfState) {
    const ias = Math.round((selfState.ias_ms || 0) * 1.944);
    const altFt = Math.round((selfState.alt_msl_m || 0) * 3.28084);
    const aglFt = Math.round((selfState.alt_agl_m || 0) * 3.28084);
    document.getElementById('s-hdg').textContent  = Math.round(selfState.heading_deg || 0) + '°';
    document.getElementById('s-ias').textContent  = ias + ' kts';
    document.getElementById('s-alt').textContent  = altFt.toLocaleString() + ' ft';
    document.getElementById('s-agl').textContent  = aglFt.toLocaleString() + ' ft';
    document.getElementById('self-aircraft').textContent = (selfState.aircraft || '—').toUpperCase();
  }

  // Contact list
  const visible = contacts.filter(c => c.dist_m <= DISPLAY_RANGE_KM * 1000);
  visible.sort((a, b) => a.dist_m - b.dist_m);
  document.getElementById('list-count').textContent   = visible.length;
  document.getElementById('contact-count').textContent = visible.length;

  const list = document.getElementById('contact-list');
  list.innerHTML = visible.slice(0, 30).map(c => {
    const distKm = (c.dist_m / 1000).toFixed(1);
    const altKft  = ((c.alt_msl_m || 0) * 3.28084 / 1000).toFixed(1);
    const dot = `<div class="iff-dot" style="background:${iffColor(c.coalition)};flex-shrink:0"></div>`;
    const sel = c.id === selectedId ? ' selected' : '';
    const name = (c.name || c.type || '???').substring(0, 10);
    return `<div class="contact-row${sel}" onclick="selectContact('${c.id}')">${dot}<span class="contact-name">${name}</span><span class="contact-dist">${distKm}km</span><span class="contact-alt">${altKft}kft</span></div>`;
  }).join('');
}

function selectContact(id) {
  selectedId = selectedId === id ? null : id;
  const c = contacts.find(x => x.id === id);
  const panel = document.getElementById('detail-panel');
  if (!c || !selectedId) {
    panel.classList.remove('show');
    return;
  }
  panel.classList.add('show');
  document.getElementById('d-title').textContent  = (c.name || c.type || 'UNKNOWN').toUpperCase();
  document.getElementById('d-type').textContent   = c.type || '—';
  document.getElementById('d-hdg').textContent    = Math.round(c.heading_deg || 0) + '°';
  document.getElementById('d-spd').textContent    = Math.round((c.speed_ms || 0) * 1.944) + ' kts';
  document.getElementById('d-alt').textContent    = Math.round((c.alt_msl_m || 0) * 3.28084).toLocaleString() + ' ft';
  document.getElementById('d-dist').textContent   = ((c.dist_m || 0) / 1000).toFixed(1) + ' km';
  document.getElementById('d-iff').textContent    = iffName(c.coalition);
  document.getElementById('d-iff').style.color    = iffColor(c.coalition);
  updateSidebar();
}

function setRange(km) {
  DISPLAY_RANGE_KM = km;
  document.getElementById('range-display').textContent = km + ' km';
  document.querySelectorAll('.range-btn').forEach(b => {
    b.classList.toggle('active', b.textContent.trim() === km.toString());
  });
}

// ── WebSocket ────────────────────────────────────────────────────
let ws = null, reconnectTimer = null;

function setStatus(s) {
  const dot = document.getElementById('ws-dot');
  const lbl = document.getElementById('ws-lbl');
  dot.className = '';
  if (s === 'live') { dot.classList.add('live'); lbl.textContent = 'LIVE'; lbl.style.color = '#39ff6e'; }
  else if (s === 'connecting') { lbl.textContent = 'CONNECTING'; lbl.style.color = '#ffb830'; }
  else { dot.classList.add('err'); lbl.textContent = 'OFFLINE'; lbl.style.color = '#ff4040'; }
}

function initWS() {
  clearTimeout(reconnectTimer);
  if (ws) { try { ws.close(); } catch(e){} ws = null; }
  setStatus('connecting');
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(proto + '//' + location.host + '/ws/radar');

  ws.onopen = () => setStatus('live');

  ws.onmessage = (evt) => {
    try {
      const frame = JSON.parse(evt.data);
      packetCount++;
      document.getElementById('pkt-count').textContent = packetCount;
      document.getElementById('upd-time').textContent = new Date().toLocaleTimeString('pt-BR');

      if (frame.self) selfState = frame.self;
      if (frame.contacts) {
        contacts = frame.contacts;
        const now = performance.now();
        for (const c of contacts) blipTimestamps[c.id] = now;
      }
      updateSidebar();
    } catch(e) {}
  };

  ws.onerror = () => {};
  ws.onclose = (evt) => {
    setStatus('offline');
    reconnectTimer = setTimeout(initWS, 3000);
  };
}

// ── Init ─────────────────────────────────────────────────────────
animate();
initWS();
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


# ----------------------------------------------------------------
# WebSocket endpoints
# ----------------------------------------------------------------
@app.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket):
    """Real-time player telemetry at ~30Hz."""
    await manager_telem.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager_telem.disconnect(websocket)


@app.websocket("/ws/radar")
async def ws_radar(websocket: WebSocket):
    """Radar frame (self + contacts) at ~10Hz."""
    await manager_radar.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager_radar.disconnect(websocket)
