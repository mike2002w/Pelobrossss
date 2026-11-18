#!/usr/bin/env python3
"""Apple Health import for Pelobrossss (via a daily iPhone Shortcut).

The Shortcut saves one small text file per day into iCloud Drive, e.g.
  iCloud Drive/Shortcuts/Pelobrossss Health/health-2026-11-18.txt
containing lines like:
  date=2026-11-18
  resting_hr=56
  hrv=48.2
  sleep=412          (minutes asleep last night; hours or seconds also accepted)

Usage: python3 tools/health_import.py [--src DIR ...] [--private FILE] [--public FILE]

- Raw values are merged into a PRIVATE file outside the repo
  (~/.config/pelobrossss/health/health.json). They are never committed.
- Only a derived daily readiness score (0-100, band, calibrating flag) is written
  to readiness.json in the repo, which the quest reads. The repo is public.

Readiness (an app heuristic, not a clinical measure): HRV and resting HR are
compared with your own trailing 30-day baseline (z-scores), sleep with a
7.5 hour target, and the previous two days of training load pull it down a little.
Weights: HRV 40%, resting HR 25%, sleep 25%, load 10%. Until 7 days of HRV and
resting HR exist the score is marked calibrating and leans on sleep.
"""
import argparse, glob, json, os, re, statistics, datetime as dt

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser('~')
DEFAULT_SRC = [
    f"{HOME}/Library/Mobile Documents/iCloud~is~workflow~my~workflows/Documents/Pelobrossss Health",
    f"{HOME}/Library/Mobile Documents/com~apple~CloudDocs/Pelobrossss Health",
]
PRIVATE = f"{HOME}/.config/pelobrossss/health/health.json"
PUBLIC = os.path.join(REPO, 'readiness.json')
NUM = re.compile(r'-?\d+(?:[.,]\d+)?')


def first_num(s):
    m = NUM.search(s or '')
    return float(m.group(0).replace(',', '.')) if m else None


def sleep_minutes(raw):
    v = first_num(raw)
    if v is None or v <= 0: return None
    low = (raw or '').lower()
    if 'hr' in low or 'hour' in low or v < 24: return v * 60       # hours
    if 'sec' in low or v > 1440: return v / 60                     # seconds
    return v                                                       # minutes


def parse_file(path):
    rec = {}
    for line in open(path, encoding='utf-8', errors='ignore'):
        if '=' not in line and ':' not in line: continue
        k, _, v = line.partition('=') if '=' in line else line.partition(':')
        k = k.strip().lower().replace(' ', '_'); v = v.strip()
        if k == 'date':
            m = re.search(r'\d{4}-\d{2}-\d{2}', v)
            if m: rec['date'] = m.group(0)
        elif k in ('resting_hr', 'rhr', 'resting_heart_rate'): rec['resting_hr'] = first_num(v)
        elif k in ('hrv', 'heart_rate_variability'): rec['hrv'] = first_num(v)
        elif k in ('sleep', 'sleep_minutes', 'asleep'): rec['sleep_min'] = sleep_minutes(v)
    if 'date' not in rec:
        m = re.search(r'\d{4}-\d{2}-\d{2}', os.path.basename(path))
        if m: rec['date'] = m.group(0)
    # sanity ranges: drop values a Shortcut glitch could produce
    if not (25 <= (rec.get('resting_hr') or 0) <= 120): rec.pop('resting_hr', None)
    if not (3 <= (rec.get('hrv') or 0) <= 300): rec.pop('hrv', None)
    if not (60 <= (rec.get('sleep_min') or 0) <= 960): rec.pop('sleep_min', None)
    return rec if 'date' in rec else None


def load_json(p, default):
    try: return json.load(open(p))
    except Exception: return default


def training_load():
    """Working sets + cardio minutes / 5 per date, from workouts.json."""
    data = load_json(os.path.join(REPO, 'workouts.json'), {'workouts': [], 'extraCardio': []})
    load = {}
    for w in data.get('workouts', []):
        sets = sum(1 for e in w.get('exercises', []) for s in e.get('sets', []) if not s.get('warmup'))
        cmin = (w.get('cardio') or {}).get('min') or 0
        load[w['date']] = load.get(w['date'], 0) + sets + cmin / 5
    for c in data.get('extraCardio', []):
        load[c['date']] = load.get(c['date'], 0) + (c.get('min') or 0) / 5
    return load


def clamp(x, lo=0, hi=100): return max(lo, min(hi, x))


def readiness(days):
    """days: {date: {resting_hr, hrv, sleep_min}} -> list of public rows."""
    load = training_load()
    out = []
    dates = sorted(days)
    for d in dates:
        r = days[d]; D = dt.date.fromisoformat(d)
        base = [days[x] for x in dates if D - dt.timedelta(days=30) <= dt.date.fromisoformat(x) < D]
        def z(key):
            vals = [b[key] for b in base if b.get(key) is not None]
            if r.get(key) is None or len(vals) < 7: return None
            sd = statistics.pstdev(vals) or 1.0
            return (r[key] - statistics.mean(vals)) / sd
        zh, zr = z('hrv'), z('resting_hr')
        parts, wsum = 0.0, 0.0
        if zh is not None: parts += 0.40 * clamp(60 + 20 * zh); wsum += 0.40
        if zr is not None: parts += 0.25 * clamp(60 - 20 * zr); wsum += 0.25
        if r.get('sleep_min') is not None:
            parts += 0.25 * clamp(100 * r['sleep_min'] / 450); wsum += 0.25
        prev = [load.get((D - dt.timedelta(days=k)).isoformat(), 0) for k in (1, 2)]
        lscore = clamp(100 - 2.0 * (prev[0] + 0.5 * prev[1]))
        parts += 0.10 * lscore; wsum += 0.10
        if wsum <= 0.10: continue  # nothing but load: no score
        score = round(parts / wsum)
        band = 'green' if score >= 67 else ('yellow' if score >= 40 else 'red')
        calibrating = sum(1 for b in base if b.get('hrv') is not None) < 7
        out.append({'date': d, 'score': score, 'band': band, 'calibrating': calibrating})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', action='append'); ap.add_argument('--private', default=PRIVATE); ap.add_argument('--public', default=PUBLIC)
    a = ap.parse_args()
    srcs = a.src or DEFAULT_SRC
    store = load_json(a.private, {})
    found = 0
    for src in srcs:
        for p in sorted(glob.glob(os.path.join(src, '*.txt'))):
            rec = parse_file(p)
            if not rec: continue
            found += 1
            d = rec.pop('date'); cur = store.get(d, {})
            cur.update({k: v for k, v in rec.items() if v is not None})
            store[d] = cur
    os.makedirs(os.path.dirname(a.private), exist_ok=True)
    with open(a.private, 'w') as f: json.dump(dict(sorted(store.items())), f, indent=1)
    os.chmod(a.private, 0o600)
    rows = readiness(store)
    with open(a.public, 'w') as f: json.dump({'version': 1, 'note': 'Derived daily readiness score only; raw health data is kept private.', 'days': rows}, f, indent=1)
    last = rows[-1] if rows else None
    print(f"files read: {found}; days stored: {len(store)}; readiness days: {len(rows)}"
          + (f"; latest {last['date']}: {last['score']} ({last['band']}{', calibrating' if last['calibrating'] else ''})" if last else '; no readiness yet'))


if __name__ == '__main__':
    main()
