from types import SimpleNamespace

import ephem
import networkx as nx

from orbittransit.config import Constellation, Parameters
from orbittransit.models import Delivery, GroundStation, Satellite, Status, commit_candidate
from orbittransit import routing


def routing_fixture(monkeypatch):
    parameters = Parameters(link_bandwidth_mbps=0.1)
    satellites = [Satellite(sid, None, 0, sid, parameters) for sid in range(3)]
    source = object()
    station = GroundStation(0, "test", object())
    monkeypatch.setattr(routing, "reachable", lambda sats, point, params:
                        satellites[:2] if point is source else satellites[2:])
    return parameters, satellites, source, station


def test_expected_hop_path_on_small_topology(monkeypatch):
    parameters, satellites, source, station = routing_fixture(monkeypatch)
    graph = nx.Graph([(0, 1), (1, 2)])
    candidate, status = routing.shortest_isl(graph, satellites, source, station, parameters)
    assert status == Status.SUCCESS
    assert candidate.path == (1, 2)
    assert candidate.method == Delivery.ISL


def test_disconnected_graph_reports_failure(monkeypatch):
    parameters, satellites, source, station = routing_fixture(monkeypatch)
    graph = nx.Graph()
    graph.add_nodes_from(range(3))
    candidate, status = routing.shortest_isl(graph, satellites, source, station, parameters)
    assert candidate is None
    assert status == Status.NO_ROUTING_PATH


def test_no_visible_satellite_reports_failure(monkeypatch):
    parameters, satellites, source, station = routing_fixture(monkeypatch)
    monkeypatch.setattr(routing, "reachable", lambda *args: [])
    candidate, status = routing.shortest_isl(nx.Graph(), satellites, source, station, parameters)
    assert candidate is None
    assert status == Status.NO_REACHABLE_SATELLITE


def test_unselected_carry_candidates_never_reserve_resources(monkeypatch):
    parameters, satellites, source, station = routing_fixture(monkeypatch)
    now = ephem.Date("2000/1/1 12:05:00")
    contacts = SimpleNamespace(opportunities=lambda *args: [(station.id, ephem.Date(now + 10 / 1440))])
    graph = nx.Graph([(0, 2), (1, 2)])
    before = [satellite.battery_wh for satellite in satellites]
    candidate, status = routing.orbit_transit(
        graph, satellites, source, station, contacts, Constellation(planes=3, satellites_per_plane=3),
        parameters, now, ephem.Date(now + 60 / 1440))
    assert status == Status.SUCCESS
    assert candidate.method == Delivery.CARRY
    assert all(satellite.storage_used_mbit == 0 for satellite in satellites)
    assert before == [satellite.battery_wh for satellite in satellites]
    status, energy = commit_candidate(candidate, satellites, parameters)
    assert status == Status.SUCCESS and energy > 0
    assert satellites[candidate.path[0]].storage_used_mbit == parameters.chunk_mbit
    assert all(satellite.storage_used_mbit == 0 for satellite in satellites if satellite.id not in candidate.path)


def test_short_deadline_falls_back_to_isl(monkeypatch):
    parameters, satellites, source, station = routing_fixture(monkeypatch)
    now = ephem.Date("2000/1/1 12:05:00")
    contacts = SimpleNamespace(opportunities=lambda *args: [(station.id, ephem.Date(now + 50 / 1440))])
    candidate, status = routing.orbit_transit(
        nx.Graph([(0, 2), (1, 2)]), satellites, source, station, contacts,
        Constellation(planes=3, satellites_per_plane=3), parameters, now, ephem.Date(now + 10 / 1440))
    assert status == Status.SUCCESS
    assert candidate.method == Delivery.ISL


def test_carry_path_cannot_cross_an_absent_link(monkeypatch):
    parameters, satellites, source, station = routing_fixture(monkeypatch)
    now = ephem.Date("2000/1/1 12:05:00")
    contacts = SimpleNamespace(opportunities=lambda sat, count:
                               [(station.id, ephem.Date(now + 5 / 1440))] if sat.id == 2 else [])
    monkeypatch.setattr(routing, "neighboring_paths", lambda *args: [(0, 2)])
    graph = nx.Graph()
    graph.add_nodes_from(range(3))
    candidate = routing.carry_from_satellite(satellites[0], station, graph, satellites, contacts,
                                            Constellation(planes=3, satellites_per_plane=3),
                                            parameters, now, ephem.Date(now + 60 / 1440))
    assert candidate is None
