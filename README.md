# dcs-iox-api

> Bridge between **DCS World** and the outside world via UDP → REST / WebSocket.

## Arquitetura

O DCS World possui **dois ambientes Lua separados** com APIs diferentes:

| Ambiente | Arquivo | APIs disponíveis |
|---|---|---|
| Export environment | `Export.lua` (Saved Games) | `LoGetSelfData`, `LoGetIndicatedAirSpeed`, etc. |
| Mission environment | `MissionScript.lua` (trigger na missão) | `world.searchObjects`, `Unit`, `coalition`, `coord`, etc. |

`world.searchObjects` **não funciona** no Export environment — por isso contacts e telemetria são enviados em portas UDP separadas:

```
 DCS World
  ├── Export.lua  (Saved Games\DCS\Scripts)
  │     └─ player telemetry  ──► UDP :7778  (~30 Hz, JSON)
  │
  └── MissionScript.lua  (carregado via trigger DO SCRIPT FILE)
        └─ contacts         ──► UDP :7779  (~1 Hz, JSON)

                    ┌────────────────────┐
                    │  UDP Server x2     │  asyncio
                    │  7778 + 7779       │
                    └────────┬───────────┘
                             │  shared in-memory state
                    ┌────────▼───────────┐
                    │     FastAPI        │  REST + WebSocket
                    └────────────────────┘
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

---

## Instalação — Export.lua (telemetria do jogador)

1. Copie `dcs/Export.lua` para:
   ```
   %USERPROFILE%\Saved Games\DCS\Scripts\Export.lua
   ```
   > Se já existir um `Export.lua` (Tacview, SRS, etc.), **não substitua** — adicione o conteúdo ao final do arquivo existente.

2. Inicie o servidor Python antes de entrar em missão.

---

## Instalação — MissionScript.lua (contacts)

Este script precisa ser carregado **dentro de cada missão** que você queira usar:

1. Abra a missão no **Mission Editor** do DCS.

2. Vá em **Triggers** (ícone de engrenagem ou menu Mission → Triggers).

3. Crie um novo trigger com:
   - **Name**: `IOX_Start` (qualquer nome)
   - **Type**: `ONCE`
   - **Condition**: `TIME MORE (1)` — dispara 1 segundo após o início da missão
   - **Action**: `DO SCRIPT FILE` → aponte para `dcs/MissionScript.lua`

4. Salve a missão (`.miz`). O script é embarcado dentro do arquivo `.miz` — **não precisa** estar em nenhuma pasta específica na hora de jogar.

> **Missões prontas (não editáveis):** não é possível injetar o MissionScript. Use apenas missões suas ou que você possa editar.

---

## Endpoints

| Método | Path | Descrição |
|--------|------|-----------|
| `GET` | `/health` | Status, uptime, contagem de pacotes |
| `GET` | `/state` | Estado completo da aeronave |
| `GET` | `/telemetry` | Posição + velocidade + atitude (resumido) |
| `GET` | `/contacts` | Lista de contatos detectados pelo MissionScript |
| `WS` | `/ws/telemetry` | Stream telemetria ~30Hz |
| `WS` | `/ws/contacts` | Stream contacts ~1Hz |
| `GET` | `/docs` | Swagger UI |

### Exemplo `/telemetry`

```json
{
  "aircraft": "F-16C_50",
  "timestamp": 123.45,
  "position": { "lat": 41.123, "lon": 29.456, "alt_msl_m": 4572.0 },
  "speed": { "ias_ms": 180.5, "ias_kts": 350.9, "mach": 0.62 },
  "attitude": { "heading_deg": 270.0, "pitch_deg": 3.5, "bank_deg": -1.2 }
}
```

### Exemplo `/contacts`

```json
{
  "timestamp": 145.0,
  "count": 3,
  "contacts": [
    {
      "id": "MiG-29 #001",
      "name": "MiG-29 #001",
      "type": "MiG-29A",
      "category": "unit",
      "lat": 41.200,
      "lon": 29.800,
      "alt_msl_m": 6000.0,
      "heading_deg": 180.0,
      "speed_ms": 250.0,
      "speed_kts": 486.0,
      "coalition": 1,
      "dist_m": 42000.0
    }
  ]
}
```

---

## Estrutura do projeto

```
dcs-iox-api/
├── dcs/
│   ├── Export.lua          # Telemetria do jogador (Saved Games)
│   └── MissionScript.lua   # Contacts (carregado via trigger na missão)
├── server/
│   ├── __init__.py
│   ├── main.py             # Entry point: UDP 7778 + 7779 + FastAPI
│   ├── api.py              # FastAPI app, REST + WS
│   ├── models.py           # Pydantic models
│   └── state.py            # Shared in-memory state
├── tests/
│   ├── mock_dcs.py         # Simulador UDP (sem DCS real)
│   └── test_api.http
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## Variáveis de ambiente

| Variável | Default | Descrição |
|----------|---------|----------|
| `UDP_HOST` | `127.0.0.1` | Interface UDP |
| `UDP_PORT_TELEMETRY` | `7778` | Porta telemetria (Export.lua) |
| `UDP_PORT_CONTACTS` | `7779` | Porta contacts (MissionScript.lua) |
| `API_HOST` | `0.0.0.0` | Interface HTTP/WS |
| `API_PORT` | `8000` | Porta HTTP/WS |

---

## Desenvolvimento

```bash
# Testar sem DCS: simula frames a 30Hz
python tests/mock_dcs.py

# VSCode: F5 → "DCS IOX: Full Stack Test"
```
