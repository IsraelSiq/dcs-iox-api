# dcs-iox-api

> Real-time telemetry and tactical radar for **DCS World**, served as a local REST/WebSocket API.

Captures live data from DCS World using the native `Export.lua` hook and `LoGetWorldObjects()`, streams it through a FastAPI server, and renders a tactical radar with sweep animation directly in the browser — no mods, no external tools required.

---

## Features

- **Tactical radar** — animated sweep, contact trails, altitude filter, threat alerts
- **Full unit awareness** — all coalition units (air + ground + naval) via `LoGetWorldObjects()`
- **Player telemetry** — speed, altitude, heading, G-load, fuel, AoA at ~30 Hz
- **REST + WebSocket API** — integrate with any overlay, stream deck, or external tool
- **Single UDP port** — contacts and telemetry in one packet, one listener
- **Standalone `.exe`** — runs without Python installed, opens browser automatically
- **Local mock** — test radar and API without DCS running

---

## Architecture

```
DCS World
  └── Export.lua  (%USERPROFILE%\Saved Games\DCS\Scripts)
        ├── LoGetSelfData()        player telemetry
        └── LoGetWorldObjects()    all units on the map
              │
              └──► UDP :7778 (JSON, ~30 Hz)
                        │
               ┌────────▼────────┐
               │   FastAPI       │  asyncio UDP listener
               │   server/       │  shared in-memory state
               └────────┬────────┘
                        │
               ┌────────▼────────┐
               │   :8000         │  REST + WebSocket + Radar UI
               └─────────────────┘
```

No `MissionScript.lua`. No second port. No file I/O. Just `Export.lua` → UDP → server.

---

## Quick Start

### Option A — Python

```bash
git clone https://github.com/IsraelSiq/dcs-iox-api.git
cd dcs-iox-api
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python launcher.py
```

### Option B — Standalone `.exe`

```bash
pip install pyinstaller
python build.py
# Output: dist/dcs-iox-api.exe
```

Double-click `dcs-iox-api.exe` — server starts and radar opens in your browser automatically.

### Option C — Docker

```bash
docker compose up --build
```

---

## DCS Setup

Copy `dcs/Export.lua` to:

```
%USERPROFILE%\Saved Games\DCS\Scripts\Export.lua
```

> **Already have an Export.lua?** (Tacview, SRS, DCS-BIOS) Don't overwrite it — open the existing file and paste the contents of `dcs/Export.lua` at the end.

That's it. Start the server, then launch DCS. The radar populates as soon as you're in a mission.

---

## Radar

Open **`http://localhost:8000/radar`** in your browser.

| Feature | Details |
|---|---|
| Sweep animation | Rotating scan line at 36°/s with trailing glow |
| Contact trails | Last 8 positions per unit |
| Threat alert | Red banner when any enemy unit is within 20 km |
| Altitude filter | Min/max sliders in feet |
| Coalition colors | Blue = friendly · Red = enemy · Yellow = neutral |
| Labels | Unit name · altitude (ft) · speed (kts) |
| Toggles | Trails · Labels · Speed vectors |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Status, uptime, packet count, DCS connection |
| `GET` | `/state` | Full aircraft state |
| `GET` | `/telemetry` | Position + speed + attitude (summary) |
| `GET` | `/contacts` | All detected units |
| `GET` | `/radar` | Tactical radar UI |
| `GET` | `/dashboard` | HUD overlay |
| `WS` | `/ws/telemetry` | Live telemetry stream ~30 Hz |
| `WS` | `/ws/contacts` | Live contacts stream |
| `GET` | `/docs` | Swagger UI |

### `GET /health`

```json
{
  "status": "ok",
  "uptime": 142.3,
  "packets_received": 4280,
  "dcs_connected": true,
  "contacts_count": 7
}
```

### `GET /contacts`

```json
{
  "timestamp": 145.0,
  "count": 2,
  "contacts": [
    {
      "id": "c3",
      "name": "Hostile-1",
      "type": "MiG-29",
      "category": "Air",
      "coalition": 2,
      "lat": 41.812,
      "lon": 41.623,
      "alt_msl_m": 9000.0,
      "heading_deg": 185.0,
      "speed_ms": 280.0,
      "speed_kts": 544.4,
      "dist_m": 58000.0,
      "source": "export"
    }
  ]
}
```

---

## Local Testing (no DCS required)

```bash
# Terminal 1 — server
python -m server.main

# Terminal 2 — mock (simulates 7 units with real movement)
python tests/mock_dcs.py
```

Open `http://localhost:8000/radar` — contacts appear with sweep, trails and threat alerts.

---

## Project Structure

```
dcs-iox-api/
├── dcs/
│   ├── Export.lua          # DCS hook — telemetry + LoGetWorldObjects()
│   └── README.md           # DCS-specific install notes
├── server/
│   ├── main.py             # UDP listener + FastAPI entry point
│   ├── api.py              # REST endpoints + WebSocket + radar/dashboard UI
│   ├── models.py           # Pydantic models (AircraftState, ContactState)
│   ├── state.py            # Shared in-memory state
│   └── log_handler.py      # Buffered log handler
├── tests/
│   └── mock_dcs.py         # UDP mock — simulates DCS output locally
├── launcher.py             # Entry point: starts server + opens browser
├── build.py                # PyInstaller build script → dist/dcs-iox-api.exe
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `UDP_HOST` | `127.0.0.1` | UDP bind address |
| `UDP_PORT_TELEMETRY` | `7778` | Telemetry + contacts port |

---

## Requirements

- Python 3.10+
- DCS World 2.9+ (Open Beta or Stable)
- Windows (DCS is Windows-only; server runs on any OS)

```
fastapi
uvicorn[standard]
pydantic
```

---

## License

MIT
