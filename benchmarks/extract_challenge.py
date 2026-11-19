"""Extract the Oyster Bay regional/time subset from adsb.lol's split 2026-09-08 tar."""

import argparse
import csv
from datetime import datetime, timezone
import gzip
import io
import json
import re
from pathlib import Path
import tarfile


class Parts(io.RawIOBase):
    def __init__(self, paths):
        self.paths = iter(paths)
        self.current = None

    def readable(self):
        return True

    def readinto(self, buf):
        while True:
            if self.current is None:
                path = next(self.paths, None)
                if path is None:
                    return 0
                self.current = path.open("rb")
            count = self.current.readinto(buf)
            if count:
                return count
            self.current.close()
            self.current = None

    def close(self):
        if self.current:
            self.current.close()
        super().close()


def extract(parts, out):
    midnight = datetime(2026, 9, 8, tzinfo=timezone.utc).timestamp()
    low, high = midnight + 20 * 3600 + 40 * 60, midnight + 21 * 3600 + 20 * 60
    count = 0
    with (
        io.BufferedReader(Parts(parts), 1 << 20) as stream,
        tarfile.open(fileobj=stream, mode="r|") as tar,
        out.open("w", newline="") as f,
    ):
        writer = csv.writer(f)
        writer.writerow(
            [
                "flight",
                "segment",
                "utc_s",
                "lat",
                "lon",
                "alt_m",
                "alt_source",
                "alt_reference",
            ]
        )
        for entry in tar:
            if not entry.isfile() or "/trace_full_" not in entry.name:
                continue
            raw = tar.extractfile(entry).read()
            if raw.startswith(b"\x1f\x8b"):
                raw = gzip.decompress(raw)
            if b"-73." not in raw or not re.search(rb",\s*40\.[789]\d*\s*,\s*-73\.", raw):
                continue
            track = json.loads(raw)
            if not isinstance(track, dict):
                continue
            base = track.get("timestamp", 0)
            for r in track.get("trace", []):
                if not isinstance(r, list) or len(r) < 4:
                    continue
                t, lat, lon, alt = r[:4]
                if not all(isinstance(v, (int, float)) for v in [t, lat, lon, alt]):
                    continue
                if (
                    low <= t + base <= high
                    and 40.7 <= lat < 41
                    and -73.75 <= lon <= -73.30
                ):
                    writer.writerow(
                        [
                            track["icao"],
                            "region",
                            t + base,
                            lat,
                            lon,
                            round(alt * 0.3048, 3),
                            "barometric_approximation",
                            "MSL",
                        ]
                    )
                    count += 1
        print(f"Extracted {count} airborne fixes.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("out", type=Path)
    p.add_argument("parts", type=Path, nargs="+")
    args = p.parse_args()
    extract(args.parts, args.out)
