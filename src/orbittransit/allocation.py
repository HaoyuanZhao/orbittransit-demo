"""Nearest-station assignment and orbital traffic diffusion."""

from collections import Counter
import math

from geopy.distance import geodesic

from .orbit import neighboring_paths, reachable
from .routing import valid_path


def nearest_assignment(tasks, stations):
    if not stations:
        return [None] * len(tasks)
    return [min(stations, key=lambda station: geodesic(
        (task.lat, task.lon), (float(station.point.lat) * 180 / math.pi,
                              float(station.point.lon) * 180 / math.pi)).kilometers).id
            for task in tasks]


def diffuse_assignment(tasks, sources, stations, satellites, graph, contacts,
                        constellation, parameters):
    """Allocate nearest first; move excess assignments along neighboring planes."""
    if not stations:
        return [None] * len(tasks)
    per_station = math.floor(parameters.station_capacity_mbit / parameters.chunk_mbit
                             * parameters.station_admission_fraction)
    if per_station == 0:
        return [None] * len(tasks)
    assignments = []
    loads = Counter()
    for task in tasks:
        ordered = sorted(stations, key=lambda station: geodesic(
            (task.lat, task.lon), (math.degrees(station.point.lat), math.degrees(station.point.lon))).kilometers)
        station_id = next((station.id for station in ordered if loads[station.id] < per_station), ordered[0].id)
        assignments.append(station_id)
        loads[station_id] += 1
    overloaded = sorted((sid for sid in loads if loads[sid] > per_station),
                        key=lambda sid: (-loads[sid], sid))
    for station_id in overloaded:
        excess = loads[station_id] - per_station
        indices = [index for index, sid in enumerate(assignments) if sid == station_id][:excess]
        for index in indices:
            selected, fewest_hops = None, math.inf
            for satellite in reachable(satellites, sources[index], parameters):
                for path in [(satellite.id,), *neighboring_paths(satellite, constellation)]:
                    if not valid_path(graph, path):
                        continue
                    available = next((sid for sid, _ in contacts.opportunities(
                        satellites[path[-1]], constellation.satellites_per_plane)
                        if loads[sid] < per_station), None)
                    if available is not None:
                        if len(path) - 1 < fewest_hops:
                            selected, fewest_hops = available, len(path) - 1
                        break
            loads[station_id] -= 1
            assignments[index] = selected
            if selected is not None:
                loads[selected] += 1
    return assignments


def station_admission(assignments, parameters):
    """FIFO admission within one planning interval; no cross-interval queue."""
    counts = Counter()
    accepted = []
    for station_id in assignments:
        if station_id is None:
            accepted.append(False)
            continue
        counts[station_id] += 1
        accepted.append(counts[station_id] * parameters.chunk_mbit <= parameters.station_capacity_mbit)
    return accepted, counts
