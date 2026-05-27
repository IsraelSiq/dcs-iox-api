-- =============================================================
-- dcs-iox-api | MissionScript.lua  (DCS 2.9+)
--
-- Roda DENTRO da missão via trigger "DO SCRIPT FILE".
-- Tem acesso completo a world.searchObjects, Unit, coalition, etc.
-- Envia contacts JSON via UDP -> 127.0.0.1:7779
--
-- INSTALAÇÃO:
--   1. No Mission Editor, crie um trigger:
--        Condition : TIME MORE (1)   (dispara 1 segundo após a missão iniciar)
--        Action    : DO SCRIPT FILE  -> selecione este arquivo
--   2. Salve a missão. Toda vez que entrar nela o script inicia automaticamente.
-- =============================================================

local IOXM = {}
IOXM.host            = "127.0.0.1"
IOXM.port            = 7779            -- porta separada da telemetria do jogador (7778)
IOXM.update_interval = 1.0             -- contacts a 1 Hz (suficiente, menos carga)
IOXM.radar_range_m   = 150000          -- 150 km
IOXM.socket          = nil

-- ----------------------------------------------------------------
-- Helpers JSON mínimos (sem dependência externa)
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
-- Inicializa socket
-- ----------------------------------------------------------------
local function init_socket()
  local ok, sock_lib = pcall(require, "socket")
  if not ok or not sock_lib then
    env.info("[IOX-Mission] luasocket não encontrado: " .. tostring(sock_lib))
    return false
  end
  local ok2, udp = pcall(function() return sock_lib.udp() end)
  if not ok2 or not udp then
    env.info("[IOX-Mission] Falha ao criar UDP socket: " .. tostring(udp))
    return false
  end
  udp:setsockname("*", 0)
  udp:setpeername(IOXM.host, IOXM.port)
  IOXM.socket = udp
  env.info("[IOX-Mission] Socket OK -> " .. IOXM.host .. ":" .. IOXM.port)
  return true
end

-- ----------------------------------------------------------------
-- Descobre o jogador local (slot 1, coalition qualquer)
-- ----------------------------------------------------------------
local function get_player_unit()
  -- Tenta pelo nome genérico que o DCS atribui ao slot
  local slot_names = { "Pilot", "pilot", "Player", "player" }
  for _, name in ipairs(slot_names) do
    local u = Unit.getByName(name)
    if u and u:isExist() then return u end
  end
  -- Fallback: varre todos os grupos de todas as coalitions
  for _, coal in ipairs({coalition.side.RED, coalition.side.BLUE, coalition.side.NEUTRAL}) do
    for _, group in ipairs(coalition.getGroups(coal, Group.Category.AIRPLANE) or {}) do
      for _, unit in ipairs(group:getUnits() or {}) do
        if unit:isActive() and unit:isExist() then
          -- pega o primeiro ativo como aproximação
          return unit
        end
      end
    end
  end
  return nil
end

-- ----------------------------------------------------------------
-- Coleta contacts ao redor do jogador
-- ----------------------------------------------------------------
local function collect_contacts(player_unit)
  local contacts = {}
  local player_name = player_unit:getName()
  local center_pt   = player_unit:getPoint()

  local lla_player  = coord.LOtoLL(center_pt)
  local p_lat = safe_num(lla_player.latitude)
  local p_lon = safe_num(lla_player.longitude)

  local volume = {
    id     = world.VolumeType.SPHERE,
    params = { point = center_pt, radius = IOXM.radar_range_m },
  }

  local categories = { Object.Category.UNIT, Object.Category.STATIC }

  for _, cat in ipairs(categories) do
    world.searchObjects(cat, volume, function(obj)
      local ok_name, obj_name = pcall(function() return obj:getName() end)
      if not ok_name then return true end
      if obj_name == player_name then return true end  -- ignora o próprio jogador

      local ok_pos, pos3 = pcall(function() return obj:getPoint() end)
      if not ok_pos or not pos3 then return true end

      local ok_lla, lla = pcall(coord.LOtoLL, pos3)
      if not ok_lla or not lla then return true end

      local c_lat = safe_num(lla.latitude)
      local c_lon = safe_num(lla.longitude)
      local c_alt = safe_num(lla.altitude or pos3.y or 0)
      local dist  = haversine(p_lat, p_lon, c_lat, c_lon)

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
      local ok_coal, coal_val = pcall(function() return obj:getCoalition() end)
      if ok_coal and coal_val then c_coal = coal_val end

      local c_type = "unknown"
      local ok_desc, desc = pcall(function() return obj:getDesc() end)
      if ok_desc and desc and desc.typeName then c_type = safe_str(desc.typeName) end

      local c_cat = "unit"
      if cat == Object.Category.STATIC then c_cat = "static" end

      table.insert(contacts, {
        id          = safe_str(obj_name),
        name        = safe_str(obj_name),
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

  env.info(string.format("[IOX-Mission] contacts coletados: %d", #contacts))
  return contacts, p_lat, p_lon
end

-- ----------------------------------------------------------------
-- Tick principal
-- ----------------------------------------------------------------
local function ioxm_tick()
  if not IOXM.socket then return end

  local player = get_player_unit()
  if not player then
    env.info("[IOX-Mission] nenhum player encontrado, aguardando...")
    return
  end

  local ok_contacts, contacts, p_lat, p_lon = pcall(collect_contacts, player)
  if not ok_contacts then
    env.info("[IOX-Mission] erro em collect_contacts: " .. tostring(contacts))
    return
  end

  local t = timer.getTime()
  local hdr = json_flat({
    msg_type  = "contacts",
    timestamp = t,
    count     = #contacts,
  })
  local msg = hdr:sub(1, -2) .. ',"contacts":' .. json_array(contacts) .. "}"

  local ok_send, err = pcall(function() IOXM.socket:send(msg) end)
  if not ok_send then
    env.info("[IOX-Mission] erro ao enviar UDP: " .. tostring(err))
  end
end

-- ----------------------------------------------------------------
-- Scheduler via timer.scheduleFunction
-- ----------------------------------------------------------------
local function schedule_tick(_, time)
  local ok, err = pcall(ioxm_tick)
  if not ok then
    env.info("[IOX-Mission] tick error: " .. tostring(err))
  end
  return time + IOXM.update_interval
end

-- ----------------------------------------------------------------
-- Entry point — chamado quando o trigger DO SCRIPT FILE dispara
-- ----------------------------------------------------------------
env.info("[IOX-Mission] Inicializando...")
if init_socket() then
  timer.scheduleFunction(schedule_tick, nil, timer.getTime() + 1)
  env.info("[IOX-Mission] Scheduler iniciado. Contacts a cada " .. IOXM.update_interval .. "s")
else
  env.info("[IOX-Mission] FALHA na inicialização — contacts não serão enviados")
end
