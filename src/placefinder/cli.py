import argparse
import json

from .inputs import index_tracks, mark, prepare
from .search import search


def main():
    parser = argparse.ArgumentParser(
        description="Match aircraft tones against historical tracks."
    )
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser(
        "prepare", help="decode a recording manifest and export spectrograms"
    )
    p.add_argument("manifest")
    p.add_argument("out")
    p = sub.add_parser(
        "index", help="normalize an MSL track CSV to a reusable day index"
    )
    p.add_argument("csv")
    p.add_argument("out")
    p = sub.add_parser(
        "mark", help="trace and fit a falling tone inside a marked window"
    )
    p.add_argument("spec")
    p.add_argument("out")
    p.add_argument("--window", nargs=2, type=float, required=True)
    p.add_argument("--band", nargs=2, type=float, required=True)
    p.add_argument("--points", help="manual JSON list of [clip seconds, tone Hz]")
    p = sub.add_parser("search", help="score a known point or a regional search box")
    p.add_argument("spec")
    p.add_argument("day")
    p.add_argument("out")
    p.add_argument("--events", nargs="+", required=True)
    area = p.add_mutually_exclusive_group(required=True)
    area.add_argument("--point", type=float, nargs=2, metavar=("LAT", "LON"))
    area.add_argument("--bbox", type=float, nargs=4, metavar=("S", "N", "W", "E"))
    p.add_argument(
        "--utc", type=float, help="Unix time of first decoded sample, single-event only"
    )
    p.add_argument(
        "--uncertainty",
        type=float,
        default=1.0,
        help="shared clock sweep half-width, s",
    )
    p.add_argument("--gap-tol", type=float, default=5.0, help="heard CPA tolerance, s")
    p.add_argument(
        "--spacing", type=float, default=200.0, help="coarse spacing in metres"
    )
    p.add_argument(
        "--ground", type=float, default=0.0, help="constant terrain elevation, m MSL"
    )
    p.add_argument(
        "--dem",
        action="store_true",
        help="use cached/downloaded Terrarium terrain tiles",
    )
    p.add_argument(
        "--mic-height",
        type=float,
        default=0.0,
        help="microphone height above ground, m",
    )
    p.add_argument("--c", type=float, default=343.0, help="effective sound speed, m/s")
    p.add_argument(
        "--no-delay", dest="delay", action="store_false", help="validation control"
    )
    p.add_argument(
        "--quiet", type=float, nargs=2, help="clean quiet interval in clip seconds"
    )
    p.add_argument(
        "--wind",
        type=float,
        nargs=2,
        default=(0.0, 0.0),
        metavar=("EAST", "NORTH"),
        help="uniform wind in m/s",
    )
    p.add_argument(
        "--cache",
        help="directory for content-addressed coarse matches on fixed terrain",
    )
    args = vars(parser.parse_args())
    action = args.pop("action")
    try:
        if action == "search":
            _, summary = search(**args)
            print(json.dumps(summary, indent=2))
        else:
            {"prepare": prepare, "mark": mark, "index": index_tracks}[action](**args)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, f"{action}: {error}\n")


if __name__ == "__main__":
    main()
