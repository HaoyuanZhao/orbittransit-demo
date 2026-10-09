"""CSV summaries and small static figures; also supports replotting a saved run."""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .config import STRATEGIES


METHODS = {
    "shortest_isl": {"name": "Shortest ISL + nearest GS", "short": "Shortest ISL",
                     "color": "#dd8452", "hatch": "//"},
    "orbittransit": {"name": "OrbitTransit", "short": "OrbitTransit",
                     "color": "#4c72b0", "hatch": ""},
}
TASK_COLUMNS = ["strategy", "step", "elapsed_minutes", "task_id", "source_lat", "source_lon",
                "deadline_minutes", "station_id", "status", "method", "path", "isl_hops",
                "estimated_delivery_minutes", "modeled_energy_wh"]
STATION_COLUMNS = ["strategy", "step", "elapsed_minutes", "station_id", "station_name", "lat", "lon",
                   "assigned_tasks", "scheduled_tasks", "assigned_load_ratio", "capacity_mbps"]


def summarize(tasks):
    rows = []
    for strategy in STRATEGIES:
        selected = tasks[tasks.strategy == strategy]
        if selected.empty:
            continue
        successful = selected[selected.status == "success"]
        rows.append({
            "strategy": strategy, "input_tasks": len(selected),
            "scheduled_tasks": len(successful), "failed_tasks": len(selected) - len(successful),
            "scheduled_fraction": len(successful) / len(selected),
            "mean_delivery_minutes_successful": successful.estimated_delivery_minutes.mean(),
            "carry_tasks_successful": int((successful.method == "carry").sum()),
            "isl_hops_successful": int(successful.isl_hops.sum()),
            "modeled_energy_wh": successful.modeled_energy_wh.sum(),
        })
    return pd.DataFrame(rows)


def save_tables(result, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    tasks = pd.DataFrame(result["tasks"], columns=TASK_COLUMNS)
    stations = pd.DataFrame(result["stations"], columns=STATION_COLUMNS)
    resources = pd.DataFrame(result["resources"])
    summary = summarize(tasks)
    for name, data in (("tasks", tasks), ("stations", stations), ("resources", resources), ("summary", summary)):
        data.to_csv(directory / f"{name}.csv", index=False)
    return summary


def plot_comparison(directory):
    directory = Path(directory)
    summary = pd.read_csv(directory / "summary.csv").set_index("strategy")
    stations = pd.read_csv(directory / "stations.csv")
    methods = [method for method in STRATEGIES if method in summary.index]
    colors = [METHODS[method]["color"] for method in methods]
    labels = [METHODS[method]["short"] for method in methods]
    style = {"font.size": 11, "axes.titlesize": 12, "axes.spines.top": False,
             "axes.spines.right": False, "axes.edgecolor": ".8", "grid.color": ".85",
             "grid.linestyle": ":", "pdf.fonttype": 42, "ps.fonttype": 42}
    with plt.rc_context(style):
        fig, axes = plt.subplots(1, 3, figsize=(12, 3.6), layout="constrained")
        for axis in axes:
            axis.set_axisbelow(True)
            axis.grid(axis="y")
        values = summary.loc[methods, "scheduled_fraction"].to_numpy() * 100
        axes[0].bar(labels, values, color=colors, width=.58)
        axes[0].set(title="Delivery plans within deadline", ylabel="Scheduled / input tasks (%)", ylim=(0, 112))
        for index, value in enumerate(values):
            axes[0].text(index, value + 2, f"{value:.1f}%", ha="center")
        latencies = summary.loc[methods, "mean_delivery_minutes_successful"].to_numpy()
        axes[1].bar(labels, np.nan_to_num(latencies), color=colors, width=.58)
        axes[1].set(title="Estimated delivery time", ylabel="Mean over successful plans (min)")
        ymax = max(6, float(np.nanmax(latencies)) * 1.25) if np.any(np.isfinite(latencies)) else 6
        axes[1].set_ylim(0, ymax)
        for index, value in enumerate(latencies):
            label = f"{value:.1f}" if np.isfinite(value) else "No successful plans"
            axes[1].text(index, (value if np.isfinite(value) else 0) + ymax * .03, label, ha="center", fontsize=10)
        if not stations.empty:
            names = stations.drop_duplicates("station_id").sort_values("station_id").station_name.tolist()
            positions = np.arange(len(names))
            width = .7 / len(methods)
            for index, method in enumerate(methods):
                selected = stations[stations.strategy == method]
                load = selected.groupby("station_id").assigned_load_ratio.mean().to_numpy()
                offset = (index - (len(methods) - 1) / 2) * width
                axes[2].bar(positions + offset, load, width=width, color=METHODS[method]["color"],
                            hatch=METHODS[method]["hatch"], label=METHODS[method]["short"])
            axes[2].axhline(1, color=".35", linestyle="--", linewidth=1)
            axes[2].set_xticks(positions, names)
            axes[2].legend(fontsize=9, loc="upper right")
        else:
            axes[2].text(.5, .5, "No ground stations configured", ha="center", transform=axes[2].transAxes)
        axes[2].set(title="Ground-station demand", ylabel="Mean assigned demand / capacity", ylim=(0, None))
        fig.savefig(directory / "comparison.png", dpi=180)
        fig.savefig(directory / "comparison.pdf")
        plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Regenerate figures from saved OrbitTransit CSV output")
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    plot_comparison(args.directory)


if __name__ == "__main__":
    main()
