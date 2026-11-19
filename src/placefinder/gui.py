"""Guided Windows interface for regional audio searches."""

import os
from math import isfinite
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from tempfile import mkdtemp

from dopplertrack.audio import Spectrogram

from .inputs import index_tracks, mark, prepare, write_json
from .search import search

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/benchmark"


def run_job(settings, notify):
    base = ROOT / "runs/interface"
    base.mkdir(parents=True, exist_ok=True)
    out = Path(mkdtemp(prefix="search-", dir=base))
    example = settings is None
    if example:
        media = DATA / "challenge.webm"
        tracks = DATA / "tracks.csv"
        windows = [(2090, 2200, 80, 187), (3042, 3120, 95, 185)]
        box = [40.865, 40.890, -73.541, -73.510]
        utc = None
    else:
        media, tracks = map(Path, settings[:2])
        if not media.is_file() or not tracks.is_file():
            raise ValueError("Choose a recording and a flight track CSV first.")

        def numbers(value, count, label):
            try:
                values = [float(x) for x in value.replace(",", " ").split()]
                if len(values) == count and all(map(isfinite, values)):
                    return values
            except ValueError:
                pass
            raise ValueError(f"Enter {count} numbers for {label}.")

        windows = [numbers(settings[2], 4, "the first flyover")]
        utc = None
        if settings[3].strip():
            windows.append(numbers(settings[3], 4, "the second flyover"))
        else:
            utc = numbers(settings[5], 1, "the recording start time")[0]
        box = numbers(settings[4], 4, "the search area")
        south, north, west, east = box
        if not (-89 < south < north < 89 and -180 <= west < east <= 180):
            raise ValueError("Enter the search area in south, north, west, east order.")
        for start, end, low, high in windows:
            if not (0 <= start < end and 40 <= low < high <= 450):
                raise ValueError(
                    "Each flyover needs increasing times and a pitch range between 40 and 450 Hz."
                )
        if len(windows) == 2 and windows[0][1] >= windows[1][0]:
            raise ValueError("The second flyover must start after the first one ends.")
    if not media.is_file():
        raise ValueError(
            "The example recording is missing. Download challenge.webm using the benchmark instructions in the README."
        )
    notify("Reading the recording and drawing its sound chart…")
    manifest = out / "recording.json"
    write_json(manifest, {"source": str(media.resolve())})
    spec = out / "spec.npz"
    prepare(manifest, spec)
    sound = Spectrogram.load(spec)
    events = []
    for i, (a, b, lo, hi) in enumerate(windows, 1):
        notify(f"Following the changing pitch of flyover {i}…")
        event = out / f"event{i}.json"
        mark(
            sound, [a, b], [lo, hi], event, DATA / f"ridge{i}.json" if example else None
        )
        events.append(event)
    del sound
    notify("Reading the aircraft positions…")
    day = out / "day.npz"
    index_tracks(tracks, day)
    notify("Checking possible spots on the map…")
    frame, summary = search(
        spec, events, day, out, bbox=box, utc=utc, dem=True, uncertainty=6, gap_tol=10
    )
    verdict = summary["verdict"]
    if verdict == "insufficient evidence" or frame.empty:
        return out, "There wasn’t enough matching sound to pick a spot."
    best = frame.iloc[0]
    message = (
        "Several spots fit the sound almost equally well."
        if verdict == "ambiguous"
        else "One spot fits the sound best."
    )
    return out, f"{message}\nBest guess: {best.lat:.5f}, {best.lon:.5f}"


def main():
    import tkinter as tk
    from tkinter import filedialog, ttk

    root = tk.Tk()
    root.title("Place Finder by Sound")
    panel = ttk.Frame(root, padding=24)
    panel.pack(fill="both", expand=True)
    panel.columnconfigure(0, weight=1)
    ttk.Label(
        panel, text="Find where a recording was made", font=("Segoe UI", 18, "bold")
    ).grid(sticky="w")
    ttk.Label(
        panel,
        text="Try the example first. It uses two planes heard in the same recording.",
    ).grid(sticky="w", pady=(4, 14))
    mode = tk.StringVar(value="Example recording")
    choice = ttk.Combobox(
        panel,
        textvariable=mode,
        values=["Example recording", "My recording"],
        state="readonly",
    )
    choice.grid(sticky="w")
    form = ttk.Frame(panel)
    form.grid(sticky="ew", pady=8)
    fields = []
    labels = [
        "Audio or video file",
        "Aircraft tracks for the same area and date (CSV)",
        "First flyover: start second, end second, low Hz, high Hz",
        "Second flyover: same four numbers (leave blank for one plane)",
        "Search area: south, north, west, east in degrees",
        "For one plane only: recording start in Unix UTC seconds",
    ]
    for i, label in enumerate(labels):
        ttk.Label(form, text=label).grid(row=i * 2, column=0, sticky="w")
        val = tk.StringVar()
        fields.append(val)
        ttk.Entry(form, textvariable=val, width=54).grid(
            row=i * 2 + 1, column=0, sticky="ew", pady=(0, 5)
        )
        if i < 2:

            def browse(v=val):
                path = filedialog.askopenfilename()
                if path:
                    v.set(path)

            ttk.Button(form, text="Browse…", command=browse).grid(
                row=i * 2 + 1, column=1
            )
    form.grid_remove()
    choice.bind(
        "<<ComboboxSelected>>",
        lambda _: form.grid() if mode.get() == "My recording" else form.grid_remove(),
    )
    status = tk.StringVar(
        value="Click Find location to start. Everything is filled in for the example."
    )
    updates = Queue()
    result = None

    def poll():
        nonlocal result
        try:
            while True:
                kind, value = updates.get_nowait()
                if kind == "progress":
                    status.set(value)
                else:
                    run.state(["!disabled"])
                    choice.configure(state="readonly")
                    if kind == "done":
                        result, message = value
                        status.set(message)
                        folder.state(["!disabled"])
                        if (result / "winner.png").exists():
                            overlay.state(["!disabled"])
                    else:
                        status.set(f"Search stopped. {value}")
                    return
        except Empty:
            root.after(150, poll)

    def start():
        settings = [v.get() for v in fields] if mode.get() == "My recording" else None
        for widget in (run, overlay, folder):
            widget.state(["disabled"])
        choice.configure(state="disabled")

        def work():
            try:
                value = run_job(settings, lambda msg: updates.put(("progress", msg)))
                updates.put(("done", value))
            except Exception as exc:
                updates.put(("error", str(exc)))

        Thread(target=work, daemon=True).start()
        poll()

    run = ttk.Button(panel, text="Find location", command=start)
    run.grid(sticky="w", pady=10)
    ttk.Label(panel, textvariable=status, wraplength=490).grid(sticky="w", pady=6)
    actions = ttk.Frame(panel)
    actions.grid(sticky="w", pady=8)
    overlay = ttk.Button(
        actions,
        text="See the sound match",
        command=lambda: os.startfile(result / "winner.png"),
    )
    folder = ttk.Button(
        actions, text="Open results folder", command=lambda: os.startfile(result)
    )
    for button in (overlay, folder):
        button.pack(side="left", padx=(0, 6))
        button.state(["disabled"])
    root.mainloop()


if __name__ == "__main__":
    main()
