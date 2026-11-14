"""customer-watch adapter template: the probes of your own system of record.

Copy this folder to <watch home>/adapter/ and point config.json -> "adapter" at adapter.py.
The core imports this file and makes itself importable as `core`.

A probe is probe(st, customers, ctx) -> [(slug, channel, key, data)]:
  st         the gate's state dict; keep your own cursors in st["cursor"][<name>]
  customers  core.Customer objects: .address(field), .person(name), .company(text), .slug, ...
  ctx        {"session": <session id>, "watch": <watch.json>}
  key        stable per item; the same key never wakes the session twice
  data       {"at": ISO, ...}; add "from_me": True for messages I sent myself, so the tick
             can log them as personal trust touches

FAST_PROBES run every 60 s, SLOW_PROBES every 5 min. Use core.shared_feed() when every
gate on this machine reads the same organization-wide feed, so one fetch serves all of them.
"""
import core
from core import call, shared_feed


def probe_email(st, customers, ctx):
    def fetch(since):
        # Replace with your own MCP server and tool. Return (rows, extra, full_page).
        d = call("my-crm", "list_emails", {"since": since, "limit": 100})
        rows = (d or {}).get("emails", []) if isinstance(d, dict) else []
        return rows, {}, len(rows) >= 100

    rows, _ = shared_feed("email", fetch, "id", "created_at")
    hits = []
    for r in rows:
        for c in customers:
            if c.address(r.get("from")) or c.address(r.get("to")):
                hits.append((c.slug, "email", r["id"], {
                    "at": r.get("created_at"), "from": r.get("from"), "to": r.get("to"),
                    "subject": r.get("subject"), "from_me": core.is_me(r.get("from"))}))
    return hits


FAST_PROBES = [probe_email]
SLOW_PROBES = []


def roster_users():
    """Optional, for a roster session: [{"email", "org_id", "org_name", "last_seen"}] of active users."""
    raise SystemExit("roster_users() is not set up in this adapter")


def my_messages(since):
    """Optional, for trust.py --backfill: my own sent messages since an ISO time.

    [{"id", "at", "how": "email|linkedin|...", "to_emails": [...], "to_linkedin": [...], "to_name", "link"}]
    """
    return []
