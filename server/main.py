# server/main.py
# Issue #2 - UDP Listener Server
import asyncio
import json
import logging
import signal
import sys
from datetime import datetime
from server.models import AircraftState

# ----------------------------------------------------------------
# Config
# ----------------------------------------------------------------
UDP_HOST = "127.0.0.1"
UDP_PORT = 7778
LOG_LEVEL = logging.DEBUG

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("iox-server")

# ----------------------------------------------------------------
# Shared state (in-memory)
# ----------------------------------------------------------------
latest_state: AircraftState | None = None
packet_count: int = 0


# ----------------------------------------------------------------
# UDP Protocol
# ----------------------------------------------------------------
class DCSUDPProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport
        log.info(f"UDP server listening on {UDP_HOST}:{UDP_PORT}")

    def datagram_received(self, data: bytes, addr):
        global latest_state, packet_count

        try:
            raw = json.loads(data.decode("utf-8"))
            state = AircraftState(**raw)
            latest_state = state
            packet_count += 1

            # Log a summary every 30 packets (~1 second at 30Hz)
            if packet_count % 30 == 0:
                log.info(
                    f"[#{packet_count}] {state.aircraft} | "
                    f"ALT {state.alt_msl_m:.0f}m | "
                    f"IAS {state.ias_ms * 1.944:.0f}kts | "
                    f"HDG {state.heading_deg:.0f}° | "
                    f"MACH {state.mach:.2f}"
                )
            else:
                log.debug(
                    f"[#{packet_count}] {state.aircraft} ts={state.timestamp:.2f}"
                )

        except json.JSONDecodeError as e:
            log.warning(f"Invalid JSON from {addr}: {e}")
        except Exception as e:
            log.error(f"Error processing packet from {addr}: {e}")

    def error_received(self, exc):
        log.error(f"UDP error: {exc}")

    def connection_lost(self, exc):
        log.warning("UDP connection lost")


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
async def main():
    loop = asyncio.get_running_loop()

    log.info("=" * 50)
    log.info(" dcs-iox-api  |  UDP Listener")
    log.info(f" Listening on udp://{UDP_HOST}:{UDP_PORT}")
    log.info("=" * 50)

    transport, protocol = await loop.create_datagram_endpoint(
        lambda: DCSUDPProtocol(),
        local_addr=(UDP_HOST, UDP_PORT),
    )

    # Graceful shutdown on Ctrl+C
    stop_event = asyncio.Event()

    def _shutdown():
        log.info("Shutting down...")
        stop_event.set()

    loop.add_signal_handler(signal.SIGINT, _shutdown)
    loop.add_signal_handler(signal.SIGTERM, _shutdown)

    try:
        await stop_event.wait()
    finally:
        transport.close()
        log.info(f"Server stopped. Total packets received: {packet_count}")


if __name__ == "__main__":
    asyncio.run(main())
