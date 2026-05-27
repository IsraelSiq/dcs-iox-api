# server/main.py
# Entry point: starts UDP listeners (7778 telemetry + 7779 contacts) + FastAPI
import asyncio
import json
import logging
import os
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
# Config via env vars
# ----------------------------------------------------------------
UDP_HOST             = os.getenv("UDP_HOST",             "127.0.0.1")
UDP_PORT_TELEMETRY   = int(os.getenv("UDP_PORT_TELEMETRY", "7778"))   # Export.lua
UDP_PORT_CONTACTS    = int(os.getenv("UDP_PORT_CONTACTS",  "7779"))   # MissionScript.lua


# ----------------------------------------------------------------
# Protocol: player telemetry (Export.lua -> 7778)
# ----------------------------------------------------------------
class TelemetryProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport
        log.info(f"UDP telemetry  ready on {UDP_HOST}:{UDP_PORT_TELEMETRY}")

    def datagram_received(self, data: bytes, addr):
        shared.packet_count += 1
        try:
            payload = json.loads(data.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return

        payload.pop("msg_type", None)
        # Legacy packets may carry embedded contacts — handle gracefully
        raw_contacts = payload.pop("contacts", [])
        if raw_contacts:
            _ingest_contacts(raw_contacts, time.time())

        try:
            shared.latest_state = AircraftState(**payload)
        except Exception as e:
            log.warning(f"[telemetry] failed to parse AircraftState: {e}")

    def error_received(self, exc):
        log.warning(f"[telemetry] UDP error: {exc}")


# ----------------------------------------------------------------
# Protocol: contacts (MissionScript.lua -> 7779)
# ----------------------------------------------------------------
class ContactsProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport
        log.info(f"UDP contacts   ready on {UDP_HOST}:{UDP_PORT_CONTACTS}")

    def datagram_received(self, data: bytes, addr):
        try:
            payload = json.loads(data.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return

        raw_contacts = payload.get("contacts", [])
        ts           = payload.get("timestamp", time.time())
        _ingest_contacts(raw_contacts, ts)

    def error_received(self, exc):
        log.warning(f"[contacts] UDP error: {exc}")


# ----------------------------------------------------------------
# Shared contacts ingestion
# ----------------------------------------------------------------
def _ingest_contacts(raw_contacts: list, timestamp: float):
    new_contacts: dict = {}
    for c in raw_contacts:
        try:
            contact = ContactState(**c)
            new_contacts[contact.id] = contact
        except Exception:
            pass
    shared.contacts           = new_contacts
    shared.contacts_timestamp = timestamp
    log.debug(f"[contacts] ingested {len(new_contacts)} contact(s)")


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------
async def main():
    shared.start_time = time.time()
    loop = asyncio.get_running_loop()

    # UDP: player telemetry
    transport_telemetry, _ = await loop.create_datagram_endpoint(
        TelemetryProtocol,
        local_addr=(UDP_HOST, UDP_PORT_TELEMETRY),
    )

    # UDP: contacts from MissionScript
    transport_contacts, _ = await loop.create_datagram_endpoint(
        ContactsProtocol,
        local_addr=(UDP_HOST, UDP_PORT_CONTACTS),
    )

    log.info(
        f"[dcs-iox-api] UDP telemetry={UDP_HOST}:{UDP_PORT_TELEMETRY}  "
        f"contacts={UDP_HOST}:{UDP_PORT_CONTACTS}"
    )

    config = uvicorn.Config(
        "server.api:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None

    try:
        await server.serve()
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("Shutdown signal received")
    finally:
        transport_telemetry.close()
        transport_contacts.close()
        log.info("[dcs-iox-api] Shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
