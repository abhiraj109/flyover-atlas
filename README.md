# Place Finder by Sound

Match a marked aircraft tone to a historical flight track, or match two flyovers using one shared recording clock. Open the resulting GeoJSON in QGIS and inspect the spectrogram overlay before interpreting the highest-scoring point.

## Open the Windows app

Install Python 3.12 or newer, uv, and FFmpeg. Make sure uv, ffmpeg, and ffprobe are on PATH. For the example, download the recording using the [benchmark instructions](data/benchmark/README.md) and save it as data/benchmark/challenge.webm.

Double-click **Open Place Finder.cmd** in the project folder. The launcher opens a local workspace in your browser. Leave **Example** selected and click **Find location**. The results show the best match, the sound charts, and downloads for QGIS and spreadsheets. For your own recording, choose **My recording** and supply its matching track CSV and flyover windows. Terrain lookup needs internet the first time. Each run saves its results in a new folder under runs/interface. The server listens on this computer only. To open the original desktop window with Tkinter, run `uv run python -m placefinder.gui`.

## Run locally

Install Python 3.12 or newer, uv, and FFmpeg with both `ffmpeg` and `ffprobe` on PATH. The lockfile pins the Python dependencies, including the MIT-licensed flight index and geodesy routines from [dopplertrack 0.3.0](https://github.com/mjshiggins/dopplertrack).

```powershell
uv sync --locked
uv run placefinder --help
uv run pytest -q
uv run python benchmarks/validate.py runs/synthetic
```

The last command generates clean and noisy WAV files, tracks, measured ridges, known-point overlays, timed and unknown-start searches, negative controls, and a metrics CSV. Its synthetic truth is used to generate audio and evaluate results after searching. The search receives a regional box. The predeclared distance tolerance is 250 m.

## Public challenge

Run these commands from the project directory. The supplied recording manifest selects channel zero of the first audio stream. The two short ridge files contain manual measurements from the challenge spectrogram. The point command uses the published benchmark reference. The box command uses the two measured events and the regional tracks without a UTC start or reference point.

```powershell
New-Item -ItemType Directory -Force runs/challenge | Out-Null
uv run placefinder prepare data/benchmark/recording.json runs/challenge/spec.npz
uv run placefinder mark runs/challenge/spec.npz data/benchmark/event1.json --window 2090 2200 --band 80 187 --points data/benchmark/ridge1.json
uv run placefinder mark runs/challenge/spec.npz data/benchmark/event2.json --window 3042 3120 --band 95 185 --points data/benchmark/ridge2.json
uv run placefinder index data/benchmark/tracks.csv runs/challenge/day.npz
uv run placefinder search runs/challenge/spec.npz runs/challenge/day.npz runs/challenge/known --events data/benchmark/event1.json data/benchmark/event2.json --point 40.876466 -73.524951 --uncertainty 6 --gap-tol 10 --dem
uv run placefinder search runs/challenge/spec.npz runs/challenge/day.npz runs/challenge/regional --events data/benchmark/event1.json data/benchmark/event2.json --bbox 40.865 40.890 -73.541 -73.510 --spacing 200 --uncertainty 6 --gap-tol 10 --dem
```

The public clip has no independently verified UTC start. For a recording with a known start, use one event and pass Unix seconds for its first decoded sample. Here is the timed search on the generated fixture.

```powershell
uv run placefinder search runs/synthetic/clean.npz runs/synthetic/day.npz runs/synthetic/timed --events runs/synthetic/e1.json --bbox 34.999 35.011 -100.011 -99.995 --utc 1700000000 --uncertainty 1
```

## Input and output

- **Recording.** Supply JSON with `source` relative to the manifest, zero-based `audio_stream` and `channel`, and optional `discontinuities` as clip seconds. The decoder selects that stream and channel, resamples at 2 kHz, and computes a 2.048 s Hann STFT every 0.2 s. The NPZ contains raw dB and per-frequency median-subtracted dB from 40–450 Hz. The sibling PNG displays both. The JSON records the decoded duration and sample rates.
- **Events.** Mark a time window and frequency band on the plot. Supply five or more increasing time/frequency picks, or omit `--points` to trace the ridge automatically. Inspect the saved points when other tones cross the window. The fit stores heard CPA, slant range, speed and emitted frequency. Trace one harmonic consistently and treat it as its own tone. Declare a cut between events to prevent a shared-clock search across it.
- **Tracks.** CSV columns are `flight,segment,utc_s,lat,lon,alt_m,alt_source,alt_reference`. Time is Unix UTC, including adjacent UTC dates when needed. Coordinates are WGS84 degrees. Convert heights to a common MSL reference before import. Label pressure altitude explicitly when used as an approximation. Indexing sorts samples, keeps the first duplicate timestamp, splits at gaps over 20 s, and discards stretches shorter than 20 s. Flight type is optional. Archive inputs and source terms are described in [the benchmark notes](data/benchmark/README.md).
- **Search.** The day index uses 10 s time buckets and spatial joins to reject incompatible flights before evaluating regional microphone points. Each curve uses emission-time radial velocity and per-sample propagation. Use a measured `--ground` height or `--dem`, plus `--mic-height` if known. MSL heights in local WGS84 geometry approximate a constant geoid offset. Terrain tiles are fetched on first use. The pair search locks both events to one clock, fits each tone independently, and ranks on the weaker event’s contrast against bins 4 Hz away. Each event needs at least 80% coverage. The default 200 m grid refines four leading neighborhoods at 100 m and 50 m. An optional `--quiet FROM TO` subtracts 1 dB per intervening closer pass.
- **Results.** `results.csv` and `results.geojson` retain candidate coordinates, aircraft and segment IDs, individual scores and coverage, emitted tones, inferred Unix start, combined score, cluster and verdict. `ranked-flights.csv` keeps the best point per ordered flight group. `winner.png` and, where a competitor exists, `runner-up.png` show the observed ridge and the scored prediction. Cluster zero denotes points outside the leading score band. The runner-up is the next leading cluster, or the next flight group when there is only one leading cluster.
- **Interpretation.** The 3 dB evidence floor, 2 dB near-best band and 250 m ambiguity radius are heuristics. A broad footprint or competing clusters produce `ambiguous`. A weak or absent fit produces `insufficient evidence`. A known-point overlay tests only the supplied point. A verdict of `candidate` carries no calibrated probability.
- **Reuse and scale.** Save the normalized day NPZ. For fixed terrain, `--cache DIRECTORY` also reuses coarse matches for identical data and parameters. The regional grid cost still grows with area and surviving flight groups. Process larger archives in regional and UTC-day partitions with time and spatial padding. See [measured runs](benchmarks/results.md) before expanding the box.
