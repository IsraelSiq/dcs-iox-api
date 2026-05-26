# tests/mock_dcs.py
# Simula o Export.lua enviando frames UDP a 30Hz
# Uso: python tests/mock_dcs.py
import asyncio
import json
import math
import time
import socket
import os

UDP_HOST = os.getenv("UDP_HOST", "127.0.0.1")
UDP_PORT = int(os.getenv("UDP_PORT", "7778"))


def build_frame(t: float) -> dict:
    """Gera estado simulado de um F-16 em voo circular."""
    heading = (t * 5) % 360
    rad = math.radians(heading)
    return {
        "aircraft": "F-16C_50",
        "timestamp": t,
        "lat": 41.0 + math.sin(rad) * 0.1,
        "lon": 29.0 + math.cos(rad) * 0.1,
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


async def run():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"[mock_dcs] Sending to {UDP_HOST}:{UDP_PORT} at 30Hz. Ctrl+C to stop.")
    t = 0.0
    try:
        while True:
            frame = build_frame(t)
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
