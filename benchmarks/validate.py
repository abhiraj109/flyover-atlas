"""Rebuild the synthetic recording independently of the search and exercise its controls."""

import argparse
import time
import tracemalloc
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.io.wavfile import write
from dopplertrack.geo import enu_to_lla, haversine_m

from placefinder.inputs import index_tracks, mark, prepare, read_json, write_json
from placefinder.search import search

START = 1700000000.0
TRUTH = (35.0048, -100.0034)
BOX = (34.999, 35.011, -100.011, -99.995)
TOLERANCE_M = 250


def fixture(folder):
    folder.mkdir(exist_ok=True, parents=True)
    sr = 2000
    times = np.arange(240 * sr) / sr
    noise = np.random.default_rng(421).normal(0, 0.025, len(times))
    audio = noise.copy()
    variable = noise.copy()
    rows = []
    for ident, center, v, side, alt, f0 in [
        ("alpha", 55, 87, 370, 520, 124),
        ("bravo", 175, 66, 480, 620, 163),
        ("decoy", 178, 88, 1200, 1150, 0),
    ]:
        te = np.arange(center - 48, center + 49, 0.02)
        tau = te - center
        along = v * tau
        cross = side + 0.20 * tau**2
        r = np.sqrt(along**2 + cross**2 + alt**2)
        arrival = te + r / 343
        if f0:
            # A constant emitted phase evaluated at the inverse arrival-time map.
            emission = np.interp(times, arrival, te, left=np.nan, right=np.nan)
            audio += (
                0.25
                * np.nan_to_num(np.sin(2 * np.pi * f0 * emission))
                * np.exp(-(((times - center) / 30) ** 2))
            )
            # +/-2% RPM modulation with a twenty-second period.
            phase = 2 * np.pi * f0 * emission - 0.4 * f0 * np.cos(
                2 * np.pi * emission / 20
            )
            variable += (
                0.25
                * np.nan_to_num(np.sin(phase))
                * np.exp(-(((times - center) / 30) ** 2))
            )
        take = np.arange(0, len(te), 100)
        e, n = (along, cross) if ident == "alpha" else (cross, along)
        lat, lon, height = enu_to_lla(e[take], n[take], np.full(len(take), alt), *TRUTH)
        rows.extend(zip([ident] * len(take), te[take] + START, lat, lon, height))
    df = pd.DataFrame(rows, columns=["flight", "utc_s", "lat", "lon", "alt_m"])
    df.assign(segment="pass", alt_reference="MSL", alt_source="simulated").to_csv(
        folder / "tracks.csv", index=False
    )
    for name, x in [("clean", audio), ("noise", noise), ("rpm", variable)]:
        write(folder / f"{name}.wav", sr, (x * 32767).astype(np.int16))
        manifest = folder / f"{name}.json"
        write_json(
            manifest,
            dict(
                source=f"{name}.wav", channel=0, utc_start_s=START, discontinuities=[]
            ),
        )
        prepare(manifest, folder / f"{name}.npz")
    for i, (window, band) in enumerate(
        [([35, 80], [92, 171]), ([152, 201], [130, 211])], 1
    ):
        mark(folder / "clean.npz", window, band, folder / f"e{i}.json")
    index_tracks(folder / "tracks.csv", folder / "day.npz")
    tracks = pd.read_csv(folder / "tracks.csv")
    tracks[~tracks.utc_s.between(START + 42, START + 70)].to_csv(
        folder / "dropout.csv", index=False
    )
    index_tracks(folder / "dropout.csv", folder / "dropout.npz")


def validate(folder):
    fixture(folder)
    e1, e2 = [folder / f"e{i}.json" for i in [1, 2]]
    changed = read_json(e2)
    changed["heard"] += 30
    changed["window"] = [t + 30 for t in changed["window"]]
    changed["points"] = [[t + 30, hz] for t, hz in changed["points"]]
    write_json(folder / "bad-gap.json", changed)
    results = []
    cases = [
        ("known", dict(point=TRUTH)),
        ("timed", dict(bbox=BOX, utc=START)),
        ("pair", dict(bbox=BOX, cache=folder / "cache")),
        ("noise", dict(bbox=BOX)),
        ("excluded", dict(bbox=(35.06, 35.07, -100.08, -100.07))),
        ("broken-gap", dict(bbox=BOX)),
        ("no-delay", dict(bbox=BOX, delay=False)),
        ("sound-speed", dict(bbox=BOX, c=335.0)),
        ("wind", dict(bbox=BOX, wind=(8.0, -3.0))),
        ("rpm", dict(bbox=BOX)),
        ("dropout", dict(bbox=BOX)),
        ("wider", dict(bbox=(34.99, 35.02, -100.02, -99.985))),
        ("reindexed", dict(bbox=BOX)),
        ("cached", dict(bbox=BOX, cache=folder / "cache")),
    ]
    for name, opts in cases:
        events = (
            [e1]
            if name == "timed"
            else [e1, folder / "bad-gap.json" if name == "broken-gap" else e2]
        )
        index = folder / "day.npz"
        if name == "reindexed":
            index = folder / "fresh.npz"
            index_tracks(folder / "tracks.csv", index)
        if name == "dropout":
            index = folder / "dropout.npz"
        tracemalloc.start()
        start = time.perf_counter()
        frame, info = search(
            folder / (name + ".npz" if name in ("noise", "rpm") else "clean.npz"),
            events,
            index,
            folder / name,
            uncertainty=1,
            **opts,
        )
        peak = tracemalloc.get_traced_memory()[1] / (1024**2)
        tracemalloc.stop()
        flights = [f"flight{i + 1}" for i in range(len(events))]
        ranked = frame.drop_duplicates(flights)
        true = ranked.flight1 == "alpha"
        if len(events) == 2:
            true &= ranked.flight2 == "bravo"
        positions = np.flatnonzero(true)
        best = frame.iloc[0] if len(frame) else None
        error = haversine_m(best.lat, best.lon, *TRUTH) if best is not None else None
        results.append(
            dict(
                case=name,
                verdict=info["verdict"],
                true_rank=int(positions[0] + 1) if len(positions) else None,
                error_m=round(error, 1) if error is not None else None,
                cluster_rows=int((frame.cluster == best.cluster).sum())
                if best is not None and best.cluster
                else 0,
                coverage=min(best[f"coverage{i + 1}"] for i in range(len(events)))
                if best is not None
                else None,
                flight_margin_db=ranked.score.iloc[0] - ranked.score.iloc[1]
                if len(ranked) > 1
                else None,
                points=info["evaluated_points"],
                scored=len(frame),
                seconds=round(time.perf_counter() - start, 2),
                peak_traced_mib=round(peak, 2),
            )
        )
        print(results[-1], flush=True)
        if name == "cached":
            assert info["coarse_cache_hit"]
    metrics = pd.DataFrame(results)
    metrics.to_csv(folder / "metrics.csv", index=False)
    for name in ["known", "timed", "pair"]:
        row = metrics.set_index("case").loc[name]
        assert row.true_rank == 1 and row.error_m <= TOLERANCE_M, row
    for name in ["noise", "excluded", "broken-gap", "dropout"]:
        assert (
            metrics.set_index("case").loc[name, "verdict"] == "insufficient evidence"
        ), name
    assert (folder / "pair/results.csv").read_bytes() == (
        folder / "reindexed/results.csv"
    ).read_bytes()
    assert (folder / "pair/results.csv").read_bytes() == (
        folder / "cached/results.csv"
    ).read_bytes()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    validate(parser.parse_args().out)
