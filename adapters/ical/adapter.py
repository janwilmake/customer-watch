"""customer-watch adapter: meetings from a calendar's secret iCal address. Standard library only.

Google Calendar and Outlook both publish a private .ics address per calendar. config.json:

  "adapter": ["adapters/ical"],
  "ical": {
    "url": {"keychain": "customer-watch-ical"},   # the secret address is a password: keep it out of config.json
    "past_days": 3, "ahead_days": 14
  }

A meeting matches a customer by an attendee's address, or by the customer's name in the title.
Repeating events are expanded for DAILY, WEEKLY (with BYDAY) and MONTHLY rules, with EXDATE and
moved instances (RECURRENCE-ID). Other rules count only their first instance.
"""
import datetime as dt
import re
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import core
from core import load, locked, save

FETCH_EVERY = 240
DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
MAILTO = re.compile(r"mailto:([^;:\s]+)", re.I)


def unfold(raw):
    return re.sub(r"\r?\n[ \t]", "", raw).splitlines()


def prop(line):
    """('DTSTART', {'TZID': 'Europe/Amsterdam'}, '20261113T100000')"""
    head, _, value = line.partition(":")
    name, *params = head.split(";")
    return name.upper(), dict(p.split("=", 1) for p in params if "=" in p), value


def zone_of(value, params):
    """The zone a date-time is written in: UTC for a trailing Z, its TZID, else my own timezone."""
    if value.strip().endswith("Z"):
        return dt.timezone.utc
    try:
        return ZoneInfo(params["TZID"].strip('"')) if params.get("TZID") else core.tz()
    except (ZoneInfoNotFoundError, ValueError):
        return core.tz()


def stamp(value, params):
    """An iCal date or date-time as an aware UTC datetime."""
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        return dt.datetime.strptime(value[:8], "%Y%m%d").replace(tzinfo=core.tz()).astimezone(dt.timezone.utc)
    t = dt.datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    return t.replace(tzinfo=zone_of(value, params)).astimezone(dt.timezone.utc)


def events(raw):
    """Each VEVENT as a dict: uid, start, title, attendees, rrule, exdates, recurrence_id, cancelled."""
    out, ev = [], None
    for line in unfold(raw):
        if line == "BEGIN:VEVENT":
            ev = {"attendees": [], "exdates": set()}
        elif line == "END:VEVENT" and ev is not None:
            if ev.get("start"):
                out.append(ev)
            ev = None
        elif ev is not None:
            name, params, value = prop(line)
            if name == "UID":
                ev["uid"] = value
            elif name == "DTSTART":
                ev["start"] = stamp(value, params)
                ev["zone"] = core.tz() if params.get("VALUE") == "DATE" else zone_of(value, params)
            elif name == "SUMMARY":
                ev["title"] = value.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ")
            elif name in ("ATTENDEE", "ORGANIZER"):
                m = MAILTO.search(line)
                if m:
                    ev["attendees"].append(m.group(1).lower())
            elif name == "RRULE":
                ev["rrule"] = dict(p.split("=", 1) for p in value.split(";") if "=" in p)
            elif name == "EXDATE":
                ev["exdates"] |= {stamp(v, params) for v in value.split(",")}
            elif name == "RECURRENCE-ID":
                ev["recurrence_id"] = stamp(value, params)
            elif name == "STATUS":
                ev["cancelled"] = value.upper() == "CANCELLED"
    return out


def instances(ev, start, end):
    """The start times of an event inside [start, end), with simple repeating rules expanded."""
    first, rule = ev["start"], ev.get("rrule")
    if not rule:
        return [first] if start <= first < end else []
    freq, step = rule.get("FREQ"), int(rule.get("INTERVAL", 1))
    until = stamp(rule["UNTIL"], {}) if rule.get("UNTIL") else None
    count = int(rule["COUNT"]) if rule.get("COUNT") else None
    zone = ev.get("zone") or core.tz()  # repeat in the event's own zone, so a UTC series stays in UTC
    local = first.astimezone(zone)
    days = [DAYS.index(d[-2:]) for d in rule.get("BYDAY", "").split(",") if d[-2:] in DAYS] or [local.weekday()]
    out, n, k = [], 0, 0
    while k < 2000:
        if freq == "DAILY":
            cands = [local + dt.timedelta(days=k * step)]
        elif freq == "WEEKLY":
            week = local - dt.timedelta(days=local.weekday()) + dt.timedelta(weeks=k * step)
            cands = [week + dt.timedelta(days=d) for d in sorted(days)]
        elif freq == "MONTHLY":
            y, m = divmod(local.month - 1 + k * step, 12)
            try:
                cands = [local.replace(year=local.year + y, month=m + 1)]
            except ValueError:
                cands = []
        else:
            return [first] if start <= first < end else []
        k += 1
        for c in cands:
            # Keep the wall-clock time of the event's zone across a daylight-saving change.
            c = c.replace(tzinfo=None).replace(tzinfo=zone).astimezone(dt.timezone.utc)
            if c < first:
                continue
            if (until and c > until) or (count and n >= count) or c >= end:
                return out
            n += 1
            if c >= start and c not in ev["exdates"]:
                out.append(c)
    return out


def meetings(raw, start, end):
    evs = events(raw)
    moved = {(e["uid"], e["recurrence_id"]) for e in evs if e.get("recurrence_id")}
    out = []
    for e in evs:
        if e.get("cancelled"):
            continue
        if e.get("recurrence_id"):
            times = [e["start"]] if start <= e["start"] < end else []
        else:
            times = [t for t in instances(e, start, end) if (e.get("uid"), t) not in moved]
        out += [{"uid": e.get("uid", ""), "at": core.iso(t), "title": e.get("title", ""),
                 "attendees": e["attendees"]} for t in times]
    return out


def feed():
    with locked("ical") as path:
        cache = load(path, {})
        if time.time() - cache.get("fetched", 0) >= FETCH_EVERY:
            s = core.config().get("ical") or {}
            url = core.secret(s.get("url"))
            if not url:
                sys.stderr.write("ical: config.json has no ical.url\n")
                return []
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    raw = r.read().decode("utf-8", errors="replace")
            except OSError as e:
                sys.stderr.write(f"ical: {e}\n")
                return cache.get("meetings", [])
            now = core.now()
            rows = meetings(raw, now - dt.timedelta(days=s.get("past_days", 3)), now + dt.timedelta(days=s.get("ahead_days", 14)))
            cache = {"fetched": time.time(), "meetings": rows}
            save(path, cache)
        return cache.get("meetings", [])


def probe_meetings(st, customers, ctx):
    now = core.iso(core.now())
    hits = []
    for m in feed():
        for c in customers:
            if any(c.address(a) for a in m["attendees"]) or c.company(m["title"]):
                hits.append((c.slug, "meeting", f'{m["uid"]}:{m["at"]}', {
                    "at": m["at"], "title": m["title"], "attendees": m["attendees"],
                    "upcoming": m["at"] > now, "mine": True, "source": "ical"}))
    return hits


SLOW_PROBES = [probe_meetings]
