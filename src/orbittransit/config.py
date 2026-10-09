"""Small, explicit inputs for reproducible delivery scenarios."""

from dataclasses import dataclass, field
import json
import math
from pathlib import Path

import ephem


STRATEGIES = ("shortest_isl", "orbittransit")


@dataclass(frozen=True)
class Parameters:
    interval_minutes: float = 5.0
    ground_station_capacity_mbps: float = 10_000.0
    link_bandwidth_mbps: float = 1_000.0
    min_elevation_degrees: float = 25.0
    max_ground_link_km: float = 1_500.0
    max_isl_km: float = 5_014.0
    satellite_storage_gb: float = 100.0
    battery_capacity_wh: float = 83.33
    solar_charge_w: float = 120.0
    ground_link_power_w: float = 45.0
    isl_power_w: float = 35.0
    disk_io_power_w: float = 3.0
    station_admission_fraction: float = 0.8

    @property
    def interval_days(self):
        return self.interval_minutes / 1440.0

    @property
    def chunk_mbit(self):
        return self.link_bandwidth_mbps * self.interval_minutes * 60.0

    @property
    def station_capacity_mbit(self):
        return self.ground_station_capacity_mbps * self.interval_minutes * 60.0

    @property
    def storage_mbit(self):
        return self.satellite_storage_gb * 1_000.0 * 8.0

    @property
    def isl_energy_wh(self):
        return self.isl_power_w * self.interval_minutes / 60.0

    @property
    def ground_energy_wh(self):
        return self.ground_link_power_w * self.interval_minutes / 60.0

    @property
    def io_energy_wh(self):
        return self.disk_io_power_w * self.interval_minutes / 60.0


@dataclass(frozen=True)
class Constellation:
    planes: int = 36
    satellites_per_plane: int = 11
    altitude_km: float = 550.0
    inclination_degrees: float = 53.0


@dataclass(frozen=True)
class Scenario:
    name: str
    stations: tuple[dict, ...]
    sources: tuple[dict, ...]
    parameters: Parameters = field(default_factory=Parameters)
    constellation: Constellation = field(default_factory=Constellation)
    seed: int = 123
    steps: int = 6
    start_time: str = "2000/1/1 12:00:00"
    deadline_minutes: tuple[int, int] = (20, 180)
    strategies: tuple[str, ...] = STRATEGIES

    @classmethod
    def from_dict(cls, data):
        allowed = {"name", "stations", "sources", "parameters", "constellation",
                   "seed", "steps", "start_time", "deadline_minutes", "strategies"}
        unknown = set(data) - allowed
        if unknown:
            raise ValueError(f"Unknown configuration fields: {', '.join(sorted(unknown))}")
        scenario = cls(
            name=data["name"], stations=tuple(data["stations"]), sources=tuple(data["sources"]),
            parameters=Parameters(**data.get("parameters", {})),
            constellation=Constellation(**data.get("constellation", {})),
            seed=data.get("seed", 123), steps=data.get("steps", 6),
            start_time=data.get("start_time", "2000/1/1 12:00:00"),
            deadline_minutes=tuple(data.get("deadline_minutes", [20, 180])),
            strategies=tuple(data.get("strategies", STRATEGIES)),
        )
        scenario.validate()
        return scenario

    @classmethod
    def load(cls, path):
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def validate(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be a non-empty string")
        if type(self.seed) is not int or type(self.steps) is not int or self.steps < 1:
            raise ValueError("seed and steps must be integers; steps must be positive")
        c = self.constellation
        if any(type(n) is not int or n < 3 for n in (c.planes, c.satellites_per_plane)):
            raise ValueError("The grid requires at least three planes and satellites per plane")
        if not math.isfinite(c.altitude_km) or c.altitude_km <= 0:
            raise ValueError("altitude_km must be positive and finite")
        if not math.isfinite(c.inclination_degrees) or not 0 <= c.inclination_degrees <= 180:
            raise ValueError("inclination_degrees must be between 0 and 180")
        if not self.sources:
            raise ValueError("At least one source is required")
        for point in (*self.stations, *self.sources):
            if (not math.isfinite(point["lat"]) or not -90 <= point["lat"] <= 90
                    or not math.isfinite(point["lon"]) or not -180 <= point["lon"] <= 180):
                raise ValueError("Coordinates must be finite latitude/longitude in degrees")
        for point in self.sources:
            if type(point.get("tasks_per_step", 1)) is not int or point.get("tasks_per_step", 1) < 1:
                raise ValueError("tasks_per_step must be a positive integer")
        low, high = self.deadline_minutes
        if type(low) is not int or type(high) is not int or not 0 < low <= high:
            raise ValueError("deadline_minutes must be an ordered pair of positive integers")
        if (not self.strategies or len(set(self.strategies)) != len(self.strategies)
                or any(s not in STRATEGIES for s in self.strategies)):
            raise ValueError(f"strategies must be unique choices from {STRATEGIES}")
        p = self.parameters
        for name, value in vars(p).items():
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be non-negative and finite")
        for name in ("interval_minutes", "ground_station_capacity_mbps", "link_bandwidth_mbps"):
            if getattr(p, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if not 0 <= p.min_elevation_degrees < 90 or not 0 < p.station_admission_fraction <= 1:
            raise ValueError("Invalid elevation threshold or station admission fraction")
        ephem.Date(self.start_time)
