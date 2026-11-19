import json
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from scipy.signal import stft
from dopplertrack.adsb import Trace
from dopplertrack.audio import Spectrogram
from dopplertrack.doppler import ideal_curve
from dopplertrack.search import DayIndex
from dopplertrack.tracks import ridge


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False), encoding="utf-8")


def prepare(manifest, out):
    meta = read_json(manifest)
    media = Path(manifest).parent / meta["source"]
    stream, channel = meta.get("audio_stream", 0), meta.get("channel", 0)
    streams = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_streams",
                "-of",
                "json",
                str(media),
            ]
        )
    )["streams"]
    if not 0 <= stream < len(streams) or not 0 <= channel < streams[stream]["channels"]:
        raise ValueError("selected stream or channel is missing")
    sr, window, hop = 2000, 4096, 400
    raw = subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(media),
            "-map",
            f"0:a:{stream}",
            "-af",
            f"pan=mono|c0=c{channel}",
            "-ar",
            str(sr),
            "-f",
            "f32le",
            "-",
        ]
    )
    x = np.frombuffer(raw, "<f4")
    if len(x) < window + hop:
        raise ValueError("recording too short for two STFT frames")
    # Block the transform to bound temporary memory on hour-long recordings.
    power = []
    for start in range(0, len(x) - window + 1, 1000 * hop):
        block = x[start : start + 999 * hop + window]
        f, _, z = stft(
            block,
            sr,
            nperseg=window,
            noverlap=window - hop,
            boundary=None,
            padded=False,
        )
        band = (f >= 40) & (f <= 450)
        power.append(10 * np.log10(np.maximum(abs(z[band]) ** 2, 1e-20)))
    raw_db = np.concatenate(power, axis=1)
    t = (window / 2 + np.arange(raw_db.shape[1]) * hop) / sr
    clean = raw_db - np.median(raw_db, axis=1, keepdims=True)
    cuts = np.asarray(meta.get("discontinuities", []), float)
    if cuts.ndim != 1 or not np.all((cuts >= 0) & (cuts < len(x) / sr)):
        raise ValueError("discontinuities must be clip times in seconds")
    np.savez_compressed(out, t=t, f=f[band], S=clean, raw_db=raw_db, cut_times_s=cuts)
    fig, axes = plt.subplots(2, 1, sharex=True, figsize=(10, 6), layout="constrained")
    for ax, values, title in zip(
        axes, [raw_db, clean], ["Raw power (dB)", "Above frequency median (dB)"]
    ):
        stride = max(1, len(t) // 1600)
        im = ax.pcolormesh(
            t[::stride],
            f[band],
            values[:, ::stride],
            shading="auto",
            rasterized=True,
            vmin=np.percentile(values, 10),
            vmax=np.percentile(values, 99),
        )
        ax.set_ylabel("Frequency (Hz)")
        fig.colorbar(im, ax=ax, label=title)
    axes[-1].set_xlabel("Clip time (s)")
    fig.savefig(Path(out).with_suffix(".png"))
    plt.close(fig)
    write_json(
        Path(out).with_suffix(".json"),
        dict(
            meta,
            source_sample_rate=int(streams[stream]["sample_rate"]),
            decoded_sample_rate=sr,
            duration_s=len(x) / sr,
            audio_stream=stream,
            channel=channel,
        ),
    )


def index_tracks(csv, out):
    df = pd.read_csv(csv, dtype={"flight": str, "segment": str}, keep_default_na=False)
    cols = ["utc_s", "lat", "lon", "alt_m"]
    required = {"flight", "segment", "alt_reference", "alt_source", *cols}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(
            "Flight tracks CSV is missing columns: " + ", ".join(sorted(missing))
        )
    df[cols] = df[cols].apply(pd.to_numeric)
    if (
        not np.isfinite(df[cols].to_numpy(dtype=float)).all()
        or not (df.lat.between(-90, 90) & df.lon.between(-180, 180)).all()
    ):
        raise ValueError("invalid track coordinate or time")
    if set(df.alt_reference) != {"MSL"} or (df.alt_source == "").any():
        raise ValueError(
            "convert heights to a common MSL reference and label altitude source"
        )
    traces = []
    for (flight, _), rows in df.groupby(["flight", "segment"]):
        rows = rows.sort_values("utc_s", kind="stable").drop_duplicates("utc_s")
        for _, part in rows.groupby(rows.utc_s.diff().gt(20).cumsum()):
            t, lat, lon, alt = part[cols].to_numpy().T
            if len(t) >= 2 and t[-1] - t[0] >= 20:
                traces.append(
                    Trace(
                        flight,
                        None,
                        None,
                        None,
                        t,
                        lat,
                        lon,
                        alt,
                        np.full(len(t), np.nan),
                        np.zeros(len(t), bool),
                    )
                )
    if not traces:
        raise ValueError("no continuous track of at least 20 seconds")
    DayIndex.build(traces).save(out)


def mark(spec, window, band, out, points=None):
    sp = spec if isinstance(spec, Spectrogram) else Spectrogram.load(spec)
    sp = sp.crop(*window, *band)
    if min(sp.S.shape) < 5:
        raise ValueError(
            "event window must contain at least five frames and frequency bins"
        )
    if points:
        t, hz = np.asarray(read_json(points), float).T
        if (
            len(t) < 5
            or not np.isfinite([t, hz]).all()
            or np.any(np.diff(t) <= 0)
            or t.min() < window[0]
            or t.max() > window[1]
            or hz.min() < band[0]
            or hz.max() > band[1]
        ):
            raise ValueError(
                "ridge needs five ordered finite points in the selected window and band"
            )
    else:
        t, hz = sp.t, ridge(sp)
    c = 343.0

    def residual(p):
        f0, v, d, heard = p
        return (
            ideal_curve(t, f0, v, d, heard - d / c, c, span=max(600, np.ptp(t) + 200))
            - hz
        )

    fit = least_squares(
        residual,
        [np.median(hz), 90, 1000, np.median(t)],
        bounds=([band[0], 15, 30, window[0]], [band[1], 250, 18000, window[1]]),
        loss="soft_l1",
        x_scale="jac",
    )
    f0, speed, distance, heard = fit.x
    write_json(
        out,
        dict(
            window=window,
            band=band,
            points=np.column_stack([t, hz]).tolist(),
            f0=f0,
            speed=speed,
            distance=distance,
            heard=heard,
        ),
    )
