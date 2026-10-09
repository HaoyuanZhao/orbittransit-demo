"""Run one self-contained scenario; no data download or solver is needed."""

import argparse
from dataclasses import asdict
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import time

from . import __version__
from .config import Scenario
from .reporting import plot_comparison, save_tables
from .simulation import run_scenario


def main():
    parser = argparse.ArgumentParser(description="Compare satellite delivery strategies on a synthetic scenario")
    parser.add_argument("--config", type=Path, required=True, help="Scenario JSON file")
    parser.add_argument("--output", type=Path, required=True, help="New or empty result directory")
    args = parser.parse_args()
    try:
        scenario = Scenario.load(args.config)
        if args.output.exists() and (not args.output.is_dir() or any(args.output.iterdir())):
            parser.error("--output must be a new or empty directory; use another directory for a new run")
        started = time.perf_counter()
        result = run_scenario(scenario)
        summary = save_tables(result, args.output)
        plot_comparison(args.output)
        configuration = asdict(scenario)
        source_hash = hashlib.sha256()
        for source in sorted(Path(__file__).parent.glob("*.py")):
            source_hash.update(source.name.encode())
            source_hash.update(source.read_bytes())
        record = {
            "version": __version__, "authority": "demonstration; not full paper reproduction",
            "config": configuration,
            "config_sha256": hashlib.sha256(json.dumps(configuration, sort_keys=True).encode()).hexdigest(),
            "workload_sha256": result["workload_sha256"], "source_sha256": source_hash.hexdigest(),
            "dependencies": {name: version(name) for name in
                             ("ephem", "sgp4", "astropy", "networkx", "geopy", "numpy", "pandas", "matplotlib")},
        }
        (args.output / "run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(summary[["strategy", "input_tasks", "scheduled_tasks", "failed_tasks"]].to_string(index=False))
        print(f"Saved CSV, figures and run metadata to {args.output} ({time.perf_counter() - started:.2f}s)")
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    main()
