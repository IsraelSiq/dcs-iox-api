# server/main.py
import asyncio
import json
import logging
import signal
import time

import uvicorn

from server import state as shared
from server.api import app
from server.log_handler import BufferHandler
from server.models import AircraftState

# ----------------------------------------------------------------
# Logging setup
# ----------------------------------------------------------------
fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
buf_handler = BufferHandler()
buf_handler.setFormatter(fmt)

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(fmt)

root = logging.getLogger()
root.setLevel(logging.DEBUG)
root.addHandler(stream_handler)
root.addHandler(buf_handler)   # mirrors every log into shared.log_buffer

log = logging.getLogger("iox-server")

# ----------------------------------------------------------------
# UDP config
# ----------------------------------------------------------------
UDP_HOST = "127.0.0.1"
UDP_PORT = 7778

# ----------------------------------------------------------------
# UDP Protocol
# ----------------------------------------------------------------
class DCSProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        log.info(f"UDP server listening on {UDP_HOST}:{UDP_PORT}")

    def datagram_received(self, data: bytes, addr):
        try:
            payload = json.loads(data.decode("utf-8"))
            shared.latest_state = AircraftState(**payload)
            shared.packet_count += 1

            if shared.packet_count % 30 == 0:  # log once per second (~30Hz)
                s = shared.latest_state
                log.info(
                    f"[#{shared.packet_count}] {s.aircraft} | "
                    f"ALT {s.alt_msl_m:.0f}m | "
                    f"IAS {s.ias_ms * 1.944:.0f}kts | "
                    f"HDG {s.heading_deg:.0f}\u00b0 | "
                    f"MACH {s.mach:.2f}"
                )
        except Exception as e:
            log.warning(f"Bad packet from {addr}: {e}")

    def error_received(self, exc):
        log.error(f"UDP error: {exc}")

    def connection_lost(self, exc):
        log.warning("UDP connection closed")


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
async def main():
    banner = [
        "=" * 50,
        " dcs-iox-api  |  UDP Listener",
        f" Listening on udp://{UDP_HOST}:{UDP_PORT}",
        "=" * 50,
    ]
    for line in banner:
        log.info(line)

    loop = asyncio.get_event_loop()

    # Create UDP server
    transport, _ = await loop.create_datagram_endpoint(
        DCSProtocol,
        local_addr=(UDP_HOST, UDP_PORT),
    )

    # Graceful shutdown (Windows-compatible)
    _stop = asyncio.Event()

    def _shutdown(*_):
        log.info("Shutdown signal received")
        _stop.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Start uvicorn
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
        loop="none",
    )
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    log.info("FastAPI listening on http://127.0.0.1:8000")
    log.info("Live log dashboard: http://127.0.0.1:8000/logs/view")

    await _stop.wait()

    log.info("Shutting down...")
    server.should_exit = True
    await server_task
    transport.close()


if __name__ == "__main__":
    asyncio.run(main())
else:
    asyncio.run(main())
