#!/usr/bin/env python3
"""customer-watch Asana sync: one Asana task per open promise and wish, kept in step both ways.

Usage:
  sync.py plan [<slug>...]        print the items that have no task yet, as JSON, for the model to title
  sync.py push <titles.json>      create a task for each item in the file: [{"key", "title", "notes"}]
  sync.py sync [<slug>...]        Asana -> ledger, then ledger -> Asana, for the items that have a task
  sync.py link <key> <task-gid>   attach an existing task to an item (no write to Asana)

Settings live in config.json -> "asana" (see ADAPTER.md). The index of linked tasks is
<home>/asana.json. A promise about a wish ("wish": "<name>") shares the task of that wish.
A wish that several customers share is one task, with every customer in the customer field.
"""
import datetime as dt
import glob
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import core  # noqa: E402
from core import HOME, call, iso, load, now, save  # noqa: E402

INDEX = os.path.join(HOME, "asana.json")
PROMISE_CLOSED = {"done", "kept", "dropped", "cancelled"}
WISH_CLOSED = {"shipped", "dropped", "done", "parked", "wontfix"}
TASK_FIELDS = ("name,completed,modified_at,permalink_url,due_on,assignee.name,"
               "memberships.project.gid,memberships.section.name,custom_fields.gid,custom_fields.display_value")


def settings():
    s = core.config().get("asana") or {}
    if not s.get("project"):
        sys.exit("config.json has no asana.project")
    return {"server": "asana", "customers": {}, **s}


def api(tool, args):
    d = call(settings()["server"], tool, args, timeout=120)
    if not isinstance(d, dict):
        sys.exit(f"asana {tool} failed: {str(d)[:300]} (an expired token? one Asana MCP call from a Claude Code session refreshes it, then run this again)")
    return d


def project_meta():
    """Section and field ids by name, read once a day into the cache."""
    path = os.path.join(core.CACHE, "asana-project.json")
    meta = load(path, {})
    if meta.get("project") == settings()["project"] and meta.get("day") == iso(now())[:10]:
        return meta
    d = api("get_project", {"project_id": settings()["project"], "include_sections": True,
                            "opt_fields": "custom_field_settings.custom_field.gid,custom_field_settings.custom_field.name,"
                                          "custom_field_settings.custom_field.enum_options.gid,"
                                          "custom_field_settings.custom_field.enum_options.name"})["data"]
    fields = {}
    for fs in d.get("custom_field_settings", []):
        f = fs["custom_field"]
        fields[f["name"]] = {"gid": f["gid"], "options": {o["name"]: o["gid"] for o in f.get("enum_options") or []}}
    meta = {"project": settings()["project"], "day": iso(now())[:10],
            "sections": {s["name"]: s["gid"] for s in d.get("sections") or []}, "fields": fields}
    os.makedirs(core.CACHE, exist_ok=True)
    save(path, meta)
    return meta


def tasks(since=None):
    """Every task of the project, or those changed since an ISO time."""
    args = {"project": settings()["project"], "limit": 100, "opt_fields": TASK_FIELDS}
    if since:
        args["modified_since"] = since
    out = []
    while True:
        d = api("get_tasks", args)
        out += d.get("data", [])
        nxt = (d.get("next_page") or {}).get("offset")
        if not nxt:
            return out
        args["offset"] = nxt


def section_of(task):
    for m in task.get("memberships", []):
        if (m.get("project") or {}).get("gid") == settings()["project"]:
            return (m.get("section") or {}).get("name")
    return None


def field_value(task, gid):
    for f in task.get("custom_fields", []):
        if f.get("gid") == gid:
            return f.get("display_value")
    return None


# --- the items -------------------------------------------------------------------------------

def ledgers(slugs=None):
    out = {}
    for path in sorted(glob.glob(os.path.join(HOME, "customers", "*", "ledger.json"))):
        slug = os.path.basename(os.path.dirname(path))
        if not slugs or slug in slugs:
            out[slug] = load(path, {})
    return out


def promise_key(slug, p):
    return f"p:{slug}:" + hashlib.sha1((p.get("what") or "").encode()).hexdigest()[:10]


def items(all_ledgers):
    """{key: item}. An item holds its ledger entries, so a write reaches every customer that shares it."""
    out = {}
    for slug, d in all_ledgers.items():
        name = (d.get("customer") or {}).get("name") or slug
        for w in d.get("wishes", []):
            wname = w.get("name") or w.get("what")
            if not wname:
                continue
            it = out.setdefault("w:" + wname, {"key": "w:" + wname, "kind": w.get("kind") or "feature",
                                               "entries": [], "promises": []})
            it["entries"].append((slug, name, w))
        for p in d.get("promises", []):
            if p.get("wish") and any(w.get("name") == p["wish"] for w in d.get("wishes", [])):
                out.setdefault("w:" + p["wish"], {"key": "w:" + p["wish"], "kind": "feature",
                                                  "entries": [], "promises": []})["promises"].append((slug, name, p))
                continue
            k = promise_key(slug, p)
            out[k] = {"key": k, "kind": "promise", "entries": [(slug, name, p)], "promises": []}
    return out


def is_open(it):
    if it["kind"] == "promise":
        return it["entries"][0][2].get("status") not in PROMISE_CLOSED
    return (any(e.get("status") not in WISH_CLOSED for _, _, e in it["entries"])
            or any(p.get("status") not in PROMISE_CLOSED for _, _, p in it["promises"]))


def gid_of(it):
    return next((e.get("asana") for _, _, e in it["entries"] if e.get("asana")), None)


def due_of(it):
    dues = [p.get("due") for _, _, p in it["promises"] + (it["entries"] if it["kind"] == "promise" else [])
            if p.get("due") and p.get("status") not in PROMISE_CLOSED]
    return min(dues)[:10] if dues else None


def source_kind(url):
    u = (url or "").lower()
    if "intercom" in u:
        return "intercom"
    if "/conversations/email/" in u or "mail.google" in u or "outlook" in u:
        return "email"
    if "/conversations/meeting/" in u or "/conversations/offline/" in u:
        return "meeting"
    if "/conversations/phone/" in u:
        return "call"
    return "other" if u else None


def wanted_section(it):
    """The section the ledger says the task belongs in, or None to leave it where it is."""
    entries = [e for _, _, e in it["entries"]]
    if it["kind"] == "promise":
        p = entries[0]
        if p.get("status") in PROMISE_CLOSED:
            return "done"
        return "in_progress" if p.get("in_progress") else None
    if all(e.get("status") in WISH_CLOSED for e in entries):
        if all(e.get("told_at") or e.get("status") != "shipped" for e in entries):
            return "done"
        return None  # shipped, not told yet: the told loop moves it on
    if any(e.get("in_progress") for e in entries):
        return "in_progress"
    return None


def field_map(it, meta):
    """The custom field values of an item: {field gid: value}."""
    s, names = settings(), settings().get("fields", {})
    out = {}

    def enum(field_key, option):
        f = meta["fields"].get(names.get(field_key, ""))
        if f and option in f["options"]:
            return f["gid"], f["options"][option]
        return None, None

    f = meta["fields"].get(names.get("customer", ""))
    if f:
        opts = sorted({f["options"][s["customers"][slug]] for slug, _, _ in it["entries"]
                       if s["customers"].get(slug) in f["options"]})
        if opts:
            out[f["gid"]] = opts
    kind = {"promise": "promise", "bug": "bug"}.get(it["kind"], "feature")
    gid, opt = enum("type", (s.get("type_options") or {}).get(kind))
    if gid:
        out[gid] = [opt]
    first = it["entries"][0][2]
    src = first.get("source") or first.get("link")
    gid, opt = enum("source", (s.get("source_options") or {}).get(source_kind(src)))
    if gid:
        out[gid] = [opt]
    pri = "promise" if it["kind"] == "promise" else (first.get("priority") or "")
    gid, opt = enum("priority", (s.get("priority_options") or {}).get("must-have" if pri.startswith("must") else pri))
    if gid:
        out[gid] = opt
    url_field = meta["fields"].get(names.get("source_url", ""))
    if url_field and src:
        out[url_field["gid"]] = src
    return out


def label(it):
    names = []
    for _, name, _ in it["entries"]:
        if name not in names:
            names.append(name)
    word = "klanten" if settings().get("language") == "nl" else "customers"
    return " + ".join(names) if len(names) <= 3 else f"{len(names)} {word}"


def plan_rows(its):
    rows = []
    for it in its.values():
        if gid_of(it) or not is_open(it):
            continue
        e = it["entries"][0][2]
        rows.append({"key": it["key"], "kind": it["kind"], "customers": label(it),
                     "text": e.get("what") or e.get("name"), "words": e.get("words"),
                     "notes": (e.get("notes") or [])[-2:] if isinstance(e.get("notes"), list) else e.get("note"),
                     "priority": e.get("priority"), "our_person": e.get("our_person"),
                     "due": due_of(it), "source": e.get("source") or e.get("link")})
    return rows


# --- writes ----------------------------------------------------------------------------------

def save_ledgers(all_ledgers, slugs):
    for slug in slugs:
        save(core.ledger_path(slug), all_ledgers[slug])


def record(index, task, key):
    index.setdefault("tasks", {})[task["gid"]] = {
        "key": key, "modified_at": task.get("modified_at"), "section": section_of(task),
        "completed": task.get("completed"), "url": task.get("permalink_url")}


def push(path):
    titles = {r["key"]: r for r in load(path, [])}
    all_ledgers, meta, index = ledgers(), project_meta(), load(INDEX, {})
    its = items(all_ledgers)
    todo = [its[k] for k in titles if k in its and not gid_of(its[k]) and is_open(its[k])]
    new_section = meta["sections"].get((settings().get("sections") or {}).get("open", ""))
    made = 0
    for i in range(0, len(todo), 25):
        batch = todo[i:i + 25]
        specs = []
        for it in batch:
            t = titles[it["key"]]
            spec = {"name": f"{label(it)} · {t['title']}", "project_id": settings()["project"],
                    "notes": (t.get("notes") or "").strip() + f"\n\ncustomer-watch: {it['key']}",
                    "custom_fields": json.dumps(field_map(it, meta))}
            if new_section:
                spec["section_id"] = new_section
            if due_of(it):
                spec["due_on"] = due_of(it)
            specs.append(spec)
        started = iso(now() - dt.timedelta(minutes=2))
        res = api("create_tasks", {"default_project": settings()["project"], "tasks": specs})
        for f in res.get("failed") or []:
            sys.stderr.write(f"failed: {json.dumps(f, ensure_ascii=False)[:300]}\n")
        # The reply does not reliably carry the new ids, so find each task by its exact name.
        by_name = {}
        for t in tasks(started):
            by_name.setdefault(t["name"], []).append(t)
        for it, spec in zip(batch, specs):
            got = by_name.get(spec["name"]) or []
            if len(got) != 1:
                sys.stderr.write(f"not linked ({len(got)} tasks named so): {it['key']}\n")
                continue
            for _, _, e in it["entries"] + it["promises"]:
                e["asana"] = got[0]["gid"]
            index.setdefault("tasks", {})[got[0]["gid"]] = {"key": it["key"], "modified_at": None}
            made += 1
        save_ledgers(all_ledgers, {s for it in batch for s, _, _ in it["entries"] + it["promises"]})
        save(INDEX, index)
    refresh(index)
    print(f"created {made} of {len(todo)} tasks")


def refresh(index):
    """Record the state of every linked task, so the gate skips our own writes."""
    for t in tasks():
        if t["gid"] in index.get("tasks", {}):
            record(index, t, index["tasks"][t["gid"]]["key"])
    index["refreshed"] = iso(now())
    save(INDEX, index)


def sync(slugs):
    s, meta, index = settings(), project_meta(), load(INDEX, {})
    sec = s.get("sections") or {}
    all_ledgers = ledgers()
    its = {k: it for k, it in items(all_ledgers).items() if gid_of(it)}
    if slugs:
        its = {k: it for k, it in its.items() if any(sl in slugs for sl, _, _ in it["entries"])}
    live = {t["gid"]: t for t in tasks()}
    touched, updates, moves, report = set(), [], [], []
    stamp = iso(now())
    for key, it in its.items():
        gid = gid_of(it)
        t = live.get(gid)
        if not t:
            report.append(f"gone: {key} ({gid})")
            continue
        was = (index.get("tasks", {}).get(gid) or {}).get("section")
        here = section_of(t)
        # Asana -> ledger: a teammate moved the task.
        if here != was and was is not None:
            if here == sec.get("done") or t.get("completed"):
                for slug, _, e in it["entries"]:
                    if it["kind"] == "promise" and e.get("status") not in PROMISE_CLOSED:
                        e["status"], e["closed_by"] = "done", "asana"
                        touched.add(slug)
                    elif it["kind"] != "promise" and e.get("status") not in WISH_CLOSED:
                        e["status"], e["closed_by"] = "shipped", "asana"
                        e.setdefault("shipped_at", stamp)
                        touched.add(slug)
                report.append(f"done in asana: {key}")
            elif here == sec.get("told"):
                for slug, _, e in it["entries"]:
                    if it["kind"] == "promise":
                        if e.get("status") not in PROMISE_CLOSED:
                            e["status"], e["closed_by"] = "done", "asana"
                    else:
                        if e.get("status") not in WISH_CLOSED:
                            e["status"] = "shipped"
                            e.setdefault("shipped_at", stamp)
                        e.setdefault("told_at", stamp)
                        e.setdefault("told_by", "asana")
                    touched.add(slug)
                report.append(f"told in asana: {key}")
        # ledger -> Asana.
        up = {}
        want = wanted_section(it)
        if want == "done":
            if not t.get("completed"):
                up["completed"] = True
            if here not in (sec.get("done"), sec.get("told")) and meta["sections"].get(sec.get("done")):
                moves.append((gid, meta["sections"][sec["done"]]))
        elif want == "in_progress" and here == sec.get("open") and meta["sections"].get(sec.get("in_progress")):
            moves.append((gid, meta["sections"][sec["in_progress"]]))
        if is_open(it) and due_of(it) and due_of(it) != t.get("due_on"):
            up["due_on"] = due_of(it)
        fields = field_map(it, meta)
        cust = meta["fields"].get((s.get("fields") or {}).get("customer", ""))
        if cust and cust["gid"] in fields:
            have = sorted(x.strip() for x in (field_value(t, cust["gid"]) or "").split(",") if x.strip())
            want_names = sorted(n for n, g in cust["options"].items() if g in fields[cust["gid"]])
            if have != want_names:
                up["custom_fields"] = {cust["gid"]: fields[cust["gid"]]}
        if up:
            updates.append({"task": gid, **up})
    for i in range(0, len(updates), 50):
        api("update_tasks", {"tasks": updates[i:i + 50]})
    if moves:
        api("update_tasks", {"tasks": [{"task": g, "add_projects": [{"project_id": s["project"], "section_id": sid}]}
                                       for g, sid in moves]})
    save_ledgers(all_ledgers, touched)
    refresh(index)
    for line in report:
        print(line)
    print(f"sync: {len(its)} linked, {len(updates)} updated, {len(moves)} moved, {len(touched)} ledgers changed")


def link(key, gid):
    all_ledgers, index = ledgers(), load(INDEX, {})
    it = items(all_ledgers).get(key)
    if not it:
        sys.exit(f"no item {key}")
    for _, _, e in it["entries"] + it["promises"]:
        e["asana"] = gid
    save_ledgers(all_ledgers, {s for s, _, _ in it["entries"] + it["promises"]})
    index.setdefault("tasks", {})[gid] = {"key": key, "modified_at": None}
    refresh(index)
    print(f"linked {key} -> {gid}")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, rest = sys.argv[1], sys.argv[2:]
    if cmd == "plan":
        print(json.dumps(plan_rows(items(ledgers(set(rest) or None))), ensure_ascii=False, indent=1))
    elif cmd == "push" and rest:
        push(rest[0])
    elif cmd == "sync":
        sync(set(rest))
    elif cmd == "link" and len(rest) == 2:
        link(*rest)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
