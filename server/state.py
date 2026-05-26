# server/state.py
import time
from collections import deque
from server.models import AircraftState

# Shared state
latest_state: AircraftState | None = None
start_time: float = time.time()
packet_count: int = 0

# Ring buffer: keeps the last 200 log entries
log_buffer: deque[dict] = deque(maxlen=200)
