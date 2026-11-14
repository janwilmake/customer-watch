#!/usr/bin/env python3
"""customer-watch roster: the "everyone else" set of a catch-all session, from the product's users.

Usage:
  roster.py <session-id>           print the roster and what would change
  roster.py <session-id> --apply   also write watch.json and a starter ledger per new customer

A customer is one business email domain of the users that the adapter reports as active
(roster_users()). Each organization belongs to the domain most of its users have, so the personal second org
of a customer's employee lands with the company. An org of free-mail users stands alone (a trial).

Left out: internal users and orgs (internal.json), customers that another live Roost session
watches (its watch.json), and customers in ignore.json. Output: one JSON object.
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys

import core
from core import HOME, load, save

FREE_MAIL = {"gmail.com", "googlemail.com", "hotmail.com", "hotmail.nl", "outlook.com", "outlook.nl",
             "live.com", "live.nl", "icloud.com", "me.com", "yahoo.com", "ziggo.nl", "kpnmail.nl",
             "proton.me", "protonmail.com", "msn.com", "planet.nl", "home.nl", "xs4all.nl"}


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "unknown"


def users():
    """Active product users from the adapter: [{"email", "org_id", "org_name", "last_seen"}]."""
    hooks = core.adapter_hook("roster_users")
    if not hooks:
        sys.exit("roster: no adapter has roster_users(); a roster session needs one")
    return [row for hook in hooks for row in hook()]


def groups(rows, internal):
    """Each org belongs to the business domain most of its users have; free-mail orgs stand alone."""
    keep = []
    for r in rows:
        domain = r["email"].rsplit("@", 1)[1]
        if domain in internal["domains"] or r["org_id"] in internal["org_ids"]:
            continue
        r["domain"] = domain
        keep.append(r)
    per_org = {}
    for r in keep:
        if r["domain"] not in FREE_MAIL:
            counts = per_org.setdefault(r["org_id"], {})
            counts[r["domain"]] = counts.get(r["domain"], 0) + 1
    owner = {org: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] for org, c in per_org.items()}
    dominant = set(owner.values())
    comps = {}
    for r in keep:
        key = owner.get(r["org_id"], "org:" + r["org_id"])
        # A user whose own domain is another customer's belongs to that customer, not to this org.
        if r["domain"] in dominant and r["domain"] != key:
            continue
        c = comps.setdefault(key, {"domains": set(), "org_ids": {}, "emails": set(), "last_seen": ""})
        if r["domain"] not in FREE_MAIL:
            c["domains"].add(r["domain"])
        c["org_ids"].setdefault(r["org_id"], {"name": r["org_name"], "users": 0})["users"] += 1
        c["emails"].add(r["email"])
        c["last_seen"] = max(c["last_seen"], r["last_seen"])
    out = []
    for key, c in comps.items():
        named = [kv for kv in c["org_ids"].items() if kv[1]["name"] and "@" not in kv[1]["name"]]
        main_org = max(named or c["org_ids"].items(), key=lambda kv: kv[1]["users"])
        name = main_org[1]["name"] or main_org[0]
        locals_ = {e.split("@")[0] for e in c["emails"]}
        if not key.startswith("org:") and (" " not in name and ("." in name or name.lower() in locals_)):
            name = key.rsplit(".", 1)[0]  # an org named after one user: name the company by its domain
        out.append({"name": name, "domains": sorted(c["domains"]), "org_id": main_org[0],
                    "org_ids": sorted(c["org_ids"]), "emails": sorted(c["emails"]),
                    "users": len(c["emails"]), "last_seen": c["last_seen"]})
    return out


def live_sessions():
    """The ids of the live sessions: from Roost, or, without Roost, every session folder."""
    if not core.roost():
        return set(os.listdir(os.path.join(HOME, "sessions")))
    try:
        return {s["id"] for s in json.loads(subprocess.run(["curl", "-s", core.roost()], capture_output=True,
                                                           text=True, timeout=10).stdout)["sessions"]}
    except (ValueError, KeyError, subprocess.TimeoutExpired):
        sys.exit("roost: cannot list the live sessions")


def covered_elsewhere(session):
    """Match keys of every customer that another live session watches."""
    live = live_sessions()
    keys = {"domains": set(), "org_ids": set(), "names": set(), "slugs": set()}
    for sid in os.listdir(os.path.join(HOME, "sessions")):
        if sid == session or sid not in live:
            continue
        for slug in load(os.path.join(HOME, "sessions", sid, "watch.json"), {}).get("slugs", []):
            c = load(os.path.join(HOME, "customers", slug, "ledger.json"), {}).get("customer", {})
            keys["slugs"].add(slug)
            keys["domains"] |= set(c.get("domains", []))
            keys["org_ids"] |= ({c.get("org_id")} | set(c.get("org_ids", []))) - {None}
            keys["names"] |= {n.lower() for n in [c.get("name", "")] + c.get("aliases", []) if n}
    return keys


def matches(cust, keys):
    return bool(set(cust["domains"]) & keys["domains"] or set(cust["org_ids"]) & keys["org_ids"]
                or cust["name"].lower() in keys["names"])


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    session = sys.argv[1]
    sdir = os.path.join(HOME, "sessions", session)
    internal = load(os.path.join(HOME, "internal.json"), {"domains": [], "org_ids": []})
    internal = {"domains": set(internal["domains"]), "org_ids": set(internal["org_ids"])}
    ignore = load(os.path.join(HOME, "ignore.json"), [])
    ignore_keys = {"domains": {d for i in ignore for d in i.get("domains", [])},
                   "org_ids": {o for i in ignore for o in i.get("org_ids", [])},
                   "names": {i["name"].lower() for i in ignore if i.get("name")}}
    elsewhere = covered_elsewhere(session)
    # An existing ledger keeps its slug, so the history of a customer never forks.
    known = {}
    for slug in os.listdir(os.path.join(HOME, "customers")):
        c = load(os.path.join(HOME, "customers", slug, "ledger.json"), {}).get("customer", {})
        known[slug] = {"domains": set(c.get("domains", [])),
                       "org_ids": ({c.get("org_id")} | set(c.get("org_ids", []))) - {None}}

    roster, skipped = [], []
    for cust in sorted(groups(users(), internal), key=lambda c: c["name"].lower()):
        slug = next((s for s, k in known.items()
                     if set(cust["domains"]) & k["domains"] or set(cust["org_ids"]) & k["org_ids"]),
                    slugify(cust["name"]))
        cust["slug"] = slug
        if slug in elsewhere["slugs"] or matches(cust, elsewhere):
            skipped.append({"slug": slug, "why": "watched by another session"})
        elif matches(cust, ignore_keys):
            skipped.append({"slug": slug, "why": "ignore.json"})
        else:
            roster.append(cust)

    watch = load(os.path.join(sdir, "watch.json"), {})
    before = set(watch.get("slugs", []))
    after = {c["slug"] for c in roster}
    result = {"watch": sorted(after), "added": sorted(after - before), "dropped": sorted(before - after),
              "skipped": skipped}
    if "--apply" in sys.argv:
        for cust in roster:
            path = os.path.join(HOME, "customers", cust["slug"], "ledger.json")
            if os.path.exists(path):
                continue
            os.makedirs(os.path.dirname(path), exist_ok=True)
            free = not cust["domains"]
            save(path, {"customer": {
                "name": cust["name"], "aliases": [], "domains": cust["domains"], "org_id": cust["org_id"],
                "org_ids": cust["org_ids"], "owners": [], "slack_channels": [],
                # A trial named after one person would match every meeting and Slack line with that word.
                "name_match": not free and len(cust["name"]) >= 4,
                "contacts": [{"name": "", "role": "user", "emails": [e], "phones": [], "linkedin_ids": [],
                              "contact_profile_id": None, "whatsapp_conversation_ids": [],
                              "intercom_contact_ids": []} for e in cust["emails"]]},
                "conversations": [], "promises": [], "wishes": [], "meetings": {"last": None, "next": None},
                "last_contact_at": None, "last_message": None, "usage": {}, "standing": {},
                "changed": None, "backfilled": False})
        watch["slugs"] = sorted(after)
        watch["roster"] = True
        watch["reconciled"] = dt.datetime.now(core.tz()).strftime("%Y-%m-%d")
        os.makedirs(sdir, exist_ok=True)
        save(os.path.join(sdir, "watch.json"), watch)
    print(json.dumps(result, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
