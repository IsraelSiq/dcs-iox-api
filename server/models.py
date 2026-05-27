# server/models.py
# Issue #5 - Generic aircraft data model
from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Union
import time


COALITION_MAP = {"neutral": 0, "red": 1, "blue": 2}


class AircraftState(BaseModel):
    """Player aircraft telemetry state."""

    # Meta
    timestamp:   float = Field(0.0)
    aircraft:    str   = Field("unknown")
    received_at: float = Field(default_factory=time.time)

    # Position
    lat:       float = Field(0.0)
    lon:       float = Field(0.0)
    alt_msl_m: float = Field(0.0)
    alt_agl_m: float = Field(0.0)

    # Speed
    speed_ms: float = Field(0.0)
    ias_ms:   float = Field(0.0)
    tas_ms:   float = Field(0.0)
    mach:     float = Field(0.0)
    vvi_ms:   float = Field(0.0)

    # Attitude
    heading_deg: float = Field(0.0)
    pitch_deg:   float = Field(0.0)
    bank_deg:    float = Field(0.0)
    aoa_deg:     float = Field(0.0)

    # Systems
    fuel_kg:    float = Field(0.0)
    rpm_pct:    float = Field(0.0)   # single engine %
    rpm_1:      float = Field(0.0)
    rpm_2:      float = Field(0.0)
    g_load:     float = Field(1.0)
    throttle:   float = Field(0.0)
    flaps_pct:  float = Field(0.0)
    gear_down:  bool  = Field(False)
    airbrake_pct: float = Field(0.0)
    engine_fire:  bool  = Field(False)

    # Coalition (0=neutral, 1=red, 2=blue)
    coalition: int = Field(2)

    class Config:
        extra = "allow"   # ignore unknown fields from Export.lua


class ContactState(BaseModel):
    """A world contact detected within radar range."""

    id:          str   = Field(...)
    name:        str   = Field("")
    type:        str   = Field("unknown")
    lat:         float = Field(0.0)
    lon:         float = Field(0.0)
    alt_msl_m:   float = Field(0.0)
    heading_deg: float = Field(0.0)
    speed_ms:    float = Field(0.0)
    speed_kts:   float = Field(0.0)
    coalition:   int   = Field(0)   # 0=neutral, 1=red, 2=blue
    dist_m:      float = Field(0.0)
    received_at: float = Field(default_factory=time.time)

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, data: dict) -> dict:
        # Accept coalition as string or int
        coal = data.get("coalition", 0)
        if isinstance(coal, str):
            data["coalition"] = COALITION_MAP.get(coal.lower(), 0)

        # Accept 'aircraft' as alias for 'type'
        if "type" not in data or not data["type"] or data["type"] == "unknown":
            if "aircraft" in data:
                data["type"] = data["aircraft"]

        # Accept 'id' as string (convert int IDs from DCS)
        if "id" in data and not isinstance(data["id"], str):
            data["id"] = str(data["id"])

        return data

    class Config:
        extra = "allow"


class ContactsPacket(BaseModel):
    """Batch of contacts from a single DCS frame."""
    timestamp: float
    count:     int
    contacts:  List[ContactState] = []
