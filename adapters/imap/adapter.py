"""customer-watch adapter: email over IMAP. Python standard library only, no MCP server.

Works with Gmail and Google Workspace, Outlook / Microsoft 365, Fastmail, iCloud and any IMAP host.
config.json:

  "adapter": ["adapters/imap"],
  "imap": {
    "host": "imap.gmail.com",
    "user": "you@company.com",
    "password": {"keychain": "customer-watch-imap"},   # an app password; see ADAPTER.md
    "folders": null,          # default: Gmail's All Mail, else INBOX and the \\Sent folder
    "drafts_folder": null     # default: the folder flagged \\Drafts
  }

It reads headers only (From, To, Cc, Date, Subject, Message-ID), never a body: the session reads
the full message itself when it wakes.
"""
import datetime as dt
import email.utils
import imaplib
import re
import sys
import time
from email.header import decode_header, make_header
from email.parser import HeaderParser

import core
from core import load, locked, save

HEADERS = "FROM TO CC DATE SUBJECT MESSAGE-ID IN-REPLY-TO"
KEEP = 3 * 3600      # how long a fetched row stays in the shared cache for every gate to match
BATCH = 200          # at most this many new messages per folder per probe
LIST_LINE = re.compile(r'\((?P<flags>[^)]*)\) "(?P<delim>[^"]*)" (?P<name>.+)')


def settings():
    s = core.config().get("imap") or {}
    if not (s.get("host") and s.get("user")):
        raise RuntimeError("config.json has no imap.host and imap.user")
    return s


def connect():
    s = settings()
    box = imaplib.IMAP4_SSL(s["host"], s.get("port", 993))
    box.login(s["user"], core.secret(s.get("password")) or "")
    return box


def folders(box):
    """{flag: name} of the special folders, plus every name: \\All, \\Sent, \\Drafts."""
    out = {}
    typ, data = box.list()
    for raw in data or []:
        m = LIST_LINE.match(raw.decode(errors="replace") if isinstance(raw, bytes) else raw)
        if not m:
            continue
        name = m.group("name").strip().strip('"')
        for flag in m.group("flags").split():
            out.setdefault(flag, name)
    return out


def watched(box):
    s = settings()
    if s.get("folders"):
        return s["folders"]
    special = folders(box)
    if "\\All" in special:
        return [special["\\All"]]  # Gmail: All Mail holds the inbox and the sent mail once
    return ["INBOX"] + ([special["\\Sent"]] if "\\Sent" in special else [])


def text(value):
    try:
        return str(make_header(decode_header(value or "")))
    except (ValueError, LookupError):
        return value or ""


def when(value):
    try:
        t = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return core.iso(t.astimezone(dt.timezone.utc))


def rows_from(data, folder):
    """Parse a UID FETCH answer of header fields into rows."""
    out = []
    for part in data or []:
        if not isinstance(part, tuple):
            continue
        meta, raw = part
        uid = re.search(rb"UID (\d+)", meta)
        h = HeaderParser().parsestr(raw.decode("utf-8", errors="replace"))
        out.append({
            "id": (h.get("Message-ID") or f"{folder}:{uid.group(1).decode() if uid else '?'}").strip(),
            "at": when(h.get("Date")), "from": text(h.get("From")), "to": text(h.get("To")),
            "cc": text(h.get("Cc")), "subject": text(h.get("Subject")), "in_reply_to": (h.get("In-Reply-To") or "").strip(),
            "folder": folder, "uid": int(uid.group(1)) if uid else None})
    return out


def quote(folder):
    return '"' + folder.replace('"', '\\"') + '"'


def fetch_new(box, state):
    """New messages since the last probe, per folder, by UID. A new folder starts from now."""
    rows = []
    for folder in watched(box):
        typ, _ = box.select(quote(folder), readonly=True)
        if typ != "OK":
            continue
        validity = (box.untagged_responses.get("UIDVALIDITY") or [b"0"])[0]
        validity = validity.decode() if isinstance(validity, bytes) else str(validity)
        known = state.setdefault(folder, {})
        typ, data = box.uid("SEARCH", None, "ALL")
        uids = [int(u) for u in (data[0] or b"").split()] if typ == "OK" and data else []
        if known.get("validity") != validity:
            # First sight of this folder (or the server renumbered it): start from now.
            state[folder] = {"validity": validity, "last": max(uids, default=0)}
            continue
        new = [u for u in uids if u > known.get("last", 0)][:BATCH]
        if new:
            typ, data = box.uid("FETCH", ",".join(map(str, new)), f"(UID BODY.PEEK[HEADER.FIELDS ({HEADERS})])")
            rows += rows_from(data if typ == "OK" else [], folder)
            known["last"] = max(new)
    return rows


def feed():
    """The recent rows, fetched at most once a minute for every gate on this machine."""
    with locked("imap") as path:
        cache = load(path, {})
        if time.time() - cache.get("fetched", 0) >= core.FEED_EVERY:
            state = cache.get("folders", {})
            try:
                box = connect()
                try:
                    new = fetch_new(box, state)
                finally:
                    box.logout()
            except (OSError, imaplib.IMAP4.error, RuntimeError) as e:
                sys.stderr.write(f"imap: {e}\n")
                return cache.get("rows", [])
            seen = time.time()
            rows = [r for r in cache.get("rows", []) if seen - r.get("seen", 0) < KEEP]
            ids = {r["id"] for r in rows}
            rows += [{**r, "seen": seen} for r in new if r["id"] not in ids]
            cache = {"fetched": seen, "folders": state, "rows": rows}
            save(path, cache)
        return cache.get("rows", [])


def probe_email(st, customers, ctx):
    hits = []
    for r in feed():
        for c in customers:
            if c.address(r.get("from")) or c.address(r.get("to")) or c.address(r.get("cc")):
                hits.append((c.slug, "email", r["id"], {
                    "at": r.get("at"), "from": r.get("from"), "to": r.get("to"), "subject": r.get("subject"),
                    "message_id": r["id"], "folder": r.get("folder"), "from_me": core.is_me(r.get("from"))}))
    return hits


FAST_PROBES = [probe_email]


def my_messages(since):
    """My own sent mail since an ISO time, for trust.py --backfill."""
    start = dt.datetime.fromisoformat(since.replace("Z", "+00:00"))
    box = connect()
    out = []
    try:
        special = folders(box)
        folder = (core.config().get("imap") or {}).get("sent_folder") or special.get("\\Sent") or "Sent"
        if box.select(quote(folder), readonly=True)[0] != "OK":
            return []
        typ, data = box.uid("SEARCH", None, "SINCE", start.strftime("%d-%b-%Y"))
        uids = (data[0] or b"").split() if typ == "OK" and data else []
        for i in range(0, len(uids), 200):
            chunk = b",".join(uids[i:i + 200]).decode()
            typ, data = box.uid("FETCH", chunk, f"(UID BODY.PEEK[HEADER.FIELDS ({HEADERS})])")
            for r in rows_from(data if typ == "OK" else [], folder):
                if not core.is_me(r["from"]) or not r["at"] or r["at"] < since:
                    continue
                to = email.utils.getaddresses([r["to"], r["cc"]])
                out.append({"id": "imap:" + r["id"], "at": r["at"], "how": "email",
                            "to_emails": [a.lower() for _, a in to if a], "to_linkedin": [],
                            "to_name": next((n for n, a in to if n), ""), "link": None})
    finally:
        box.logout()
    return out
