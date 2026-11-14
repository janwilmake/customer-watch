#!/usr/bin/env python3
"""customer-watch report: one overview across every customer ledger. No model, like note.py.

Usage:
  report.py daily            for me: what is late, the calls to make, the drafts to send, today's meetings
  report.py weekly           for the team: status per customer, the most-asked wishes, what shipped,
                             who is at risk, and my trust work. Company names and counts only, unless
                             config.json sets "report": {"names": true}: then it also names the
                             champion, the individual trials and the reporter of each fix. Never a
                             phone number or message text.
  report.py roost <session>  post the daily overview to that session's Roost note (Late badge)

It prints Markdown that Slack and most chat tools render. The session that runs the report sends it.
"""
import datetime as dt
import os
import re
import statistics
import sys

import core
import note
from core import HOME, load
from note import parse, when

NOW = core.now()
ME = core.me()
STALE_HOURS = 12  # a watched customer whose session has not run its full check for this long


def ledgers():
    root = os.path.join(HOME, "customers")
    out = {}
    for slug in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        led = load(os.path.join(root, slug, "ledger.json"), None)
        if led:
            out[slug] = led
    return out


def name(slug, led):
    return (led.get("customer") or {}).get("name") or slug


def is_person(led):
    """A trial of one person (no company domain): never named in the team report."""
    c = led.get("customer") or {}
    return not c.get("domains") or c.get("name_match") is False


def watchers():
    """{slug: hours since its session's last full check}, for every live session that watches it."""
    try:
        import roster
        live = roster.live_sessions()
    except SystemExit:
        live = set(os.listdir(os.path.join(HOME, "sessions")))
    out = {}
    for sid in live:
        sdir = os.path.join(HOME, "sessions", sid)
        watch = load(os.path.join(sdir, "watch.json"), {})
        last = load(os.path.join(sdir, "state.json"), {}).get("last_full")
        age = (NOW.timestamp() - last) / 3600 if last else None
        for slug in watch.get("slugs", []):
            if slug not in out or (age is not None and (out[slug] is None or age < out[slug])):
                out[slug] = age
    return out


def plural(n, word):
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def short(text, limit=110):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def counts(led):
    convs = [c for c in led.get("conversations", []) if c.get("status") == "open" and not note.delegated(c)]
    ours = [c for c in convs if c.get("ball") == "us" and not note.in_progress(c, NOW)]
    promises = [p for p in led.get("promises", []) if p.get("status") == "open" and not note.delegated(p)]
    theirs = [c for c in convs if c.get("ball") == "them"]
    return len(ours) + len(promises), len(theirs)


# ---- daily, for me ------------------------------------------------------------------------------

def daily():
    leds = ledgers()
    watched = watchers()
    late = {s: note.late_items(l, NOW) for s, l in leds.items()}
    calls = [(s, c) for s, l in leds.items() for c in note.calls(l)]
    drafts = [(s, d) for s, l in leds.items() for d in note.drafts(l)]
    untold = [(s, w) for s, l in leds.items() for w, _ in note.untold(l, NOW)]
    soon = []
    for s, l in leds.items():
        nxt = ((l.get("meetings") or {}).get("next") or {})
        at = parse(nxt.get("at"))
        if at and NOW <= at <= NOW + dt.timedelta(hours=36):
            soon.append((at, s, nxt))
    n_late = sum(len(v) for v in late.values())
    out = [f"**Customers, {NOW.astimezone(core.tz()).strftime('%a %-d %b')}** — "
           f"{n_late} late at {plural(sum(1 for v in late.values() if v), 'customer')} · "
           f"{plural(len(calls), 'call')} to make · {plural(len(drafts), 'draft')} to send · "
           f"{plural(len(untold), 'fix')} not told".replace("fixs", "fixes")]

    if n_late:
        out.append("\n**Late**")
        rows = sorted(((len(v), s) for s, v in late.items() if v), reverse=True)
        shown = 0
        for _, s in rows:
            for item in late[s]:
                if shown < 15:
                    out.append(f"• {name(s, leds[s])}: {short(item)}")
                shown += 1
        if shown > 15:
            out.append(f"• … and {shown - 15} more")
    if calls:
        out.append("\n**Calls to make**")
        out += [f"• {c.get('contact')} ({name(s, leds[s])}) {c.get('phone') or ''}: {short(c.get('why'), 90)}".replace("  ", " ")
                for s, c in calls[:8]]
    if drafts:
        out.append("\n**Drafts to send**")
        for s, d in drafts[:8]:
            age = (NOW - parse(d["at"])).days if parse(d.get("at")) else 0
            out.append(f"• {d.get('contact')} ({name(s, leds[s])}, {d.get('channel')}, {age} d): {d.get('link')}")
    if soon:
        out.append("\n**Meetings in the next 36 hours**")
        for at, s, m in sorted(soon, key=lambda r: r[0]):
            ask = (m.get("prep") or {}).get("ask")
            out.append(f"• {when(core.iso(at))}: {m.get('who')}" + (f" — ask: {short(ask, 60)}" if ask else ""))
    stale = [s for s in leds if s in watched and watched[s] is not None and watched[s] > STALE_HOURS]
    unwatched = [s for s in leds if s not in watched and not is_person(leds[s])]
    if stale or unwatched:
        out.append("\n**Check the watch**")
        if stale:
            out.append("• no full check for 12 h+: " + ", ".join(name(s, leds[s]) for s in stale[:10]))
        if unwatched:
            out.append("• no live session: " + ", ".join(name(s, leds[s]) for s in unwatched[:10]))
    return "\n".join(out)


# ---- weekly, for the team -----------------------------------------------------------------------

def champion(led):
    for p in (led.get("customer") or {}).get("contacts", []):
        if "champion" in (p.get("role") or "").lower() and p.get("name"):
            return p["name"]
    return None


def weekly():
    names = bool((core.config().get("report") or {}).get("names"))
    leds = ledgers()
    week = NOW - dt.timedelta(days=7)
    me = ME.get("first_name") or "me"
    companies = {s: l for s, l in leds.items() if names or not is_person(l)}
    people = {s: l for s, l in leds.items() if not names and is_person(l)}

    touches = [e for l in leds.values() for e in l.get("trust_log") or [] if parse(e.get("at")) and parse(e["at"]) >= week]
    asks = [e for e in touches if e.get("kind") == "ask"]
    in_contact = {s for s, l in leds.items() if parse(l.get("last_contact_at")) and parse(l["last_contact_at"]) >= week}
    shipped = [(s, w) for s, l in leds.items() for w in l.get("wishes", [])
               if w.get("status") == "shipped" and parse(w.get("shipped_at")) and parse(w["shipped_at"]) >= week]
    told_h = [(parse(w["told_at"]) - parse(w["shipped_at"])).total_seconds() / 3600 for _, w in shipped if parse(w.get("told_at"))]
    n_late = sum(len(note.late_items(l, NOW)) for l in leds.values())

    iso = NOW.astimezone(core.tz()).isocalendar()
    out = [f"**{me}'s customers, week {iso[1]}**",
           f"{len(in_contact)} of {len(leds)} customers in contact this week · {n_late} things late · "
           f"{len(shipped)} wishes shipped, {len(told_h)} told"
           + (f" (median {statistics.median(told_h):.0f} h from live to told)" if told_h else "")
           + f" · {plural(len(touches), 'personal touch').replace('touchs', 'touches')} by {me}"
           + (f" · {len(asks)} asks, {sum(1 for a in asks if a.get('outcome') == 'yes')} yes" if asks else "")]

    out.append("\n**Per customer**")
    rows = []
    for s, l in companies.items():
        late, (ours, theirs) = len(note.late_items(l, NOW)), counts(l)
        u = l.get("usage") or {}
        users = f" · users {u.get('active_users_14d')} ({u.get('active_users_prev_14d')} before)" if u.get("active_users_14d") is not None else ""
        nxt = parse(((l.get("meetings") or {}).get("next") or {}).get("at"))
        champ = champion(l) if names else None
        line = (f"• **{name(s, l)}**" + (f" ({champ})" if champ else "") + f" — late {late} · waiting for us {ours} · for them {theirs} · "
                f"last contact {when(l.get('last_contact_at'))[:10].rstrip()}"
                + (f" · next meeting {when(core.iso(nxt))[:10].rstrip()}" if nxt and nxt >= NOW else "") + users)
        rows.append((-late, -ours, name(s, l).lower(), line))
    busy = [r for r in sorted(rows) if r[0] or r[1]]
    out += [r[3] for r in busy[:12]]
    rest = len(rows) - min(len(busy), 12)
    if rest:
        out.append(f"• {plural(rest, 'more customer')}: nothing late or waiting on us" if len(busy) <= 12
                   else f"• {plural(rest, 'more customer')}, with less waiting")
    if people:
        late_p = sum(len(note.late_items(l, NOW)) for l in people.values())
        out.append(f"• {len(people)} individual trials — late {late_p}")

    wishes = {}
    for s, l in leds.items():
        for w in l.get("wishes", []):
            if w.get("status") == "open" and w.get("name"):
                g = wishes.setdefault(w["name"], {"customers": set(), "must": 0, "kind": w.get("kind", "feature")})
                g["customers"].add(s)
                g["must"] += w.get("priority") == "must-have"
    if wishes:
        out.append("\n**Most asked for** (open)")
        top = sorted(wishes.items(), key=lambda kv: (-len(kv[1]["customers"]), -kv[1]["must"], kv[0]))[:8]
        for wname, g in top:
            n = len(g["customers"])
            out.append(f"• `{wname}` ({g['kind']}) — {n} customer{'s' if n > 1 else ''}"
                       + (f", must-have for {g['must']}" if g["must"] else ""))

    if shipped:
        out.append("\n**Shipped this week**")
        for s, w in shipped[:10]:
            who = name(s, leds[s]) if names or not is_person(leds[s]) else "an individual trial"
            if names and w.get("reporter"):
                who += f" ({w['reporter']})"
            out.append(f"• `{w.get('name')}` for {who} — " + ("told ✅" if w.get("told_at") else "not told yet"))

    risk = []
    for s, l in companies.items():
        why = []
        u = l.get("usage") or {}
        prev, cur = u.get("active_users_prev_14d") or 0, u.get("active_users_14d") or 0
        if prev >= 3 and cur <= 0.7 * prev:
            why.append(f"usage {prev} → {cur}")
        last = parse(l.get("last_contact_at"))
        nxt = parse(((l.get("meetings") or {}).get("next") or {}).get("at"))
        if (not last or (NOW - last).days > 14) and not (nxt and nxt >= NOW):
            why.append("no contact for 2 weeks")
        late = len(note.late_items(l, NOW))
        if late >= 3:
            why.append(f"{late} things late")
        if why:
            risk.append(f"• **{name(s, l)}**: " + ", ".join(why))
    if risk:
        out.append("\n**Needs attention**")
        out += risk[:10]
    return "\n".join(out)


def roost(session):
    leds = ledgers()
    text = note.compact(leds, NOW).split("\n", 1)
    body = text[1] if len(text) > 1 else ""
    notes = (f"About: overview of all {len(leds)} customers (report.py); the daily report goes to Slack.\n"
             f"All customers — Late: {sum(len(note.late_items(l, NOW)) for l in leds.values())}\n" + body)
    out = core.roost(session)
    if not out:
        print(notes)
        return
    import json
    import subprocess
    r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-X", "POST", "-H",
                        "content-type: application/json", "-d", json.dumps({"notes": notes[:3000]}), out],
                       capture_output=True, text=True)
    print(r.stdout)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "daily":
        print(daily())
    elif mode == "weekly":
        print(weekly())
    elif mode == "roost" and len(sys.argv) > 2:
        roost(sys.argv[2])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
