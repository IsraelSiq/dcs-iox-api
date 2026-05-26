# server/main.py
# Entry point: starts UDP listener + FastAPI server
import asyncio
import json
import logging
import signal
import sys
import time
import uvicorn

from server.log_handler import BufferHandler
from server import state as shared
from server.models import AircraftState, ContactState

# ----------------------------------------------------------------
# Logging
# ----------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "iox-api"):
    logging.getLogger(name).addHandler(BufferHandler())

log = logging.getLogger("iox-api")

# ----------------------------------------------------------------
# UDP listener — handles both 'self' and 'contacts' packets
# ----------------------------------------------------------------
UDP_HOST = "127.0.0.1"
UDP_PORT = 7778


class IOXProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport
        log.info(f"UDP listener ready on {UDP_HOST}:{UDP_PORT}")

    def datagram_received(self, data: bytes, addr):
        shared.packet_count += 1
        try:
            payload = json.loads(data.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return

        msg_type = payload.get("msg_type", "self")

        if msg_type == "contacts":
            raw_contacts = payload.get("contacts", [])
            new_contacts = {}
            for c in raw_contacts:
                try:
                    contact = ContactState(**c)
                    new_contacts[contact.id] = contact
                except Exception:
                    pass
            shared.contacts = new_contacts
            shared.contacts_timestamp = payload.get("timestamp", time.time())

        else:  # 'self' or legacy packet
            try:
                shared.latest_state = AircraftState(**payload)
            except Exception as e:
                log.warning(f"Failed to parse self packet: {e}")

    def error_received(self, exc):
        log.warning(f"UDP error: {exc}")


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
async def main():
    shared.start_time = time.time()
    loop = asyncio.get_running_loop()

    # UDP server
    transport, _ = await loop.create_datagram_endpoint(
        IOXProtocol,
        local_addr=(UDP_HOST, UDP_PORT),
    )
    log.info(f"[dcs-iox-api] UDP listening on {UDP_HOST}:{UDP_PORT}")

    # FastAPI via uvicorn
    config = uvicorn.Config(
        "server.api:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        loop="asyncio",
    )
    server = uvicorn.Server(config)

    # Graceful shutdown (works on Windows too)
    def _shutdown():
        log.info("Shutdown signal received")
        server.should_exit = True
        transport.close()

    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _shutdown)

    try:
        await server.serve()
    finally:
        transport.close()
        log.info("[dcs-iox-api] Shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
