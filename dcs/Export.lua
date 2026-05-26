-- =============================================================
-- dcs-iox-api | Export.lua
-- DCS World -> UDP socket bridge
-- Sends player telemetry + world contacts as JSON to localhost:7778
-- Install path: %USERPROFILE%\Saved Games\DCS\Scripts\Export.lua
-- =============================================================

local IOX = {}
IOX.host            = "127.0.0.1"
IOX.port            = 7778
IOX.socket          = nil
IOX.update_interval = 0.033  -- ~30Hz
IOX.radar_range_m   = 100000 -- 100 km

-- ----------------------------------------------------------------
-- Helpers
-- ----------------------------------------------------------------

local function safe_number(v)
  if type(v) == "number" then return v else return 0 end
end

-- Minimal JSON encoder for flat tables (string/number/boolean values)
local function json_encode(t)
  local parts = {}
  for k, v in pairs(t) do
    local val
    if     type(v) == "number"  then val = string.format("%.6f", v)
    elseif type(v) == "boolean" then val = tostring(v)
    elseif type(v) == "string"  then
      -- escape quotes and backslashes
      val = '"' .. v:gsub('\\', '\\\\'):gsub('"', '\\"') .. '"'
    else val = '""'
    end
    table.insert(parts, '"' .. tostring(k) .. '":' .. val)
  end
  return "{" .. table.concat(parts, ",") .. "}"
end

-- Encode an array of flat tables as a JSON array
local function json_encode_array(arr)
  local items = {}
  for _, t in ipairs(arr) do
    table.insert(items, json_encode(t))
  end
  return "[" .. table.concat(items, ",") .. "]"
end

-- Haversine distance in metres between two lat/lon points
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
-- Lifecycle callbacks
-- ----------------------------------------------------------------

function LuaExportStart()
  local socket = require("socket")
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

function LuaExportActivityNextEvent(t)
  local tNext = t + IOX.update_interval
  if not IOX.socket then return tNext end

  -- ================================================================
  -- 1. PLAYER (self) data
  -- ================================================================
  local ok, self_data = pcall(LoGetSelfData)
  if not ok or not self_data then return tNext end

  local lat, lon, alt = 0, 0, 0
  if self_data.LatLongAlt then
    lat = safe_number(self_data.LatLongAlt.Lat)
    lon = safe_number(self_data.LatLongAlt.Long)
    alt = safe_number(self_data.LatLongAlt.Alt)
  end

  local vx, vy, vz = 0, 0, 0
  local speed_ms = 0
  if self_data.Velocity then
    vx = safe_number(self_data.Velocity.x)
    vy = safe_number(self_data.Velocity.y)
    vz = safe_number(self_data.Velocity.z)
    speed_ms = math.sqrt(vx*vx + vy*vy + vz*vz)
  end

  local heading, pitch, bank = 0, 0, 0
  if self_data.Heading then
    heading = math.deg(safe_number(self_data.Heading))
    if heading < 0 then heading = heading + 360 end
  end

  local ok4, pbh = pcall(LoGetADIPitchBankHeading)
  if ok4 and pbh then
    pitch   = math.deg(safe_number(pbh.Pitch))
    bank    = math.deg(safe_number(pbh.Bank))
    heading = math.deg(safe_number(pbh.Heading))
    if heading < 0 then heading = heading + 360 end
  end

  local fuel_internal = 0
  local ok5, fuel_data = pcall(LoGetFuelInternalFuelTotal)
  if ok5 and fuel_data then fuel_internal = safe_number(fuel_data) end

  local throttle_1, throttle_2 = 0, 0
  local ok6, engine_data = pcall(LoGetEngineInfo)
  if ok6 and engine_data and engine_data.RPM then
    throttle_1 = safe_number(engine_data.RPM.left  or engine_data.RPM[1] or 0)
    throttle_2 = safe_number(engine_data.RPM.right or engine_data.RPM[2] or 0)
  end

  local ias_ms, tas_ms, mach, aoa, vvi = 0, 0, 0, 0, 0
  local ok7,  ind  = pcall(LoGetIndicatedAirSpeed);  if ok7  then ias_ms = safe_number(ind)  end
  local ok8,  tas  = pcall(LoGetTrueAirSpeed);       if ok8  then tas_ms = safe_number(tas)  end
  local ok9,  mac  = pcall(LoGetMachNumber);         if ok9  then mach   = safe_number(mac)  end
  local ok10, aoar = pcall(LoGetAngleOfAttack);      if ok10 then aoa    = math.deg(safe_number(aoar)) end
  local ok11, vvir = pcall(LoGetVerticalVelocity);   if ok11 then vvi    = safe_number(vvir) end

  local alt_agl = 0
  local ok12, agl = pcall(LoGetAltitudeAboveGroundLevel)
  if ok12 then alt_agl = safe_number(agl) end

  -- Player coalition (0=neutral, 1=red, 2=blue)
  local player_coalition = 2  -- assume blue
  local ok_unit, player_unit = pcall(function()
    return Unit.getByName(self_data.UnitName or "")
  end)
  if ok_unit and player_unit then
    local ok_coal, coal = pcall(function() return player_unit:getCoalition() end)
    if ok_coal then player_coalition = coal end
  end

  local self_payload = {
    msg_type       = "self",
    timestamp      = t,
    aircraft       = self_data.Name or "unknown",
    lat            = lat,
    lon            = lon,
    alt_msl_m      = alt,
    alt_agl_m      = alt_agl,
    speed_ms       = speed_ms,
    ias_ms         = ias_ms,
    tas_ms         = tas_ms,
    mach           = mach,
    aoa_deg        = aoa,
    vvi_ms         = vvi,
    heading_deg    = heading,
    pitch_deg      = pitch,
    bank_deg       = bank,
    fuel_kg        = fuel_internal,
    rpm_1          = throttle_1,
    rpm_2          = throttle_2,
    coalition      = player_coalition,
  }

  pcall(function() IOX.socket:send(json_encode(self_payload)) end)

  -- ================================================================
  -- 2. CONTACTS — world objects within radar range
  -- ================================================================
  local ok_w, world_objects = pcall(LoGetWorldObjects)
  if not ok_w or not world_objects then return tNext end

  local contacts = {}
  for id, obj in pairs(world_objects) do
    -- Skip player's own unit
    if obj.UnitName ~= self_data.UnitName then

      local c_lat, c_lon, c_alt = 0, 0, 0
      if obj.LatLongAlt then
        c_lat = safe_number(obj.LatLongAlt.Lat)
        c_lon = safe_number(obj.LatLongAlt.Long)
        c_alt = safe_number(obj.LatLongAlt.Alt)
      end

      -- Range check
      local dist = haversine(lat, lon, c_lat, c_lon)
      if dist <= IOX.radar_range_m then

        local c_hdg   = 0
        local c_speed = 0
        if obj.Heading then
          c_hdg = math.deg(safe_number(obj.Heading))
          if c_hdg < 0 then c_hdg = c_hdg + 360 end
        end
        if obj.Velocity then
          local cvx = safe_number(obj.Velocity.x)
          local cvy = safe_number(obj.Velocity.y)
          local cvz = safe_number(obj.Velocity.z)
          c_speed = math.sqrt(cvx*cvx + cvy*cvy + cvz*cvz)
        end

        -- Coalition: 1=red, 2=blue, 0=neutral
        local c_coal = safe_number(obj.CoalitionID or obj.coalition or 0)

        table.insert(contacts, {
          id         = tostring(id),
          name       = obj.UnitName  or "",
          type       = obj.Name      or "unknown",
          lat        = c_lat,
          lon        = c_lon,
          alt_msl_m  = c_alt,
          heading_deg= c_hdg,
          speed_ms   = c_speed,
          coalition  = c_coal,
          dist_m     = dist,
        })
      end
    end
  end

  -- Send contacts packet
  local contacts_payload = json_encode({
    msg_type  = "contacts",
    timestamp = t,
    count     = #contacts,
  })
  -- Append contacts array manually (our encoder only does flat tables)
  contacts_payload = contacts_payload:sub(1, -2)
    .. ',"contacts":' .. json_encode_array(contacts) .. "}"

  pcall(function() IOX.socket:send(contacts_payload) end)

  return tNext
end
