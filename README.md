# dcs-iox-api

> Bridge between **DCS World** and the outside world via UDP → REST / WebSocket.

```
 DCS World
  Export.lua
      │
      │  UDP :7778  (JSON frames ~30Hz)
      ▼
 ┌────────────┐
 │ UDP Server │  asyncio DatagramProtocol
 └─────┬──────┘
       │  shared in-memory state
 ┌─────▼──────┐
 │  FastAPI   │  REST + WebSocket
 └────────────┘
   :8000
```

---

## Quick start (local)

```bash
# 1. Clone
git clone https://github.com/IsraelSiq/dcs-iox-api.git
cd dcs-iox-api

# 2. Virtualenv
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Dependências
pip install -r requirements.txt

# 4. Rodar
python -m server.main
```

Abra http://localhost:8000/docs para o Swagger UI.

---

## Quick start (Docker)

```bash
docker compose up --build
```

Ou só o container:
```bash
docker build -t dcs-iox-api .
docker run --rm -p 8000:8000 -p 7778:7778/udp dcs-iox-api
```

---

## Instalação do Export.lua no DCS

1. Copie `dcs/Export.lua` para:
   ```
   %USERPROFILE%\Saved Games\DCS\Scripts\Export.lua
   ```
   > Se já existir um `Export.lua`, adicione o conteúdo ao final do arquivo existente.

2. Inicie o servidor antes de entrar em missão:
   ```bash
   python -m server.main
   # ou: docker compose up
   ```

3. Entre em qualquer missão no DCS. Em ~1s os dados começam a chegar.

---

## Endpoints

| Método | Path | Descrição |
|--------|------|-----------|
| `GET` | `/health` | Status do servidor, uptime, contagem de pacotes |
| `GET` | `/state` | Estado completo da aeronave (todos os campos) |
| `GET` | `/telemetry` | Posição + velocidade + atitude (resumido) |
| `WS` | `/ws/telemetry` | Stream em tempo real ~30Hz |
| `GET` | `/docs` | Swagger UI |

### Exemplo `/telemetry`

```json
{
  "aircraft": "F-16C_50",
  "timestamp": 123.45,
  "position": {
    "lat": 41.123,
    "lon": 29.456,
    "alt_msl_m": 4572.0,
    "alt_agl_m": 4450.0
  },
  "speed": {
    "ias_ms": 180.5,
    "ias_kts": 350.9,
    "tas_ms": 195.2,
    "mach": 0.62,
    "vvi_ms": 2.1
  },
  "attitude": {
    "heading_deg": 270.0,
    "pitch_deg": 3.5,
    "bank_deg": -1.2,
    "aoa_deg": 4.1
  }
}
```

### WebSocket (JavaScript)

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/telemetry');
ws.onmessage = (e) => {
  const state = JSON.parse(e.data);
  console.log(state.aircraft, state.heading_deg);
};
```

---

## Estrutura do projeto

```
dcs-iox-api/
├── dcs/
│   └── Export.lua          # Script Lua para DCS World
├── server/
│   ├── __init__.py
│   ├── main.py             # Entry point: UDP + FastAPI
│   ├── api.py              # FastAPI app, REST + WS
│   ├── models.py           # Pydantic AircraftState
│   └── state.py            # Shared in-memory state
├── tests/
│   ├── mock_dcs.py         # Simulador UDP (sem DCS real)
│   └── test_api.http       # REST Client snippets
├── .vscode/
│   └── launch.json
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## Variáveis de ambiente

| Variável | Default | Descrição |
|----------|---------|----------|
| `UDP_HOST` | `127.0.0.1` | Interface UDP (use `0.0.0.0` para rede local) |
| `UDP_PORT` | `7778` | Porta UDP que o Export.lua envia |
| `API_HOST` | `0.0.0.0` | Interface HTTP/WS |
| `API_PORT` | `8000` | Porta HTTP/WS |

> No Docker as variáveis já estão configuradas como `0.0.0.0` para aceitar conexões externas.

---

## Desenvolvimento

```bash
# Testar sem DCS: simula frames a 30Hz
python tests/mock_dcs.py

# VSCode: F5 → "DCS IOX: Full Stack Test" (sobe server + mock juntos)
```
