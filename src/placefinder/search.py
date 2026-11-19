from itertools import product
from hashlib import file_digest, sha256
import json
from pathlib import Path
import os
from tempfile import NamedTemporaryFile
import time

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from dopplertrack.audio import Spectrogram
from dopplertrack.geo import lla_to_enu
from dopplertrack.search import DayIndex, pair_join, single_join
from dopplertrack.terrain import Terrain

from .inputs import plt, read_json, write_json


def curve(seg, observer, c, delay, wind=(0.0, 0.0), velocity=None):
    q = seg.enu - observer
    distance = np.linalg.norm(q, axis=1)
    if np.min(distance) < 1:
        return None
    if velocity is None:
        velocity = np.gradient(seg.enu, seg.t, axis=0)
    dot = np.sum(velocity * q, axis=1)
    if any(wind):
        w = np.array([*wind, 0.0])
        den = c * c - w @ w
        # Solve |q + wind * travel| = c * travel, then differentiate in emission time.
        projection = q @ w
        root = np.sqrt(projection**2 + den * distance**2)
        travel = (projection + root) / den
        rate = (dot + travel * (velocity @ w)) / root
    else:
        travel = distance / c
        rate = dot / (distance * c)
    arrival = seg.t + travel if delay else seg.t
    if np.any(np.diff(arrival) <= 0) or np.any(rate <= -1):
        return None
    i = distance.argmin()
    if i == 0 or i == len(distance) - 1:
        return None
    return arrival, 1 / (1 + rate), arrival[i], distance[i], seg.speed[i]


def event_scores(sp, event, prediction, starts):
    times = np.linspace(*event["window"], 64)
    freqs = event["f0"] * np.linspace(0.96, 1.04, 9)
    arrival, ratio = prediction[:2]
    model = np.interp(
        starts[:, None] + times, arrival, ratio, left=np.nan, right=np.nan
    )
    f = model[:, None, :] * freqs[None, :, None]
    t = np.broadcast_to(times, f.shape)
    mid = sp.sample(t, f, fill=np.nan)
    sides = (sp.sample(t, f - 4, fill=np.nan) + sp.sample(t, f + 4, fill=np.nan)) / 2
    contrast = mid - sides
    coverage = np.isfinite(contrast).mean(axis=2)
    scores = np.where(coverage >= 0.8, np.nan_to_num(contrast).mean(axis=2), -np.inf)
    j = scores.argmax(axis=1)
    i = np.arange(len(starts))
    return scores[i, j], freqs[j], coverage[i, j]


def search(
    spec,
    events,
    day,
    out,
    *,
    bbox=None,
    point=None,
    utc=None,
    uncertainty=1.0,
    gap_tol=5.0,
    spacing=200.0,
    ground=0.0,
    mic_height=0.0,
    dem=False,
    c=343.0,
    delay=True,
    quiet=None,
    refine=True,
    cache=None,
    wind=(0.0, 0.0),
):
    started = time.perf_counter()
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if len(events) not in (1, 2) or (len(events) == 1) != (utc is not None):
        raise ValueError(
            "use one event with UTC start, or two ordered events without UTC"
        )
    if (point is None) == (bbox is None):
        raise ValueError("select a point or bounding box")
    if not (
        spacing > 0
        and c > 250
        and np.hypot(*wind) < c
        and 0 <= uncertainty <= 120
        and gap_tol >= 0
    ):
        raise ValueError("invalid spacing, sound speed, or clock tolerance")
    ev = [read_json(p) for p in events]
    for e in ev:
        bounds = [
            *e["window"],
            *e["band"],
            e["speed"],
            e["distance"],
            e["f0"],
            e["heard"],
        ]
        if (
            not np.isfinite(bounds).all()
            or min(e["speed"], e["distance"], e["f0"]) <= 0
            or not e["window"][0] <= e["heard"] <= e["window"][1]
            or not e["band"][0] < e["band"][1]
        ):
            raise ValueError("invalid event fit or time/frequency bounds")
    if len(ev) == 2 and ev[0]["window"][1] >= ev[1]["window"][0]:
        raise ValueError("events must be separate and in recording order")
    sp, idx = Spectrogram.load(spec), DayIndex.load(day)
    with np.load(spec) as data:
        cuts = data.get("cut_times_s", [])
    if any(ev[0]["window"][0] <= cut <= ev[-1]["window"][1] for cut in cuts):
        raise ValueError("marked events cross a declared recording discontinuity")
    if any(not sp.t[0] <= e["window"][0] < e["window"][1] <= sp.t[-1] for e in ev):
        raise ValueError("event falls outside the spectrogram")
    if point is not None:
        south, west = point
        if not (-89 < south < 89 and -180 <= west <= 180):
            raise ValueError("invalid regional latitude or longitude")
        north, east = point
    else:
        south, north, west, east = bbox
        if not (-89 < south < north < 89 and -180 <= west < east <= 180):
            raise ValueError("expected a regional box: south north west east")
    metres_lat = 111320.0
    metres_lon = metres_lat * np.cos(np.deg2rad((south + north) / 2))
    terrain = Terrain().elevation if dem else None
    speeds = [(e["speed"] * 0.55, e["speed"] * 1.45) for e in ev]
    ranges = [(e["distance"] * 0.35, e["distance"] * 2.7) for e in ev]
    heard_gap = ev[-1]["heard"] - ev[0]["heard"]
    mask = idx.sample_mask_in_bbox([south, north, west, east], ranges[0][1] + 2000)
    # Join in emission time when running the no-delay control.
    join_c = c if delay else 1e15
    if len(ev) == 1:
        pairs = single_join(
            idx,
            utc + ev[0]["heard"],
            speeds[0],
            ranges[0],
            uncertainty + gap_tol,
            join_c,
            a_mask=mask,
        )
        groups = [(int(i),) for i in pairs.seg1.unique()]
    else:
        pairs = pair_join(
            idx,
            heard_gap,
            speeds[0],
            ranges[0],
            speeds[1],
            ranges[1],
            gap_tol,
            join_c,
            a_mask=mask,
        )
        groups = [
            (int(i), int(j))
            for i, j in pairs[["seg1", "seg2"]].drop_duplicates().to_numpy()
            if i != j and idx.icao[i] != idx.icao[j]
        ]
    rows, visited = [], set()
    segments = sorted({s for g in groups for s in g})
    velocities = {
        s: np.gradient(idx.segs[s].enu, idx.segs[s].t, axis=0) for s in segments
    }
    offsets = np.linspace(
        -uncertainty, uncertainty, 1 + int(np.ceil(uncertainty * 2 / 0.5))
    )

    def evaluate(x, y):
        key = (round(x, 3), round(y, 3))
        if key in visited:
            return
        visited.add(key)
        lat, lon = south + y / metres_lat, west + x / metres_lon
        if not (south <= lat <= north and west <= lon <= east):
            return
        alt = (
            float(terrain(np.array([lat]), np.array([lon]))[0]) if terrain else ground
        ) + mic_height
        obs = lla_to_enu(lat, lon, alt, idx.lat0, idx.lon0)
        predictions = {
            s: curve(idx.segs[s], obs, c, delay, wind, velocities[s]) for s in segments
        }
        for group in groups:
            pred = [predictions[s] for s in group]
            if any(
                p is None or not (r[0] <= p[3] <= r[1] and v[0] <= p[4] <= v[1])
                for p, r, v in zip(pred, ranges, speeds)
            ):
                continue
            start0 = pred[0][2] - ev[0]["heard"]
            if len(ev) == 1 and abs(start0 - utc) > uncertainty + gap_tol:
                continue
            if len(ev) == 2 and abs(pred[1][2] - pred[0][2] - heard_gap) > gap_tol:
                continue
            starts = (utc if utc is not None else start0) + offsets
            scores = [event_scores(sp, e, p, starts) for e, p in zip(ev, pred)]
            # Both events must support the same clock.
            combined = np.min([s[0] for s in scores], axis=0)
            if not np.any(np.isfinite(combined)):
                continue
            k = combined.argmax()
            score = combined[k]
            if quiet:
                for i, seg in enumerate(idx.segs):
                    if i not in group:
                        q = curve(seg, obs, c, delay, wind)
                        if (
                            q
                            and quiet[0] <= q[2] - starts[k] <= quiet[1]
                            and q[3] < max(p[3] for p in pred)
                        ):
                            score -= 1.0
            row = dict(
                lat=lat,
                lon=lon,
                height_m=alt,
                x=x,
                y=y,
                score=score,
                start_utc_s=starts[k],
            )
            for n, (s, values) in enumerate(zip(group, scores), 1):
                row.update(
                    {
                        f"flight{n}": idx.icao[s],
                        f"segment{n}": s,
                        f"event{n}_db": values[0][k],
                        f"tone{n}_hz": values[1][k],
                        f"coverage{n}": values[2][k],
                    }
                )
            rows.append(row)

    cache_file = None
    if cache is not None:
        if dem:
            raise ValueError(
                "coarse cache requires fixed ground height so its inputs are reproducible"
            )
        digest = sha256(
            json.dumps(
                [
                    ev,
                    bbox,
                    point,
                    utc,
                    uncertainty,
                    gap_tol,
                    spacing,
                    ground,
                    mic_height,
                    c,
                    delay,
                    quiet,
                    wind,
                ],
                sort_keys=True,
            ).encode()
        )
        for path in (spec, day, __file__):
            with open(path, "rb") as f:
                digest.update(file_digest(f, "sha256").digest())
        Path(cache).mkdir(parents=True, exist_ok=True)
        cache_file = Path(cache) / (digest.hexdigest() + ".json")
    cache_hit = cache_file is not None and cache_file.exists()
    if cache_hit:
        saved = read_json(cache_file)
        rows = saved["rows"]
        visited.update(map(tuple, saved["visited"]))
    else:
        for x, y in product(
            np.arange(0, (east - west) * metres_lon + 0.001, spacing),
            np.arange(0, (north - south) * metres_lat + 0.001, spacing),
        ):
            evaluate(x, y)
        if cache_file:
            with NamedTemporaryFile(mode="w", dir=cache_file.parent, delete=False) as f:
                json.dump(dict(rows=rows, visited=sorted(visited)), f, allow_nan=False)
            os.replace(f.name, cache_file)
    coarse_count = len(rows)
    if refine and rows and bbox:
        for step in (spacing / 2, spacing / 4):
            seeds = []
            for r in sorted(rows, key=lambda v: -v["score"]):
                if all(np.hypot(r["x"] - x, r["y"] - y) > 2 * step for x, y in seeds):
                    seeds.append((r["x"], r["y"]))
                if len(seeds) == 4:
                    break
            for (x, y), dx, dy in product(seeds, range(-2, 3), range(-2, 3)):
                evaluate(x + dx * step, y + dy * step)
    columns = ["lat", "lon", "height_m", "x", "y", "score", "start_utc_s"]
    for n in range(1, len(ev) + 1):
        columns.extend(
            [f"flight{n}", f"segment{n}", f"event{n}_db", f"tone{n}_hz", f"coverage{n}"]
        )
    frame = (
        pd.DataFrame(rows, columns=columns)
        .sort_values("score", ascending=False)
        .reset_index(drop=True)
    )
    frame["cluster"] = 0
    verdict = "insufficient evidence"
    leaders = []
    flights = [f"flight{n + 1}" for n in range(len(ev))]
    if len(frame):
        near = frame[frame.score >= max(3.0, frame.score.iloc[0] - 2.0)]
        for _, part in near.groupby(flights):
            xy = part[["x", "y"]].to_numpy()
            tree = cKDTree(xy)
            remaining = set(range(len(xy)))
            while remaining:
                component = [remaining.pop()]
                for i in component:
                    neighbors = remaining.intersection(
                        tree.query_ball_point(xy[i], spacing * 1.5)
                    )
                    remaining.difference_update(neighbors)
                    component.extend(neighbors)
                ids = part.index[component]
                leaders.append(int(ids.min()))
                frame.loc[ids, "cluster"] = len(leaders)
        if leaders:
            spread = max(np.hypot(near.x - near.x.iloc[0], near.y - near.y.iloc[0]))
            verdict = "ambiguous" if len(leaders) > 1 or spread > 250 else "candidate"
    frame["verdict"] = verdict
    frame.to_csv(out / "results.csv", index=False)
    frame.drop_duplicates(flights).to_csv(out / "ranked-flights.csv", index=False)
    features = [
        dict(
            type="Feature",
            geometry=dict(type="Point", coordinates=[r["lon"], r["lat"]]),
            properties=r,
        )
        for r in frame.to_dict("records")
    ]
    write_json(
        out / "results.geojson", dict(type="FeatureCollection", features=features)
    )
    for name in ["winner.png", "runner-up.png"]:
        (out / name).unlink(missing_ok=True)
    if len(frame):
        other = next((i for i in sorted(leaders) if i != 0), None)
        if other is None:
            distinct = frame.drop_duplicates(flights)
            other = distinct.index[1] if len(distinct) > 1 else None
        for name, i in zip(["winner", "runner-up"], [0, other]):
            if i is None:
                continue
            row = frame.iloc[i]
            obs = lla_to_enu(row.lat, row.lon, row.height_m, idx.lat0, idx.lon0)
            fig, axes = plt.subplots(
                1,
                len(ev),
                squeeze=False,
                figsize=(6 * len(ev), 4),
                layout="constrained",
            )
            for n, (e, ax) in enumerate(zip(ev, axes[0]), 1):
                w = sp.crop(*e["window"], *e["band"])
                ax.pcolormesh(
                    w.t, w.f, w.S, vmin=0, vmax=15, shading="auto", cmap="magma"
                )
                p = curve(idx.segs[int(row[f"segment{n}"])], obs, c, delay, wind)
                ax.plot(*np.array(e["points"]).T, "w:", label="Observed ridge")
                ax.plot(
                    p[0] - row.start_utc_s,
                    p[1] * row[f"tone{n}_hz"],
                    "c-",
                    label="Flight prediction",
                )
                ax.set(
                    xlim=e["window"],
                    ylim=e["band"],
                    xlabel="Clip time (s)",
                    ylabel="Frequency (Hz)",
                    title=f"{row[f'flight{n}']} at {row.lat:.5f}, {row.lon:.5f}",
                )
                ax.legend()
            fig.savefig(out / f"{name}.png")
            plt.close(fig)
    summary = dict(
        verdict=verdict,
        flight_groups=len(groups),
        evaluated_points=len(visited),
        coarse_matches=coarse_count,
        coarse_cache_hit=cache_hit,
        scored_rows=len(frame),
        clusters=len(leaders),
        elapsed_s=round(time.perf_counter() - started, 3),
    )
    write_json(out / "summary.json", summary)
    return frame, summary
