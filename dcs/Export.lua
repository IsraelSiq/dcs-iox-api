-- =============================================================
-- dcs-iox-api | Export.lua
-- DCS World -> UDP socket bridge
-- Sends aircraft telemetry as JSON to localhost:7778
-- Install path: %USERPROFILE%\Saved Games\DCS\Scripts\Export.lua
-- =============================================================

local IOX = {}
IOX.host = "127.0.0.1"
IOX.port = 7778
IOX.socket = nil
IOX.update_interval = 0.033  -- ~30Hz (seconds)
IOX.last_update = 0

-- ----------------------------------------------------------------
-- Helpers
-- ----------------------------------------------------------------

local function safe_number(v)
  if type(v) == "number" then return v else return 0 end
end

local function json_encode(t)
  local parts = {}
  for k, v in pairs(t) do
    local val
    if type(v) == "number"  then val = string.format("%.6f", v)
    elseif type(v) == "boolean" then val = tostring(v)
    elseif type(v) == "string"  then val = '"' .. v .. '"'
    else val = '""'
    end
    table.insert(parts, '"' .. k .. '":' .. val)
  end
  return "{" .. table.concat(parts, ",") .. "}"
end

-- ----------------------------------------------------------------
-- Lifecycle callbacks
-- ----------------------------------------------------------------

function LuaExportStart()
  local lfs   = require("lfs")
  local socket = require("socket")

  IOX.socket = socket.udp()
  IOX.socket:setsockname("*", 0)
  IOX.socket:setpeername(IOX.host, IOX.port)
  log.write("IOX", log.INFO, "[dcs-iox-api] Export started, streaming to " .. IOX.host .. ":" .. IOX.port)
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

  -- Only send if socket is open
  if not IOX.socket then
    return tNext
  end

  local ok, self_data = pcall(LoGetSelfData)
  if not ok or not self_data then
    return tNext
  end

  -- ---- Position ----
  local lat, lon, alt = 0, 0, 0
  if self_data.LatLongAlt then
    lat = safe_number(self_data.LatLongAlt.Lat)
    lon = safe_number(self_data.LatLongAlt.Long)
    alt = safe_number(self_data.LatLongAlt.Alt)  -- meters MSL
  end

  -- ---- Velocity ----
  local vx, vy, vz = 0, 0, 0
  local speed_ms = 0
  if self_data.Velocity then
    vx = safe_number(self_data.Velocity.x)
    vy = safe_number(self_data.Velocity.y)
    vz = safe_number(self_data.Velocity.z)
    speed_ms = math.sqrt(vx*vx + vy*vy + vz*vz)
  end

  -- ---- Attitude ----
  local heading, pitch, bank = 0, 0, 0
  local ok2, angles = pcall(LoGetMCPState)  -- fallback
  local ok3, att = pcall(LoGetAccelerationUnits)

  -- Heading from self_data
  if self_data.Heading then
    heading = math.deg(safe_number(self_data.Heading))
    if heading < 0 then heading = heading + 360 end
  end

  -- Pitch and bank from LoGetADIPitchBankHeading
  local ok4, pbh = pcall(LoGetADIPitchBankHeading)
  if ok4 and pbh then
    pitch   = math.deg(safe_number(pbh.Pitch))
    bank    = math.deg(safe_number(pbh.Bank))
    heading = math.deg(safe_number(pbh.Heading))
    if heading < 0 then heading = heading + 360 end
  end

  -- ---- Engine / Fuel ----
  local fuel_internal = 0
  local ok5, fuel_data = pcall(LoGetFuelInternalFuelTotal)
  if ok5 and fuel_data then
    fuel_internal = safe_number(fuel_data)
  end

  -- ---- Throttle ----
  local throttle_1, throttle_2 = 0, 0
  local ok6, engine_data = pcall(LoGetEngineInfo)
  if ok6 and engine_data then
    if engine_data.RPM then
      throttle_1 = safe_number(engine_data.RPM.left  or engine_data.RPM[1] or 0)
      throttle_2 = safe_number(engine_data.RPM.right or engine_data.RPM[2] or 0)
    end
  end

  -- ---- Indicator speeds ----
  local ias_ms, tas_ms, mach, aoa, vvi = 0, 0, 0, 0, 0
  local ok7, ind = pcall(LoGetIndicatedAirSpeed)
  if ok7 then ias_ms = safe_number(ind) end

  local ok8, tas_d = pcall(LoGetTrueAirSpeed)
  if ok8 then tas_ms = safe_number(tas_d) end

  local ok9, mach_d = pcall(LoGetMachNumber)
  if ok9 then mach = safe_number(mach_d) end

  local ok10, aoa_d = pcall(LoGetAngleOfAttack)
  if ok10 then aoa = math.deg(safe_number(aoa_d)) end

  local ok11, vvi_d = pcall(LoGetVerticalVelocity)
  if ok11 then vvi = safe_number(vvi_d) end

  -- ---- Altitude AGL ----
  local alt_agl = 0
  local ok12, agl_d = pcall(LoGetAltitudeAboveGroundLevel)
  if ok12 then alt_agl = safe_number(agl_d) end

  -- ---- Aircraft type ----
  local aircraft_type = self_data.Name or "unknown"

  -- ---- Build payload ----
  local payload = {
    timestamp      = t,
    aircraft       = aircraft_type,
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
  }

  local json_str = json_encode(payload)

  local ok_send, err = pcall(function()
    IOX.socket:send(json_str)
  end)

  if not ok_send then
    log.write("IOX", log.WARNING, "[dcs-iox-api] Send error: " .. tostring(err))
  end

  return tNext
end
