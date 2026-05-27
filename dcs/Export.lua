-- =============================================================
-- dcs-iox-api | Export.lua  (DCS 2.9+)
-- Envia telemetria do jogador + contacts via UDP JSON -> 127.0.0.1:7778
--
-- INSTALAÇÃO:
--   Copie este arquivo para:
--   %USERPROFILE%\Saved Games\DCS\Scripts\Export.lua
--
--   Se já existir um Export.lua com outros scripts (Tacview, SRS, etc.),
--   NAO substitua — apenas adicione o bloco IOX no final do arquivo existente.
-- =============================================================

local IOX = {}
IOX.host            = "127.0.0.1"
IOX.port            = 7778
IOX.socket          = nil
IOX.update_interval = 0.033   -- ~30 Hz
IOX.radar_range_m   = 150000  -- 150 km

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

local function json_array(arr)
  local items = {}
  for _, t in ipairs(arr) do
    table.insert(items, json_flat(t))
  end
  return "[" .. table.concat(items, ",") .. "]"
end

local function haversine(lat1, lon1, lat2, lon2)
  local R  = 6371000
  local d1 = math.rad(lat2 - lat1)
  local d2 = math.rad(lon2 - lon1)
  local a  = math.sin(d1/2)^2
              + math.cos(math.rad(lat1)) * math.cos(math.rad(lat2))
              * math.sin(d2/2)^2
  return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
end

-- ----------------------------------------------------------------
-- Carrega luasocket pelo caminho interno do DCS
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
      local u = sock.udp()
      return u
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
      "[dcs-iox-api] luasocket nao encontrado! "
      .. "package.cpath: " .. tostring(package.cpath))
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
-- Player data
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
  local ok3, v = pcall(LoGetIndicatedAirSpeed);  if ok3 and v then ias_ms  = safe_num(v)           end
  local ok4, v = pcall(LoGetTrueAirSpeed);       if ok4 and v then tas_ms  = safe_num(v)           end
  local ok5, v = pcall(LoGetMachNumber);         if ok5 and v then mach    = safe_num(v)           end
  local ok6, v = pcall(LoGetAngleOfAttack);      if ok6 and v then aoa_deg = math.deg(safe_num(v)) end
  local ok7, v = pcall(LoGetVerticalVelocity);   if ok7 and v then vvi_ms  = safe_num(v)           end

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

  local coalition = 2
  local ok12, unit = pcall(function()
    return Unit.getByName(safe_str(sd.UnitName))
  end)
  if ok12 and unit then
    local ok13, c = pcall(function() return unit:getCoalition() end)
    if ok13 and c then coalition = c end
  end

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
    coalition   = coalition,
    _lat        = lat,
    _lon        = lon,
    _alt        = alt,
  }, sd
end

-- ----------------------------------------------------------------
-- Contacts via world.searchObjects com callback (DCS 2.9+)
-- Usa Unit:getPoint() diretamente como centro do volume —
-- evita coord.LLtoLO que retorna userdata incompatível com
-- a checagem type() == "table".
-- ----------------------------------------------------------------
local function get_contacts(player_lat, player_lon, player_alt, player_unit_name)
  local contacts = {}

  -- Pega o ponto 3D nativo do DCS direto da unidade do jogador
  local ok_unit, player_unit = pcall(Unit.getByName, player_unit_name)
  if not ok_unit or not player_unit then
    log.write("IOX", log.WARNING, string.format(
      "[IOX] get_contacts: Unit.getByName falhou para '%s'", tostring(player_unit_name)))
    return contacts
  end

  local ok_pt, center_lo = pcall(function() return player_unit:getPoint() end)
  if not ok_pt or not center_lo then
    log.write("IOX", log.WARNING, "[IOX] get_contacts: getPoint() falhou")
    return contacts
  end

  local volume = {
    id     = world.VolumeType.SPHERE,
    params = {
      point  = center_lo,
      radius = IOX.radar_range_m,
    },
  }

  local categories = { Object.Category.UNIT, Object.Category.STATIC }

  for _, cat in ipairs(categories) do
    local count_before = #contacts

    local ok_search, err = pcall(function()
      world.searchObjects(cat, volume, function(obj)
        local ok_name, obj_name = pcall(function() return obj:getName() end)
        if not ok_name then return true end
        if obj_name == player_unit_name then return true end

        local ok_pos, pos3 = pcall(function() return obj:getPoint() end)
        if not ok_pos or not pos3 then return true end

        local ok_lla, lla = pcall(coord.LOtoLL, pos3)
        if not ok_lla or not lla then return true end

        local c_lat = safe_num(lla.latitude  or lla.Lat  or 0)
        local c_lon = safe_num(lla.longitude or lla.Long or 0)
        local c_alt = safe_num(lla.altitude  or lla.Alt  or pos3.y or 0)
        local dist  = haversine(player_lat, player_lon, c_lat, c_lon)

        local c_hdg, c_spd = 0, 0
        local ok_vel, vel = pcall(function() return obj:getVelocity() end)
        if ok_vel and vel then
          c_spd = math.sqrt(safe_num(vel.x)^2 + safe_num(vel.y)^2 + safe_num(vel.z)^2)
          if c_spd > 1 then
            c_hdg = math.deg(math.atan2(vel.x, vel.z))
            if c_hdg < 0 then c_hdg = c_hdg + 360 end
          end
        end

        local c_coal = 0
        local ok_coal, coal = pcall(function() return obj:getCoalition() end)
        if ok_coal and coal then c_coal = coal end

        local c_type = "unknown"
        local ok_desc, desc = pcall(function() return obj:getDesc() end)
        if ok_desc and desc and desc.typeName then c_type = safe_str(desc.typeName) end

        table.insert(contacts, {
          id          = safe_str(obj_name),
          name        = safe_str(obj_name),
          type        = c_type,
          lat         = c_lat,
          lon         = c_lon,
          alt_msl_m   = c_alt,
          heading_deg = c_hdg,
          speed_ms    = c_spd,
          speed_kts   = c_spd * 1.944,
          coalition   = c_coal,
          dist_m      = dist,
        })

        return true  -- continua iterando
      end)
    end)

    log.write("IOX", log.INFO, string.format(
      "[IOX] searchObjects cat=%d ok=%s encontrados=%d err=%s",
      cat, tostring(ok_search), #contacts - count_before, tostring(err)))
  end

  log.write("IOX", log.INFO, string.format(
    "[IOX] get_contacts total=%d", #contacts))

  return contacts
end

-- ----------------------------------------------------------------
-- Loop interno — chamado dentro do pcall principal
-- ----------------------------------------------------------------
local function iox_tick(t)
  if not IOX.socket then return end

  local self_payload, sd = get_self_data(t)
  if not self_payload then return end

  local _lat = self_payload._lat
  local _lon = self_payload._lon
  local _alt = self_payload._alt
  self_payload._lat = nil
  self_payload._lon = nil
  self_payload._alt = nil

  IOX.socket:send(json_flat(self_payload))

  local unit_name = sd and safe_str(sd.UnitName) or ""
  local contacts  = get_contacts(_lat, _lon, _alt, unit_name)

  local hdr = json_flat({
    msg_type  = "contacts",
    timestamp = t,
    count     = #contacts,
  })
  local contacts_msg = hdr:sub(1, -2) .. ',"contacts":' .. json_array(contacts) .. "}"
  IOX.socket:send(contacts_msg)
end

-- ----------------------------------------------------------------
-- Loop principal 30 Hz
-- tNext É SEMPRE retornado — mesmo em caso de erro interno
-- ----------------------------------------------------------------
function LuaExportActivityNextEvent(t)
  local tNext = t + IOX.update_interval
  pcall(iox_tick, t)
  return tNext
end
