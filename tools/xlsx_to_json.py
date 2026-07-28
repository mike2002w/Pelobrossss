#!/usr/bin/env python3
"""
Convert pelobrosssss-workout-tracker.xlsx into workouts.json, the canonical
data file the PWA and the stats dashboard both read.

The app requires workout.type to be exactly one of Push/Pull/Legs/Arms/Cardio
(stats/index.html counts into a fixed-key object). Michael's real day names are
richer than that ("Pull + Arms", "Legs + Push", "Upper (Planet Fitness)"), so we
map to a canonical type for app logic and keep the original in `typeLabel`.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

CANON = ("Push", "Pull", "Legs", "Arms", "Cardio")

EQUIP = {
    "Smith": "Smith",
    "Dumbbell": "DB",
    "Cable": "Cable",
    "Machine": "Machine",
    "Bodyweight": "BW",
}
UNIT = {"lbs": "lb", "kg": "kg", "BW": "bw"}

MODALITY = {
    "Run (Peloton)": "Run",
    "Outdoor Run": "Run",
    "Run": "Run",
    "Treadmill": "Treadmill",
    "Elliptical": "Elliptical",
    "Rowing": "Rowing",
    "Stairs": "Stairs",
    "Walk": "Walk",
}

# keyword -> canonical bucket, for day labels that name no canonical type
# ("Upper", "Full Body (light)", "Travel (New Orleans)")
LEG_WORDS = ("squat", "rdl", "calf", "lunge", "leg press", "hamstring")
PUSH_WORDS = ("bench", "press", "flye", "fly", "tricep", "lateral", "dip", "chest")
PULL_WORDS = ("row", "pulldown", "curl", "shrug", "face pull", "lat ")


# The spreadsheet disambiguates variants in the name ("Bench Press (Smith)"),
# but the app keys off name + equipment as separate fields. Leaving the suffix
# on would split one lift into two chart series and break PR tracking, so strip
# any suffix that just restates the equipment column.
EQUIP_SUFFIX = re.compile(r"\s*\((DB|Smith|Cable|Machine|BW)\)\s*$", re.I)
TRAILING_MACHINE = re.compile(r"\s+Machine$", re.I)


def normalize_name(name):
    n = EQUIP_SUFFIX.sub("", name)
    return TRAILING_MACHINE.sub("", n).strip()


def classify_exercise(name):
    n = name.lower()
    if any(w in n for w in LEG_WORDS):
        return "Legs"
    # check pull before push: "Tricep Pulldown" contains both "tricep" and
    # "pulldown", and it is a push movement, so push has to win for that one.
    if any(w in n for w in PUSH_WORDS):
        return "Push"
    if any(w in n for w in PULL_WORDS):
        return "Pull"
    return None


def canon_type(label, exercise_names):
    """Earliest canonical word in the label wins; fall back to the exercises."""
    hits = [(label.find(t), t) for t in CANON if label.find(t) >= 0]
    # "Cardio + Pull" is a lifting day with cardio attached, so prefer the lift
    hits = [(i, t) for i, t in hits if t != "Cardio"] or hits
    if hits:
        return min(hits)[1]
    votes = defaultdict(int)
    for nm in exercise_names:
        c = classify_exercise(nm)
        if c:
            votes[c] += 1
    if votes:
        return max(votes.items(), key=lambda kv: kv[1])[0]
    return "Cardio"


def num(v):
    return None if v is None or v == "" else v


def build(xlsx_path):
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)

    # ---- Sets -> sessions keyed by date ----
    sessions = {}
    unknown_equip, unknown_unit = set(), set()
    for r in wb["Sets"].iter_rows(min_row=2, values_only=True):
        if not r[0]:
            continue
        date = r[0].date().isoformat()
        label, exercise = r[2], r[3]
        if r[4] not in EQUIP:
            unknown_equip.add(r[4])
        if r[5] not in UNIT:
            unknown_unit.add(r[5])
        equip = EQUIP.get(r[4], "DB")
        key = (normalize_name(exercise), equip)
        s = sessions.setdefault(date, {"label": label, "ex": {}, "order": []})
        if key not in s["ex"]:
            s["ex"][key] = {
                "name": key[0],
                "equipment": equip,
                "unit": UNIT.get(r[5], "lb"),
                # The workbook's Progress and PR Summary formulas match on the
                # exercise name ALONE, so "Bench Press (Smith)" vs "(DB)" is how
                # variants stay apart there. Keep the original spelling so the
                # export can round-trip without breaking those formulas.
                "sheetName": exercise,
                "sets": [],
            }
            s["order"].append(key)
        s["ex"][key]["sets"].append(
            {
                "weight": r[7] or 0,
                "reps": r[8] or 8,
                "warmup": str(r[9]).upper() == "Y",
            }
        )

    if unknown_equip or unknown_unit:
        print(f"  ! unmapped equipment={unknown_equip} unit={unknown_unit}", file=sys.stderr)

    # ---- Cardio -> first bout per date attaches to the session, rest spill ----
    cardio_by_date = defaultdict(list)
    for r in wb["Cardio"].iter_rows(min_row=2, values_only=True):
        if not r[0]:
            continue
        date = r[0].date().isoformat()
        bout = {"machine": MODALITY.get(r[2], r[2])}
        if num(r[4]) is not None:
            bout["min"] = round(float(r[4]), 2)
        if num(r[5]) is not None and (r[6] or "mi") == "mi":
            bout["mi"] = round(float(r[5]), 2)
        if num(r[7]) is not None:
            bout["cal"] = int(r[7])
        if num(r[8]) is not None:
            bout["hr"] = int(r[8])
        if num(r[10]) is not None:
            bout["notes"] = str(r[10])
        cardio_by_date[date].append(bout)

    # ---- merge into the app's model ----
    workouts, extra_cardio = [], []
    for date in sorted(set(sessions) | set(cardio_by_date)):
        s = sessions.get(date)
        bouts = cardio_by_date.get(date, [])
        exercises = [s["ex"][n] for n in s["order"]] if s else []
        label = s["label"] if s else "Cardio"
        w = {
            "id": len(workouts) + 1,
            "date": date,
            "type": canon_type(label, [e["name"] for e in exercises]) if exercises else "Cardio",
            "typeLabel": label,
            "cardio": bouts[0] if bouts else None,
            "exercises": exercises,
        }
        workouts.append(w)
        for b in bouts[1:]:
            extra_cardio.append(dict(b, date=date))

    return {
        "version": 1,
        "generatedFrom": Path(xlsx_path).name,
        "workouts": workouts,
        "extraCardio": extra_cardio,
    }


if __name__ == "__main__":
    src = sys.argv[1]
    out = Path(sys.argv[2])
    data = build(src)
    out.write_text(json.dumps(data, indent=1))
    w = data["workouts"]
    sets = sum(len(e["sets"]) for x in w for e in x["exercises"])
    print(f"  {len(w)} workouts, {sets} sets, {len(data['extraCardio'])} extra cardio bouts")
    print(f"  {w[0]['date']} -> {w[-1]['date']}")
    print(f"  wrote {out}")
