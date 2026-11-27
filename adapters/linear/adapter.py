"""customer-watch Linear adapter: a wish's ticket that is done wakes the session to tell the customer.

FAST_PROBES   probe_tickets: the team's issues changed since the last probe, fetched once a minute
              for every gate on this Mac (core.shared_feed). An open wish whose `ticket` is in a
              shipped status gives a `release` item, the same as a merged pull request in `prs`.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402

TICKET = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


def settings():
    return {"server": "linear", "shipped_statuses": ["Done"], **(core.config().get("linear") or {})}


def tickets(wish):
    """The ticket ids of a wish: `ticket` (an id or a Linear url) and `tickets`."""
    raw = [wish.get("ticket")] + list(wish.get("tickets") or [])
    return [m.group(1) for r in raw if isinstance(r, str) for m in [TICKET.search(r.upper())] if m]


def fetch(since):
    s = settings()
    args = {"updatedAt": since, "limit": 250, "orderBy": "updatedAt"}
    if s.get("team"):
        args["team"] = s["team"]
    d = core.call(s["server"], "list_issues", args)
    issues = (d or {}).get("issues", []) if isinstance(d, dict) else []
    rows = [{"id": i.get("id"), "status": i.get("status"), "url": i.get("url"), "title": i.get("title"),
             "completedAt": i.get("completedAt"), "updatedAt": (i.get("updatedAt") or "")[:19] + "Z"}
            for i in issues if i.get("id")]
    return rows, {}, len(issues) >= 250


def probe_tickets(st, customers, ctx):
    if not core.config().get("linear"):
        return []
    rows, _ = core.shared_feed("linear", fetch, "id", "updatedAt")
    shipped = set(settings()["shipped_statuses"])
    done = {r["id"]: r for r in rows if r.get("status") in shipped}
    hits = []
    for c in customers:
        for w in core.load(core.ledger_path(c.slug), {}).get("wishes") or []:
            if w.get("status") != "open":
                continue
            for t in tickets(w):
                if t in done:
                    r = done[t]
                    hits.append((c.slug, "release", f"{w.get('name')}:{t}", {
                        "at": r.get("completedAt") or r.get("updatedAt"), "wish": w.get("name"),
                        "reporter": w.get("reporter"), "ticket": t, "status": r.get("status"),
                        "link": r.get("url"), "title": r.get("title")}))
    return hits


FAST_PROBES = [probe_tickets]
