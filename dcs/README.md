# DCS Export.lua

Script Lua que roda **dentro do DCS World** e envia telemetria da aeronave via UDP para o servidor local.

## Instalação

1. Copie `Export.lua` para:
   ```
   %USERPROFILE%\Saved Games\DCS\Scripts\Export.lua
   ```
   > Se já tiver um `Export.lua` existente, adicione o conteúdo deste arquivo ao final do seu.

2. Inicie o DCS World e carregue qualquer missão.

3. O script começa a enviar dados automaticamente para `localhost:7778` em ~30Hz.

## Dados enviados

| Campo | Descrição | Unidade |
|-------|-----------|--------|
| `timestamp` | Tempo de missão DCS | segundos |
| `aircraft` | Nome do módulo | string |
| `lat` / `lon` | Latitude / Longitude | graus decimais |
| `alt_msl_m` | Altitude acima do nível do mar | metros |
| `alt_agl_m` | Altitude acima do solo | metros |
| `speed_ms` | Velocidade 3D (vetor) | m/s |
| `ias_ms` | Velocidade indicada (IAS) | m/s |
| `tas_ms` | Velocidade real (TAS) | m/s |
| `mach` | Número de Mach | - |
| `aoa_deg` | Ângulo de ataque | graus |
| `vvi_ms` | Velocidade vertical | m/s |
| `heading_deg` | Proa magnética | graus |
| `pitch_deg` | Arfagem (Pitch) | graus |
| `bank_deg` | Inclinação (Bank/Roll) | graus |
| `fuel_kg` | Combustível interno total | kg |
| `rpm_1` / `rpm_2` | RPM motor 1 / 2 | % |

## Protocolo

- Transporte: **UDP**
- Host: `127.0.0.1`
- Porta: `7778`
- Formato: JSON (uma linha por pacote)
- Taxa: ~30Hz (configurável via `IOX.update_interval`)

## Configuração

Edite o topo do `Export.lua` para ajustar:
```lua
IOX.host = "127.0.0.1"   -- IP do servidor
IOX.port = 7778           -- Porta UDP
IOX.update_interval = 0.033  -- 0.033 = 30Hz, 0.016 = 60Hz
```
