-- =============================================================
-- dcs-iox-api | MissionScript.lua  (DCS 2.9+)
--
-- Roda DENTRO da missao via trigger "DO SCRIPT FILE".
-- Envia contacts via UDP para o servidor Python na porta 7779.
--
-- Dois modos de coleta por contato:
--   source="search"  -> world.searchObjects (visao onisciente)
--   source="awacs"   -> coalition.getDetectedTargets (o que o AWACS ve)
--   source="both"    -> detectado pelos dois
--
-- INSTALACAO:
--   1. No Mission Editor, crie um trigger:
--        Type      : ONCE
--        Condition : TIME MORE (1)
--        Action    : DO SCRIPT FILE -> selecione este arquivo
--   2. Salve a missao.
-- =============================================================

local IOXM = {}
IOXM.update_interval  = 1.0
IOXM.radar_range_m    = 150000
IOXM.host             = "127.0.0.1"
IOXM.port             = 7779

-- Coalicao do jogador (ajuste se voce joga pelo RED)
-- coalition.side.BLUE = 2 | coalition.side.RED = 1
IOXM.player_coalition = coalition.side.BLUE

-- Carrega luasocket
local socket = require("socket")
local udp    = socket.udp()
udp:settimeout(0)

env.info(string.format("[IOX-Mission] Inicializando UDP -> %s:%d", IOXM.host, IOXM.port))

-- ----------------------------------------------------------------
-- Helpers JSON minimos
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

local function json_str(s) return '"' .. json_escape(s) .. '"' end

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
  for _, item in ipairs(arr) do table.insert(items, json_flat(item)) end
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
-- Helper: extrai dados de posicao/movimento de qualquer objeto
-- ----------------------------------------------------------------
local function extract_contact_data(obj, pname, p_lat, p_lon, source)
  local ok_n, oname = pcall(function() return obj:getName() end)
  if not ok_n or oname == pname then return nil end

  local ok_p, pos3 = pcall(function() return obj:getPoint() end)
  if not ok_p or not pos3 then return nil end

  local ok_l, lla = pcall(coord.LOtoLL, pos3)
  if not ok_l or not lla then return nil end

  local c_lat = safe_num(lla.latitude)
  local c_lon = safe_num(lla.longitude)
  local c_alt = safe_num(lla.altitude or pos3.y or 0)
  local dist  = haversine(p_lat, p_lon, c_lat, c_lon)

  if dist > IOXM.radar_range_m then return nil end

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

  return {
    id               = safe_str(oname),
    name             = safe_str(oname),
    type             = c_type,
    source           = source,
    lat              = c_lat,
    lon              = c_lon,
    alt_msl_m        = c_alt,
    heading_deg      = c_hdg,
    speed_ms         = c_spd,
    speed_kts        = c_spd * 1.944,
    coalition        = c_coal,
    dist_m           = dist,
    awacs_visible    = false,
    awacs_type_known = false,
  }
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
-- Fonte 1: world.searchObjects (visao onisciente)
-- ----------------------------------------------------------------
local function collect_search(player_unit, p_lat, p_lon)
  local contacts  = {}
  local pname     = player_unit:getName()
  local center_pt = player_unit:getPoint()

  local volume = {
    id     = world.VolumeType.SPHERE,
    params = { point = center_pt, radius = IOXM.radar_range_m },
  }

  for _, cat in ipairs({ Object.Category.UNIT, Object.Category.STATIC }) do
    world.searchObjects(cat, volume, function(obj)
      local c = extract_contact_data(obj, pname, p_lat, p_lon, "search")
      if c then table.insert(contacts, c) end
      return true
    end)
  end

  return contacts
end

-- ----------------------------------------------------------------
-- Fonte 2: coalition.getDetectedTargets (visao AWACS/sensores)
-- ----------------------------------------------------------------
local DETECTION_TYPES = {
  Controller.Detection.RADAR,
  Controller.Detection.OPTIC,
  Controller.Detection.IRST,
  Controller.Detection.RWR,
  Controller.Detection.DLINK,
}

local function collect_awacs(player_unit, p_lat, p_lon)
  local contacts = {}
  local pname    = player_unit:getName()

  local ok_det, detected = pcall(
    coalition.getDetectedTargets,
    IOXM.player_coalition,
    DETECTION_TYPES
  )

  if not ok_det or not detected then
    env.info("[IOX-Mission] AWACS: getDetectedTargets falhou")
    return contacts
  end

  for _, det in ipairs(detected) do
    local obj = det.object
    if obj and obj:isExist() then
      local c = extract_contact_data(obj, pname, p_lat, p_lon, "awacs")
      if c then
        c.awacs_visible    = det.visible or false
        c.awacs_type_known = det.type    or false
        table.insert(contacts, c)
      end
    end
  end

  return contacts
end

-- ----------------------------------------------------------------
-- Merge: combina search + awacs sem duplicar por ID
-- Se mesmo ID aparece nos dois -> source="both"
-- ----------------------------------------------------------------
local function merge_contacts(search_list, awacs_list)
  local merged = {}
  local seen   = {}

  for _, c in ipairs(search_list) do
    merged[c.id] = c
    seen[c.id]   = true
  end

  for _, c in ipairs(awacs_list) do
    if seen[c.id] then
      merged[c.id].source           = "both"
      merged[c.id].awacs_visible    = c.awacs_visible
      merged[c.id].awacs_type_known = c.awacs_type_known
    else
      merged[c.id] = c
      seen[c.id]   = true
    end
  end

  local result = {}
  for _, c in pairs(merged) do table.insert(result, c) end
  return result
end

-- ----------------------------------------------------------------
-- Envia payload UDP
-- ----------------------------------------------------------------
local MAX_UDP = 8000

local function udp_send(payload)
  if #payload <= MAX_UDP then
    udp:sendto(payload, IOXM.host, IOXM.port)
    return
  end
  env.info("[IOX-Mission] payload grande (" .. #payload .. "b), truncando")
  udp:sendto(payload:sub(1, MAX_UDP), IOXM.host, IOXM.port)
end

-- ----------------------------------------------------------------
-- Tick principal
-- ----------------------------------------------------------------
local function ioxm_tick()
  local player = get_player_unit()
  if not player then
    env.info("[IOX-Mission] aguardando player...")
    return
  end

  local center_pt = player:getPoint()
  local plla      = coord.LOtoLL(center_pt)
  local p_lat     = safe_num(plla.latitude)
  local p_lon     = safe_num(plla.longitude)

  local ok1, search_contacts = pcall(collect_search, player, p_lat, p_lon)
  if not ok1 then
    env.info("[IOX-Mission] erro collect_search: " .. tostring(search_contacts))
    search_contacts = {}
  end

  local ok2, awacs_contacts = pcall(collect_awacs, player, p_lat, p_lon)
  if not ok2 then
    env.info("[IOX-Mission] erro collect_awacs: " .. tostring(awacs_contacts))
    awacs_contacts = {}
  end

  local contacts = merge_contacts(search_contacts, awacs_contacts)

  local t       = timer.getTime()
  local payload = string.format(
    '{"timestamp":%.3f,"contacts":%s}',
    t, json_array(contacts)
  )

  udp_send(payload)
  env.info(string.format(
    "[IOX-Mission] %d contacts (search=%d awacs=%d) -> UDP %s:%d",
    #contacts, #search_contacts, #awacs_contacts, IOXM.host, IOXM.port
  ))
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
env.info("[IOX-Mission] Scheduler iniciado (search+awacs) a cada " .. IOXM.update_interval .. "s")
