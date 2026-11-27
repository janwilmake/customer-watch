#!/usr/bin/env python3
"""customer-watch topics: what every customer says about one topic, without the transcripts.

Usage:
  topic.py list                              the topics, what belongs to each, and the owner session
  topic.py init <topic> "<about>" [<owner-session-id>]   create or update a topic
  topic.py add <topic> <file.json | ->       add statements: [{"customer", "contact", "quote", "kind",
                                             "wish", "source", "at"}]; repeats are dropped
  topic.py claim <topic> <wish> [<wish>...]  the topic owns these wishes: customer sessions hand them over
  topic.py backfill <topic> <regex>          add the words of every ledger wish whose name or words match
  topic.py who <slug>                        the watch session of a customer (name, socket), to message it
  topic.py owner <topic>                     the topic's own session (name, socket)
  topic.py stats <topic>                     per wish: customers, statements, must-haves

A customer session reads every message and adds the statements about a topic here. The topic's
session wakes only for new statements (gate.py, topic mode), so it never reads a transcript.
"""
import hashlib
import json
import os
import re
import sys

import core
from core import HOME, iso, load, now, save

KINDS = {"wish", "bug", "praise", "objection", "question", "other"}
QUOTE_MAX = 400


def topic_dir(name):
    return os.path.join(HOME, "topics", name)


def feedback_path(name):
    return os.path.join(topic_dir(name), "feedback.jsonl")


def statements(name):
    out = []
    try:
        with open(feedback_path(name)) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
    except OSError:
        pass
    return out


def statement_id(s):
    return hashlib.sha1(f"{s.get('customer')}|{s.get('source')}|{s.get('quote')}".encode()).hexdigest()[:12]


def add(name, rows, by=None):
    if name not in core.topics():
        sys.exit(f"no topic {name}: topic.py init {name} \"<about>\" first")
    have = {s.get("id") for s in statements(name)}
    added = []
    with core.locked("topic-" + name):
        with open(feedback_path(name), "a") as f:
            for r in rows:
                quote = " ".join(str(r.get("quote") or "").split())
                if not quote or not r.get("customer"):
                    continue
                s = {"at": r.get("at"), "customer": r["customer"], "contact": r.get("contact"),
                     "quote": quote[:QUOTE_MAX], "kind": r.get("kind") if r.get("kind") in KINDS else "other",
                     "wish": r.get("wish"), "source": r.get("source"), "added_by": by, "added_at": iso(now())}
                s["id"] = statement_id(s)
                if s["id"] in have:
                    continue
                have.add(s["id"])
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
                added.append(s["id"])
    return added


def agent_of(sid):
    a = core.agent_session(sid) or {}
    return {"session": sid, "name": a.get("name"), "alive": bool(a.get("alive")),
            "socket": f"uds:/tmp/cc-socks/{a['pid']}.sock" if a.get("alive") else None}


def who(slug):
    sdir = os.path.join(HOME, "sessions")
    out = []
    for sid in sorted(os.listdir(sdir)) if os.path.isdir(sdir) else []:
        if slug in (load(os.path.join(sdir, sid, "watch.json"), {}) or {}).get("slugs", []):
            out.append(agent_of(sid))
    return out


def stats(name):
    by_wish = {}
    for s in statements(name):
        w = by_wish.setdefault(s.get("wish") or "(no wish)", {"customers": set(), "statements": 0})
        w["customers"].add(s["customer"])
        w["statements"] += 1
    must = {}
    for p in core.ledger_paths():
        for wish in load(p, {}).get("wishes") or []:
            if wish.get("priority") == "must-have" and wish.get("status") == "open":
                must.setdefault(wish.get("name"), set()).add(os.path.basename(os.path.dirname(p)))
    rows = [{"wish": k, "customers": len(v["customers"]), "statements": v["statements"],
             "must_have_for": len(must.get(k, set()) & v["customers"])} for k, v in by_wish.items()]
    return sorted(rows, key=lambda r: (-r["customers"], -r["must_have_for"], -r["statements"]))


def backfill(name, pattern):
    rx = re.compile(pattern, re.I)
    rows = []
    for p in core.ledger_paths():
        slug = os.path.basename(os.path.dirname(p))
        for w in load(p, {}).get("wishes") or []:
            if w.get("status") not in ("open", "shipped") or not w.get("words"):
                continue
            if rx.search(w.get("name") or "") or rx.search(w.get("words") or ""):
                rows.append({"customer": slug, "contact": w.get("reporter"), "quote": w["words"],
                             "kind": "bug" if w.get("kind") == "bug" else "wish", "wish": w.get("name"),
                             "source": w.get("source"), "at": w.get("date")})
    return add(name, rows, by="backfill")


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cmd = a[0]
    if cmd == "list":
        print(json.dumps({k: {"about": v.get("about"), "owner": v.get("owner"), "wishes": len(v.get("wishes") or [])}
                          for k, v in core.topics().items()}, indent=1, ensure_ascii=False))
    elif cmd == "init" and len(a) >= 3:
        os.makedirs(topic_dir(a[1]), exist_ok=True)
        path = os.path.join(topic_dir(a[1]), "topic.json")
        t = load(path, {})
        t.update({"name": a[1], "about": a[2]})
        if len(a) > 3:
            t["owner"] = a[3]
        t.setdefault("wishes", [])
        save(path, t)
        print(json.dumps(t, indent=1, ensure_ascii=False))
    elif cmd == "add" and len(a) == 3:
        rows = json.load(sys.stdin if a[2] == "-" else open(a[2]))
        print(f"added {len(add(a[1], rows if isinstance(rows, list) else [rows], by=os.environ.get('CUSTOMER_WATCH_SESSION')))} statement(s)")
    elif cmd == "claim" and len(a) >= 3:
        path = os.path.join(topic_dir(a[1]), "topic.json")
        t = load(path, None) or sys.exit(f"no topic {a[1]}")
        t["wishes"] = sorted(set(t.get("wishes") or []) | set(a[2:]))
        save(path, t)
        print(f"{a[1]} owns {len(t['wishes'])} wish(es)")
    elif cmd == "backfill" and len(a) == 3:
        print(f"added {len(backfill(a[1], a[2]))} statement(s) from the ledgers")
    elif cmd == "who" and len(a) == 2:
        print(json.dumps(who(a[1]), indent=1))
    elif cmd == "owner" and len(a) == 2:
        owner = (core.topics().get(a[1]) or {}).get("owner")
        print(json.dumps(agent_of(owner) if owner else None, indent=1))
    elif cmd == "stats" and len(a) == 2:
        for r in stats(a[1]):
            print(f"{r['customers']:3} customers  {r['must_have_for']:2} must-have  {r['statements']:3} statements  {r['wish']}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
