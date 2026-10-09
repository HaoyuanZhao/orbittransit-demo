"""Bounded planning scenarios using the extracted OrbitTransit models."""

from collections import Counter
from dataclasses import asdict
import hashlib
import json
import random

import ephem

from .allocation import diffuse_assignment, nearest_assignment, station_admission
from .models import GroundStation, Plan, Status, Task, commit_candidate, observer
from .orbit import build_constellation, build_contact_map, build_graph
from .routing import orbit_transit, shortest_isl


def make_workload(scenario):
    """Generate every deadline before comparing strategies, using a private RNG."""
    rng = random.Random(scenario.seed)
    repeats = max(point.get("tasks_per_step", 1) for point in scenario.sources)
    workload = []
    identifier = 0
    for step in range(scenario.steps):
        tasks = []
        for repeat in range(repeats):
            for point in scenario.sources:
                if repeat < point.get("tasks_per_step", 1):
                    tasks.append(Task(identifier, step, point["lat"], point["lon"],
                                      rng.randint(*scenario.deadline_minutes)))
                    identifier += 1
        workload.append(tasks)
    return workload


def workload_hash(workload):
    payload = [[asdict(task) for task in interval] for interval in workload]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def run_strategy(scenario, workload, strategy):
    parameters = scenario.parameters
    constellation = scenario.constellation
    satellites = build_constellation(constellation, parameters, scenario.start_time)
    start = ephem.Date(scenario.start_time)
    stations = [GroundStation(index, point.get("name", f"GS-{index + 1}"),
                              observer(point["lat"], point["lon"], start))
                for index, point in enumerate(scenario.stations)]
    station_map = {station.id: station for station in stations}
    task_records, station_records, resource_records = [], [], []
    for step, tasks in enumerate(workload):
        date = ephem.Date(start + (step + 1) * parameters.interval_days)
        for satellite in satellites:
            satellite.release_expired(date)
        for station in stations:
            station.point.date = date
        sources = [observer(task.lat, task.lon, date) for task in tasks]
        graph = build_graph(satellites, constellation, parameters, date)
        if strategy == "orbittransit":
            contacts = build_contact_map(satellites, stations, constellation, parameters, date)
            assignments = diffuse_assignment(tasks, sources, stations, satellites, graph, contacts,
                                              constellation, parameters)
        else:
            assignments = nearest_assignment(tasks, stations)
        admitted, station_demand = station_admission(assignments, parameters)
        plans = []
        for index, task in enumerate(tasks):
            station_id = assignments[index]
            if station_id is None:
                plans.append(Plan(task, None, Status.NO_AVAILABLE_STATION))
                continue
            station = station_map[station_id]
            if strategy == "orbittransit":
                candidate, status = orbit_transit(
                    graph, satellites, sources[index], station, contacts, constellation,
                    parameters, date, ephem.Date(date + task.deadline_minutes / 1440))
            else:
                candidate, status = shortest_isl(graph, satellites, sources[index], station, parameters)
            plan = Plan(task, station_id, status, candidate)
            if candidate is not None:
                if candidate.delivery_minutes > task.deadline_minutes + 1e-7:
                    plan.status = Status.DEADLINE_EXCEEDED
                elif not admitted[index]:
                    plan.status = Status.STATION_OVERLOAD
                else:
                    plan.status, plan.energy_wh = commit_candidate(candidate, satellites, parameters)
            plans.append(plan)
        for plan in plans:
            candidate = plan.candidate
            task_records.append({
                "strategy": strategy, "step": step,
                "elapsed_minutes": (step + 1) * parameters.interval_minutes,
                "task_id": plan.task.id, "source_lat": plan.task.lat, "source_lon": plan.task.lon,
                "deadline_minutes": plan.task.deadline_minutes, "station_id": plan.station_id,
                "status": plan.status.value, "method": candidate.method.value if candidate else "",
                "path": json.dumps(candidate.path) if candidate else "[]",
                "isl_hops": len(candidate.path) - 1 if candidate else 0,
                "estimated_delivery_minutes": candidate.delivery_minutes if candidate else None,
                "modeled_energy_wh": plan.energy_wh,
            })
        served = Counter(plan.station_id for plan in plans if plan.status == Status.SUCCESS)
        for station in stations:
            demand = station_demand[station.id]
            station_records.append({
                "strategy": strategy, "step": step,
                "elapsed_minutes": (step + 1) * parameters.interval_minutes,
                "station_id": station.id, "station_name": station.name,
                "lat": float(station.point.lat) * 180 / ephem.pi,
                "lon": float(station.point.lon) * 180 / ephem.pi,
                "assigned_tasks": demand, "scheduled_tasks": served[station.id],
                "assigned_load_ratio": demand * parameters.chunk_mbit / parameters.station_capacity_mbit,
                "capacity_mbps": parameters.ground_station_capacity_mbps,
            })
        for satellite in satellites:
            resource_records.append({
                "strategy": strategy, "step": step, "satellite_id": satellite.id,
                "storage_used_mbit": satellite.storage_used_mbit,
                "storage_capacity_mbit": parameters.storage_mbit,
                "battery_wh": satellite.battery_wh,
            })
            satellite.charge()
    return task_records, station_records, resource_records


def run_scenario(scenario):
    scenario.validate()
    workload = make_workload(scenario)
    tasks, stations, resources = [], [], []
    for strategy in scenario.strategies:
        result = run_strategy(scenario, workload, strategy)
        tasks.extend(result[0])
        stations.extend(result[1])
        resources.extend(result[2])
    return {"tasks": tasks, "stations": stations, "resources": resources,
            "workload_sha256": workload_hash(workload)}
