"""customer-watch adapter: HubSpot CRM. Emails, calls, meetings and notes logged on contacts.

UNTESTED against a live portal: built from the public CRM v3/v4 API. Reports and PRs welcome.

A private app token with the scopes crm.objects.contacts.read and the engagement scopes
(sales-email-read, crm.objects.calls.read, crm.objects.meetings.read, crm.objects.notes.read
where your portal has them). config.json:

  "adapter": ["adapters/hubspot"],
  "hubspot": {
    "token": {"keychain": "customer-watch-hubspot"},
    "types": ["emails", "calls", "meetings", "notes"],
    "owner_id": "12345"          # optional: my HubSpot owner id, so my own engagements count as from_me
  }

An engagement matches a customer through its associated contacts' emails, or through the
customer's name in its subject or title.
"""
import datetime as dt
import json
import sys
import urllib.error
import urllib.request

import core
from core import shared_feed

API = "https://api.hubapi.com"
PROPS = {
    "emails": ["hs_timestamp", "hs_email_subject", "hs_email_from_email", "hs_email_to_email",
               "hs_email_cc_email", "hs_email_direction", "hubspot_owner_id", "hs_lastmodifieddate"],
    "calls": ["hs_timestamp", "hs_call_title", "hs_call_direction", "hs_call_duration", "hubspot_owner_id",
              "hs_lastmodifieddate"],
    "meetings": ["hs_timestamp", "hs_meeting_title", "hs_meeting_start_time", "hs_meeting_outcome",
                 "hubspot_owner_id", "hs_lastmodifieddate"],
    "notes": ["hs_timestamp", "hubspot_owner_id", "hs_lastmodifieddate"],
}
CHANNEL = {"emails": "email", "calls": "call", "meetings": "meeting", "notes": "note"}


def settings():
    return core.config().get("hubspot") or {}


def api(method, path, body=None):
    token = core.secret(settings().get("token"))
    if not token:
        raise RuntimeError("config.json has no hubspot.token")
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def ms(iso):
    return str(int(dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000))


def contact_emails(kind, ids):
    """{engagement id: [emails of its associated contacts]}, in two batch calls."""
    if not ids:
        return {}
    links = api("POST", f"/crm/v4/associations/{kind}/contacts/batch/read",
                {"inputs": [{"id": i} for i in ids]}).get("results", [])
    to = {str(r["from"]["id"]): [str(t["toObjectId"]) for t in r.get("to", [])] for r in links}
    people = {c for cs in to.values() for c in cs}
    emails = {}
    if people:
        got = api("POST", "/crm/v3/objects/contacts/batch/read",
                  {"properties": ["email"], "inputs": [{"id": c} for c in people]}).get("results", [])
        emails = {r["id"]: (r.get("properties") or {}).get("email") for r in got}
    return {i: [emails[c] for c in cs if emails.get(c)] for i, cs in to.items()}


def search(kind, since, extra=None):
    filters = [{"propertyName": "hs_lastmodifieddate", "operator": "GT", "value": ms(since)}] + (extra or [])
    body = {"filterGroups": [{"filters": filters}], "properties": PROPS[kind], "limit": 100,
            "sorts": [{"propertyName": "hs_lastmodifieddate", "direction": "ASCENDING"}]}
    return api("POST", f"/crm/v3/objects/{kind}/search", body).get("results", [])


def fetcher(kind):
    def fetch(since):
        try:
            rows = search(kind, since)
            people = contact_emails(kind, [r["id"] for r in rows])
        except (OSError, urllib.error.URLError, RuntimeError, ValueError) as e:
            sys.stderr.write(f"hubspot {kind}: {e}\n")
            return [], {}, False
        out = []
        for r in rows:
            p = r.get("properties") or {}
            out.append({"id": r["id"], "updated": p.get("hs_lastmodifieddate") or r.get("updatedAt"),
                        "at": p.get("hs_meeting_start_time") or p.get("hs_timestamp"),
                        "title": p.get("hs_email_subject") or p.get("hs_call_title") or p.get("hs_meeting_title") or "",
                        "addresses": " ".join(filter(None, [p.get("hs_email_from_email"), p.get("hs_email_to_email"),
                                                            p.get("hs_email_cc_email")] + people.get(r["id"], []))),
                        "from": p.get("hs_email_from_email"), "direction": p.get("hs_email_direction") or p.get("hs_call_direction"),
                        "owner": p.get("hubspot_owner_id")})
        return out, {}, len(rows) >= 100
    return fetch


def probe(kind):
    def run(st, customers, ctx):
        rows, _ = shared_feed(f"hubspot-{kind}", fetcher(kind), "id", "updated")
        owner = str(settings().get("owner_id") or "")
        hits = []
        for r in rows:
            for c in customers:
                if c.address(r["addresses"]) or c.company(r["title"]):
                    mine = core.is_me(r.get("from")) or (owner and str(r.get("owner")) == owner)
                    hits.append((c.slug, CHANNEL[kind], f"{kind}:{r['id']}", {
                        "at": r["at"], "title": r["title"], "direction": r["direction"], "source": "hubspot",
                        "hubspot_id": r["id"], "from_me": bool(mine) if kind == "emails" else None,
                        "mine": bool(mine)}))
        return hits
    run.__name__ = f"probe_hubspot_{kind}"
    return run


TYPES = settings().get("types") or ["emails", "calls", "meetings", "notes"]
FAST_PROBES = [probe(k) for k in TYPES if k in ("emails", "notes")]
SLOW_PROBES = [probe(k) for k in TYPES if k in ("calls", "meetings")]


def my_messages(since):
    """My own logged outgoing emails, for trust.py --backfill."""
    rows = search("emails", since, [{"propertyName": "hs_email_direction", "operator": "EQ", "value": "EMAIL"}])
    out = []
    for r in rows:
        p = r.get("properties") or {}
        if not core.is_me(p.get("hs_email_from_email")):
            continue
        to = [a.strip().lower() for a in (p.get("hs_email_to_email") or "").replace(";", ",").split(",") if a.strip()]
        out.append({"id": "hubspot:" + r["id"], "at": p.get("hs_timestamp"), "how": "email",
                    "to_emails": to, "to_linkedin": [], "to_name": "", "link": None})
    return out
