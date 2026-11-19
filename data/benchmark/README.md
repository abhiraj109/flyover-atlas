# Oyster Bay benchmark inputs

The local media file is the audio stream from Colsto’s hour-long public challenge upload. The first decoded sample defines clip time zero. The absolute start and continuity are unverified. The author’s narrated demonstration is a separate video. [Challenge recording](https://youtu.be/4CxVxuMVkMc) · [Demonstration](https://www.youtube.com/watch?v=UytYrhYLOKI)

The downloaded WebM SHA-256 is `6884324b4fb9babbc89b10de71f283dd338766a15d2fbd1aeedb52216276692d`. To obtain a local copy from the project root, run the following command. The selected format may change upstream.

```powershell
uvx yt-dlp --no-playlist -f bestaudio -o "data/benchmark/challenge.%(ext)s" https://youtu.be/4CxVxuMVkMc
```

The regional track database is derived from ADSB.lol and its contributing feeders under the Open Database License 1.0. It includes airborne barometric fixes from 20:40 through 21:20 UTC on 2026-09-08 between 40.7–41.0° N and 73.75–73.30° W. Heights are pressure altitude converted from feet to metres, used as an approximation to MSL. The archive is filtered by position and time without a whitelist of aircraft IDs. This deliberately narrow time slice limits the unknown-start test. [Source release](https://github.com/adsblol/globe_history_2026/releases/tag/v2026.09.08-planes-readsb-prod-0) · [Database license](https://opendatacommons.org/licenses/odbl/1-0/)

To rebuild the CSV from the two original release parts, pass them in archive order.

```powershell
uv run python benchmarks/extract_challenge.py data/benchmark/tracks.csv v2026.09.08-planes-readsb-prod-0.tar.aa v2026.09.08-planes-readsb-prod-0.tar.ab
```

The reference point (40.876466, −73.524951) and expected pair (a1dfeb, ace391) come from the published known-point baseline. Distance measures agreement with that reference. Its survey accuracy is unknown. Manual ridge picks were read from this project's own spectrogram. [Baseline known-point output](https://github.com/mjshiggins/dopplertrack/blob/2d899bbfe1529e2b4351f328969bb37776d57cb4/docs/results/oyster_bay_known_point.csv)
