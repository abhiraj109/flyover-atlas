# Flyover Atlas CLI

Run these commands from the repository root after completing the [setup](../README.md#try-the-example). Use `uv run flyover-atlas --help` to list the commands, or add `--help` after a command to see its options.

## Reproduce the public benchmark

The example recording has two measured flyovers. The first search checks the published reference position. The second searches a regional box without receiving the reference position or an absolute recording start time.

```powershell
New-Item -ItemType Directory -Force runs/challenge | Out-Null
uv run flyover-atlas prepare data/benchmark/recording.json runs/challenge/spec.npz
uv run flyover-atlas mark runs/challenge/spec.npz runs/challenge/event1.json --window 2090 2200 --band 80 187 --points data/benchmark/ridge1.json
uv run flyover-atlas mark runs/challenge/spec.npz runs/challenge/event2.json --window 3042 3120 --band 95 185 --points data/benchmark/ridge2.json
uv run flyover-atlas index data/benchmark/tracks.csv runs/challenge/day.npz
uv run flyover-atlas search runs/challenge/spec.npz runs/challenge/day.npz runs/challenge/known --events runs/challenge/event1.json runs/challenge/event2.json --point 40.876466 -73.524951 --uncertainty 6 --gap-tol 10 --dem
uv run flyover-atlas search runs/challenge/spec.npz runs/challenge/day.npz runs/challenge/regional --events runs/challenge/event1.json runs/challenge/event2.json --bbox 40.865 40.890 -73.541 -73.510 --uncertainty 6 --gap-tol 10 --dem
```

`--bbox` takes south, north, west, and east in degrees. `--dem` uses terrain tiles. For a search at a fixed ground elevation, use `--ground` in metres above mean sea level and add `--mic-height` in metres if known.

## Prepare your own recording

Create `recording.json` beside your audio or video file. Audio stream and channel numbering start at zero. List any cuts as seconds from the beginning of the decoded audio.

```json
{
  "source": "recording.wav",
  "audio_stream": 0,
  "channel": 0,
  "discontinuities": []
}
```

Run `uv run flyover-atlas prepare recording.json recording.npz` and open the generated `recording.png` to find the flyover. Time runs along the horizontal axis and pitch along the vertical axis. Pick a window around one curved line that changes in pitch and note the start and end times and the lowest and highest frequencies. Use the same tone or harmonic throughout a window.

```powershell
uv run flyover-atlas mark recording.npz flyover.json --window 35 80 --band 92 171
```

The command traces the pitch curve within the window. If other tones cross it, pass `--points picks.json` with at least five `[seconds, Hz]` pairs ordered by time. The fit records the closest-approach time as heard, the slant range, speed, and emitted frequency.

### Search with one flyover and a known clock

Pass one event and `--utc` in Unix seconds for the first audio sample. Generate the synthetic benchmark to try the exact command below.

```powershell
uv run python benchmarks/validate.py runs/synthetic
uv run flyover-atlas search runs/synthetic/clean.npz runs/synthetic/day.npz runs/synthetic/timed --events runs/synthetic/e1.json --bbox 34.999 35.011 -100.011 -99.995 --utc 1700000000 --uncertainty 1
```

### Search with two flyovers and an unknown clock

Pass two events in recording order and omit `--utc`. The search finds a recording start time that fits both windows. Use a continuous recording between the events.

## Flight track format

Provide a CSV with these columns and run `uv run flyover-atlas index tracks.csv day.npz` to build the reusable search index.

| Column | Format |
| --- | --- |
| `flight` | Aircraft identifier. Preserve leading zeros. |
| `segment` | Identifier for a continuous flight segment. |
| `utc_s` | Unix timestamp in seconds. Include adjacent UTC dates if your recording crosses midnight. |
| `lat`, `lon` | WGS84 latitude and longitude in degrees. |
| `alt_m` | Altitude in metres above mean sea level. |
| `alt_source` | Height source. Label pressure altitude if used as an approximation. |
| `alt_reference` | `MSL` after converting heights to a common reference. |

Indexing sorts the fixes, keeps the first duplicate timestamp, splits tracks at gaps greater than 20 seconds, and skips stretches shorter than 20 seconds.

## Output files

| File | Use |
| --- | --- |
| `summary.json` | Verdict, number of grid points and candidates, and runtime. |
| `results.csv` | All scored points, event scores, coverage, inferred start time, and cluster membership. |
| `results.geojson` | Candidate points for GIS tools such as QGIS. |
| `ranked-flights.csv` | Highest-ranked point for each ordered flight group. |
| `winner.png`, `runner-up.png` | Predicted aircraft tones over the recording's sound chart when matches exist. |

## How the search works

The decoder resamples the selected audio channel at 2 kHz. The sound chart uses a 2.048 s Hann window every 0.2 s and stores both raw and median-subtracted power from 40 to 450 Hz. The flight index uses time buckets and spatial joins to reject incompatible tracks before evaluating possible microphone positions.

The search predicts pitch from the aircraft's radial velocity and accounts for the time sound takes to reach each spot. A candidate needs at least 80% coverage. A two-flyover search ranks positions using the weaker event's contrast against nearby frequencies. By default the grid starts at 200 m and refines up to four leading neighborhoods at 100 m and 50 m. The 3 dB evidence floor, 2 dB near-best band, and 250 m ambiguity radius are heuristics.

Reuse the day index for searches against the same tracks. With fixed ground elevation, `--cache DIRECTORY` can reuse coarse matches for identical inputs and settings. Runtime grows with the area and the number of matching flight groups. [Measured runs](../benchmarks/results.md)
