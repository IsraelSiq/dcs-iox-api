# server/models.py
# Issue #5 - Generic aircraft data model
from pydantic import BaseModel, Field
from typing import Optional
import time


class AircraftState(BaseModel):
    """Generic DCS aircraft telemetry state."""

    # Meta
    timestamp: float = Field(0.0, description="DCS mission time (seconds)")
    aircraft: str = Field("unknown", description="Aircraft module name (e.g. F-16C_50)")
    received_at: float = Field(default_factory=time.time, description="Server receive time (unix)")

    # Position
    lat: float = Field(0.0, description="Latitude (decimal degrees)")
    lon: float = Field(0.0, description="Longitude (decimal degrees)")
    alt_msl_m: float = Field(0.0, description="Altitude MSL (meters)")
    alt_agl_m: float = Field(0.0, description="Altitude AGL (meters)")

    # Speed
    speed_ms: float = Field(0.0, description="3D speed vector magnitude (m/s)")
    ias_ms: float = Field(0.0, description="Indicated Air Speed (m/s)")
    tas_ms: float = Field(0.0, description="True Air Speed (m/s)")
    mach: float = Field(0.0, description="Mach number")
    vvi_ms: float = Field(0.0, description="Vertical Velocity Indicator (m/s)")

    # Attitude
    heading_deg: float = Field(0.0, description="Magnetic heading (degrees, 0-360)")
    pitch_deg: float = Field(0.0, description="Pitch angle (degrees)")
    bank_deg: float = Field(0.0, description="Bank/Roll angle (degrees)")
    aoa_deg: float = Field(0.0, description="Angle of Attack (degrees)")

    # Systems
    fuel_kg: float = Field(0.0, description="Internal fuel total (kg)")
    rpm_1: float = Field(0.0, description="Engine 1 RPM (%)")
    rpm_2: float = Field(0.0, description="Engine 2 RPM (%)")

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
            }
        }
