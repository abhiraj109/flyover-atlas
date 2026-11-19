import numpy as np
from dopplertrack.search import Segment
from placefinder.search import curve
from placefinder.inputs import index_tracks
from dopplertrack.search import DayIndex
import pandas as pd


def test_doppler_and_travel_time():
    t = np.arange(-20.0, 21.0)
    xyz = np.stack([90 * t, np.zeros(len(t)), np.full(len(t), 520)], axis=1)
    segment = Segment(0, "test", t, xyz, np.full(len(t), 90.0))
    arrival, ratio, cpa, d, v = curve(segment, np.zeros(3), 343, True)
    r = np.hypot(90 * t, 520)
    np.testing.assert_allclose(arrival, t + r / 343)
    np.testing.assert_allclose(ratio, 343 / (343 + 90**2 * t / r))
    assert ratio[0] > 1 > ratio[-1] and ratio[20] == 1 and cpa == 520 / 343
    assert (d, v) == (520, 90)


def test_track_gaps_and_duplicate_fixes(tmp_path):
    t = [120, 0, 10, 10, 20, 100, 110]
    df = pd.DataFrame(
        dict(
            utc_s=t,
            flight="000012",
            segment="a",
            lat=10.0,
            lon=30.0,
            alt_m=600.0,
            alt_reference="MSL",
            alt_source="simulated",
        )
    )
    csv = tmp_path / "tracks.csv"
    df.to_csv(csv, index=False)
    index_tracks(csv, tmp_path / "day.npz")
    index = DayIndex.load(tmp_path / "day.npz")
    assert list(index.icao) == ["000012", "000012"]
    assert all(np.diff(seg.t).max() == 1 for seg in index.segs)
    assert not np.any((index.t > 20) & (index.t < 100))
