#!/usr/bin/env python3
"""customer-watch trust: the weekly count of personal trust work, across every ledger.

Usage:
  trust.py [--days 7] [--names]      the weekly count
  trust.py --backfill 30             log my own sent messages of the last 30 days into trust_log

The backfill needs the adapter's my_messages(since); it matches each message to a customer
contact by email address, LinkedIn id or name, and skips messages it already logged.

It counts my own trust log entries (trust_log in each ledger) in the window and in the window
before it, the fixes told and how fast, and how many key contacts I touched recently. Without
--names it prints counts only, so the output can go into a post or a team update as it is.
"""
import argparse
import datetime as dt
import os
import statistics

import core
from core import HOME, load, save

KINDS = ["touch", "video", "call", "visit", "connect", "told", "booked", "help", "ask",
         "referral-given", "referral-received"]


def parse(value):
    if not value:
        return None
    t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=core.tz())


def ledgers():
    root = os.path.join(HOME, "customers")
    for slug in sorted(os.listdir(root)):
        led = load(os.path.join(root, slug, "ledger.json"), None)
        if led:
            yield slug, led


def backfill(days):
    hooks = core.adapter_hook("my_messages")
    if not hooks:
        raise SystemExit("backfill: no adapter has my_messages(since)")
    since = core.iso(core.now() - dt.timedelta(days=days))
    msgs = [m for hook in hooks for m in hook(since)]
    added = 0
    for slug, led in ledgers():
        c = core.Customer(slug, led)
        contacts = (led.get("customer") or {}).get("contacts", [])
        log = led.setdefault("trust_log", [])
        known = {e.get("id") for e in log}
        for m in msgs:
            if m["id"] in known:
                continue
            emails = set(m.get("to_emails") or [])
            ids = set(m.get("to_linkedin") or []) - {None}
            hit = next((p for p in contacts if emails & {e.lower() for e in p.get("emails", [])}
                        or ids & set(p.get("linkedin_ids", []))), None)
            if not hit and (any(c.address(e) for e in emails) or c.person(m.get("to_name"))):
                hit = next((p for p in contacts if c.person(m.get("to_name"))
                            and p.get("name", "").lower() == m["to_name"].strip().lower()), {"name": m.get("to_name")})
            if hit and hit.get("name"):
                log.append({"id": m["id"], "at": m["at"], "contact": hit["name"], "kind": "touch",
                            "how": m["how"], "link": m.get("link"), "backfill": True})
                known.add(m["id"])
                added += 1
        if log:
            log.sort(key=lambda e: e.get("at") or "")
            save(core.ledger_path(slug), led)
    print(f"backfill: {len(msgs)} messages of mine, {added} new trust log entries")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--names", action="store_true", help="also list who, per kind (private use only)")
    ap.add_argument("--backfill", type=int, metavar="DAYS", help="log my own sent messages into trust_log")
    a = ap.parse_args()
    if a.backfill:
        return backfill(a.backfill)
    now = core.now()
    start, prev = now - dt.timedelta(days=a.days), now - dt.timedelta(days=2 * a.days)
    me = core.me()
    every = me.get("touch_every_days", 21)

    count, before, who = {k: 0 for k in KINDS}, {k: 0 for k in KINDS}, {k: [] for k in KINDS}
    told_hours, untold, key_total, key_touched, connected, met = [], 0, 0, 0, 0, 0
    customers_touched = set()
    asks = {}  # kind of ask -> [made, yes, no]
    for slug, led in ledgers():
        name = (led.get("customer") or {}).get("name", slug)
        for e in led.get("trust_log") or []:
            at, kind = parse(e.get("at")), e.get("kind", "touch")
            if not at or kind not in count:
                continue
            if at >= start and kind == "ask":
                a_ = asks.setdefault(e.get("ask", "other"), [0, 0, 0])
                a_[0] += 1
                a_[1] += e.get("outcome") == "yes"
                a_[2] += e.get("outcome") == "no"
            if at >= start:
                count[kind] += 1
                who[kind].append(f"{e.get('contact')} ({name})")
                customers_touched.add(slug)
            elif at >= prev:
                before[kind] += 1
        for w in led.get("wishes") or []:
            shipped, told = parse(w.get("shipped_at")), parse(w.get("told_at"))
            if w.get("status") == "shipped" and shipped and shipped >= start:
                if told:
                    told_hours.append((told - shipped).total_seconds() / 3600)
                else:
                    untold += 1
        log = led.get("trust_log") or []
        for p in (led.get("customer") or {}).get("contacts", []):
            if not core.is_key(p.get("role")):
                continue
            key_total += 1
            mine = [parse(e["at"]) for e in log if e.get("contact") == p.get("name") and parse(e.get("at"))]
            if mine and (now - max(mine)).days <= every:
                key_touched += 1
            if (p.get("trust") or {}).get("linkedin_connected"):
                connected += 1
            if any(e.get("kind") == "visit" for e in log if e.get("contact") == p.get("name")):
                met += 1

    print(f"Trust, last {a.days} days (the {a.days} before in brackets)")
    for k in KINDS:
        if count[k] or before[k]:
            print(f"- {k}: {count[k]} ({before[k]})" + (f": {', '.join(who[k])}" if a.names and who[k] else ""))
    print(f"- customers I personally touched: {len(customers_touched)}")
    for k, (made, yes, no) in sorted(asks.items()):
        print(f"- asks for a {k}: {made} made, {yes} yes, {no} no, {made - yes - no} open")
    if told_hours or untold:
        med = f"median {statistics.median(told_hours):.1f} h from live to told" if told_hours else "none told"
        print(f"- fixes live: {len(told_hours) + untold}, told: {len(told_hours)} ({med}), not told: {untold}")
    if key_total:
        print(f"- key contacts: {key_total}; touched in the last {every} days: {key_touched}; "
              f"LinkedIn connected: {connected}; met in person: {met}")


if __name__ == "__main__":
    main()
