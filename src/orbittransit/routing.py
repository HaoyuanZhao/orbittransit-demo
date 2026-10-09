"""Shortest-ISL and deadline-aware orbital carrying, adapted from OrbitTransit.

Planning is pure: candidates never reserve storage or debit batteries.
"""

import ephem
import networkx as nx

from .models import Candidate, Delivery, Status
from .orbit import neighboring_paths, reachable


def valid_path(graph, path):
    return all(graph.has_edge(first, second) for first, second in zip(path, path[1:]))


def shortest_isl(graph, satellites, source, station, parameters):
    ingress = reachable(satellites, source, parameters)
    egress = reachable(satellites, station.point, parameters)
    if not ingress or not egress:
        return None, Status.NO_REACHABLE_SATELLITE
    best = None
    for first in ingress:
        for last in egress:
            try:
                path = tuple(nx.shortest_path(graph, first.id, last.id))
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue
            if best is None or len(path) < len(best.path):
                best = Candidate(path, parameters.interval_minutes, Delivery.ISL)
    return (best, Status.SUCCESS) if best else (None, Status.NO_ROUTING_PATH)


def carry_from_satellite(satellite, station, graph, satellites, contacts,
                         constellation, parameters, date, deadline):
    paths = [(satellite.id,), *neighboring_paths(satellite, constellation)]
    for path in paths:
        if not valid_path(graph, path):
            continue
        if any(not satellites[sid].has_space(parameters.chunk_mbit) for sid in path):
            continue
        for station_id, arrival in contacts.opportunities(satellites[path[-1]], constellation.satellites_per_plane):
            if station_id != station.id or arrival + parameters.interval_days > deadline:
                continue
            wait_days = max(0.0, float(arrival - date))
            # The original model approximates relay residence by an average duration.
            until = ephem.Date(date + wait_days / len(path))
            reservations = tuple((sid, float(until)) for sid in path)
            return Candidate(path, wait_days * 1440 + parameters.interval_minutes,
                             Delivery.CARRY, reservations)
    return None


def orbit_transit(graph, satellites, source, station, contacts, constellation,
                  parameters, date, deadline):
    ingress = reachable(satellites, source, parameters)
    if not ingress:
        return None, Status.NO_REACHABLE_SATELLITE
    best_carry = None
    for satellite in ingress:
        candidate = carry_from_satellite(satellite, station, graph, satellites, contacts,
                                        constellation, parameters, date, deadline)
        if candidate is not None and (best_carry is None or len(candidate.path) < len(best_carry.path)):
            best_carry = candidate
    best_isl, status = shortest_isl(graph, satellites, source, station, parameters)
    if best_carry is None:
        return best_isl, status
    if best_isl is None:
        return best_carry, Status.SUCCESS
    carry_cost = len(best_carry.path) * parameters.isl_energy_wh + 2 * parameters.io_energy_wh
    isl_cost = len(best_isl.path) * parameters.isl_energy_wh
    if carry_cost < isl_cost:
        return best_carry, Status.SUCCESS
    return best_isl, Status.SUCCESS
