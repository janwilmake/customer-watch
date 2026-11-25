"""customer-watch Asana adapter: wakes a session when a teammate changes a customer's task.

FAST_PROBES   probe_asana: the project's tasks changed since the last probe, fetched once a
              minute for every gate on this Mac (core.shared_feed). Our own writes are skipped:
              sync.py records the modified_at of every task it writes in <home>/asana.json.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
import sync  # noqa: E402


def fetch(since):
    rows = [{"gid": t["gid"], "name": t.get("name"), "modified_at": (t.get("modified_at") or "")[:19] + "Z",
             "section": sync.section_of(t), "completed": t.get("completed"), "url": t.get("permalink_url"),
             "assignee": (t.get("assignee") or {}).get("name"),
             "customers": [x.strip() for f in t.get("custom_fields", []) for x in (f.get("display_value") or "").split(",")
                           if f.get("gid") == customer_field()]}
            for t in sync.tasks(since)]
    return rows, {}, False


def customer_field():
    name = (sync.settings().get("fields") or {}).get("customer")
    f = sync.project_meta()["fields"].get(name or "")
    return f and f["gid"]


def probe_asana(st, customers, ctx):
    if not (core.config().get("asana") or {}).get("project"):
        return []
    try:
        rows, _ = core.shared_feed("asana", fetch, "gid", "modified_at")
    except SystemExit as e:  # sync.api exits on a failed call; a probe must never stop the gate
        sys.stderr.write(f"asana probe: {e}\n")
        return []
    index = core.load(sync.INDEX, {}).get("tasks", {})
    option_to_slug = {v: k for k, v in (sync.settings().get("customers") or {}).items()}
    watched = {c.slug for c in customers}
    hits = []
    for r in rows:
        known = index.get(r["gid"]) or {}
        if known.get("modified_at") and known["modified_at"][:19] == r["modified_at"][:19]:
            continue  # our own write
        slugs = {option_to_slug[o] for o in r.get("customers") or [] if o in option_to_slug}
        key = known.get("key") or ""
        if key.startswith("p:"):
            slugs.add(key.split(":")[1])
        for slug in slugs & watched:
            hits.append((slug, "asana", f"{r['gid']}:{r['modified_at']}", {
                "at": r["modified_at"], "task": r["gid"], "item": key or None, "name": r.get("name"),
                "section": r.get("section"), "completed": r.get("completed"), "assignee": r.get("assignee"),
                "link": r.get("url"), "new": not known}))
    return hits


FAST_PROBES = [probe_asana]
