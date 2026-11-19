#!/usr/bin/env python3
"""Merge staged sessions into workouts.json (the single source of truth).

Usage: python3 tools/merge_pending.py [--auto] [extra_sessions.json]

- Reads pending_additions.json (+ an optional extra file in the same schema).
- --auto merges only CLEAN sessions and leaves the rest staged with a reason:
    clean = date not already in workouts.json, type in Push/Pull/Legs/Arms/Cardio,
            every set has weight+reps, and every exercise name+equipment already
            exists in workouts.json (new lifts need a human look at the sheetName).
  Without --auto every session is merged (new lifts included).
- A session whose date already exists is merged as an ADD-ON (added 2026-11-18):
    * if the existing day is only an Apple Health import (source "apple-health"),
      the chat session takes the day over and the imported run is kept as its
      cardio (or as extraCardio if the chat logged other cardio);
    * otherwise exercises not already on that day (same name + equipment) are
      appended, and cardio is filled in if the day had none. Exact repeats are
      dropped silently.
- Assigns fresh ids in date order, sorts, appends extraCardio.
- Archives what was merged as pending_additions.merged-<date>.json and rewrites
  pending_additions.json with whatever is still waiting.
Run tools/sync.sh afterwards to regenerate the workbook.
"""
import json, sys, os, datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
AUTO = "--auto" in sys.argv
extra_path = next((a for a in sys.argv[1:] if not a.startswith("--")), None)
TODAY = dt.date.today().isoformat()
TYPES = {"Push", "Pull", "Legs", "Arms", "Cardio"}
RENAME = {"Cable Chest Press": ("Standing Cable Press", "Standing Cable Press")}

wp = os.path.join(REPO, "workouts.json"); pp = os.path.join(REPO, "pending_additions.json")
data = json.load(open(wp))
pending = json.load(open(pp)) if os.path.exists(pp) else {"workouts": [], "extraCardio": [], "flaggedForReview": []}
extra = json.load(open(extra_path)) if extra_path else {"workouts": [], "extraCardio": []}

existing_dates = {w["date"] for w in data["workouts"]}
catalog = {(e["name"], e.get("equipment", "")) for w in data["workouts"] for e in w["exercises"]}
old_flags = [f for f in pending.get("flaggedForReview", []) if not f.startswith("Nothing staged")]

def problems(w):
    out = []
    if w.get("type") not in TYPES: out.append(f"bad type {w.get('type')!r}")
    for e in w.get("exercises", []):
        if e["name"] in RENAME: e["name"], e["sheetName"] = RENAME[e["name"]]
        if not e.get("sheetName"): out.append(f"{e['name']}: no sheetName")
        for s in e.get("sets", []):
            if s.get("weight") is None or s.get("reps") is None: out.append(f"{e['name']}: set missing weight or reps")
            s.setdefault("warmup", False)
        if AUTO and (e["name"], e.get("equipment", "")) not in catalog: out.append(f"{e['name']} ({e.get('equipment','')}) is a new lift, confirm the name")
    return out

merged, held, held_flags, addons = [], [], [], []
next_id = max(w["id"] for w in data["workouts"]) + 1
by_date = {x["date"]: x for x in data["workouts"]}
for w in sorted(pending.get("workouts", []) + extra.get("workouts", []), key=lambda w: w["date"]):
    probs = problems(w)
    if probs:
        held.append(w); held_flags.append(f"{w['date']}: held, " + "; ".join(probs)); continue
    if w["date"] in by_date:
        cur = by_date[w["date"]]
        if cur.get("source") == "apple-health":
            run = cur.get("cardio")
            cur.update({"type": w["type"], "typeLabel": w.get("typeLabel") or w["type"], "exercises": w.get("exercises", [])})
            cur.pop("source", None)
            if w.get("cardio"):
                if run and (w["cardio"].get("machine") or "").lower() != "run":
                    ec = dict(run); ec["date"] = w["date"]; data.setdefault("extraCardio", []).append(ec)
                cur["cardio"] = w["cardio"]
            addons.append(f"{w['date']}: chat session replaced the imported-run-only day")
            continue
        have = {(e["name"], e.get("equipment", "")) for e in cur["exercises"]}
        new = [e for e in w.get("exercises", []) if (e["name"], e.get("equipment", "")) not in have]
        cur["exercises"].extend(new)
        filled = False
        if not cur.get("cardio") and w.get("cardio"):
            cur["cardio"] = w["cardio"]; filled = True
        if new or filled:
            addons.append(f"{w['date']}: added " + ", ".join([e["name"] for e in new] + (["cardio"] if filled else [])))
        continue
    rec = {"id": next_id, "date": w["date"], "type": w["type"], "typeLabel": w.get("typeLabel") or w["type"],
           "cardio": w.get("cardio"), "exercises": w.get("exercises", [])}
    data["workouts"].append(rec); existing_dates.add(w["date"]); merged.append(rec); next_id += 1
data["workouts"].sort(key=lambda w: (w["date"], w["id"]))
merged_dates = {w["date"] for w in merged}
ec_all = pending.get("extraCardio", []) + extra.get("extraCardio", [])
ec_in = [c for c in ec_all if c["date"] in merged_dates or c["date"] in existing_dates]
ec_hold = [c for c in ec_all if c not in ec_in]
data["extraCardio"] = data.get("extraCardio", []) + ec_in

if merged or ec_in or addons:
    with open(wp, "w") as f: json.dump(data, f, indent=1, ensure_ascii=False)
    arch = os.path.join(REPO, f"pending_additions.merged-{TODAY}.json")
    json.dump({"workouts": merged, "extraCardio": ec_in, "flaggedForReview": old_flags}, open(arch, "w"), indent=2)
note = (f"Nothing staged. On {TODAY} {len(merged)} session(s) ({', '.join(w['date'] for w in merged) or 'none'}) and {len(addons)} add-on(s) were merged into workouts.json."
        if not held else f"{len(held)} session(s) held for review on {TODAY}; see flaggedForReview.")
json.dump({"workouts": held, "extraCardio": ec_hold, "flaggedForReview": [note] + held_flags + ([f for f in old_flags] if held else [])},
          open(pp, "w"), indent=2)

print(f"merged {len(merged)} session(s), {len(ec_in)} extra cardio; held {len(held)}; workouts.json now {len(data['workouts'])} sessions through {data['workouts'][-1]['date']}")
for w in merged:
    ex = "; ".join(f"{e['name']} " + "/".join(f"{s['weight']}{'w' if s.get('warmup') else ''}" for s in e["sets"]) for e in w["exercises"])
    c = w.get("cardio") or {}
    print(f"  + #{w['id']} {w['date']} {w['typeLabel']}{' · ' + str(c.get('machine')) + ' ' + str(c.get('min')) + ' min' if c else ''} | {ex}")
for a_ in addons: print("  ~ " + a_)
for f in held_flags: print("  ! " + f)
