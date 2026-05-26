# server/state.py
# Shared in-memory state between UDP listener and REST/WS API
import time
from server.models import AircraftState
from typing import Optional

latest_state: Optional[AircraftState] = None
packet_count: int = 0
start_time: float = time.time()
