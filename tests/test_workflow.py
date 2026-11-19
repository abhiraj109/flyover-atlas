import json

import numpy as np
import pytest
from scipy.io.wavfile import write
from placefinder.inputs import prepare
from placefinder.search import search
from benchmarks.validate import BOX, START, fixture


def test_prepared_tone_and_channel(tmp_path):
    t = np.arange(12000) / 2000
    audio = np.column_stack([np.sin(2 * np.pi * f * t) for f in (120, 210)])
    write(tmp_path / "stereo.wav", 2000, (audio * 16000).astype(np.int16))
    meta = tmp_path / "recording.json"
    meta.write_text(
        json.dumps(dict(source="stereo.wav", channel=1, discontinuities=[3.0]))
    )
    prepare(meta, tmp_path / "spec.npz")
    with np.load(tmp_path / "spec.npz") as sp:
        assert abs(sp["f"][sp["raw_db"].mean(axis=1).argmax()] - 210) < 0.5
        np.testing.assert_allclose(np.median(sp["S"], axis=1), 0, atol=1e-4)
        assert sp["cut_times_s"].tolist() == [3.0]


def test_regional_modes_and_cut(tmp_path):
    fixture(tmp_path)
    spec, day = tmp_path / "clean.npz", tmp_path / "day.npz"
    e1, e2 = tmp_path / "e1.json", tmp_path / "e2.json"
    for events, utc in [([e1], START), ([e1, e2], None)]:
        frame, _ = search(
            spec, events, day, tmp_path / "out", bbox=BOX, utc=utc, refine=False
        )
        assert frame.iloc[0].flight1 == "alpha"
        if len(events) == 2:
            assert frame.iloc[0].flight2 == "bravo"
        assert len(
            json.loads((tmp_path / "out/results.geojson").read_text())["features"]
        ) == len(frame)
    with np.load(spec) as data:
        arrays = dict(data)
    arrays["cut_times_s"] = [120.0]
    np.savez(tmp_path / "edited.npz", **arrays)
    with pytest.raises(ValueError, match="discontinuity"):
        search(tmp_path / "edited.npz", [e1, e2], day, tmp_path / "edited", bbox=BOX)
