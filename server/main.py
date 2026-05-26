# server/main.py
# Issue #2 - UDP Listener Server
# Runs the UDP socket + FastAPI in the same process via asyncio
import asyncio
import json
import logging
import signal
import uvicorn

from server.models import AircraftState
from server import state as shared

UDP_HOST = "127.0.0.1"
UDP_PORT = 7778
API_HOST = "127.0.0.1"
API_PORT = 8000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("iox-server")


# ----------------------------------------------------------------
# UDP Protocol
# ----------------------------------------------------------------
class DCSUDPProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport
        log.info(f"UDP listening on {UDP_HOST}:{UDP_PORT}")

    def datagram_received(self, data: bytes, addr):
        try:
            raw = json.loads(data.decode("utf-8"))
            shared.latest_state = AircraftState(**raw)
            shared.packet_count += 1

            if shared.packet_count % 30 == 0:
                s = shared.latest_state
                log.info(
                    f"[#{shared.packet_count}] {s.aircraft} | "
                    f"ALT {s.alt_msl_m:.0f}m | "
                    f"IAS {s.ias_ms * 1.944:.0f}kts | "
                    f"HDG {s.heading_deg:.0f}\u00b0 | "
                    f"MACH {s.mach:.2f}"
                )
        except Exception as e:
            log.warning(f"Packet error: {e}")

    def error_received(self, exc):
        log.error(f"UDP error: {exc}")


# ----------------------------------------------------------------
# Main: UDP + FastAPI side by side
# ----------------------------------------------------------------
async def main():
    loop = asyncio.get_running_loop()

    log.info("=" * 55)
    log.info(" dcs-iox-api  |  Starting services")
    log.info(f" UDP  -> udp://{UDP_HOST}:{UDP_PORT}")
    log.info(f" REST -> http://{API_HOST}:{API_PORT}")
    log.info(f" Docs -> http://{API_HOST}:{API_PORT}/docs")
    log.info(f" WS   -> ws://{API_HOST}:{API_PORT}/ws/telemetry")
    log.info("=" * 55)

    # Start UDP listener
    transport, _ = await loop.create_datagram_endpoint(
        DCSUDPProtocol,
        local_addr=(UDP_HOST, UDP_PORT),
    )

    # Start FastAPI with uvicorn
    config = uvicorn.Config(
        "server.api:app",
        host=API_HOST,
        port=API_PORT,
        log_level="warning",  # reduce noise, UDP logs already handle this
    )
    server = uvicorn.Server(config)

    stop_event = asyncio.Event()

    def _shutdown():
        log.info("Shutting down...")
        stop_event.set()
        server.should_exit = True

    loop.add_signal_handler(signal.SIGINT, _shutdown)
    loop.add_signal_handler(signal.SIGTERM, _shutdown)

    try:
        await server.serve()
    finally:
        transport.close()
        log.info(f"Stopped. Total packets: {shared.packet_count}")


if __name__ == "__main__":
    asyncio.run(main())
