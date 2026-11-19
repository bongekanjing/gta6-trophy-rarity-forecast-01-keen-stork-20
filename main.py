"""Forecast every GTA VI trophy's Exophase earn rate at a case's target instant.

The page prints a rate as k/n, so this entry keeps the two apart: the tracked
player count n is exact, shared by all 55 trophies and estimated once from the
history; each trophy's holder count k is a small integer recovered from the
printed rate, smoothed over the late reads, and carried to the target along the
fitted rise in n. The forecast is 100*k/n with a band that carries the n
extrapolation, the count's Poisson noise and the model's own misfit.

Standard library only. `python3 -P -s main.py` is how the grader runs it, so the
directory is put back on sys.path before model.py is imported.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import model

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))


def forecast(case, name):
    """One case's forecast, in the shape the scorer reads."""
    history = case.get("history") or []
    if not history:
        raise ValueError(name + " carries no reads to forecast from")
    if list(case.get("levels") or model.LEVELS) != list(model.LEVELS):
        raise ValueError(name + " asks for levels " + repr(case.get("levels")))

    horizon_h = case["horizon_minutes"] / 60.0
    n_target, growth, n_unc = model.player_curve(history, horizon_h)
    if n_target is None:
        raise ValueError(name + " has no usable players-tracked reading")

    # The tracked count at the first and last usable read, for the growth exponent.
    counts = [r.get("players_tracked") for r in history]
    counts = [c for c in counts if isinstance(c, (int, float)) and c > 0]
    n_first = counts[0] if counts else n_target
    n_last = counts[-1] if counts else n_target

    rows = []
    for i, trophy in enumerate(case.get("trophies") or []):
        series = model.count_series(history, i, counts or [])
        if not series:
            # No readable rate for this trophy: hold the page's floor.
            rows.append({"id": trophy["id"],
                         "q": [model.round4(model.LOW_PCT)] * 5})
            continue
        # The tracked count at each of this trophy's own reads, so the holder
        # count can be regressed against it over exactly the same window.
        n_series = [c for c in (r.get("players_tracked") for r in history)
                    if isinstance(c, (int, float)) and c > 0]
        n_series = n_series[-len(series):] if n_series else []
        rows.append({"id": trophy["id"],
                     "q": model.forecast_trophy(series, n_series, trophy,
                                                n_target, growth, n_unc)})
    return {"trophies": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Name order, so two executions of a case write the same bytes.
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        out = forecast(case, path.name)
        text = json.dumps(out, separators=(",", ":"), sort_keys=False) + "\n"
        (OUTPUT_DIR / (path.stem + ".out")).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
