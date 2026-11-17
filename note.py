#!/usr/bin/env python3
"""customer-watch note: renders the note of a session from its customers' ledgers.

Usage: note.py <session-id> [--post]

The Late count is computed here, from the ledger and the clock, never by the model, so the badge
follows the same rules on every render. Every render also writes <home>/sessions/<id>/note.md.
--post sends the note to Roost when config.json has a roost_url; without it, it prints.
"""
import datetime as dt
import json
import os
import subprocess
import sys

import core
from core import HOME

AMS = core.tz()  # the user's own timezone, from config.json
CFG = core.config()
ME = core.me()
LATE_HOURS = CFG["late_after_working_hours"]


def parse(value):
    if not value:
        return None
    t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=AMS)


def when(value):
    t = parse(value)
    return t.astimezone(AMS).strftime("%a %-d %b %H:%M") if t else "none found"


def working_hours(since, until):
    """Hours between two moments that fall on Monday to Friday, in the user's timezone."""
    total, t = 0.0, since.astimezone(AMS)
    end = until.astimezone(AMS)
    while t < end:
        step = min(end, (t + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))
        if t.weekday() < 5:
            total += (step - t).total_seconds() / 3600
        t = step
    return total


def add_working_hours(since, hours):
    """The moment that lies `hours` working hours (Monday to Friday, the user's timezone) after `since`."""
    t, left = since.astimezone(AMS), hours
    while True:
        step = (t + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        if t.weekday() < 5:
            span = (step - t).total_seconds() / 3600
            if span >= left:
                return t + dt.timedelta(hours=left)
            left -= span
        t = step


BACK_AFTER_WORKING_DAYS = 2


def due(item):
    """When an open item of ours turns late: the reply limit of a conversation, or the date of a promise."""
    if item.get("ball") == "us" and parse(item.get("waiting_since")):
        return add_working_hours(parse(item["waiting_since"]), LATE_HOURS)
    return parse(item.get("due"))


def with_due(text, item):
    d = due(item)
    return f"{text} (due {when(d.isoformat())})" if d else text


def label(item):
    return item.get("todo") or item.get("subject") or item.get("what") or item.get("name") or "an item"


def delegated(item):
    """The hand-over of an open item to a teammate, or None."""
    d = item.get("delegated")
    return d if item.get("status") == "open" and isinstance(d, dict) and parse(d.get("since")) else None


def delegations(ledger, now):
    """(waiting for team, late again): a handed-over item counts for the team until the teammate is late."""
    team, late = [], []
    for kind in ("conversations", "promises", "wishes"):
        for item in ledger.get(kind, []):
            d = delegated(item)
            if not d:
                continue
            days = working_hours(parse(d["since"]), now) / 24
            who = d.get("to") or "the team"
            if days >= d.get("back_after_working_days", BACK_AFTER_WORKING_DAYS):
                late.append((item, f"(late: {who} has not replied for {days:.0f} working days) {d.get('ask') or label(item)}"))
            else:
                back = add_working_hours(parse(d["since"]), d.get("back_after_working_days", BACK_AFTER_WORKING_DAYS) * 24)
                team.append((item, f"{who}: {d.get('ask') or label(item)} (asked {when(d['since'])}, back by {when(back.isoformat())})"))
    return team, late


def in_progress(item, now):
    """The hand-over of an open item to this session, or None once its `until` has passed.

    After `until` the item counts as before, so a session that died cannot hide it.
    """
    ip = item.get("in_progress")
    if item.get("status") != "open" or delegated(item) or not isinstance(ip, dict):
        return None
    until = parse(ip.get("until"))
    return ip if until and until > now else None


def progress(ledger, now):
    """What the user handed to this session, as lines for the note."""
    out = []
    for kind in ("conversations", "promises", "wishes"):
        for item in ledger.get(kind, []):
            ip = in_progress(item, now)
            if ip:
                out.append((item, f"{ip.get('what') or label(item)} (until {when(ip['until'])})"))
    return out


def sources(item):
    return {item.get("link"), item.get("id"), item.get("source"), item.get("wish"), item.get("name")} - {None, ""}


def late_items(ledger, now):
    team, late_again = delegations(ledger, now)
    busy = progress(ledger, now)
    items = [text for _, text in late_again]
    # A handed-over item, and every wish or promise about it, is that one thing: it does not count again.
    handed = team + late_again + busy
    late_sources = set().union(*(sources(item) for item, _ in handed)) if handed else set()
    for c in ledger.get("conversations", []):
        if delegated(c) or in_progress(c, now):
            continue
        if c.get("status") == "open" and c.get("ball") == "us" and c.get("waiting_since"):
            hours = working_hours(parse(c["waiting_since"]), now)
            if hours > LATE_HOURS:
                items.append(f"(late: no reply for {hours / 24:.0f} working days) {c.get('todo') or c.get('subject')}")
                late_sources |= {c.get("link"), c.get("id")} - {None, ""}
    for p in ledger.get("promises", []):
        if delegated(p) or in_progress(p, now) or p.get("wish") in late_sources or p.get("source") in late_sources:
            continue
        if p.get("status") == "open" and p.get("due") and parse(p["due"]) < now:
            items.append(f"(late: promised by {when(p['due'])}) {p.get('what')}")
            late_sources |= {p.get("source"), p.get("wish")} - {None, ""}
    # A wish with a promised date still ahead is late only when that date passes, as a promise.
    promised = set().union(*(
        {p.get("wish"), p.get("source")} for p in ledger.get("promises", [])
        if p.get("status") == "open" and parse(p.get("due")) and parse(p["due"]) >= now
    )) - {None, ""}
    # A wish whose conversation waits for the customer's answer waits on them, not on us.
    theirs = set().union(*(
        {c.get("link"), c.get("id")} for c in ledger.get("conversations", [])
        if c.get("status") == "open" and c.get("ball") == "them"
    )) - {None, ""}
    for w in ledger.get("wishes", []):
        # A wish that a late conversation or promise already counts is the same late thing.
        if delegated(w) or in_progress(w, now) or w.get("source") in late_sources or w.get("name") in late_sources:
            continue
        if w.get("name") in promised or w.get("source") in promised or w.get("source") in theirs:
            continue
        if (w.get("status") == "open" and w.get("priority") == "must-have"
                and parse(w.get("date")) and (now - parse(w["date"])).days > 14):
            items.append(f"(late: open since {when(w['date'])[:10].rstrip()}) {w.get('kind', 'feature')} {w.get('name')}")
    for w, hours in untold(ledger, now):
        if hours > LATE_HOURS:
            items.append(f"(late: live since {when(w['shipped_at'])}, not told) tell {w.get('reporter') or 'the reporter'} yourself: {w.get('name')}")
    last = parse(ledger.get("last_contact_at"))
    upcoming = parse(((ledger.get("meetings") or {}).get("next") or {}).get("at"))
    if last and (now - last).days > 7 and not (upcoming and upcoming > now):
        items.append(f"(late: no contact since {when(ledger['last_contact_at'])}) plan a touchpoint")
    return items


def deadline_items(ledger, now):
    """(moment, text) for every open thing with a date: when it turns late, or when it turned late.

    Roost gets these next to the note, so the agenda holds them all while the note stays short.
    """
    out = []
    covered = set()
    for kind in ("conversations", "promises", "wishes"):
        for item in ledger.get(kind, []):
            d = delegated(item)
            if d:
                back = add_working_hours(parse(d["since"]), d.get("back_after_working_days", BACK_AFTER_WORKING_DAYS) * 24)
                out.append((back, f"{d.get('to') or 'the team'}: {d.get('ask') or label(item)}"))
                covered |= sources(item)
            elif in_progress(item, now):
                ip = item["in_progress"]
                out.append((parse(ip["until"]), f"in progress: {ip.get('what') or label(item)}"))
                covered |= sources(item)
    for c in ledger.get("conversations", []):
        if c.get("status") == "open" and not delegated(c) and not in_progress(c, now) and due(c):
            out.append((due(c), label(c)))
    for p in ledger.get("promises", []):
        if p.get("status") == "open" and not delegated(p) and not in_progress(p, now) and parse(p.get("due")):
            out.append((parse(p["due"]), label(p)))
            covered |= {p.get("wish"), p.get("source")} - {None, ""}
    theirs = set().union(*(
        {c.get("link"), c.get("id")} for c in ledger.get("conversations", [])
        if c.get("status") == "open" and c.get("ball") == "them"
    )) - {None, ""}
    for w in ledger.get("wishes", []):
        if (w.get("status") == "open" and w.get("priority") == "must-have" and parse(w.get("date"))
                and not delegated(w) and not in_progress(w, now)
                and not ({w.get("name"), w.get("source")} & (covered | theirs))):
            out.append((parse(w["date"]) + dt.timedelta(days=14), f"{w.get('kind', 'feature')} {w.get('name')}"))
    for w, _ in untold(ledger, now):
        out.append((add_working_hours(parse(w["shipped_at"]), LATE_HOURS),
                    f"tell {w.get('reporter') or 'the reporter'} that {w.get('name')} is live"))
    last = parse(ledger.get("last_contact_at"))
    upcoming = parse(((ledger.get("meetings") or {}).get("next") or {}).get("at"))
    if last and not (upcoming and upcoming > now):
        out.append((last + dt.timedelta(days=7), "plan a touchpoint"))
    return sorted(out, key=lambda x: x[0])


def untold(ledger, now):
    """(wish, working hours since it went live) for each shipped wish nobody told the customer about."""
    out = []
    for w in ledger.get("wishes", []):
        if w.get("status") == "shipped" and parse(w.get("shipped_at")) and not w.get("told_at") \
                and not delegated({**w, "status": "open"}) and not in_progress({**w, "status": "open"}, now):
            out.append((w, working_hours(parse(w["shipped_at"]), now)))
    return out


def touches(ledger, name):
    """My own trust log entries with one contact, newest first."""
    rows = [e for e in ledger.get("trust_log") or [] if e.get("contact") == name and parse(e.get("at"))]
    return sorted(rows, key=lambda e: parse(e["at"]), reverse=True)


def trust_moves(ledger, now):
    """The next personal moves: tell a reporter that a fix is live, then each key contact's next step.

    These never count as Late (except a fix left untold, which late_items counts): the badge stays
    "a customer waits for us", and trust is a list to work through when there is time.
    The step per contact comes from nextstep.py, so the note and every draft agree.
    """
    import nextstep
    moves = []
    for w, hours in untold(ledger, now):
        if hours <= LATE_HOURS:
            moves.append(f"tell {w.get('reporter') or 'the reporter'} yourself that {w.get('name')} is live (a short video works best)")
    every = ME.get("touch_every_days", 21)
    for st in nextstep.contact_steps(ledger, now):
        s = st["signals"]
        name = st["contact"]
        if not s["key"] or s["untold_fixes"] or any(c.get("contact") == name for c in calls(ledger)):
            continue
        override = ((next((p for p in ledger["customer"]["contacts"] if p.get("name") == name), {})
                     .get("trust") or {}).get("next_move"))
        last = parse((s["last_touch"] or {}).get("at"))
        if override:
            moves.append(f"{name}: {override}")
        elif s["open_ask"] and (now - parse(s["open_ask"]["at"])).days >= nextstep.OPEN_ASK_DAYS:
            moves.append(f"{name}: the {s['open_ask']['ask']} ask of {when(s['open_ask']['at'])[:10].rstrip()} has no answer: follow up once, or close it")
        elif not st["step"].startswith("no ask"):
            moves.append(f"{name}: {st['step']}")
        elif last and (now - last).days > every:
            moves.append(f"{name}: no personal touch from you since {when(s['last_touch']['at'])[:10].rstrip()}")
    return moves


def calls(ledger):
    return [c for c in ledger.get("calls_to_make") or [] if c.get("status", "open") == "open"]


def drafts(ledger):
    return [d for d in ledger.get("drafts") or [] if d.get("status", "open") == "open"]


def block(slug, ledger, now, prefix):
    c = ledger.get("customer", {})
    name = c.get("name", slug)
    convs = [x for x in ledger.get("conversations", []) if x.get("status") == "open"]
    ours = [x for x in convs if x.get("ball") == "us" and not delegated(x) and not in_progress(x, now)] + [
        p for p in ledger.get("promises", []) if p.get("status") == "open" and not delegated(p) and not in_progress(p, now)]
    theirs = [x for x in convs if x.get("ball") == "them" and not delegated(x)]
    late = late_items(ledger, now)
    team = [text for _, text in delegations(ledger, now)[0]]
    busy = [text for _, text in progress(ledger, now)]
    m = ledger.get("meetings") or {}

    def meet(x):
        if not x:
            return "none found"
        ask = (x.get("prep") or {}).get("ask")
        return f"{x.get('who')}, {when(x.get('at'))}" + (f" (ask: {ask})" if ask else "")

    msg = ledger.get("last_message") or {}
    lines = [
        f"{name + ' — ' if prefix else ''}Late: {len(late)} · Waiting for us: {len(ours)} · Waiting for them: {len(theirs)}"
        f"{f' · Waiting for team: {len(team)}' if team else ''}"
        f"{f' · In progress: {len(busy)}' if busy else ''}",
        f"Last meeting: {meet(m.get('last'))}",
        f"Last message: {msg.get('who', 'none found')}{', ' + when(msg.get('at')) if msg else ''}"
        f"{' (' + msg['channel'] + ')' if msg.get('channel') else ''}",
        f"Next meeting: {meet(m.get('next'))}",
    ]
    if ledger.get("changed"):
        lines.append(f"Changed: {ledger['changed']}")
    if late:
        lines += ["Waiting for you:"] + [f"- {i}" for i in late]
    if team:
        lines += ["Waiting for team:"] + [f"- {i}" for i in team]
    if busy:
        lines += ["In progress:"] + [f"- {i}" for i in busy]
    open_now = [x for x in ours if not any(label(x) in i for i in late)]
    open_now.sort(key=lambda x: due(x) or now + dt.timedelta(days=3650))
    if open_now:
        lines += ["Open, not late:"] + [f"- {with_due(label(x), x)}" for x in open_now[:4]]
    todo_calls = calls(ledger)
    if todo_calls:
        lines.append("Calls to make:")
        for i, c in enumerate(todo_calls[:2]):
            lines.append(f"- {c.get('contact')} {c.get('phone') or ''}: {c.get('why')}".replace("  ", " "))
            if i == 0:
                lines += [f"  · {n}" for n in (c.get("notes") or [])[:4]]
    ready = drafts(ledger)
    if ready:
        lines += ["Drafts ready:"] + [f"- {d.get('contact')} ({d.get('channel')}): {d.get('link')}" for d in ready[:3]]
    moves = trust_moves(ledger, now)
    if moves:
        lines += ["Trust:"] + [f"- {m}" for m in moves[:3]]
    return "\n".join(lines)


COMPACT_ABOVE = 3


def short(text, limit=110):
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def compact(ledgers, now):
    """Many customers: one header line per customer that needs us, its late things, then a count of the rest.

    Roost asks for notes under 300 words; the full four-line header per customer does not fit past a few.
    """
    rows, quiet = [], 0
    for slug, ledger in ledgers.items():
        name = (ledger.get("customer") or {}).get("name", slug)
        convs = [x for x in ledger.get("conversations", []) if x.get("status") == "open" and not delegated(x)]
        ours = len([x for x in convs if x.get("ball") == "us" and not in_progress(x, now)]) + len(
            [p for p in ledger.get("promises", []) if p.get("status") == "open" and not delegated(p)
             and not in_progress(p, now)])
        theirs = len([x for x in convs if x.get("ball") == "them"])
        late = late_items(ledger, now)
        team = [text for _, text in delegations(ledger, now)[0]]
        busy = [text for _, text in progress(ledger, now)]
        if not late and not ours and not team and not busy:
            quiet += 1
            continue
        dues = [d for d in (due(x) for x in convs + ledger.get("promises", [])
                            if x.get("status") == "open" and not delegated(x) and not in_progress(x, now)) if d and d >= now]
        rows.append((len(late), ours, name, theirs, late, team, busy, min(dues) if dues else None))
    rows.sort(key=lambda r: (-r[0], -r[1], r[2].lower()))
    head = CFG["roster_about"].format(n=len(ledgers))
    moves = [(name, m) for slug, ledger in ledgers.items()
             for name in [(ledger.get("customer") or {}).get("name", slug)] for m in trust_moves(ledger, now)]
    todo_calls = [((ledger.get("customer") or {}).get("name", slug), c) for slug, ledger in ledgers.items() for c in calls(ledger)]
    ready = [d for ledger in ledgers.values() for d in drafts(ledger)]
    lates = [r for r in rows if r[0] or r[5] or r[6]]
    calm = [r for r in rows if not (r[0] or r[5] or r[6])]

    def header(n_late, ours, name, theirs, team, busy):
        return (f"{name} — Late: {n_late} · Waiting for us: {ours} · Waiting for them: {theirs}"
                f"{f' · Waiting for team: {len(team)}' if team else ''}"
                f"{f' · In progress: {len(busy)}' if busy else ''}")

    # Every header with Late stays, so the badge stays whole; item lines go first when space runs out.
    items = [[f"- {short(i, 75)}" for i in late] + [f"- team: {short(i, 75)}" for i in team]
             + [f"- in progress: {short(i, 75)}" for i in busy]
             for _, _, _, _, late, team, busy, _ in lates]
    tail = [f"Waiting for us, not late: " + ", ".join(
                f"{r[2]} ({r[1]}{', next due ' + when(r[7].isoformat()) if r[7] else ''})" for r in calm) if calm else "",
            f"{quiet} quiet." if quiet else "",
            f"Calls to make: " + ", ".join(f"{c.get('contact')} ({name})" for name, c in todo_calls[:3]) if todo_calls else "",
            f"Drafts ready: {len(ready)}" if ready else "",
            f"Trust: {len(moves)} moves. Next: {short(moves[0][1], 60)} ({moves[0][0]})" if moves else ""]

    def render(shown):
        lines = [head]
        for (n_late, ours, name, theirs, late, team, busy, _), its in zip(lates, items):
            lines.append(header(n_late, ours, name, theirs, team, busy))
            lines += [i for i in its if i in shown]
        return "\n".join(x for x in lines + tail if x)

    shown = set()
    for line in (i for its in items for i in its):
        if len(render(shown | {line})) <= 3000 and len(render(shown | {line}).split()) <= 300:
            shown.add(line)
    return render(shown)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    session = sys.argv[1]
    watch = json.load(open(os.path.join(HOME, "sessions", session, "watch.json")))
    now = core.now()
    slugs = watch["slugs"]
    ledgers = {}
    for slug in slugs:
        path = os.path.join(HOME, "customers", slug, "ledger.json")
        ledgers[slug] = json.load(open(path)) if os.path.exists(path) else {}
    if watch.get("roster") or len(slugs) > COMPACT_ABOVE:
        note = compact(ledgers, now)
    else:
        note = "\n\n".join(block(s, l, now, prefix=len(slugs) > 1) for s, l in ledgers.items())
    note = note[:3000]
    with open(os.path.join(HOME, "sessions", session, "note.md"), "w") as f:
        f.write(note + "\n")
    if "--post" not in sys.argv:
        print(note)
        return
    if not core.roost(session):
        print("no roost_url in config.json: wrote note.md only")
        return
    many = len(ledgers) > 1
    deadlines = [{"at": at.isoformat(), "text": short(((ledger.get("customer") or {}).get("name", slug) + ": " if many else "") + text, 300)}
                 for slug, ledger in ledgers.items() for at, text in deadline_items(ledger, now)][:300]
    body = json.dumps({"notes": note, "deadlines": deadlines})
    out = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-X", "POST",
                          "-H", "content-type: application/json", "-d", body, core.roost(session)],
                         capture_output=True, text=True)
    print(out.stdout)


if __name__ == "__main__":
    main()
