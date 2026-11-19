# Place Finder by Sound implementation checklist

The [project plan](plan.md) describes the model, data formats, benchmark, and planned build order. Paths below are proposed for a new local Python project.

| Task | Depends on | Proposed files | Acceptance and verification |
| --- | --- | --- | --- |
| 1. Prepare one benchmark | — | `data/benchmark/recording.json`, `data/benchmark/tracks.csv` | Confirm a clean flyover, an unedited clock, known ground truth, and aircraft track coverage for the UTC window. Inspect timestamp gaps, altitude source, and units. |
| 2. Export a spectrogram and mark a ridge | 1 | `src/audio.py`, `src/events.py`, `events.json` | Decode the relevant stream, generate a labeled plot, and reopen a saved ridge with matching times and frequencies. Verify on one synthetic tone and the benchmark clip. |
| 3. Predict the ridge at a known location | 1, 2 | `src/tracks.py`, `src/doppler.py`, `tests/test_doppler.py` | Check the Doppler sign and per-sample propagation delay on an analytic flyby. Verify the actual trajectory overlays the benchmark ridge with plausible time and frequency adjustments. |
| 4. Search a region using one timed event | 3 | `src/search.py`, `src/report.py`, `tests/test_search.py` | Produce ranked points, an overlay, and a map without providing the microphone coordinates as a search input. Confirm the expected flight and measure error against the predeclared benchmark tolerance. |
| 5. Search with a locked pair of events | 4 | `src/events.py`, `src/search.py`, `tests/test_search.py` | Remove the UTC start input, fit both ridges with one shared clock, and verify that a decoy fitting only one event loses. Rank by flight pair and report competing clusters. |
| 6. Validate ambiguous and absent matches | 5 | `src/report.py`, `tests/test_search.py`, `benchmarks/results.md` | Run clean, noisy, out-of-region, and edited-clock cases. Record rank, error, coverage, and runtime. Verify that unsuitable inputs can produce an inconclusive result. |
| 7. Expand the search area | 6 | `src/tracks.py`, `src/search.py`, `benchmarks/results.md` | Confirm that cached and uncached runs agree on an identical regional input. Profile tractable larger regions and compare candidate counts, memory, and runtime with the previous baseline. |

## Checkpoints

- [x] After tasks 1–3, the benchmark audio, observed ridge, and modeled overlay reproduce from local inputs.
- [x] After tasks 4–5, the tool independently exercises both search modes and exports candidate maps with overlays.
- [x] After tasks 6–7, benchmark results include false matches and measured resource use before attempting a full-country run.

Verification and known limits are recorded in [the benchmark results](../benchmarks/results.md). The public clip exercises the unknown-start pair. The timed mode uses a synthetic first-sample UTC reference. Expansion was measured on wider regional boxes.
