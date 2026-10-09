from dataclasses import replace
from pathlib import Path
import json
import subprocess
import sys

import pytest

from orbittransit.config import Constellation, Parameters, Scenario
from orbittransit.simulation import make_workload, run_scenario, workload_hash


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.mark.parametrize("filename", ["demo.json", "higher_capacity.json"])
def test_examples_share_inputs_and_obey_resource_limits(filename):
    scenario = Scenario.load(EXAMPLES / filename)
    result = run_scenario(scenario)
    tasks = result["tasks"]
    assert len(tasks) == 240
    left = [(row["task_id"], row["deadline_minutes"], row["source_lat"], row["source_lon"])
            for row in tasks if row["strategy"] == "shortest_isl"]
    right = [(row["task_id"], row["deadline_minutes"], row["source_lat"], row["source_lon"])
             for row in tasks if row["strategy"] == "orbittransit"]
    assert left == right
    for row in tasks:
        if row["status"] == "success":
            assert row["estimated_delivery_minutes"] <= row["deadline_minutes"] + 1e-7
    assert all(0 <= row["storage_used_mbit"] <= row["storage_capacity_mbit"] for row in result["resources"])
    assert all(0 <= row["battery_wh"] <= scenario.parameters.battery_capacity_wh for row in result["resources"])
    assert all(row["scheduled_tasks"] * scenario.parameters.chunk_mbit <= scenario.parameters.station_capacity_mbit
               for row in result["stations"])


def test_capacity_variant_changes_only_capacity_and_preserves_workload():
    first = json.loads((EXAMPLES / "demo.json").read_text())
    second = json.loads((EXAMPLES / "higher_capacity.json").read_text())
    assert first["parameters"]["ground_station_capacity_mbps"] == 10000
    assert second["parameters"]["ground_station_capacity_mbps"] == 20000
    second["parameters"]["ground_station_capacity_mbps"] = 10000
    assert first == second
    assert workload_hash(make_workload(Scenario.from_dict(first))) == workload_hash(
        make_workload(Scenario.load(EXAMPLES / "higher_capacity.json")))


def tiny_scenario():
    return Scenario(name="tiny", stations=(), sources=({"lat": 0, "lon": 0},),
                    constellation=Constellation(planes=3, satellites_per_plane=3), steps=1)


def test_empty_station_list_produces_task_failures():
    result = run_scenario(tiny_scenario())
    assert len(result["tasks"]) == 2
    assert all(row["status"] == "no_available_station" for row in result["tasks"])


def test_no_ground_links_produces_task_failures():
    scenario = replace(tiny_scenario(), stations=({"lat": 0, "lon": 0, "name": "GS"},),
                       parameters=Parameters(max_ground_link_km=0))
    result = run_scenario(scenario)
    assert all(row["status"] == "no_reachable_satellite" for row in result["tasks"])


def test_exhausted_admission_capacity_is_reported():
    scenario = replace(tiny_scenario(), stations=({"lat": 0, "lon": 0, "name": "GS"},),
                       parameters=Parameters(ground_station_capacity_mbps=1), strategies=("orbittransit",))
    result = run_scenario(scenario)
    assert result["tasks"][0]["status"] == "no_available_station"


def test_repeated_scenario_has_identical_business_results():
    scenario = replace(Scenario.load(EXAMPLES / "demo.json"), steps=1)
    assert run_scenario(scenario) == run_scenario(scenario)


def test_cli_runs_from_another_directory_and_refuses_overwrite(tmp_path):
    configuration = tmp_path / "small.json"
    configuration.write_text(json.dumps({"name": "empty_stations", "stations": [],
                                         "sources": [{"lat": 0, "lon": 0}], "steps": 1,
                                         "constellation": {"planes": 3, "satellites_per_plane": 3}}))
    output = tmp_path / "output"
    command = [sys.executable, "-m", "orbittransit", "--config", str(configuration), "--output", str(output)]
    completed = subprocess.run(command, cwd=tmp_path, text=True, capture_output=True)
    assert completed.returncode == 0, completed.stderr
    for filename in ("tasks.csv", "stations.csv", "resources.csv", "summary.csv", "run.json", "comparison.png", "comparison.pdf"):
        assert (output / filename).is_file()
    metadata = json.loads((output / "run.json").read_text())
    assert metadata["config"]["name"] == "empty_stations"
    assert "workload_sha256" in metadata and "source_sha256" in metadata
    assert subprocess.run(command, cwd=tmp_path, capture_output=True).returncode != 0


@pytest.mark.parametrize("field,value", [("steps", 0), ("strategies", ["unknown"]),
                                         ("parameters", {"ground_station_capacity_mbps": 0})])
def test_invalid_configuration_is_rejected(field, value):
    data = json.loads((EXAMPLES / "demo.json").read_text())
    data[field] = value
    with pytest.raises(ValueError):
        Scenario.from_dict(data)
