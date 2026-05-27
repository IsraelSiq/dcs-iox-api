-- =============================================================
-- dcs-iox-api | MissionScript.lua  (DCS 2.9+)
--
-- Roda DENTRO da miss\195\163o via trigger "DO SCRIPT FILE".
-- Envia contacts via UDP para o servidor Python na porta 7779.
--
-- INSTALA\195\135\195\131O:
--   1. No Mission Editor, crie um trigger:
--        Type      : ONCE
--        Condition : TIME MORE (1)
--        Action    : DO SCRIPT FILE -> selecione este arquivo
--   2. Salve a miss\195\163o.
-- =============================================================

local IOXM = {}
IOXM.update_interval = 1.0
IOXM.radar_range_m   = 150000
IOXM.host            = "127.0.0.1"
IOXM.port            = 7779

-- Carrega luasocket (dispon\195\173vel no DCS Mission environment)
local socket = require("socket")
local udp    = socket.udp()
udp:settimeout(0)

env.info(string.format("[IOX-Mission] Inicializando UDP -> %s:%d", IOXM.host, IOXM.port))

-- ----------------------------------------------------------------
-- Helpers JSON m\195\173nimos
-- ----------------------------------------------------------------
local function safe_num(v)
  if type(v) == "number" and v == v then return v else return 0 end
end

local function safe_str(v)
  if type(v) == "string" then return v else return "" end
end

local function json_escape(s)
  s = tostring(s or "")
  return s:gsub('\\','\\\\'):gsub('"','\\"'):gsub('\n','\\n'):gsub('\r','\\r')
end

local function json_str(s)  return '"' .. json_escape(s) .. '"' end

local function json_flat(t)
  local parts = {}
  for k, v in pairs(t) do
    local tp = type(v)
    local val
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
  for _, item in ipairs(arr) do
    table.insert(items, json_flat(item))
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
  return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
end

-- ----------------------------------------------------------------
-- Descobre a unidade do jogador
-- ----------------------------------------------------------------
local function get_player_unit()
  for _, coal in ipairs({coalition.side.RED, coalition.side.BLUE, coalition.side.NEUTRAL}) do
    for _, grp in ipairs(coalition.getGroups(coal) or {}) do
      for _, unit in ipairs(grp:getUnits() or {}) do
        if unit:isActive() and unit:isExist() and unit:getPlayerName() ~= nil then
          return unit
        end
      end
    end
  end
  return nil
end

-- ----------------------------------------------------------------
-- Coleta contacts usando world.searchObjects
-- ----------------------------------------------------------------
local function collect_contacts(player_unit)
  local contacts  = {}
  local pname     = player_unit:getName()
  local center_pt = player_unit:getPoint()
  local plla      = coord.LOtoLL(center_pt)
  local p_lat     = safe_num(plla.latitude)
  local p_lon     = safe_num(plla.longitude)

  local volume = {
    id     = world.VolumeType.SPHERE,
    params = { point = center_pt, radius = IOXM.radar_range_m },
  }

  for _, cat in ipairs({ Object.Category.UNIT, Object.Category.STATIC }) do
    world.searchObjects(cat, volume, function(obj)
      local ok_n, oname = pcall(function() return obj:getName() end)
      if not ok_n or oname == pname then return true end

      local ok_p, pos3 = pcall(function() return obj:getPoint() end)
      if not ok_p or not pos3 then return true end

      local ok_l, lla = pcall(coord.LOtoLL, pos3)
      if not ok_l or not lla then return true end

      local c_lat = safe_num(lla.latitude)
      local c_lon = safe_num(lla.longitude)
      local c_alt = safe_num(lla.altitude or pos3.y or 0)
      local dist  = haversine(p_lat, p_lon, c_lat, c_lon)

      local c_hdg, c_spd = 0, 0
      local ok_v, vel = pcall(function() return obj:getVelocity() end)
      if ok_v and vel then
        c_spd = math.sqrt(safe_num(vel.x)^2 + safe_num(vel.y)^2 + safe_num(vel.z)^2)
        if c_spd > 1 then
          c_hdg = math.deg(math.atan2(vel.x, vel.z))
          if c_hdg < 0 then c_hdg = c_hdg + 360 end
        end
      end

      local c_coal = 0
      local ok_c, cv = pcall(function() return obj:getCoalition() end)
      if ok_c and cv then c_coal = cv end

      local c_type = "unknown"
      local ok_d, desc = pcall(function() return obj:getDesc() end)
      if ok_d and desc and desc.typeName then c_type = safe_str(desc.typeName) end

      local c_cat = (cat == Object.Category.STATIC) and "static" or "unit"

      table.insert(contacts, {
        id          = safe_str(oname),
        name        = safe_str(oname),
        type        = c_type,
        category    = c_cat,
        lat         = c_lat,
        lon         = c_lon,
        alt_msl_m   = c_alt,
        heading_deg = c_hdg,
        speed_ms    = c_spd,
        speed_kts   = c_spd * 1.944,
        coalition   = c_coal,
        dist_m      = dist,
      })
      return true
    end)
  end

  return contacts, p_lat, p_lon
end

-- ----------------------------------------------------------------
-- Envia payload UDP (fragmenta se > 8kb)
-- ----------------------------------------------------------------
local MAX_UDP = 8000

local function udp_send(payload)
  if #payload <= MAX_UDP then
    udp:sendto(payload, IOXM.host, IOXM.port)
    return
  end
  -- payload grande: envia s\195\179 os primeiros MAX_UDP bytes com contacts truncados
  -- (raro em pr\195\161tica; 150km raramente tem > 100 unidades)
  env.info("[IOX-Mission] payload grande (" .. #payload .. "b), truncando")
  udp:sendto(payload:sub(1, MAX_UDP), IOXM.host, IOXM.port)
end

-- ----------------------------------------------------------------
-- Tick: coleta contacts e envia via UDP
-- ----------------------------------------------------------------
local function ioxm_tick()
  local player = get_player_unit()
  if not player then
    env.info("[IOX-Mission] aguardando player...")
    return
  end

  local ok, contacts = pcall(collect_contacts, player)
  if not ok then
    env.info("[IOX-Mission] erro collect_contacts: " .. tostring(contacts))
    return
  end

  local t       = timer.getTime()
  local payload = string.format(
    '{"timestamp":%.3f,"contacts":%s}',
    t, json_array(contacts)
  )

  udp_send(payload)
  env.info(string.format("[IOX-Mission] %d contact(s) -> UDP %s:%d", #contacts, IOXM.host, IOXM.port))
end

-- ----------------------------------------------------------------
-- Scheduler
-- ----------------------------------------------------------------
local function schedule_tick(_, time)
  local ok, err = pcall(ioxm_tick)
  if not ok then env.info("[IOX-Mission] tick error: " .. tostring(err)) end
  return time + IOXM.update_interval
end

timer.scheduleFunction(schedule_tick, nil, timer.getTime() + 1)
env.info("[IOX-Mission] Scheduler iniciado. Contacts a cada " .. IOXM.update_interval .. "s via UDP")
