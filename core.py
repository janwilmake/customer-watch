"""customer-watch core: config, files, MCP calls, matching and Slack parsing, shared by every script.

Everything that names one company lives outside this folder, in the watch home
(~/.customer-watch, or $CUSTOMER_WATCH_HOME):

  config.json      timezone, Roost URL, Slack and Intercom servers, the adapters and their settings
  adapter/         your own adapter, if you wrote one: the probes of your system of record
                   (adapter.py) and its instructions for the model (ADAPTER.md)

Ready adapters (imap, ical, hubspot) ship in adapters/ of this folder. config.json -> "adapter"
names one or a list: "adapters/imap" resolves in this folder, "adapter/adapter.py" in the home.
  me.json, me.md   who "me" is, and the personal trust playbook

examples/ in this folder holds a template of each.
"""
import contextlib
import datetime as dt
import fcntl
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

HOME = os.path.expanduser(os.environ.get("CUSTOMER_WATCH_HOME", "~/.customer-watch"))
SKILL = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HOME, "cache")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

DEFAULTS = {
    "timezone": "UTC",
    "roost_url": "http://127.0.0.1:4777",
    "adapter": None,              # one adapter or a list: a folder or adapter.py, in the home or in this folder
    "full_tick_hours": 6,         # how often the session runs its full check (usage, connectors, questions)
    "connectors": [],             # channels the session reads itself through its own MCP connectors
    "slack": None,                # {"server", "workspace_url", "team_channels": [{"id", "name"}]}
    "intercom": None,             # {"server"}
    "roster_about": "About: {n} customers without a session of their own.",
    "late_after_working_hours": 24,
}


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def config():
    return {**DEFAULTS, **load(os.path.join(HOME, "config.json"), {})}


def me():
    """Who the user is: names, emails, chat ids, booking link, phone, the trust cadence."""
    return {"touch_every_days": 21, "trust_roles": ["champion", "decision maker"],
            **load(os.path.join(HOME, "me.json"), {})}


def is_key(role):
    """A key contact: their role names one of me.json -> trust_roles. Roles are free text."""
    r = (role or "").lower()
    return any(k.lower() in r for k in me().get("trust_roles") or [])


def tz():
    return ZoneInfo(config()["timezone"])


def roost(path=""):
    """The Roost API url, or None when config.json sets "roost_url": null (no Roost on this machine)."""
    base = config().get("roost_url")
    return base.rstrip("/") + "/api/sessions" + (f"/{path}" if path else "") if base else None


def ledger_path(slug):
    return os.path.join(HOME, "customers", slug, "ledger.json")


def adapter_paths():
    """The adapter.py of each adapter in config.json, found in the watch home first, then in this folder."""
    names = config().get("adapter") or []
    out = []
    for name in [names] if isinstance(names, str) else names:
        for base in (HOME, SKILL):
            path = os.path.join(base, name)
            if os.path.isdir(path):
                path = os.path.join(path, "adapter.py")
            if os.path.isfile(path):
                out.append(path)
                break
        else:
            sys.stderr.write(f"adapter not found: {name}\n")
    return out


def adapters():
    """Every adapter module named in config.json. Each imports this module as `core`."""
    sys.modules.setdefault("core", sys.modules[__name__])
    mods = []
    for path in adapter_paths():
        name = "customer_watch_adapter_" + re.sub(r"\W", "_", os.path.relpath(path, "/"))
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mods.append(mod)
    return mods


def adapter_hook(name):
    """The adapters that define a function, such as roster_users or my_messages."""
    return [getattr(m, name) for m in adapters() if callable(getattr(m, name, None))]


def secret(spec):
    """A secret from config.json, never stored there in clear text when it can be avoided.

    {"env": "NAME"}                     an environment variable
    {"keychain": "service"}             the macOS Keychain: security add-generic-password -s service -a you -w
    {"cmd": "op read op://vault/item"}  the output of a command, such as a password manager CLI
    "plain text"                        allowed, but then config.json holds the secret
    """
    if isinstance(spec, str) or spec is None:
        return spec
    if "env" in spec:
        return os.environ.get(spec["env"])
    if "keychain" in spec:
        args = ["security", "find-generic-password", "-s", spec["keychain"], "-w"]
        if spec.get("account"):
            args[3:3] = ["-a", spec["account"]]
        out = subprocess.run(args, capture_output=True, text=True)
        return out.stdout.strip() if out.returncode == 0 else None
    if "cmd" in spec:
        out = subprocess.run(spec["cmd"], shell=True, capture_output=True, text=True)
        return out.stdout.strip() if out.returncode == 0 else None
    return None


def now():
    """The clock. $CUSTOMER_WATCH_NOW pins it (ISO), for the demo and the tests."""
    fixed = os.environ.get("CUSTOMER_WATCH_NOW")
    if fixed:
        return dt.datetime.fromisoformat(fixed.replace("Z", "+00:00"))
    return dt.datetime.now(dt.timezone.utc)


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def call(server, tool, args, timeout=90):
    """One MCP call through agent-codemode. Returns parsed JSON, the raw text, or None on failure."""
    try:
        out = subprocess.run(
            ["agent-codemode", "call", server, tool, "--json", json.dumps(args), "--text"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0:
        sys.stderr.write(f"{tool}: exit {out.returncode}: {out.stderr.strip()[:200]}\n")
        return None
    try:
        return json.loads(out.stdout)
    except ValueError:
        return out.stdout


def lower_set(values):
    return {v.strip().lower() for v in values or [] if v and v.strip()}


def digits(value):
    return re.sub(r"\D", "", value or "")


class Customer:
    """The match keys of one customer, from its ledger."""

    def __init__(self, slug, ledger):
        c = ledger.get("customer", {})
        self.slug = slug
        # A trial named after one person would match every meeting and Slack line with that word.
        self.names = lower_set([c.get("name", "")] + c.get("aliases", [])) if c.get("name_match", True) else set()
        self.domains = lower_set(c.get("domains", []))
        contacts = c.get("contacts", [])
        self.emails = lower_set(e for p in contacts for e in p.get("emails", []))
        self.people = lower_set(p.get("name", "") for p in contacts)
        self.linkedin = {i for p in contacts for i in p.get("linkedin_ids", [])}
        self.profiles = {p["contact_profile_id"] for p in contacts if p.get("contact_profile_id")}
        self.whatsapp = {i for p in contacts for i in p.get("whatsapp_conversation_ids", [])}
        self.phones = {digits(n)[-9:] for p in contacts for n in p.get("phones", []) if len(digits(n)) >= 9}
        self.intercom = {i for p in contacts for i in p.get("intercom_contact_ids", [])}
        self.slack_channels = [ch for ch in c.get("slack_channels", []) if ch.get("id")]
        self.name_res = [re.compile(r"(?<!\w)" + re.escape(n) + r"(?!\w)", re.I) for n in self.names]

    def address(self, field):
        """True when any address in the field (one, or a comma list) is the customer's."""
        return any(a in self.emails or a.rsplit("@", 1)[-1] in self.domains
                   for a in EMAIL.findall((field or "").lower()))

    def company(self, text):
        return bool(text) and any(r.search(text) for r in self.name_res)

    def person(self, name):
        return bool(name) and name.strip().lower() in self.people


def is_me(address):
    """True when an address field holds one of my own addresses."""
    mine = lower_set(me().get("emails", []))
    return any(a in mine for a in EMAIL.findall((address or "").lower()))


@contextlib.contextmanager
def locked(name):
    """One file in the shared cache, held by one gate at a time."""
    os.makedirs(CACHE, exist_ok=True)
    with open(os.path.join(CACHE, name + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield os.path.join(CACHE, name + ".json")


LOOKBACK = dt.timedelta(hours=1)  # a message reaches the system of record minutes after its own timestamp
KEEP = dt.timedelta(hours=3)      # how long a fetched row stays in the shared feed for every gate to match
FEED_EVERY = 55


def shared_feed(name, fetch, key, at_field, refs=None):
    """The recent rows of one feed, fetched at most once a probe interval for all gates on this Mac.

    Every gate reads the organization's whole feed and keeps only its own customers, so fetching
    it once and sharing the rows keeps the number of calls flat however many gates run.
    fetch(since) returns (rows, extra, full_page). The query starts LOOKBACK before the cursor,
    because a message syncs minutes after its timestamp; the gates' seen keys drop the repeats.
    After a full page it starts at the cursor, or the same page would come back forever.
    """
    with locked(name) as path:
        feed = load(path, {})
        if time.time() - feed.get("fetched", 0) >= FEED_EVERY:
            cursor = feed.get("cursor") or iso(now())
            start = dt.datetime.strptime(cursor[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=dt.timezone.utc)
            rows, extra, full = fetch(cursor if feed.get("full") else iso(start - LOOKBACK))
            by_key = {str(r.get(key)): r for r in feed.get("rows", [])}
            by_key.update({str(r.get(key)): r for r in rows})
            cutoff = iso(now() - KEEP)
            kept = [r for r in by_key.values() if (r.get(at_field) or "") >= cutoff]
            extra = {**feed.get("extra", {}), **extra}
            if refs:
                # Keep only the extra entries that a kept row still points at.
                used = {ref for r in kept for ref in refs(r)}
                extra = {k: v for k, v in extra.items() if k in used}
            feed = {"fetched": time.time(), "full": full, "rows": kept,
                    "cursor": max([cursor] + [r[at_field] for r in rows if r.get(at_field)]), "extra": extra}
            save(path, feed)
        return feed.get("rows", []), feed.get("extra", {})


# Slack, as the Slack MCP prints it. A Slack Connect user's header reads "(U123, external: Acme)".
SLACK_MSG = re.compile(r"=== Message from (.*?) \((U\w+)([^)]*)\) at (.*?) ===[ \t]*\nMessage TS: ([\d.]+)\n(.*?)(?=\n=== Message from |\Z)", re.S)
SLACK_THREAD = re.compile(r"Thread: (\d+) repl")
SLACK_AUTHOR = re.compile(r"^=== Message from (.*?) \((U\w+)[^)]*\) at (.*?) ===|^From: (.*?)(?: <[^>]*>)? \((U\w+)\)")


def slack_text(res):
    return res.get("messages", "") if isinstance(res, dict) else (res or "")


def slack_messages(text):
    """(who, user id, ts) of each message in a channel read or a thread read; the two print authors differently."""
    out, author = [], None
    for line in text.split("\n"):
        m = SLACK_AUTHOR.match(line.strip())
        if m:
            author = (m.group(1) or m.group(4), m.group(2) or m.group(5))
        elif line.startswith("Message TS: ") and author:
            out.append((*author, line.split(": ", 1)[1].strip()))
            author = None
    return out


def slack_link(channel, ts):
    base = ((config().get("slack") or {}).get("workspace_url") or "https://slack.com").rstrip("/")
    return f"{base}/archives/{channel}/p{ts.replace('.', '')}"
