-- =============================================================
-- dcs-iox-api | Export.lua  (DCS 2.9+)
-- Envia telemetria do jogador + contacts de todas as unidades
-- via UDP 7778 (~30 Hz), usando LoGetWorldObjects() nativo.
--
-- INSTALAÇÃO:
--   Copie para: %USERPROFILE%\Saved Games\DCS\Scripts\Export.lua
--   Se já existir Export.lua (Tacview, SRS...), adicione ao final.
--
-- NÃO é necessário nenhum MissionScript.lua.
-- =============================================================

local IOX = {}
IOX.host            = "127.0.0.1"
IOX.port            = 7778
IOX.socket          = nil
IOX.update_interval = 0.033   -- ~30 Hz

-- ----------------------------------------------------------------
-- Helpers JSON mínimos (sem dependências)
-- ----------------------------------------------------------------
local function safe_num(v)
  if type(v) == "number" and v == v then return v else return 0 end
end

local function safe_str(v)
  if type(v) == "string" then return v else return "" end
end

local function json_str(s)
  s = tostring(s or "")
  s = s:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n'):gsub('\r', '\\r')
  return '"' .. s .. '"'
end

local function json_flat(t)
  local parts = {}
  for k, v in pairs(t) do
    local val
    local tp = type(v)
    if     tp == "number"  then val = string.format("%.6g", v)
    elseif tp == "boolean" then val = tostring(v)
    elseif tp == "string"  then val = json_str(v)
    else                        val = "null"
    end
    table.insert(parts, json_str(k) .. ":" .. val)
  end
  return "{" .. table.concat(parts, ",") .. "}"
end

-- ----------------------------------------------------------------
-- Carrega luasocket
-- ----------------------------------------------------------------
local function load_socket()
  local ok, sock = pcall(require, "socket")
  if ok and sock then return sock end

  local paths = {
    "./Scripts/?.dll",
    "./bin/?.dll",
    "C:/Program Files/Eagle Dynamics/DCS World/bin/?.dll",
    "C:/Program Files/Eagle Dynamics/DCS World OpenBeta/bin/?.dll",
    "C:/Program Files (x86)/Steam/steamapps/common/DCSWorld/bin/?.dll",
  }
  for _, p in ipairs(paths) do
    package.cpath = package.cpath .. ";" .. p
  end

  ok, sock = pcall(require, "socket")
  if ok and sock then return sock end

  ok, sock = pcall(require, "socket.core")
  if ok and sock then
    local M = {}
    function M.udp() return sock.udp() end
    return M
  end

  return nil
end

local function make_udp(sock_lib, host, port)
  local ok, udp = pcall(function() return sock_lib.udp() end)
  if not ok or not udp then return nil end
  udp:setsockname("*", 0)
  udp:setpeername(host, port)
  return udp
end

-- ----------------------------------------------------------------
-- Lifecycle
-- ----------------------------------------------------------------
function LuaExportStart()
  local sock_lib = load_socket()
  if not sock_lib then
    log.write("IOX", log.ERROR,
      "[dcs-iox-api] luasocket nao encontrado! cpath: " .. tostring(package.cpath))
    return
  end

  IOX.socket = make_udp(sock_lib, IOX.host, IOX.port)

  if IOX.socket then
    log.write("IOX", log.INFO,
      "[dcs-iox-api] Export started -> " .. IOX.host .. ":" .. IOX.port)
  else
    log.write("IOX", log.ERROR, "[dcs-iox-api] Falha ao criar socket UDP")
  end
end

function LuaExportStop()
  if IOX.socket then IOX.socket:close(); IOX.socket = nil end
  log.write("IOX", log.INFO, "[dcs-iox-api] Export stopped")
end

-- ----------------------------------------------------------------
-- Telemetria do jogador
-- ----------------------------------------------------------------
local function get_self_data(t)
  local ok, sd = pcall(LoGetSelfData)
  if not ok or not sd then return nil end

  local lat, lon, alt = 0, 0, 0
  if sd.LatLongAlt then
    lat = safe_num(sd.LatLongAlt.Lat)
    lon = safe_num(sd.LatLongAlt.Long)
    alt = safe_num(sd.LatLongAlt.Alt)
  end

  local heading, pitch, bank = 0, 0, 0
  local ok2, pbh = pcall(LoGetADIPitchBankHeading)
  if ok2 and pbh then
    pitch   = math.deg(safe_num(pbh.Pitch))
    bank    = math.deg(safe_num(pbh.Bank))
    heading = math.deg(safe_num(pbh.Heading))
    if heading < 0 then heading = heading + 360 end
  elseif sd.Heading then
    heading = math.deg(safe_num(sd.Heading))
    if heading < 0 then heading = heading + 360 end
  end

  local ias_ms, tas_ms, mach, aoa_deg, vvi_ms = 0, 0, 0, 0, 0
  local ok3, v = pcall(LoGetIndicatedAirSpeed); if ok3 and v then ias_ms  = safe_num(v)           end
  local ok4, v = pcall(LoGetTrueAirSpeed);      if ok4 and v then tas_ms  = safe_num(v)           end
  local ok5, v = pcall(LoGetMachNumber);        if ok5 and v then mach    = safe_num(v)           end
  local ok6, v = pcall(LoGetAngleOfAttack);     if ok6 and v then aoa_deg = math.deg(safe_num(v)) end
  local ok7, v = pcall(LoGetVerticalVelocity);  if ok7 and v then vvi_ms  = safe_num(v)           end

  local alt_agl = 0
  local ok8, v = pcall(LoGetAltitudeAboveGroundLevel)
  if ok8 and v then alt_agl = safe_num(v) end

  local fuel_kg = 0
  local ok9, v = pcall(LoGetFuelInternalFuelTotal)
  if ok9 and v then fuel_kg = safe_num(v) end

  local rpm_1, rpm_2, throttle = 0, 0, 0
  local ok10, eng = pcall(LoGetEngineInfo)
  if ok10 and eng then
    if eng.RPM then
      rpm_1 = safe_num(eng.RPM.left  or eng.RPM[1] or 0)
      rpm_2 = safe_num(eng.RPM.right or eng.RPM[2] or 0)
    end
    if eng.Throttle then
      throttle = safe_num(eng.Throttle.left or eng.Throttle[1] or eng.Throttle or 0)
    end
  end

  local g_load = 1.0
  local ok11, g = pcall(LoGetAccelerationUnits)
  if ok11 and g then g_load = safe_num(g.y or 1.0) end

  return {
    msg_type    = "self",
    timestamp   = t,
    aircraft    = safe_str(sd.Name),
    lat         = lat,
    lon         = lon,
    alt_msl_m   = alt,
    alt_agl_m   = alt_agl,
    ias_ms      = ias_ms,
    tas_ms      = tas_ms,
    mach        = mach,
    vvi_ms      = vvi_ms,
    heading_deg = heading,
    pitch_deg   = pitch,
    bank_deg    = bank,
    aoa_deg     = aoa_deg,
    fuel_kg     = fuel_kg,
    rpm_1       = rpm_1,
    rpm_2       = rpm_2,
    throttle    = throttle,
    g_load      = g_load,
  }
end

-- ----------------------------------------------------------------
-- Contacts — LoGetWorldObjects() retorna TODAS as unidades do mapa
-- coalition: 1=Allies, 2=Enemies, 0=Neutral (ou string em versões antigas)
-- ----------------------------------------------------------------
local COALITION_MAP = { Allies = 1, Enemies = 2, Neutral = 0 }

local function get_contacts(self_lat, self_lon)
  local ok, objs = pcall(LoGetWorldObjects)
  if not ok or not objs then return "[]" end

  local parts = {}
  local R = 6371000.0

  for id, obj in pairs(objs) do
    if obj and obj.LatLongAlt then
      local lat = safe_num(obj.LatLongAlt.Lat)
      local lon = safe_num(obj.LatLongAlt.Long)
      local alt = safe_num(obj.LatLongAlt.Alt)

      -- heading
      local hdg = 0
      if obj.Heading then
        hdg = math.deg(safe_num(obj.Heading))
        if hdg < 0 then hdg = hdg + 360 end
      end

      -- velocidade
      local spd_ms = 0
      if obj.Velocity then
        local vx = safe_num(obj.Velocity.x)
        local vy = safe_num(obj.Velocity.y)
        local vz = safe_num(obj.Velocity.z)
        spd_ms = math.sqrt(vx*vx + vy*vy + vz*vz)
      end

      -- coalizão: número ou string dependendo da versão do DCS
      local coal = obj.Coalition
      if type(coal) == "string" then
        coal = COALITION_MAP[coal] or 0
      else
        coal = safe_num(coal)
      end

      -- categoria
      local cat = safe_str(obj.Type and obj.Type.level1 or "")
      if cat == "" then
        cat = (obj.Flags and obj.Flags.Ground) and "Ground" or "Air"
      end

      -- distância ao jogador (haversine simples)
      local dist_m = 0
      if self_lat ~= 0 or self_lon ~= 0 then
        local dlat = math.rad(lat - self_lat)
        local dlon = math.rad(lon - self_lon)
        local a = math.sin(dlat/2)^2
                + math.cos(math.rad(self_lat)) * math.cos(math.rad(lat))
                * math.sin(dlon/2)^2
        dist_m = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
      end

      local entry = string.format(
        '{"id":%s,"name":%s,"type":%s,"category":%s,' ..
        '"coalition":%d,"lat":%.6f,"lon":%.6f,"alt_msl_m":%.1f,' ..
        '"heading_deg":%.1f,"speed_ms":%.1f,"speed_kts":%.1f,"dist_m":%.0f,"source":"export"}',
        json_str(tostring(id)),
        json_str(safe_str(obj.Name)),
        json_str(safe_str(obj.Type and obj.Type.level2 or obj.Name or "")),
        json_str(cat),
        coal, lat, lon, alt,
        hdg, spd_ms, spd_ms * 1.94384, dist_m
      )
      table.insert(parts, entry)
    end
  end

  return "[" .. table.concat(parts, ",") .. "]"
end

-- ----------------------------------------------------------------
-- Loop principal ~30 Hz
-- ----------------------------------------------------------------
local function iox_tick(t)
  if not IOX.socket then return end

  -- 1. Dados do jogador
  local self_data = get_self_data(t)
  local self_lat  = self_data and self_data.lat or 0
  local self_lon  = self_data and self_data.lon or 0

  -- 2. Contacts via LoGetWorldObjects
  local contacts_json = get_contacts(self_lat, self_lon)

  -- 3. Monta payload único e envia
  local payload
  if self_data then
    local self_json = json_flat(self_data)
    -- Injeta contacts dentro do mesmo pacote
    self_json = self_json:sub(1, -2) .. ',"contacts":' .. contacts_json .. '}'
    payload = self_json
  else
    payload = string.format(
      '{"msg_type":"contacts","timestamp":%.3f,"contacts":%s}',
      t, contacts_json)
  end

  IOX.socket:send(payload)
end

function LuaExportActivityNextEvent(t)
  local tNext = t + IOX.update_interval
  pcall(iox_tick, t)
  return tNext
end
