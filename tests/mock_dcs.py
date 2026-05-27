"""tests/mock_dcs.py  v3

Simula o DCS World enviando telemetria + contacts no mesmo pacote UDP
para a porta 7778 (igual ao Export.lua com LoGetWorldObjects).

Uso:
    python tests/mock_dcs.py

Certifique-se de que o servidor está rodando:
    python -m server.main
"""

import json
import math
import random
import socket
import time

HOST  = "127.0.0.1"
PORT  = 7778
HZ    = 30

PLAYER_LAT = 41.6102
PLAYER_LON = 41.5985


def offset_ll(lat, lon, bearing_deg, dist_m):
    R = 6_371_000.0
    b = math.radians(bearing_deg)
    la1, lo1 = math.radians(lat), math.radians(lon)
    la2 = math.asin(math.sin(la1) * math.cos(dist_m / R) +
                    math.cos(la1) * math.sin(dist_m / R) * math.cos(b))
    lo2 = lo1 + math.atan2(math.sin(b) * math.sin(dist_m / R) * math.cos(la1),
                           math.cos(dist_m / R) - math.sin(la1) * math.sin(la2))
    return math.degrees(la2), math.degrees(lo2)


def haversine(lat1, lon1, lat2, lon2):
    R = 6_371_000.0
    dl = math.radians(lat2 - lat1)
    dL = math.radians(lon2 - lon1)
    a = math.sin(dl/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dL/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


CONTACT_DEFS = [
    dict(id="c1", name="Enfield-1",  type="Su-27",  category="Air",    coalition=1, bearing=0,   dist_km=40,  alt_m=8000,  hdg=180, spd_ms=220),
    dict(id="c2", name="Colt-2",     type="F-15C",  category="Air",    coalition=1, bearing=45,  dist_km=25,  alt_m=6000,  hdg=225, spd_ms=260),
    dict(id="c3", name="Hostile-1",  type="MiG-29", category="Air",    coalition=2, bearing=5,   dist_km=60,  alt_m=9000,  hdg=185, spd_ms=280),
    dict(id="c4", name="Hostile-2",  type="Su-25",  category="Air",    coalition=2, bearing=90,  dist_km=80,  alt_m=1500,  hdg=270, spd_ms=180),
    dict(id="c5", name="Cargo-01",   type="An-26",  category="Air",    coalition=0, bearing=180, dist_km=110, alt_m=4000,  hdg=0,   spd_ms=110),
    dict(id="c6", name="TANK-01",    type="T-72",   category="Ground",  coalition=2, bearing=270, dist_km=15,  alt_m=50,    hdg=90,  spd_ms=8),
    dict(id="c7", name="Magic-1",    type="E-3A",   category="Air",    coalition=1, bearing=315, dist_km=130, alt_m=11000, hdg=135, spd_ms=200),
]

states = {}
for cd in CONTACT_DEFS:
    lat, lon = offset_ll(PLAYER_LAT, PLAYER_LON, cd["bearing"], cd["dist_km"] * 1000)
    states[cd["id"]] = {**cd, "lat": lat, "lon": lon}


def move_contacts(dt):
    for c in states.values():
        c["lat"], c["lon"] = offset_ll(c["lat"], c["lon"], c["hdg"], c["spd_ms"] * dt)
        c["hdg"] = (c["hdg"] + random.uniform(-0.3, 0.3)) % 360


player_hdg = 0.0

def build_packet(t):
    global player_hdg
    player_hdg = (player_hdg + 0.5) % 360
    ias = 220 + math.sin(t * 0.1) * 20
    alt = 6000 + math.sin(t * 0.05) * 300

    contacts = []
    for c in states.values():
        dist = haversine(PLAYER_LAT, PLAYER_LON, c["lat"], c["lon"])
        spd  = c["spd_ms"] + random.uniform(-2, 2)
        contacts.append({
            "id":          c["id"],
            "name":        c["name"],
            "type":        c["type"],
            "category":    c["category"],
            "coalition":   c["coalition"],
            "lat":         c["lat"],
            "lon":         c["lon"],
            "alt_msl_m":   c["alt_m"] + random.uniform(-30, 30),
            "heading_deg": round(c["hdg"], 1),
            "speed_ms":    round(spd, 1),
            "speed_kts":   round(spd * 1.944, 1),
            "dist_m":      round(dist, 0),
            "source":      "export",
        })

    return {
        "msg_type":     "self",
        "timestamp":    t,
        "aircraft":     "F/A-18C",
        "lat":          PLAYER_LAT,
        "lon":          PLAYER_LON,
        "alt_msl_m":    alt,
        "alt_agl_m":    alt - 200,
        "ias_ms":       ias,
        "tas_ms":       ias * 1.05,
        "mach":         ias / 340,
        "vvi_ms":       math.sin(t * 0.3) * 3,
        "heading_deg":  player_hdg,
        "pitch_deg":    math.sin(t * 0.3) * 5,
        "bank_deg":     math.sin(t * 0.2) * 15,
        "aoa_deg":      2.5 + math.sin(t * 0.4) * 1.5,
        "g_load":       1.0 + abs(math.sin(t * 0.2)) * 2,
        "fuel_kg":      max(0, 3000 - t * 0.5),
        "fuel_max_kg":  5000,
        "contacts":     contacts,
    }


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    interval  = 1.0 / HZ
    last_send = last_move = time.time()
    start = time.time()

    print(f"[mock_dcs] → {HOST}:{PORT}  @ {HZ}Hz  (telemetria + contacts no mesmo pacote)")
    print(f"[mock_dcs] {len(states)} contatos | jogador: F/A-18C em Batumi")
    print(f"[mock_dcs] Acesse: http://127.0.0.1:8000/radar")
    print(f"[mock_dcs] Ctrl+C para parar.\n")
    for c in states.values():
        coal = ["Neutral", "Friendly", "Enemy"][c['coalition']]
        print(f"  {c['id']}  {c['name']:<14} {c['type']:<8}  {coal:<10}  dist={c['dist_km']}km")
    print()

    try:
        while True:
            now = time.time()
            t   = now - start

            move_contacts(now - last_move)
            last_move = now

            if now - last_send >= interval:
                pkt = build_packet(t)
                sock.sendto(json.dumps(pkt).encode(), (HOST, PORT))
                last_send = now

                enemies = [c for c in states.values() if c["coalition"] == 2]
                closest = min(enemies, key=lambda c: haversine(PLAYER_LAT, PLAYER_LON, c["lat"], c["lon"]), default=None)
                if closest:
                    dist_km = haversine(PLAYER_LAT, PLAYER_LON, closest["lat"], closest["lon"]) / 1000
                    threat  = " ⚠️  AMEAÇA" if dist_km < 20 else ""
                    print(f"\r[t={t:6.1f}s] contacts={len(states)}  ameaça: {closest['name']} {dist_km:.1f}km{threat}   ", end="", flush=True)

            time.sleep(0.003)

    except KeyboardInterrupt:
        print("\n[mock_dcs] Encerrado.")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
