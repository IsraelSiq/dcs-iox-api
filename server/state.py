# server/state.py
# Shared in-process state — imported by main.py, api.py, udp listener
import time
from collections import deque
from typing import Optional, Dict
from server.models import AircraftState, ContactState

# Server start time (for uptime)
start_time: float = time.time()

# Latest player state (set by UDP listener)
latest_state: Optional[AircraftState] = None

# Latest contacts dict: id -> ContactState (set by UDP listener)
contacts: Dict[str, ContactState] = {}

# Last contacts timestamp (to detect stale data)
contacts_timestamp: float = 0.0

# Total UDP packets received
packet_count: int = 0

# Rolling log buffer (last 200 entries)
log_buffer: deque = deque(maxlen=200)
