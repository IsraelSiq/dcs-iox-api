# tests/mock_dcs.py
# Simula o Export.lua enviando frames UDP a 30Hz
# Inclui o jogador + 8 contacts com coalizões, altitudes, velocidades e rumos distintos
# Uso: python tests/mock_dcs.py
import asyncio
import json
import math
import time
import socket
import os

UDP_HOST = os.getenv("UDP_HOST", "127.0.0.1")
UDP_PORT = int(os.getenv("UDP_PORT", "7778"))

PLAYER_LAT = 41.0
PLAYER_LON = 29.0

# (id, aircraft_type, coalition, offset_lat_km, offset_lon_km, alt_m, speed_ms, heading_deg, orbit_radius_km, orbit_speed_deg_s)
CONTACTS_DEF = [
    # --- ALIADOS (blue) ---
    ("HAWK-1",  "F-16C_50",  "blue",    20,   15,  5000, 210, 45,  8,  4.0),
    ("HAWK-2",  "F-16C_50",  "blue",    22,   17,  5200, 205, 50,  8,  4.0),
    ("AWACS-1", "E-3A",      "blue",    40,   -5, 10000, 160, 270, 15, 1.5),
    # --- INIMIGOS (red) ---
    ("RED-1",   "MiG-29S",   "red",    -25,   30,  7500, 280, 190, 12, 3.0),
    ("RED-2",   "MiG-29S",   "red",    -28,   35,  8000, 275, 200, 12, 3.0),
    ("SU-27-1", "Su-27",     "red",    -60,   20, 12000, 320, 160,  5, 2.0),
    # --- NEUTROS / desconhecidos ---
    ("CIV-1",   "IL-76MD",   "neutral", 50,   50,  9000, 230, 95,  30, 0.8),
    ("UNK-1",   "Unknown",   "neutral",-15,  -20,  4000, 190, 310, 10, 2.5),
]

KM_PER_DEG_LAT = 111.0

def km_to_deg_lat(km):
    return km / KM_PER_DEG_LAT

def km_to_deg_lon(km, lat):
    return km / (KM_PER_DEG_LAT * math.cos(math.radians(lat)))


def build_frame(t: float) -> dict:
    heading = (t * 5) % 360
    rad = math.radians(heading)
    return {
        "aircraft": "F-16C_50",
        "timestamp": t,
        "lat": PLAYER_LAT + math.sin(rad) * 0.05,
        "lon": PLAYER_LON + math.cos(rad) * 0.05,
        "alt_msl_m": 4572.0 + math.sin(t * 0.5) * 100,
        "alt_agl_m": 4450.0 + math.sin(t * 0.5) * 100,
        "ias_ms": 180.0 + math.sin(t * 0.3) * 10,
        "tas_ms": 195.0 + math.sin(t * 0.3) * 10,
        "mach": 0.62 + math.sin(t * 0.1) * 0.02,
        "vvi_ms": math.cos(t * 0.5) * 2.0,
        "heading_deg": heading,
        "pitch_deg": math.sin(t * 0.5) * 3.0,
        "bank_deg": math.sin(t * 0.3) * 15.0,
        "aoa_deg": 4.0 + math.sin(t * 0.2) * 1.5,
        "g_load": 1.0 + abs(math.sin(t * 0.3)) * 2.0,
        "throttle": 0.75,
        "rpm_pct": 85.0,
        "fuel_kg": max(0.0, 3000.0 - t * 0.5),
        "flaps_pct": 0.0,
        "gear_down": False,
        "airbrake_pct": 0.0,
        "engine_fire": False,
    }


def build_contacts(t: float) -> list:
    contacts = []
    for (cid, atype, coalition, dlat_km, dlon_km, alt_m, spd_ms, hdg_base, orb_r_km, orb_spd) in CONTACTS_DEF:
        orbit_angle = math.radians((t * orb_spd + hdg_base) % 360)
        base_lat = PLAYER_LAT + km_to_deg_lat(dlat_km)
        base_lon = PLAYER_LON + km_to_deg_lon(dlon_km, PLAYER_LAT)

        lat = base_lat + km_to_deg_lat(math.sin(orbit_angle) * orb_r_km)
        lon = base_lon + km_to_deg_lon(math.cos(orbit_angle) * orb_r_km, base_lat)

        heading = (math.degrees(orbit_angle) + 90) % 360
        alt = alt_m + math.sin(t * 0.3 + hdg_base) * 200
        spd = spd_ms + math.sin(t * 0.2 + hdg_base * 0.1) * 15

        contacts.append({
            "id": cid,
            "aircraft": atype,
            "coalition": coalition,
            "lat": lat,
            "lon": lon,
            "alt_msl_m": round(alt, 1),
            "heading_deg": round(heading, 1),
            "speed_ms": round(spd, 1),
            "speed_kts": round(spd * 1.944, 1),
        })
    return contacts


async def run():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"[mock_dcs] Sending to {UDP_HOST}:{UDP_PORT} at 30Hz")
    print(f"[mock_dcs] Player: F-16C + {len(CONTACTS_DEF)} contacts (blue/red/neutral)")
    print("[mock_dcs] Ctrl+C to stop.")
    t = 0.0
    try:
        while True:
            frame = build_frame(t)
            frame["contacts"] = build_contacts(t)
            payload = json.dumps(frame).encode("utf-8")
            sock.sendto(payload, (UDP_HOST, UDP_PORT))
            t += 1 / 30
            await asyncio.sleep(1 / 30)
    except KeyboardInterrupt:
        print("[mock_dcs] Stopped.")
    finally:
        sock.close()


if __name__ == "__main__":
    asyncio.run(run())
