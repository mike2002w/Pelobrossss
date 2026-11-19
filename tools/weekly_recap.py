#!/usr/bin/env python3
"""Weekly recap email for the Pelobrossss log.

Usage: python3 tools/weekly_recap.py [--week YYYY-MM-DD] [--out DIR]

--week is any date inside the Monday-to-Sunday week to summarize. Default: the
last COMPLETE week before today. Writes recap-<monday>.html and .txt into --out
(default ~/.config/pelobrossss/recaps) and prints JSON {subject, html, text}.

Scoring mirrors quest/index.html (XP, levels, PRs, plateaus, muscle shares), so
the numbers in the email match the app.
"""
import json, os, re, sys, argparse, datetime as dt

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEST_URL = "https://mike2002w.github.io/Pelobrossss/quest/"
LBK = 2.20462
TITLES = [(1, 'Pre-med'), (3, 'Med student'), (6, 'Intern'), (10, 'Resident'), (14, 'Chief resident'), (18, 'Fellow'),
          (22, 'Attending'), (26, 'Professor'), (30, 'Department chair'), (35, 'Surgeon General')]
NAMES = {'chest': 'Chest', 'shoulders': 'Shoulders', 'back': 'Back', 'traps': 'Traps', 'lowerback': 'Lower back',
         'biceps': 'Biceps', 'triceps': 'Triceps', 'forearms': 'Forearms', 'core': 'Core', 'glutes': 'Glutes',
         'quads': 'Quads', 'hamstrings': 'Hamstrings', 'calves': 'Calves'}
MUSCLE_MAP = [
    (r'incline', {'chest': .55, 'shoulders': .25, 'triceps': .2}),
    (r'bench|chest press|flye|cable press|push[- ]?up', {'chest': .6, 'triceps': .25, 'shoulders': .15}),
    (r'shoulder press|overhead press|arnold', {'shoulders': .65, 'triceps': .35}),
    (r'lateral raise|front raise', {'shoulders': 1}),
    (r'face pull', {'shoulders': .5, 'traps': .3, 'back': .2}),
    (r'shrug', {'traps': 1}),
    (r'row', {'back': .65, 'biceps': .25, 'traps': .1}),
    (r'pulldown|pull-?up|chin-?up|straight arm', {'back': .7, 'biceps': .3}),
    (r'curl', {'biceps': .85, 'forearms': .15}),
    (r'tricep|dip', {'triceps': .9, 'chest': .1}),
    (r'squat|lunge|leg press|step', {'quads': .5, 'glutes': .3, 'hamstrings': .1, 'core': .1}),
    (r'rdl|deadlift|good morning|hip thrust', {'hamstrings': .5, 'glutes': .3, 'lowerback': .2}),
    (r'calf', {'calves': 1}),
    (r'abduction|adduction|hip ab|hip ad', {'glutes': .7, 'quads': .3}),
    (r'plank|crunch|core|leg raise|twist|sit-?up', {'core': 1}),
]
CORE_NOTE = re.compile(r'plank|crunch|core|leg raise|twist|sit-?up', re.I)


def weights(name):
    for pat, w in MUSCLE_MAP:
        if re.search(pat, name, re.I):
            return w
    return {}


def d(s): return dt.date.fromisoformat(s)
def monday(x): return x - dt.timedelta(days=x.weekday())
def xp_for(L): return round(300 * (L - 1) ** 1.5)
def level_for(xp):
    L = 1
    while xp_for(L + 1) <= xp: L += 1
    return L
def title_for(L): return [t for lv, t in TITLES if L >= lv][-1]
def unit(u): return 'kg' if u == 'kg' else ('' if u == 'bw' else 'lb')
def fmt(x): return f"{round(x):,}"
def num(x): return f"{x:.1f}".rstrip('0').rstrip('.')
def short(x): return x.strftime('%a %b ') + str(x.day)
def mon_day(x): return x.strftime('%b ') + str(x.day)


def analyze(data):
    ws = sorted(data['workouts'], key=lambda w: w['date'])
    extra = data.get('extraCardio', [])
    ex, sessions, prs = {}, [], []
    for w in ws:
        s = {'date': d(w['date']), 'label': w.get('typeLabel') or w['type'], 'type': w['type'], 'sets': 0, 'ton': 0.0,
             'cmin': 0.0, 'mi': 0.0, 'prs': [], 'vol': {}, 'names': []}
        for e in w.get('exercises', []):
            working = [x for x in e.get('sets', []) if not x.get('warmup') and x.get('weight') is not None]
            s['sets'] += len(working); s['names'].append(e['name'])
            for k, v in weights(e['name']).items():
                s['vol'][k] = s['vol'].get(k, 0) + v * len(working)
            assist = bool(e.get('assist')) or 'assisted' in e['name'].lower()
            if not assist and e.get('unit') != 'bw':
                s['ton'] += sum((x['weight'] * LBK if e.get('unit') == 'kg' else x['weight']) * (x.get('reps') or 0) for x in working)
            if working:
                top = min(x['weight'] for x in working) if assist else max(x['weight'] for x in working)
                key = (e['name'], e.get('equipment', ''), e.get('unit', ''))
                r = ex.setdefault(key, {'name': e['name'], 'equip': e.get('equipment', ''), 'unit': e.get('unit', 'lb'),
                                        'assist': assist, 'hist': [], 'best': None, 'best_date': None, 'stood': 0})
                better = r['best'] is None or (top < r['best'] if assist else top > r['best'])
                if better and r['best'] is not None:
                    pr = {'date': s['date'], 'name': e['name'], 'equip': r['equip'], 'unit': r['unit'], 'from': r['best'], 'to': top, 'stood': r['stood']}
                    prs.append(pr); s['prs'].append(pr)
                if better: r['best'], r['best_date'], r['stood'] = top, s['date'], 0
                else: r['stood'] += 1
                r['hist'].append((s['date'], top))
        c = w.get('cardio') or {}
        s['cmin'] += c.get('min') or 0; s['mi'] += c.get('mi') or 0
        for ec in (x for x in extra if x['date'] == w['date']):
            s['cmin'] += ec.get('min') or 0; s['mi'] += ec.get('mi') or 0
        notes = ' '.join(filter(None, [c.get('notes') or '', w.get('notes') or '']))
        if CORE_NOTE.search(notes): s['vol']['core'] = s['vol'].get('core', 0) + 2
        s['xp'] = 100 + s['sets'] * 8 + round(s['ton'] / 100) + round(s['cmin'] * 3) + round(s['mi'] * 20) + len(s['prs']) * 200
        sessions.append(s)
    dates = {w['date'] for w in ws}
    loose_xp = sum(round((x.get('min') or 0) * 3 + (x.get('mi') or 0) * 20) for x in extra if x['date'] not in dates)
    return sessions, ex, prs, loose_xp


def plateaus(ex, through):
    out = []
    for r in ex.values():
        if len(r['hist']) < 5 or r['unit'] == 'bw' or not r['best']: continue
        if r['hist'][-1][0] < through - dt.timedelta(days=60): continue
        tops = [t for _, t in r['hist']]; last = tops[-1]
        camp = 0
        for t in reversed(tops):
            if t != r['best']: break
            camp += 1
        inc = 2.5 if r['unit'] == 'kg' else 5
        kind = target = None
        if last == r['best'] and (camp >= 3 or sum(t == r['best'] for t in tops[-5:]) >= 3 or r['stood'] >= 8):
            kind, target = 'break', (r['best'] - inc if r['assist'] else r['best'] + inc)
        elif last != r['best'] and r['stood'] >= 3:
            kind, target = 'reclaim', r['best']
        if kind:
            out.append({**r, 'kind': kind, 'target': target, 'last': last, 'menace': len(tops) + r['stood'] * 2 + camp * 3})
    return sorted(out, key=lambda b: -b['menace'])


def build(week_date=None):
    data = json.load(open(os.path.join(REPO, 'workouts.json')))
    sessions, ex, prs, loose_xp = analyze(data)
    today = dt.date.today()
    wk = monday(week_date) if week_date else monday(today) - dt.timedelta(days=7)
    end = wk + dt.timedelta(days=6)
    prev_wk = wk - dt.timedelta(days=7)
    inw = [s for s in sessions if wk <= s['date'] <= end]
    prevw = [s for s in sessions if prev_wk <= s['date'] < wk]
    upto = [s for s in sessions if s['date'] <= end]
    xp_total = sum(s['xp'] for s in upto) + loose_xp
    xp_before = xp_total - sum(s['xp'] for s in inw)
    L, L0 = level_for(xp_total), level_for(xp_before)
    tot = lambda ss, k: sum(s[k] for s in ss)
    vol, pvol = {}, {}
    for s in inw:
        for k, v in s['vol'].items(): vol[k] = vol.get(k, 0) + v
    for s in prevw:
        for k, v in s['vol'].items(): pvol[k] = pvol.get(k, 0) + v
    week_prs = [p for p in prs if wk <= p['date'] <= end]
    bosses = plateaus({k: {**r, 'hist': [h for h in r['hist'] if h[0] <= end]} for k, r in ex.items()}, end)
    # streak: consecutive Monday weeks ending this week with 2+ workouts (this week needs 1)
    per = {}
    for s in sessions: per[monday(s['date'])] = per.get(monday(s['date']), 0) + 1
    streak, m = 0, wk
    if per.get(m, 0) >= 1:
        streak, m = 1, m - dt.timedelta(days=7)
        while per.get(m, 0) >= 2: streak, m = streak + 1, m - dt.timedelta(days=7)
    under = sorted([k for k in NAMES if vol.get(k, 0) < 10 and k not in ('forearms', 'lowerback')], key=lambda k: vol.get(k, 0))
    pend = {}
    try: pend = json.load(open(os.path.join(REPO, 'pending_additions.json')))
    except Exception: pass
    held = pend.get('workouts', [])

    def delta(a, b, fmt_=fmt):
        dd = a - b
        if abs(dd) < 0.5: return '<span style="color:#888">same as last week</span>'
        col = '#1d9e5f' if dd > 0 else '#c0392b'
        return f'<span style="color:{col}">{"+" if dd > 0 else "-"}{fmt_(abs(dd))} vs last week</span>'

    n, sets, ton, cmin, mi = len(inw), tot(inw, 'sets'), tot(inw, 'ton'), tot(inw, 'cmin'), tot(inw, 'mi')
    subject = f"Pelobrossss week of {mon_day(wk)}: {n} workout{'s' if n != 1 else ''}, {len(week_prs)} PR{'s' if len(week_prs) != 1 else ''}" + (f", Level {L}" if L > L0 else '')
    if n == 0: subject = f"Pelobrossss week of {mon_day(wk)}: no workouts logged"

    V, INK, MUT, LINE = '#6b5cff', '#1c1c1c', '#777', '#ececec'
    h2 = lambda t: f'<h2 style="font-size:13px;letter-spacing:.6px;text-transform:uppercase;color:{MUT};margin:26px 0 8px;font-weight:700">{t}</h2>'
    row = lambda l, r, sub='': (f'<tr><td style="padding:9px 0;border-bottom:1px solid {LINE};font-size:15px;color:{INK}">{l}'
                               + (f'<div style="font-size:12px;color:{MUT};margin-top:2px">{sub}</div>' if sub else '')
                               + f'</td><td style="padding:9px 0;border-bottom:1px solid {LINE};text-align:right;font-size:15px;font-weight:600;color:{V};white-space:nowrap">{r}</td></tr>')
    table = lambda rows: f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse">{"".join(rows)}</table>'
    tile = lambda v, l, sub: (f'<td width="25%" style="padding:12px 6px;background:#f6f5ff;border-radius:10px;text-align:center;vertical-align:top">'
                              f'<div style="font-size:22px;font-weight:700;color:{INK}">{v}</div><div style="font-size:11px;color:{MUT};margin-top:2px">{l}</div>'
                              f'<div style="font-size:10px;margin-top:4px">{sub}</div></td>')

    H = [f'<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:560px;margin:0 auto;color:{INK}">',
         f'<div style="background:#000;color:#fff;border-radius:14px;padding:20px 18px">'
         f'<div style="font-size:12px;letter-spacing:.8px;text-transform:uppercase;color:#9b9b9b">Weekly recap · {mon_day(wk)} to {mon_day(end)}</div>'
         f'<div style="font-size:28px;font-weight:700;margin-top:6px">Level {L} <span style="color:#8f83ff">{title_for(L)}</span></div>'
         f'<div style="font-size:13px;color:#bbb;margin-top:4px">+{fmt(xp_total - xp_before)} XP this week · {fmt(xp_for(L + 1) - xp_total)} XP to Level {L + 1}'
         + (f' · <b style="color:#3ddc84">leveled up from {L0}</b>' if L > L0 else '') + f' · {streak}-week streak</div></div>',
         '<table role="presentation" width="100%" cellspacing="6" cellpadding="0" style="margin-top:10px"><tr>'
         + tile(n, 'workouts', delta(n, len(prevw)))
         + tile(sets, 'working sets', delta(sets, tot(prevw, 'sets')))
         + tile(f"{ton / 1000:.1f}k", 'lb moved', delta(ton, tot(prevw, 'ton'), lambda x: f"{x / 1000:.1f}k"))
         + tile(fmt(cmin), 'cardio min', delta(cmin, tot(prevw, 'cmin'))) + '</tr></table>']
    T = [f"PELOBROSSSS WEEKLY RECAP · {mon_day(wk)} to {mon_day(end)}",
         f"Level {L} {title_for(L)}, +{fmt(xp_total - xp_before)} XP this week, {streak}-week streak",
         f"{n} workouts · {sets} working sets · {ton / 1000:.1f}k lb · {fmt(cmin)} cardio min · {num(mi)} mi", ""]

    H.append(h2('Workouts'))
    if inw:
        rows = []
        for s in inw:
            bits = [f"{s['sets']} sets" if s['sets'] else '', f"{round(s['cmin'])} min cardio" if s['cmin'] else '', 'PR' if s['prs'] else '']
            rows.append(row(f"{short(s['date'])} · {s['label']}", f"+{fmt(s['xp'])} XP", ' · '.join(b for b in bits if b)))
            T.append(f"{short(s['date'])}: {s['label']} ({', '.join(b for b in bits if b)}) +{s['xp']} XP")
        H.append(table(rows))
    else:
        H.append(f'<p style="color:{MUT};font-size:14px">Nothing logged this week. If you trained, the chat sync may have missed it.</p>')
        T.append("No workouts logged this week.")

    H.append(h2(f'Personal records ({len(week_prs)})'))
    if week_prs:
        H.append(table([row(f"{p['name']} <span style='color:{MUT};font-size:12px'>{p['equip']}</span>", f"{num(p['from'])} → {num(p['to'])} {unit(p['unit'])}",
                            f"{short(p['date'])}" + (f" · broke a {p['stood']}-session plateau" if p['stood'] >= 3 else '')) for p in week_prs]))
        T += ["", "PRs:"] + [f"  {p['name']} {num(p['from'])} -> {num(p['to'])} {unit(p['unit'])}" for p in week_prs]
    else:
        H.append(f'<p style="color:{MUT};font-size:14px">None this week.</p>')

    H.append(h2('Volume by muscle (target 10 to 20 hard sets)'))
    vrows = []
    for k in sorted(NAMES, key=lambda k: -vol.get(k, 0)):
        v = vol.get(k, 0)
        if v < 0.5 and pvol.get(k, 0) < 0.5: continue
        status = ('#1d9e5f', 'on target') if 10 <= v <= 20 else (('#b7791f', 'over 20') if v > 20 else ('#999', 'under 10'))
        bar = min(100, v / 25 * 100)
        vrows.append(f'<tr><td style="padding:7px 0;font-size:14px;width:34%">{NAMES[k]}</td>'
                     f'<td style="padding:7px 8px"><div style="background:#eee;border-radius:6px;height:8px;position:relative">'
                     f'<div style="background:{status[0]};width:{bar:.0f}%;height:8px;border-radius:6px"></div></div></td>'
                     f'<td style="padding:7px 0;font-size:13px;text-align:right;white-space:nowrap;color:{status[0]}">{num(v)} <span style="color:{MUT}">({num(pvol.get(k, 0))})</span></td></tr>')
    H.append(table(vrows) + f'<div style="font-size:11px;color:{MUT};margin-top:4px">Sets this week (last week in brackets). The band is a common coaching range, not a cited guideline.</div>')
    T += ["", "Volume (sets this week): " + ", ".join(f"{NAMES[k]} {num(vol.get(k, 0))}" for k in sorted(NAMES, key=lambda k: -vol.get(k, 0)) if vol.get(k, 0) >= 0.5)]

    # recovery from Apple Health (private file; this email goes only to him)
    health = {}
    try: health = json.load(open(os.path.expanduser('~/.config/pelobrossss/health/health.json')))
    except Exception: pass
    rdy = {}
    try: rdy = {x['date']: x for x in json.load(open(os.path.join(REPO, 'readiness.json')))['days']}
    except Exception: pass
    def avg(start, key, src):
        vals = [src[k][key] for k in src if start <= d(k) <= start + dt.timedelta(days=6) and src[k].get(key) is not None]
        return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)
    hrows, htxt = [], []
    for label, key, src, f, better in (('Readiness', 'score', rdy, lambda v: f"{v:.0f}", 1), ('HRV', 'hrv', health, lambda v: f"{v:.0f} ms", 1),
                                         ('Resting HR', 'resting_hr', health, lambda v: f"{v:.0f} bpm", -1), ('Sleep', 'sleep_min', health, lambda v: f"{int(v // 60)}h {int(v % 60):02d}m", 1)):
        cur, nd = avg(wk, key, src); prev, _ = avg(prev_wk, key, src)
        if cur is None: continue
        chg = ''
        if prev is not None and abs(cur - prev) >= 0.5:
            good = (cur - prev) * better > 0
            chg = f"<span style='color:{'#1d9e5f' if good else '#c0392b'}'>{'up' if cur > prev else 'down'} from {f(prev)}</span>"
        hrows.append(row(label, f(cur), f"average of {nd} day{'s' if nd != 1 else ''}" + (f" · {chg}" if chg else '')))
        htxt.append(f"{label} {f(cur)}" + (f" (last week {f(prev)})" if prev is not None else ''))
    stepsd = {}
    try: stepsd = json.load(open(os.path.expanduser('~/.config/pelobrossss/health/steps.json')))
    except Exception: pass
    def steps_avg(start):
        vals = [v for k, v in stepsd.items() if start <= d(k) <= start + dt.timedelta(days=6)]
        return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)
    sc, sn = steps_avg(wk); sp, _ = steps_avg(prev_wk)
    if sc is not None:
        chg = ''
        if sp is not None and abs(sc - sp) >= 1:
            chg = f"<span style='color:{'#1d9e5f' if sc > sp else '#c0392b'}'>{'up' if sc > sp else 'down'} from {fmt(sp)}</span>"
        hrows.append(row('Steps', f"{fmt(sc)}/day", f"average of {sn} day{'s' if sn != 1 else ''}" + (f" · {chg}" if chg else '')))
        htxt.append(f"Steps {fmt(sc)}/day" + (f" (last week {fmt(sp)})" if sp is not None else ''))
    if hrows:
        H.append(h2('Recovery (Apple Watch)'))
        H.append(table(hrows) + f'<div style="font-size:11px;color:{MUT};margin-top:4px">Readiness is an app heuristic from HRV and resting HR against your 30-day baseline, sleep vs 7.5 h, and training load. Not a clinical measure.</div>')
        T += ["", "Recovery: " + "; ".join(htxt)]

    H.append(h2('Plateaus to attack next week'))
    if bosses:
        H.append(table([row(f"{b['name']} <span style='color:{MUT};font-size:12px'>{b['equip']}</span>", f"{b['kind']} {num(b['target'])} {unit(b['unit'])}",
                            f"best {num(b['best'])} on {mon_day(b['best_date'])} · last {num(b['last'])}") for b in bosses[:4]]))
        T += ["", "Plateaus: " + "; ".join(f"{b['name']} {b['kind']} {num(b['target'])} {unit(b['unit'])}" for b in bosses[:4])]
    else:
        H.append(f'<p style="color:{MUT};font-size:14px">No plateaus. Every lift is moving.</p>')

    focus = [NAMES[k].lower() for k in under[:4]]
    H.append(h2('Next week'))
    plan = []
    if focus: plan.append(f"Bring up {', '.join(focus)} (fewest sets this week).")
    if bosses: plan.append(f"Lead with {bosses[0]['name']}: {bosses[0]['kind']} {num(bosses[0]['target'])} {unit(bosses[0]['unit'])}.")
    if cmin < 60: plan.append(f"Cardio was {fmt(cmin)} min; 60 closes the weekly goal.")
    if held: plan.append(f"{len(held)} session{'s' if len(held) != 1 else ''} or add-on{'s' if len(held) != 1 else ''} held in the sync queue ({', '.join(mon_day(d(w['date'])) for w in held)}); ask Claude to approve the staged workouts.")
    H.append('<ul style="padding-left:18px;margin:4px 0;font-size:14px;line-height:1.6">' + ''.join(f'<li>{p}</li>' for p in plan) + '</ul>')
    T += ["", "Next week:"] + [f"  - {p}" for p in plan]

    H.append(f'<div style="text-align:center;margin:26px 0 8px"><a href="{QUEST_URL}" style="background:{V};color:#fff;text-decoration:none;padding:12px 22px;border-radius:999px;font-weight:700;font-size:14px;display:inline-block">Open the quest</a></div>'
             f'<div style="text-align:center;font-size:11px;color:{MUT}">Generated from workouts.json ({len(sessions)} workouts through {mon_day(sessions[-1]["date"])}).</div></div>')
    T += ["", f"Open the quest: {QUEST_URL}"]
    return subject, ''.join(H), '\n'.join(T), wk


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--week'); ap.add_argument('--out', default=os.path.expanduser('~/.config/pelobrossss/recaps'))
    a = ap.parse_args()
    subject, html, text, wk = build(d(a.week) if a.week else None)
    os.makedirs(a.out, exist_ok=True)
    hp, tp = os.path.join(a.out, f'recap-{wk}.html'), os.path.join(a.out, f'recap-{wk}.txt')
    open(hp, 'w').write(html); open(tp, 'w').write(text)
    print(json.dumps({'subject': subject, 'html': hp, 'text': tp}))
