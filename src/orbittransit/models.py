"""Satellite storage, orbital contact maps and per-task delivery plans.

Adapted from the original OrbitTransit simulator by Haoyuan Zhao.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum

import ephem

from .config import Parameters


class Status(StrEnum):
    SUCCESS = "success"
    NO_REACHABLE_SATELLITE = "no_reachable_satellite"
    NO_ROUTING_PATH = "no_routing_path"
    NO_AVAILABLE_STATION = "no_available_station"
    NO_STORAGE = "no_storage"
    NO_ENERGY = "no_energy"
    STATION_OVERLOAD = "station_overload"
    DEADLINE_EXCEEDED = "deadline_exceeded"


class Delivery(StrEnum):
    ISL = "isl"
    CARRY = "carry"


def observer(lat, lon, date):
    point = ephem.Observer()
    point.lat, point.lon = str(lat), str(lon)
    point.date = date
    point.elevation = 10
    return point


@dataclass
class Satellite:
    id: int
    body: object
    plane: int
    slot: int
    parameters: Parameters
    reservations: list[tuple[float, float]] = field(default_factory=list)
    battery_wh: float = field(init=False)

    def __post_init__(self):
        self.battery_wh = self.parameters.battery_capacity_wh

    @property
    def storage_used_mbit(self):
        return sum(amount for amount, _ in self.reservations)

    def has_space(self, amount):
        return self.storage_used_mbit + amount <= self.parameters.storage_mbit

    def release_expired(self, date):
        self.reservations = [(amount, until) for amount, until in self.reservations if until > date]

    def charge(self):
        p = self.parameters
        self.battery_wh = min(p.battery_capacity_wh,
                              self.battery_wh + p.solar_charge_w * p.interval_minutes / 60)


@dataclass
class GroundStation:
    id: int
    name: str
    point: object


@dataclass(frozen=True)
class Task:
    id: int
    step: int
    lat: float
    lon: float
    deadline_minutes: int


@dataclass(frozen=True)
class Candidate:
    path: tuple[int, ...]
    delivery_minutes: float
    method: Delivery
    reservations: tuple[tuple[int, float], ...] = ()


@dataclass
class Plan:
    task: Task
    station_id: int | None
    status: Status
    candidate: Candidate | None = None
    energy_wh: float = 0.0


class OrbitLinkMap:
    """Sample one satellite per plane, then phase-shift the contact sequence."""

    def __init__(self, start_date):
        self.start_date = start_date
        self.contacts = defaultdict(list)

    def opportunities(self, satellite, satellites_per_plane):
        sequence = self.contacts[satellite.plane]
        if not sequence:
            return []
        shift = round(satellite.slot / satellites_per_plane * (len(sequence) - 1))
        shifted = sequence[shift:] + sequence[:shift]
        return [(station, ephem.Date(self.start_date + minute / 1440))
                for minute, stations in enumerate(shifted) for station in stations]


def energy_cost(candidate, parameters):
    """Per-satellite Wh using the original fixed-power interval model."""
    path = candidate.path
    if len(path) == 1:
        costs = {path[0]: parameters.ground_energy_wh * 2}
    else:
        costs = {sid: parameters.isl_energy_wh for sid in path}
        costs[path[0]] += parameters.ground_energy_wh
        costs[path[-1]] += parameters.ground_energy_wh
    if candidate.method == Delivery.CARRY:
        costs[path[0]] += parameters.io_energy_wh
        costs[path[-1]] += parameters.io_energy_wh
    return costs


def commit_candidate(candidate, satellites, parameters):
    """Check every resource first; commit the chosen candidate once or do nothing."""
    reserved = defaultdict(float)
    for sid, _ in candidate.reservations:
        reserved[sid] += parameters.chunk_mbit
    if any(not satellites[sid].has_space(amount) for sid, amount in reserved.items()):
        return Status.NO_STORAGE, 0.0
    costs = energy_cost(candidate, parameters)
    if any(satellites[sid].battery_wh < amount for sid, amount in costs.items()):
        return Status.NO_ENERGY, 0.0
    for sid, until in candidate.reservations:
        satellites[sid].reservations.append((parameters.chunk_mbit, until))
    for sid, amount in costs.items():
        satellites[sid].battery_wh = max(0.0, satellites[sid].battery_wh - amount)
    return Status.SUCCESS, sum(costs.values())
