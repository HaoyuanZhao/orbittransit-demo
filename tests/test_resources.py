import ephem

from orbittransit.allocation import station_admission
from orbittransit.config import Parameters
from orbittransit.models import Candidate, Delivery, Satellite, Status, commit_candidate


def test_storage_limit_and_failed_commit_leave_state_intact():
    parameters = Parameters(interval_minutes=1, link_bandwidth_mbps=.1, satellite_storage_gb=.001)
    satellite = Satellite(0, None, 0, 0, parameters)
    until = float(ephem.Date("2000/1/1 13:00:00"))
    candidate = Candidate((0,), 10, Delivery.CARRY, ((0, until),))
    assert commit_candidate(candidate, [satellite], parameters)[0] == Status.SUCCESS
    assert satellite.storage_used_mbit == 6
    before = satellite.battery_wh
    assert commit_candidate(candidate, [satellite], parameters) == (Status.NO_STORAGE, 0)
    assert satellite.storage_used_mbit == 6
    assert satellite.battery_wh == before
    satellite.release_expired(ephem.Date(until))
    assert satellite.storage_used_mbit == 0


def test_insufficient_energy_commits_no_storage_or_partial_debit():
    parameters = Parameters(link_bandwidth_mbps=.1)
    satellites = [Satellite(sid, None, 0, sid, parameters) for sid in range(2)]
    satellites[1].battery_wh = 0
    before = [sat.battery_wh for sat in satellites]
    candidate = Candidate((0, 1), 10, Delivery.CARRY, ((0, 1e9), (1, 1e9)))
    assert commit_candidate(candidate, satellites, parameters) == (Status.NO_ENERGY, 0)
    assert [sat.battery_wh for sat in satellites] == before
    assert all(sat.storage_used_mbit == 0 for sat in satellites)


def test_station_capacity_admits_whole_chunks_in_order():
    parameters = Parameters(interval_minutes=1, link_bandwidth_mbps=1, ground_station_capacity_mbps=3)
    accepted, demand = station_admission([0, 0, 0, 0, 0, 0, None], parameters)
    assert accepted == [True, True, True, False, False, False, False]
    assert demand[0] == 6
    assert sum(accepted) * parameters.chunk_mbit == parameters.station_capacity_mbit
