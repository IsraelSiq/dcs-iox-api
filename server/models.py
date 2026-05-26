# server/models.py
# Issue #5 - Generic aircraft data model
from pydantic import BaseModel, Field
from typing import Optional, List
import time


class AircraftState(BaseModel):
    """Player aircraft telemetry state."""

    # Meta
    timestamp:   float = Field(0.0, description="DCS mission time (seconds)")
    aircraft:    str   = Field("unknown", description="Aircraft module name")
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
    fuel_kg: float = Field(0.0)
    rpm_1:   float = Field(0.0)
    rpm_2:   float = Field(0.0)

    # Coalition (0=neutral, 1=red, 2=blue)
    coalition: int = Field(2)

    class Config:
        json_schema_extra = {
            "example": {
                "timestamp": 125.033,
                "aircraft": "F-16C_50",
                "lat": 41.123456,
                "lon": 42.654321,
                "alt_msl_m": 3048.0,
                "alt_agl_m": 2800.0,
                "speed_ms": 290.0,
                "ias_ms": 257.2,
                "tas_ms": 290.4,
                "mach": 0.87,
                "vvi_ms": -2.1,
                "heading_deg": 270.0,
                "pitch_deg": -1.5,
                "bank_deg": 0.3,
                "aoa_deg": 4.2,
                "fuel_kg": 2450.0,
                "rpm_1": 88.5,
                "rpm_2": 0.0,
                "coalition": 2,
            }
        }


class ContactState(BaseModel):
    """A world contact detected within radar range."""

    id:          str   = Field(..., description="DCS unit ID")
    name:        str   = Field("", description="Unit name")
    type:        str   = Field("unknown", description="Aircraft/unit type")
    lat:         float = Field(0.0)
    lon:         float = Field(0.0)
    alt_msl_m:   float = Field(0.0)
    heading_deg: float = Field(0.0)
    speed_ms:    float = Field(0.0)
    coalition:   int   = Field(0, description="0=neutral, 1=red, 2=blue")
    dist_m:      float = Field(0.0, description="Distance from player (metres)")
    received_at: float = Field(default_factory=time.time)


class ContactsPacket(BaseModel):
    """Batch of contacts from a single DCS frame."""
    timestamp: float
    count:     int
    contacts:  List[ContactState] = []
