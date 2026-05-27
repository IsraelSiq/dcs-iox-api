-- =============================================================
-- dcs-iox-api | Export.lua  (DCS 2.9+)
-- Envia telemetria do jogador + contacts via UDP JSON -> 127.0.0.1:7778
--
-- INSTALAÇÃO:
--   Copie este arquivo para:
--   %USERPROFILE%\Saved Games\DCS\Scripts\Export.lua
--
--   Se já existir um Export.lua com outros scripts (Tacview, SRS, etc.),
--   NÃO substitua — apenas adicione o bloco IOX no final do arquivo existente,
--   antes do último "return" se houver.
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

-- Escapa string para JSON
local function json_str(s)
  s = tostring(s or "")
  s = s:gsub('\\', '\\\\'):gsub('"', '\\"'):gsub('\n', '\\n'):gsub('\r', '\\r')
  return '"' .. s .. '"'
end

-- Encode tabela plana (valores string/number/boolean)
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

-- Encode array de tabelas planas
local function json_array(arr)
  local items = {}
  for _, t in ipairs(arr) do
    table.insert(items, json_flat(t))
  end
  return "[" .. table.concat(items, ",") .. "]"
end

-- Haversine (metros)
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
-- Lifecycle
-- ----------------------------------------------------------------

function LuaExportStart()
  local ok, socket = pcall(require, "socket")
  if not ok then
    log.write("IOX", log.ERROR, "[dcs-iox-api] luasocket not found!")
    return
  end
  IOX.socket = socket.udp()
  IOX.socket:setsockname("*", 0)
  IOX.socket:setpeername(IOX.host, IOX.port)
  log.write("IOX", log.INFO, "[dcs-iox-api] Export started -> " .. IOX.host .. ":" .. IOX.port)
end

function LuaExportStop()
  if IOX.socket then
    IOX.socket:close()
    IOX.socket = nil
  end
  log.write("IOX", log.INFO, "[dcs-iox-api] Export stopped")
end

-- ----------------------------------------------------------------
-- Coleta dados do jogador
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

  -- Velocidade
  local speed_ms = 0
  if sd.Velocity then
    local vx = safe_num(sd.Velocity.x)
    local vy = safe_num(sd.Velocity.y)
    local vz = safe_num(sd.Velocity.z)
    speed_ms = math.sqrt(vx*vx + vy*vy + vz*vz)
  end

  -- Atitude (ADI)
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

  -- IAS / TAS / Mach / AoA / VVI
  local ias_ms, tas_ms, mach, aoa_deg, vvi_ms = 0, 0, 0, 0, 0
  local ok3, v = pcall(LoGetIndicatedAirSpeed);  if ok3 and v  then ias_ms  = safe_num(v)               end
  local ok4, v = pcall(LoGetTrueAirSpeed);       if ok4 and v  then tas_ms  = safe_num(v)               end
  local ok5, v = pcall(LoGetMachNumber);         if ok5 and v  then mach    = safe_num(v)               end
  local ok6, v = pcall(LoGetAngleOfAttack);      if ok6 and v  then aoa_deg = math.deg(safe_num(v))     end
  local ok7, v = pcall(LoGetVerticalVelocity);   if ok7 and v  then vvi_ms  = safe_num(v)               end

  -- Altitude AGL
  local alt_agl = 0
  local ok8, v = pcall(LoGetAltitudeAboveGroundLevel)
  if ok8 and v then alt_agl = safe_num(v) end

  -- Combustível
  local fuel_kg = 0
  local ok9, v = pcall(LoGetFuelInternalFuelTotal)
  if ok9 and v then fuel_kg = safe_num(v) end

  -- RPM / Engine
  -- LoGetEngineInfo retorna tabela com campos variáveis por módulo
  local rpm_1, rpm_2, throttle = 0, 0, 0
  local ok10, eng = pcall(LoGetEngineInfo)
  if ok10 and eng then
    if eng.RPM then
      -- Alguns módulos: eng.RPM.left / eng.RPM.right
      -- Outros:         eng.RPM[1]   / eng.RPM[2]
      rpm_1 = safe_num(eng.RPM.left  or eng.RPM[1] or eng.RPM or 0)
      rpm_2 = safe_num(eng.RPM.right or eng.RPM[2] or 0)
    end
    if eng.Temperature then
      -- fallback: usa temperatura como proxy de throttle se RPM indisponível
    end
    if eng.Throttle then
      throttle = safe_num(eng.Throttle.left or eng.Throttle[1] or eng.Throttle or 0)
    end
  end

  -- G-load
  local g_load = 1.0
  local ok11, g = pcall(LoGetAccelerationUnits)
  if ok11 and g then g_load = safe_num(g.y or 1.0) end

  -- Coalização do jogador
  local coalition = 2  -- blue por padrão
  local ok12, unit = pcall(function()
    return Unit.getByName(safe_str(sd.UnitName))
  end)
  if ok12 and unit then
    local ok13, c = pcall(function() return unit:getCoalition() end)
    if ok13 and c then coalition = c end
  end

  return {
    -- Meta
    msg_type    = "self",
    timestamp   = t,
    aircraft    = safe_str(sd.Name),
    -- Posição
    lat         = lat,
    lon         = lon,
    alt_msl_m   = alt,
    alt_agl_m   = alt_agl,
    -- Velocidade
    speed_ms    = speed_ms,
    ias_ms      = ias_ms,
    tas_ms      = tas_ms,
    mach        = mach,
    vvi_ms      = vvi_ms,
    -- Atitude
    heading_deg = heading,
    pitch_deg   = pitch,
    bank_deg    = bank,
    aoa_deg     = aoa_deg,
    -- Sistemas
    fuel_kg     = fuel_kg,
    rpm_1       = rpm_1,
    rpm_2       = rpm_2,
    throttle    = throttle,
    g_load      = g_load,
    coalition   = coalition,
    -- para cálculo de distância dos contacts
    _lat        = lat,
    _lon        = lon,
  }, sd
end

-- ----------------------------------------------------------------
-- Coleta contacts via world.searchObjects (DCS 2.9+)
-- ----------------------------------------------------------------
local function get_contacts(player_lat, player_lon, player_unit_name)
  local contacts = {}

  -- Categorias: 1=UNIT, 2=WEAPON, 3=STATIC, 4=BASE, 5=SCENERY
  local categories = {
    Object.Category.UNIT,
    Object.Category.STATIC,
  }

  for _, cat in ipairs(categories) do
    local ok, objects = pcall(world.searchObjects, cat, {
      id   = world.VolumeType.SPHERE,
      params = {
        point  = coord.LLtoLO(player_lat, player_lon),
        radius = IOX.radar_range_m,
      },
    })

    if ok and objects then
      for _, obj in ipairs(objects) do
        local ok2, obj_name = pcall(function() return obj:getName() end)
        if ok2 and obj_name ~= player_unit_name then

          local ok3, pos3 = pcall(function() return obj:getPoint() end)
          if ok3 and pos3 then
            local ok4, lla = pcall(coord.LOtoLL, pos3)
            if ok4 and lla then
              local c_lat = safe_num(lla.latitude  or lla.Lat or 0)
              local c_lon = safe_num(lla.longitude or lla.Long or 0)
              local c_alt = safe_num(lla.altitude  or lla.Alt or pos3.y or 0)

              local dist = haversine(player_lat, player_lon, c_lat, c_lon)

              -- Heading e speed
              local c_hdg, c_spd = 0, 0
              local ok5, vel = pcall(function() return obj:getVelocity() end)
              if ok5 and vel then
                c_spd = math.sqrt(safe_num(vel.x)^2 + safe_num(vel.y)^2 + safe_num(vel.z)^2)
                if c_spd > 1 then
                  c_hdg = math.deg(math.atan2(vel.x, vel.z))
                  if c_hdg < 0 then c_hdg = c_hdg + 360 end
                end
              end

              -- Coalização
              local c_coal = 0
              local ok6, coal = pcall(function() return obj:getCoalition() end)
              if ok6 and coal then c_coal = coal end

              -- Tipo da unidade
              local c_type = "unknown"
              local ok7, desc = pcall(function() return obj:getDesc() end)
              if ok7 and desc and desc.typeName then
                c_type = safe_str(desc.typeName)
              end

              table.insert(contacts, {
                id          = tostring(ok2 and obj_name or dist),
                name        = safe_str(ok2 and obj_name or ""),
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
            end
          end
        end
      end
    end
  end

  return contacts
end

-- ----------------------------------------------------------------
-- Loop principal (30 Hz)
-- ----------------------------------------------------------------
function LuaExportActivityNextEvent(t)
  local tNext = t + IOX.update_interval
  if not IOX.socket then return tNext end

  -- 1. Player
  local self_payload, sd = get_self_data(t)
  if not self_payload then return tNext end

  -- Remove campos internos antes de enviar
  local _lat = self_payload._lat
  local _lon = self_payload._lon
  self_payload._lat = nil
  self_payload._lon = nil

  pcall(function() IOX.socket:send(json_flat(self_payload)) end)

  -- 2. Contacts (a cada frame, mesmo intervalo)
  local unit_name = sd and safe_str(sd.UnitName) or ""
  local contacts  = get_contacts(_lat, _lon, unit_name)

  -- Monta contacts packet: JSON flat + array manual
  local hdr = json_flat({
    msg_type  = "contacts",
    timestamp = t,
    count     = #contacts,
  })
  -- Injeta array no JSON (remove "}" final e adiciona campo)
  local contacts_msg = hdr:sub(1, -2) .. ',"contacts":' .. json_array(contacts) .. "}"

  pcall(function() IOX.socket:send(contacts_msg) end)

  return tNext
end
