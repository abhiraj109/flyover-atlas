"""Evaluate the public recording after preparing its spectrogram and regional day index."""

import argparse
from pathlib import Path
import tracemalloc

import numpy as np
import pandas as pd
from dopplertrack.geo import haversine_m

from placefinder.search import search


def benchmark(folder, inputs):
    reference = (40.876466, -73.524951)
    cases = {
        "known": dict(point=reference),
        "regional": dict(bbox=(40.865, 40.890, -73.541, -73.510)),
        "wider": dict(bbox=(40.853, 40.902, -73.556, -73.495)),
    }
    metrics = []
    for name, area in cases.items():
        tracemalloc.start()
        frame, summary = search(
            folder / "spec.npz",
            [inputs / "event1.json", inputs / "event2.json"],
            folder / "day.npz",
            folder / name,
            uncertainty=6,
            gap_tol=10,
            dem=True,
            **area,
        )
        peak = tracemalloc.get_traced_memory()[1] / 1024**2
        tracemalloc.stop()
        groups = frame.drop_duplicates(["flight1", "flight2"])
        true = np.flatnonzero(
            (groups.flight1 == "a1dfeb") & (groups.flight2 == "ace391")
        )
        metric = dict(
            case=name,
            **summary,
            peak_traced_mib=round(peak, 2),
            true_rank=int(true[0] + 1) if len(true) else None,
        )
        if len(frame):
            best = frame.iloc[0]
            cluster = frame[(frame.cluster == best.cluster) & (frame.cluster > 0)]
            metric.update(
                error_m=round(haversine_m(best.lat, best.lon, *reference), 1),
                footprint_points=len(cluster),
                radius_m=round(
                    np.hypot(cluster.x - best.x, cluster.y - best.y).max(), 1
                )
                if len(cluster)
                else None,
                margin_db=round(best.score - groups.score.iloc[1], 2)
                if len(groups) > 1
                else None,
                coverage=min(best.coverage1, best.coverage2),
            )
        metrics.append(metric)
        print(metric, flush=True)
    pd.DataFrame(metrics).to_csv(folder / "metrics.csv", index=False)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("run_folder", type=Path)
    p.add_argument("inputs", type=Path)
    args = p.parse_args()
    benchmark(args.run_folder, args.inputs)
