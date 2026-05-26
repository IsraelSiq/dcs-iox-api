# tests/mock_dcs.py
# Simulates DCS Export.lua sending UDP packets to the server.
# Runs without DCS open — use this to test the UDP server locally.
import asyncio
import json
import math
import time
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MOCK-DCS] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("mock-dcs")

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 7778
UPDATE_HZ = 30
INTERVAL = 1.0 / UPDATE_HZ


def generate_frame(t: float) -> dict:
    """Simulate F-16C in a gentle left-hand orbit."""
    orbit_radius_deg = 0.05
    angle = t * 0.1  # slow orbit

    return {
        "timestamp": t,
        "aircraft": "F-16C_50",
        "lat": 41.0 + orbit_radius_deg * math.cos(angle),
        "lon": 42.0 + orbit_radius_deg * math.sin(angle),
        "alt_msl_m": 3000.0 + 50 * math.sin(t * 0.05),  # gentle climb/descend
        "alt_agl_m": 2800.0 + 50 * math.sin(t * 0.05),
        "speed_ms": 250.0 + 10 * math.sin(t * 0.02),
        "ias_ms": 240.0 + 8 * math.sin(t * 0.02),
        "tas_ms": 255.0 + 8 * math.sin(t * 0.02),
        "mach": 0.82 + 0.02 * math.sin(t * 0.02),
        "vvi_ms": 1.5 * math.sin(t * 0.05),
        "heading_deg": (t * 3.0) % 360,  # slowly rotating
        "pitch_deg": 2.0 * math.sin(t * 0.05),
        "bank_deg": 15.0 * math.sin(t * 0.1),
        "aoa_deg": 4.0 + 0.5 * math.sin(t * 0.03),
        "fuel_kg": max(0.0, 2500.0 - t * 0.5),  # fuel burning
        "rpm_1": 85.0 + 5 * math.sin(t * 0.02),
        "rpm_2": 0.0,
    }


class MockDCSProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_con_lost):
        self.transport = None
        self.on_con_lost = on_con_lost

    def connection_made(self, transport):
        self.transport = transport
        log.info(f"Mock DCS ready — sending to {SERVER_HOST}:{SERVER_PORT} at {UPDATE_HZ}Hz")
        log.info("Press Ctrl+C to stop")

    def error_received(self, exc):
        log.error(f"Error: {exc}")

    def connection_lost(self, exc):
        self.on_con_lost.set_result(True)


async def main():
    loop = asyncio.get_running_loop()
    on_con_lost = loop.create_future()

    transport, protocol = await loop.create_datagram_endpoint(
        lambda: MockDCSProtocol(on_con_lost),
        remote_addr=(SERVER_HOST, SERVER_PORT),
    )

    t = 0.0
    packet_count = 0
    start_time = time.monotonic()

    try:
        while True:
            frame = generate_frame(t)
            payload = json.dumps(frame).encode("utf-8")
            transport.sendto(payload)
            packet_count += 1

            if packet_count % 30 == 0:
                elapsed = time.monotonic() - start_time
                log.info(
                    f"[#{packet_count}] t={t:.1f}s | "
                    f"ALT {frame['alt_msl_m']:.0f}m | "
                    f"HDG {frame['heading_deg']:.0f}° | "
                    f"MACH {frame['mach']:.2f} | "
                    f"FUEL {frame['fuel_kg']:.0f}kg"
                )

            t += INTERVAL
            await asyncio.sleep(INTERVAL)

    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        pass
    finally:
        elapsed = time.monotonic() - start_time
        log.info(f"Mock stopped. Sent {packet_count} packets in {elapsed:.1f}s")
        transport.close()


if __name__ == "__main__":
    asyncio.run(main())
