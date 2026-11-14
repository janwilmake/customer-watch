#!/usr/bin/env python3
"""customer-watch gate: finds new customer communication with no model in the loop.

Usage:
  gate.py <session-id> --wait   probe until something new matches, then print it and exit
  gate.py <session-id> --once   probe one time and print what matched (status, debugging)

It reads <home>/sessions/<session-id>/watch.json (the watched slugs) and each
<home>/customers/<slug>/ledger.json (the match keys). It keeps its cursors in the session folder.
The core probes read Intercom and Slack; each adapter adds the probes of a system of record.
Output: one JSON line per matched item, then a WAKE line with the reason.
"""
import concurrent.futures
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time

import core
from core import HOME, SKILL, call, iso, load, now, save, slack_link, slack_messages, slack_text

FAST_EVERY = 60          # email, chat, Intercom, Slack
SLOW_EVERY = 300         # meetings and calls: transcripts arrive minutes after the end
FULL_EVERY = core.config().get("full_tick_hours", 6) * 3600  # the full tick: usage, connectors, questions
NOTE_EVERY = 900         # re-render the Roost note, so Late grows with time alone
GIVE_UP = 4 * 3600       # exit with WAKE idle, so a hung gate never lasts forever
ROSTER_HOUR = 7          # a roster session rebuilds its customer set once a day, from this local hour
SEEN_MAX = 5000


def roster_due(watch):
    local = dt.datetime.now(core.tz())
    return (watch.get("roster") and local.hour >= ROSTER_HOUR
            and watch.get("reconciled", "") < local.strftime("%Y-%m-%d"))


AUTHOR = re.compile(r"Author: (.*?) \(([^)]*)\)")
CONTACTS = re.compile(r"Contact IDs: ([\w, ]+)")


def probe_intercom(st, customers, ctx):
    server = (core.config().get("intercom") or {}).get("server")
    if not server:
        return []
    since = st["cursor"].get("intercom", int(time.time()))
    probe_at = int(time.time())
    d = call(server, "search", {"query": f"object_type:conversations updated_at:gt:{since - 60}"})
    hits = []
    for r in (d or {}).get("results", []) if isinstance(d, dict) else []:
        text = r.get("text", "")
        author = AUTHOR.search(text)
        name, email = (author.group(1), author.group(2)) if author else ("", "")
        ids = set((CONTACTS.search(text) or [None, ""])[1].replace(" ", "").split(","))
        for c in customers:
            if c.address(email) or c.person(name) or ids & c.intercom:
                key = r["id"] + ":" + hashlib.sha1(text.encode()).hexdigest()[:12]
                hits.append((c.slug, "intercom", key, {"conversation": r["id"], "url": r.get("url"),
                                                       "author_email": email, "from_me": core.is_me(email)}))
    # Move the cursor only after a search that worked. A failed one (an expired token, no network)
    # keeps it, so the first search that works again catches up from the last good one.
    if isinstance(d, dict) and isinstance(d.get("results"), list):
        st["cursor"]["intercom"] = probe_at
    return hits


def slack_server():
    return (core.config().get("slack") or {}).get("server")


def probe_team_slack(st, customers, ctx):
    """The team's own channels about customers (slack.team_channels): a message that names a customer."""
    server = slack_server()
    me_slack = core.me().get("slack_user")
    oldest = int(time.time()) - 14 * 86400
    replies = st.setdefault("slack_replies", {})
    hits = []
    for ch in (core.config().get("slack") or {}).get("team_channels", []):
        d = call(server, "slack_read_channel", {"channel_id": ch["id"], "oldest": str(oldest), "limit": 100})
        for who, uid, _, at, ts, body in core.SLACK_MSG.findall(slack_text(d)):
            n = int((core.SLACK_THREAD.search(body) or [0, 0])[1])
            thread_text = ""
            if st.get("baselined") and n > replies.get(ts, 0):
                thread_text = slack_text(call(server, "slack_read_thread", {"channel_id": ch["id"], "message_ts": ts}))
            replies[ts] = n
            for c in customers:
                if c.company(body) or c.company(thread_text):
                    hits.append((c.slug, "slack", f"{ts}:{n}", {
                        "at": at, "from": who, "from_me": uid == me_slack, "ts": ts, "replies": n,
                        "slack_channel": ch.get("name") or ch["id"], "link": slack_link(ch["id"], ts)}))
    return hits


def probe_customer_slack(st, customers, ctx):
    """A customer's own channels (customer.slack_channels): every message and reply there is theirs.

    A channel the gate has not read before is recorded first and reported from the next probe on,
    so adding one to a ledger never floods the session with its history.
    """
    server = slack_server()
    me_slack = core.me().get("slack_user")
    oldest = str(int(time.time()) - 14 * 86400)
    replies = st.setdefault("slack_channel_replies", {})
    known = set(st.setdefault("slack_channels_seen", []))
    hits = []
    for c in customers:
        for ch in c.slack_channels:
            cid, name = ch["id"], ch.get("name") or ch["id"]
            text = slack_text(call(server, "slack_read_channel", {"channel_id": cid, "oldest": oldest, "limit": 100}))
            if not text:
                continue
            first = cid not in known
            for who, uid, tail, at, ts, body in core.SLACK_MSG.findall(text):
                n = int((core.SLACK_THREAD.search(body) or [0, 0])[1])
                key = f"{cid}:{ts}"
                grew = n > replies.get(key, 0)
                is_new = key not in replies
                replies[key] = n
                if first or not (is_new or grew):
                    continue
                hits.append((c.slug, "slack", f"{cid}:{ts}:{n}", {
                    "at": at, "from": who, "from_me": uid == me_slack, "external": "external:" in tail,
                    "ts": ts, "replies": n, "slack_channel": name, "channel_id": cid,
                    "link": slack_link(cid, ts)}))
            if first:
                known.add(cid)
                st["slack_channels_seen"] = sorted(known)
    return hits


def open_delegations(ledger):
    """The open conversations, promises and wishes that the user handed to a teammate."""
    for kind in ("conversations", "promises", "wishes"):
        for item in ledger.get(kind) or []:
            if item.get("status") == "open" and isinstance(item.get("delegated"), dict):
                yield kind, item


def probe_delegations(st, customers, ctx):
    """A teammate's reply to a handed-over item: in the DM or channel after the ask, or in its thread.

    The ledger's `delegated.via` names the ask ({"channel", "ts"}) and `delegated.slack_user` the teammate.
    """
    server = slack_server()
    hits = []
    for c in customers:
        ledger = load(core.ledger_path(c.slug), {})
        for kind, item in open_delegations(ledger):
            d = item["delegated"]
            via, user = d.get("via") or {}, d.get("slack_user")
            channel, ts = via.get("channel"), via.get("ts")
            if not (channel and ts and user):
                continue
            text = slack_text(call(server, "slack_read_channel", {"channel_id": channel, "oldest": ts, "limit": 50}))
            text += "\n" + slack_text(call(server, "slack_read_thread", {"channel_id": channel, "message_ts": ts}))
            label = item.get("id") or item.get("name") or item.get("what") or item.get("subject")
            for who, uid, reply_ts in slack_messages(text):
                if uid != user or float(reply_ts) <= float(ts):
                    continue
                hits.append((c.slug, "delegation", f"{channel}:{ts}:{reply_ts}", {
                    "at": iso(dt.datetime.fromtimestamp(float(reply_ts), dt.timezone.utc)), "from": who,
                    "to": d.get("to"), "ask": d.get("ask"), "item_kind": kind, "item": label,
                    "slack_channel": channel, "ask_ts": ts, "reply_ts": reply_ts,
                    "link": slack_link(channel, reply_ts)}))
    return hits


PR_URL = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/pull/\d+")


def probe_releases(st, customers, ctx):
    """A wish whose linked pull request merged: the fix is on its way to production, so tell the reporter.

    A wish lists its pull requests in `prs` (GitHub urls). Uses the gh CLI; without it, nothing happens.
    """
    hits = []
    for c in customers:
        ledger = load(core.ledger_path(c.slug), {})
        for w in ledger.get("wishes") or []:
            if w.get("status") != "open":
                continue
            for url in [u for u in w.get("prs") or [] if PR_URL.fullmatch(u or "")]:
                try:
                    out = subprocess.run(["gh", "pr", "view", url, "--json", "state,mergedAt,title"],
                                         capture_output=True, text=True, timeout=30)
                except (OSError, subprocess.TimeoutExpired):
                    return hits
                if out.returncode != 0:
                    continue
                pr = json.loads(out.stdout)
                if pr.get("state") == "MERGED":
                    hits.append((c.slug, "release", f"{w.get('name')}:{url}", {
                        "at": pr.get("mergedAt"), "wish": w.get("name"), "reporter": w.get("reporter"),
                        "pr": url, "title": pr.get("title")}))
    return hits


def render_note(session):
    subprocess.run([sys.executable, os.path.join(SKILL, "note.py"), session, "--post"],
                   capture_output=True, timeout=60)


def main():
    if len(sys.argv) < 3 or sys.argv[2] not in ("--wait", "--once"):
        sys.exit(__doc__)
    session, mode = sys.argv[1], sys.argv[2]
    sdir = os.path.join(HOME, "sessions", session)
    watch = load(os.path.join(sdir, "watch.json"), None)
    if not watch:
        sys.exit(f"no watch.json in {sdir}: run /customer-watch start first")
    pidfile = os.path.join(sdir, "gate.pid")
    other = load(pidfile, None)
    if mode == "--wait" and other and other != os.getpid():
        try:
            os.kill(other, 0)
            sys.exit(f"a gate already waits for this session (pid {other})")
        except OSError:
            pass
    if mode == "--wait":
        save(pidfile, os.getpid())

    fast = [probe_intercom, probe_customer_slack, probe_delegations]
    if (core.config().get("slack") or {}).get("team_channels"):
        fast.append(probe_team_slack)
    if not slack_server():
        fast = [p for p in fast if p is probe_intercom]
    mods = core.adapters()
    fast += [p for m in mods for p in getattr(m, "FAST_PROBES", [])]
    slow = [probe_releases] + [p for m in mods for p in getattr(m, "SLOW_PROBES", [])]
    ctx = {"session": session, "watch": watch}

    state_path = os.path.join(sdir, "state.json")
    st = load(state_path, {})
    st.setdefault("cursor", {})
    st.setdefault("seen", [])
    st.setdefault("started", time.time())
    st.setdefault("last_full", time.time())  # start runs the first full tick itself
    st.setdefault("last_slow", 0)
    st.setdefault("last_note", 0)
    seen = set(st["seen"])
    began = time.time()
    print(f"customer-watch gate: {', '.join(watch['slugs'])}; probe every {FAST_EVERY}s", flush=True)

    while True:
        customers = [core.Customer(s, load(core.ledger_path(s), {})) for s in watch["slugs"]]
        probes = list(fast)
        if time.time() - st["last_slow"] >= SLOW_EVERY:
            probes += slow
            st["last_slow"] = time.time()
        with concurrent.futures.ThreadPoolExecutor(max(1, len(probes))) as pool:
            results = list(pool.map(lambda p: p(st, customers, ctx), probes))
        new = []
        for slug, channel, key, data in (h for r in results for h in r):
            k = f"{slug}:{channel}:{key}"
            if k not in seen:
                seen.add(k)
                st["seen"].append(k)
                new.append({"customer": slug, "channel": channel, **data})
        st["seen"] = st["seen"][-SEEN_MAX:]
        if not st.get("baselined"):
            # The first pass only records what exists; the start backfill already covers history.
            new = []
            st["baselined"] = True

        reason = None
        if new:
            reason = f"{len(new)} new item(s)"
        elif roster_due(watch):
            reason = "roster due (daily)"
        elif time.time() - st["last_full"] >= FULL_EVERY:
            reason = f"full tick due ({FULL_EVERY / 3600:g} h)"
        elif mode == "--once":
            reason = "nothing new"
        elif time.time() - began >= GIVE_UP:
            reason = "idle; re-arm the gate"
        if reason and reason.startswith("full"):
            st["last_full"] = time.time()
        save(state_path, st)

        if reason:
            for item in new:
                print("NEW " + json.dumps(item, ensure_ascii=False))
            print(f"WAKE {iso(now())} {reason}", flush=True)
            if mode == "--wait":
                try:
                    os.remove(pidfile)
                except OSError:
                    pass
            return
        if time.time() - st["last_note"] >= NOTE_EVERY:
            render_note(session)
            st["last_note"] = time.time()
        time.sleep(FAST_EVERY)


if __name__ == "__main__":
    main()
