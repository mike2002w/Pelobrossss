#!/usr/bin/env python3
"""Import Peloton runs (and daily steps) from the iPhone Shortcut's activity files.

The "Pelobrossss Health" shortcut saves iCloud Drive/Shortcuts/Pelobrossss Health/
activity-YYYY-MM-DD.txt with:
  dist|<start>|<end>|<miles>|<source app>     one line per Walking + Running Distance
                                             sample longer than 10 min, last 3 days
  steps=<n>                                  then one bare number per line: daily step
                                             totals, oldest day first, ending today

Only samples whose source is the Peloton app become runs. Apple Health holds only
what was recorded on his own iPhone/Watch, so runs by other people on his Peloton
login never appear here.

Runs:
  - date not in workouts.json        -> new Cardio session (source: "apple-health")
  - session that day has no cardio   -> becomes that session's cardio
  - session already has a Run cardio -> skipped (the coaching chat already logged it)
  - session has other cardio         -> added to extraCardio (unless a Run is there)
  Imported runs are remembered by start time in a private state file, so a run is
  never added twice even if the chat later logs it.

Steps stay private (~/.config/pelobrossss/health/steps.json); the Monday recap uses them.

Usage: python3 tools/activity_import.py [--src DIR]
"""
import argparse, glob, json, os, re, datetime as dt

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser('~')
SRC = f"{HOME}/Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents/Pelobrossss Health"
PRIV = f"{HOME}/.config/pelobrossss/health"
STATE = os.path.join(PRIV, 'imported_runs.json')
STEPS = os.path.join(PRIV, 'steps.json')
MIN_RUN_MI = 0.5


def parse_when(s):
    s = s.strip().replace(' ', ' ').replace(' at ', ' ')
    for f in ('%b %d, %Y %I:%M %p', '%B %d, %Y %I:%M %p', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%d %H:%M'):
        try:
            return dt.datetime.strptime(s, f).replace(tzinfo=None)
        except ValueError:
            pass
    return None


def load(p, default):
    try:
        return json.load(open(p))
    except Exception:
        return default


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--src', default=SRC); ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    runs, steps = {}, load(STEPS, {})
    for path in sorted(glob.glob(os.path.join(a.src, 'activity-*.txt'))):
        m = re.search(r'(\d{4}-\d{2}-\d{2})', os.path.basename(path))
        if not m: continue
        fday = dt.date.fromisoformat(m.group(1))
        lines = open(path, encoding='utf-8', errors='ignore').read().splitlines()
        nums, in_steps = [], False
        for ln in lines:
            ln = ln.strip()
            if ln.startswith('dist|'):
                parts = ln.split('|')
                if len(parts) < 5 or 'peloton' not in parts[4].lower(): continue
                st, en = parse_when(parts[1]), parse_when(parts[2])
                try: mi = float(parts[3])
                except ValueError: continue
                if not st or not en or mi < MIN_RUN_MI: continue
                runs[st.isoformat(timespec='minutes')] = {'start': st, 'end': en, 'mi': mi}
            elif ln.startswith('steps='):
                in_steps = True; ln = ln[6:]
                if ln: nums.append(ln)
            elif in_steps and re.fullmatch(r'\d+(\.\d+)?', ln):
                nums.append(ln)
        # oldest first, last value = the file's own date (partial day)
        for i, v in enumerate(reversed(nums)):
            d = (fday - dt.timedelta(days=i)).isoformat()
            steps[d] = max(int(float(v)), steps.get(d, 0)) if i else int(float(v))

    data = json.load(open(os.path.join(REPO, 'workouts.json')))
    state = load(STATE, {'runs': []})
    done = set(state['runs'])
    by_date = {w['date']: w for w in data['workouts']}
    added, skipped = [], []
    for key in sorted(runs):
        if key in done: continue
        r = runs[key]; day = r['start'].date().isoformat()
        mins = round((r['end'] - r['start']).total_seconds() / 60, 2)
        pace = mins / r['mi'] if r['mi'] else 0
        cardio = {'machine': 'Run', 'min': mins, 'mi': round(r['mi'], 2), 'cal': None, 'hr': None,
                  'notes': f"Peloton run {r['start'].strftime('%-I:%M %p')}, {int(pace)}:{round((pace % 1) * 60):02d}/mi pace. Imported from Apple Health"}
        w = by_date.get(day)
        if w is None:
            rec = {'id': max(x['id'] for x in data['workouts']) + 1, 'date': day, 'type': 'Cardio', 'typeLabel': 'Cardio (Peloton run)',
                   'cardio': cardio, 'exercises': [], 'source': 'apple-health'}
            data['workouts'].append(rec); by_date[day] = rec; added.append(f"{day} new Cardio session: {r['mi']:.2f} mi, {mins:.0f} min")
        elif not w.get('cardio'):
            w['cardio'] = cardio; added.append(f"{day} run added as cardio to '{w.get('typeLabel')}': {r['mi']:.2f} mi, {mins:.0f} min")
        elif (w['cardio'].get('machine') or '').lower() == 'run' or any(c['date'] == day and (c.get('machine') or '').lower() == 'run' for c in data.get('extraCardio', [])):
            skipped.append(f"{day} run already logged from the chat")
        else:
            ec = dict(cardio); ec['date'] = day
            data.setdefault('extraCardio', []).append(ec); added.append(f"{day} run added as a second cardio bout: {r['mi']:.2f} mi, {mins:.0f} min")
        done.add(key)

    data['workouts'].sort(key=lambda w: (w['date'], w['id']))
    if not a.dry_run:
        if added:
            with open(os.path.join(REPO, 'workouts.json'), 'w') as f: json.dump(data, f, indent=1, ensure_ascii=False)
        os.makedirs(PRIV, exist_ok=True)
        json.dump({'runs': sorted(done)}, open(STATE, 'w'), indent=1)
        json.dump(dict(sorted(steps.items())), open(STEPS, 'w'), indent=1)
        for p in (STATE, STEPS): os.chmod(p, 0o600)
    print(f"peloton runs found: {len(runs)}; added: {len(added)}; skipped: {len(skipped)}; step days stored: {len(steps)}")
    for x in added: print('  + ' + x)
    for x in skipped: print('  = ' + x)


if __name__ == '__main__':
    main()
