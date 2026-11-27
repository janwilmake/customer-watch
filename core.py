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
    "tell_after_working_hours": 24,  # a fix live this long without telling the reporter is Late
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


def topics():
    """Every topic: {name: topic.json}. A topic with an owner session owns the wishes it lists."""
    import glob
    out = {}
    for path in glob.glob(os.path.join(HOME, "topics", "*", "topic.json")):
        t = load(path, {})
        out[t.get("name") or os.path.basename(os.path.dirname(path))] = t
    return out


def topic_of_wish(name, cache=None):
    """The topic that owns a wish, or None. Only a topic with an owner session takes a wish over."""
    owned = cache if cache is not None else {w: n for n, t in topics().items() if t.get("owner") for w in t.get("wishes") or []}
    return owned.get(name)


def ledger_paths():
    import glob
    return sorted(glob.glob(os.path.join(HOME, "customers", "*", "ledger.json")))


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


def parse_iso(value):
    """Epoch seconds of an ISO time, or 0."""
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


# Servers whose stored token has expired. Only Claude Code refreshes a token, so the gate wakes a session.
CREDENTIAL_ERRORS = set()
CREDENTIAL_QUIET = 30 * 60  # one wake per server for all gates on this Mac in this time


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
        if "credential error" in out.stderr:
            CREDENTIAL_ERRORS.add(server)
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


def claim_credential_wake(server):
    """True for the first gate on this Mac to report this server's expired token in CREDENTIAL_QUIET."""
    with locked("credential-" + server) as path:
        if time.time() - load(path, {}).get("at", 0) < CREDENTIAL_QUIET:
            return False
        save(path, {"at": time.time()})
        return True


AGENT_SESSIONS = os.path.expanduser(os.environ.get("CUSTOMER_WATCH_AGENT_SESSIONS", "~/.claude/sessions"))
AGENT_PROJECTS = os.path.expanduser(os.environ.get("CUSTOMER_WATCH_AGENT_PROJECTS", "~/.claude/projects"))
DOWN_AFTER = 30 * 60      # a watch whose gate has not probed this long is down
WATCHDOG_EVERY = 10 * 60  # one gate on this Mac checks the other watches this often
REPORT_GONE_EVERY = 24 * 3600


def agent_session(session):
    """{"pid", "name", "alive"} of the Claude Code process of a session, or None when not found."""
    import glob
    for path in glob.glob(os.path.join(AGENT_SESSIONS, "*.json")):
        d = load(path, {})
        if d.get("sessionId") == session and d.get("pid"):
            try:
                os.kill(int(d["pid"]), 0)
                alive = True
            except OSError:
                alive = False
            return {"pid": d["pid"], "name": d.get("name"), "alive": alive}
    return None


def transcript_age(session):
    """When the session's transcript was last written (epoch seconds), or 0 when it is not found."""
    import glob
    paths = glob.glob(os.path.join(AGENT_PROJECTS, "*", session + ".jsonl"))
    return max((os.path.getmtime(p) for p in paths), default=0)


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def down_watches(me):
    """The other watch sessions whose gate stopped probing, at most once a WATCHDOG_EVERY for all gates.

    A gate saves state.json on every probe, so its age is the heartbeat. A stalled session (its process
    lives) is reported once per down spell; a gone one (no process) once a day.
    """
    with locked("watchdog") as path:
        mark = load(path, {})
        if time.time() - mark.get("checked", 0) < WATCHDOG_EVERY:
            return []
        mark["checked"] = time.time()
        reported = mark.setdefault("reported", {})
        out = []
        for sid in sorted(os.listdir(os.path.join(HOME, "sessions")) if os.path.isdir(os.path.join(HOME, "sessions")) else []):
            sdir = os.path.join(HOME, "sessions", sid)
            if sid == me or not os.path.exists(os.path.join(sdir, "watch.json")):
                continue
            if pid_alive(load(os.path.join(sdir, "gate.pid"), None)):
                continue
            try:
                beat = os.path.getmtime(os.path.join(sdir, "state.json"))
            except OSError:
                continue
            if time.time() - beat < DOWN_AFTER:
                continue
            agent = agent_session(sid) or {}
            if agent.get("alive") and time.time() - transcript_age(sid) < DOWN_AFTER:
                continue  # a long turn: the session works and re-arms its gate after it
            state = "stalled" if agent.get("alive") else "gone"
            since = iso(dt.datetime.fromtimestamp(beat, dt.timezone.utc))
            last = reported.get(sid) or {}
            if last.get("since") == since and (state == "stalled" or time.time() - last.get("at", 0) < REPORT_GONE_EVERY):
                continue
            reported[sid] = {"since": since, "at": time.time()}
            out.append({"session": sid, "name": agent.get("name"), "state": state, "since": since,
                        "socket": f"uds:/tmp/cc-socks/{agent['pid']}.sock" if agent.get("alive") else None})
        save(path, mark)
        return out


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
