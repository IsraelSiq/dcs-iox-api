-- =============================================================
-- dcs-iox-api | Export.lua  (DCS 2.9+)
-- Envia APENAS telemetria do jogador via UDP -> 127.0.0.1:7778
--
-- Contacts são enviados pelo MissionScript.lua (porta 7779)
-- pois world.searchObjects NÃO está disponível no Export environment.
--
-- INSTALAÇÃO:
--   Copie este arquivo para:
--   %USERPROFILE%\Saved Games\DCS\Scripts\Export.lua
--
--   Se já existir um Export.lua (Tacview, SRS, etc.),
--   NAO substitua — adicione o bloco IOX no final do arquivo existente.
-- =============================================================

local IOX = {}
IOX.host            = "127.0.0.1"
IOX.port            = 7778
IOX.socket          = nil
IOX.update_interval = 0.033   -- ~30 Hz

-- ----------------------------------------------------------------
-- Helpers
-- ----------------------------------------------------------------
local function safe_num(v)
  if type(v) == "number" and v == v then return v else return 0 end
end

local function safe_str(v)
  if type(v) == "string" then return v else return "" end
end

local function json_str(s)
  s = tostring(s or "")
  s = s:gsub('\\','\\\\'):gsub('"','\\"'):gsub('\n','\\n'):gsub('\r','\\r')
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

  local dcs_paths = {
    "./Scripts/?.dll",
    "./bin/?.dll",
    "C:/Program Files/Eagle Dynamics/DCS World/bin/?.dll",
    "C:/Program Files/Eagle Dynamics/DCS World OpenBeta/bin/?.dll",
    "C:/Program Files (x86)/Steam/steamapps/common/DCSWorld/bin/?.dll",
  }
  for _, p in ipairs(dcs_paths) do
    package.cpath = package.cpath .. ";" .. p
  end

  ok, sock = pcall(require, "socket")
  if ok and sock then return sock end

  ok, sock = pcall(require, "socket.core")
  if ok and sock then
    local M = {}
    function M.udp()
      return sock.udp()
    end
    return M
  end

  return nil
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

  local ok, udp = pcall(function() return sock_lib.udp() end)
  if not ok or not udp then
    log.write("IOX", log.ERROR, "[dcs-iox-api] Falha ao criar socket UDP: " .. tostring(udp))
    return
  end

  udp:setsockname("*", 0)
  udp:setpeername(IOX.host, IOX.port)
  IOX.socket = udp

  log.write("IOX", log.INFO,
    "[dcs-iox-api] Export started -> " .. IOX.host .. ":" .. tostring(IOX.port))
end

function LuaExportStop()
  if IOX.socket then
    IOX.socket:close()
    IOX.socket = nil
  end
  log.write("IOX", log.INFO, "[dcs-iox-api] Export stopped")
end

-- ----------------------------------------------------------------
-- Player telemetry
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

  local speed_ms = 0
  if sd.Velocity then
    local vx = safe_num(sd.Velocity.x)
    local vy = safe_num(sd.Velocity.y)
    local vz = safe_num(sd.Velocity.z)
    speed_ms = math.sqrt(vx*vx + vy*vy + vz*vz)
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
  local ok3, v = pcall(LoGetIndicatedAirSpeed);  if ok3 and v then ias_ms  = safe_num(v)            end
  local ok4, v = pcall(LoGetTrueAirSpeed);       if ok4 and v then tas_ms  = safe_num(v)            end
  local ok5, v = pcall(LoGetMachNumber);         if ok5 and v then mach    = safe_num(v)            end
  local ok6, v = pcall(LoGetAngleOfAttack);      if ok6 and v then aoa_deg = math.deg(safe_num(v))  end
  local ok7, v = pcall(LoGetVerticalVelocity);   if ok7 and v then vvi_ms  = safe_num(v)            end

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
    speed_ms    = speed_ms,
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
-- Loop principal ~30 Hz — somente telemetria do jogador
-- ----------------------------------------------------------------
local function iox_tick(t)
  if not IOX.socket then return end
  local payload = get_self_data(t)
  if not payload then return end
  IOX.socket:send(json_flat(payload))
end

function LuaExportActivityNextEvent(t)
  local tNext = t + IOX.update_interval
  pcall(iox_tick, t)
  return tNext
end
