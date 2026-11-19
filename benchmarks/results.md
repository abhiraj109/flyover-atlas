# Regional benchmark results

## Evaluation setup

The acceptance target was first rank and a best point within 250 m of the reference. The timed search uses a synthetic recording with a known first-sample UTC timestamp. The public challenge uses the unknown-start pair mode, a 40-minute track archive slice, and the fixed 40.865–40.890° N, 73.541–73.510° W box shown in the README. Its known-point overlay is a separate run. A regional result cannot establish an unrestricted search rank.

## Synthetic controls

The deterministic fixture generates audio by evaluating the emitted phase at the inverse arrival time. The scorer predicts frequency from the track velocity. The microphone lies off the coarse grid and the second window includes a competing flight. The end-to-end check rebuilds its inputs from scratch and measures the best-ranked grid point against the reference after scoring.

| Case | Best-point error | Outcome |
| --- | ---: | --- |
| Known point | 0 m by construction | Both curves supported |
| Single event with measured UTC | 43.2 m | Expected flight first. Competing microphone locations remain |
| Two events, unknown UTC | 8.2 m | Expected ordered pair first |
| Noise only | 566.6 m | Insufficient evidence despite a numerical winner |
| Excluded region, wrong gap, track dropout | — | Insufficient evidence |
| Propagation delay disabled | 78.7 m | Ambiguous |
| Sound speed 335 m/s | 133.3 m | Expected pair first |
| Uniform wind 8 m/s east, 3 m/s south | 8.2 m | Ambiguous |
| Varying engine RPM | 839.5 m | Ambiguous. The correct flight IDs still give a poor point estimate |
| Larger regional box | 13.8 m | Expected pair first |

The wider grid evaluated 380 locations versus 172 in the baseline. Its 276 scored rows compare with 196 at baseline. Rebuilding the track index and reusing the coarse cache both produced byte-identical ranked point files. Times include report plotting. Memory is peak allocation recorded by Python tracemalloc during each search, which excludes external processes and some native allocations. The CSV includes runtime, memory, support, cluster size, true group rank and margin to the best competing group. [Measured synthetic runs](synthetic-results.csv)
## Public challenge recording

The independently indexed regional slice contains 5,590 airborne fixes for 108 aircraft and 130 continuous searchable segments. The first expected aircraft has 16 fixes with a median gap of 19.86 s and a maximum of 19.99 s. The second has 70 fixes with a median gap of 4.92 s and a maximum of 19.93 s. Heights are barometric approximations. The original absolute recording start is unknown, so this benchmark validates the locked pair. The synthetic benchmark supplies independent clock truth for the timed mode.

At the published reference point, the expected pair ranked first. Both predictions covered the full scoring window. In the regional search, the expected ordered pair again ranked first, with its best point **23.6 m** from the reference. The weaker ridge scored 15.44 dB and the next flight pair scored 5.34 dB. Forty nearby points occupied the leading cluster and extended 255 m from the best point. The location verdict was **ambiguous**.

Reproduce the known-point, regional and larger-box profiles with the command below after the README preparation steps. Python allocation tracking adds overhead. The uninstrumented regional search took 8.8 s on the same machine. The CSV records measured footprint, score margin, reference error, memory, time and candidate counts for each run. [Public challenge metrics](challenge-results.csv)

```powershell
uv run python benchmarks/challenge.py runs/challenge data/benchmark
```
