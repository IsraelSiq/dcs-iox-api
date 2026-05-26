# server/api.py
# Issue #3 - REST endpoints
# Issue #4 - WebSocket real-time stream
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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
            # Keep connection alive, wait for client disconnect
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
