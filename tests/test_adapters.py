"""The ready adapters, against a fake IMAP server, an iCal fixture and a faked HubSpot API.

Run: python3 -m unittest discover tests
"""
import datetime as dt
import importlib.util
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("CUSTOMER_WATCH_HOME", os.path.join(ROOT, "examples", "demo"))
os.environ.setdefault("CUSTOMER_WATCH_NOW", "2026-11-12T15:00:00Z")
sys.path.insert(0, ROOT)

import core  # noqa: E402
import note  # noqa: E402

UTC = dt.timezone.utc
ACME = core.Customer("acme-staffing", core.load(core.ledger_path("acme-staffing"), {}))


def load(name):
    sys.modules.setdefault("core", core)
    path = os.path.join(ROOT, "adapters", name, "adapter.py")
    spec = importlib.util.spec_from_file_location(f"test_adapter_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Loading(unittest.TestCase):
    def test_a_list_of_adapters_resolves_in_the_skill_folder(self):
        cfg = {**core.DEFAULTS, "adapter": ["adapters/imap", "adapters/ical", "adapters/nope"]}
        with mock.patch.object(core, "config", return_value=cfg), mock.patch("sys.stderr"):
            paths = core.adapter_paths()
        self.assertEqual([os.path.basename(os.path.dirname(p)) for p in paths], ["imap", "ical"])

    def test_secrets_come_from_the_environment(self):
        with mock.patch.dict(os.environ, {"CW_TEST_SECRET": "s3cret"}):
            self.assertEqual(core.secret({"env": "CW_TEST_SECRET"}), "s3cret")
        self.assertEqual(core.secret("plain"), "plain")


class FakeIMAP:
    """Enough of imaplib.IMAP4_SSL for the adapter: Gmail-style folders, one new mail."""
    mails = {}

    def __init__(self, host, port):
        self.untagged_responses = {}

    def login(self, user, password):
        return "OK", [b"ok"]

    def logout(self):
        return "BYE", []

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\All \\HasNoChildren) "/" "[Gmail]/All Mail"',
                      b'(\\Sent \\HasNoChildren) "/" "[Gmail]/Sent Mail"', b'(\\Drafts) "/" "[Gmail]/Drafts"']

    def select(self, folder, readonly=False):
        self.untagged_responses = {"UIDVALIDITY": [b"7"]}
        return "OK", [b"1"]

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            return "OK", [" ".join(str(u) for u in sorted(self.mails)).encode()]
        uids = [int(u) for u in args[0].split(",")]
        out = []
        for u in uids:
            out.append((f"{u} (UID {u} BODY[HEADER.FIELDS (FROM TO)] {{0}}".encode(), self.mails[u].encode()))
            out.append(b")")
        return "OK", out


MAIL = ("From: Sanne de Vries <sanne@acme-staffing.example>\r\nTo: Alex <alex@example.ai>\r\n"
        "Date: Thu, 12 Nov 2026 15:58:00 +0100\r\nSubject: =?utf-8?q?Caf=C3=A9_next_week=3F?=\r\n"
        "Message-ID: <abc@acme-staffing.example>\r\n\r\n")


class Imap(unittest.TestCase):
    def setUp(self):
        self.imap = load("imap")
        self.tmp = tempfile.mkdtemp()
        cfg = {**core.DEFAULTS, "imap": {"host": "imap.example", "user": "alex@example.ai", "password": "x"}}
        self.patches = [mock.patch.object(core, "CACHE", self.tmp), mock.patch.object(core, "config", return_value=cfg),
                        mock.patch.object(core, "FEED_EVERY", 0), mock.patch("imaplib.IMAP4_SSL", FakeIMAP)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_the_first_probe_starts_from_now_and_the_next_one_reports_a_new_mail(self):
        FakeIMAP.mails = {1: MAIL.replace("abc", "old")}
        self.assertEqual(self.imap.probe_email({}, [ACME], {}), [])
        FakeIMAP.mails[2] = MAIL
        hits = self.imap.probe_email({}, [ACME], {})
        self.assertEqual(len(hits), 1)
        slug, channel, key, data = hits[0]
        self.assertEqual((slug, channel, key), ("acme-staffing", "email", "<abc@acme-staffing.example>"))
        self.assertEqual(data["subject"], "Café next week?")
        self.assertEqual(data["at"], "2026-11-12T14:58:00Z")
        self.assertEqual(data["folder"], "[Gmail]/All Mail")
        self.assertFalse(data["from_me"])

    def test_a_draft_is_saved_never_sent(self):
        sys.modules.setdefault("adapters.imap.adapter", self.imap)
        spec = importlib.util.spec_from_file_location("imap_draft", os.path.join(ROOT, "adapters", "imap", "draft.py"))
        draft = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(draft)
        body = os.path.join(self.tmp, "body.txt")
        with open(body, "w") as f:
            f.write("Hey Sanne,\n\nIt is live.\n")
        args = mock.Mock(to="sanne@acme-staffing.example", cc=None, subject="Re: bulk move",
                         body_file=body, in_reply_to="<abc@acme-staffing.example>")
        msg = draft.build(args, {"name": "Alex Example"}, {"user": "alex@example.ai"})
        self.assertEqual(msg["In-Reply-To"], "<abc@acme-staffing.example>")
        self.assertIn("Alex Example", msg["From"])
        self.assertIn("It is live.", msg.get_content())


ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:once
DTSTART;TZID=Europe/Amsterdam:20261113T100000
SUMMARY:Pricing\\, with Acme
ATTENDEE;CN=Pieter:mailto:pieter@acme-staffing.example
END:VEVENT
BEGIN:VEVENT
UID:weekly
DTSTART:20261002T080000Z
RRULE:FREQ=WEEKLY;BYDAY=FR
EXDATE:20261120T080000Z
SUMMARY:Weekly sync
ATTENDEE:mailto:sanne@acme-staffing.example
END:VEVENT
BEGIN:VEVENT
UID:weekly
RECURRENCE-ID:20261127T080000Z
DTSTART:20261126T130000Z
SUMMARY:Weekly sync (moved)
ATTENDEE:mailto:sanne@acme-staffing.example
END:VEVENT
BEGIN:VEVENT
UID:gone
DTSTART:20261116T090000Z
STATUS:CANCELLED
SUMMARY:Acme demo
END:VEVENT
BEGIN:VEVENT
UID:other
DTSTART;VALUE=DATE:20261117
SUMMARY:Dentist
END:VEVENT
END:VCALENDAR
"""


class Ical(unittest.TestCase):
    def setUp(self):
        self.ical = load("ical")

    def test_repeats_moves_and_cancellations(self):
        got = self.ical.meetings(ICS, dt.datetime(2026, 11, 10, tzinfo=UTC), dt.datetime(2026, 12, 1, tzinfo=UTC))
        by = sorted((m["at"], m["title"]) for m in got)
        self.assertEqual(by, [
            ("2026-11-13T08:00:00Z", "Weekly sync"),
            ("2026-11-13T09:00:00Z", "Pricing, with Acme"),       # 10:00 Amsterdam
            ("2026-11-16T23:00:00Z", "Dentist"),                  # an all-day event, from local midnight
            ("2026-11-26T13:00:00Z", "Weekly sync (moved)"),      # the 27th moved to the 26th; the 20th is skipped
        ])

    def test_a_meeting_matches_by_attendee_or_by_name(self):
        rows = self.ical.meetings(ICS, dt.datetime(2026, 11, 10, tzinfo=UTC), dt.datetime(2026, 12, 1, tzinfo=UTC))
        with mock.patch.object(self.ical, "feed", return_value=rows):
            hits = self.ical.probe_meetings({}, [ACME], {})
        self.assertEqual(sorted(h[3]["title"] for h in hits),
                         ["Pricing, with Acme", "Weekly sync", "Weekly sync (moved)"])


class Hubspot(unittest.TestCase):
    def setUp(self):
        self.hub = load("hubspot")
        self.tmp = tempfile.mkdtemp()

    def fake_api(self, method, path, body=None):
        if path.endswith("/emails/search"):
            return {"results": [{"id": "e1", "properties": {
                "hs_timestamp": "2026-11-12T14:00:00Z", "hs_lastmodifieddate": "2026-11-12T14:00:01Z",
                "hs_email_subject": "Quote", "hs_email_from_email": "alex@example.ai",
                "hs_email_to_email": "someone@elsewhere.example", "hs_email_direction": "EMAIL"}}]}
        if "associations" in path:
            return {"results": [{"from": {"id": "e1"}, "to": [{"toObjectId": 501}]}]}
        if path.endswith("/contacts/batch/read"):
            return {"results": [{"id": "501", "properties": {"email": "pieter@acme-staffing.example"}}]}
        return {"results": []}

    def test_an_engagement_matches_through_its_contacts(self):
        with mock.patch.object(core, "CACHE", self.tmp), mock.patch.object(core, "FEED_EVERY", 0), \
                mock.patch.object(self.hub, "api", self.fake_api):
            hits = self.hub.probe("emails")({}, [ACME], {})
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0][:3], ("acme-staffing", "email", "emails:e1"))


class Releases(unittest.TestCase):
    def test_a_merged_pull_request_on_a_wish_wakes_the_session(self):
        import gate
        led = core.load(core.ledger_path("acme-staffing"), {})
        led["wishes"][1]["prs"] = ["https://github.com/acme/app/pull/7", "not a url"]
        done = mock.Mock(returncode=0, stdout='{"state": "MERGED", "mergedAt": "2026-11-12T13:00:00Z", "title": "InMail templates"}')
        with mock.patch.object(gate, "load", return_value=led), mock.patch("subprocess.run", return_value=done) as run:
            hits = gate.probe_releases({}, [ACME], {})
        self.assertEqual(run.call_count, 1)  # the non-url is skipped
        self.assertEqual(hits[0][1], "release")
        self.assertEqual(hits[0][3]["wish"], "inmail-templates")


class Asana(unittest.TestCase):
    """One task per open item; a shared wish is one task; a teammate's move closes the item."""

    def setUp(self):
        sys.path.insert(0, os.path.join(ROOT, "adapters", "asana"))
        import sync
        self.sync = sync
        self.cfg = {**core.DEFAULTS, "asana": {
            "project": "P", "sections": {"open": "New", "in_progress": "Doing", "told": "Told", "done": "Done"},
            "fields": {"customer": "Klant", "type": "Type"}, "type_options": {"feature": "Feature request", "promise": "Issue"},
            "customers": {"a": "Acme", "b": "Beta"}}}
        self.meta = {"sections": {"New": "s1", "Doing": "s2", "Told": "s3", "Done": "s4"},
                     "fields": {"Klant": {"gid": "fk", "options": {"Acme": "oa", "Beta": "ob"}},
                                "Type": {"gid": "ft", "options": {"Feature request": "of", "Issue": "oi"}}}}
        self.ledgers = {
            "a": {"customer": {"name": "Acme"}, "wishes": [{"name": "bulk-move", "kind": "feature", "status": "open"}],
                  "promises": [{"what": "ship bulk move", "wish": "bulk-move", "due": "2026-11-20T17:00:00+01:00", "status": "open"},
                               {"what": "call Tom", "status": "open"}]},
            "b": {"customer": {"name": "Beta"}, "wishes": [{"name": "bulk-move", "kind": "feature", "status": "open"}]}}

    def test_a_shared_wish_is_one_item_with_both_customers(self):
        with mock.patch.object(core, "config", return_value=self.cfg):
            its = self.sync.items(self.ledgers)
            self.assertEqual(sorted(its), ["p:a:" + self.sync.hashlib.sha1(b"call Tom").hexdigest()[:10], "w:bulk-move"])
            wish = its["w:bulk-move"]
            self.assertEqual(self.sync.due_of(wish), "2026-11-20")
            self.assertEqual(self.sync.field_map(wish, self.meta), {"fk": ["oa", "ob"], "ft": ["of"]})
            self.assertEqual(self.sync.label(wish), "Acme + Beta")

    def test_a_task_moved_to_done_closes_the_wish_for_every_customer(self):
        for d in self.ledgers.values():
            d["wishes"][0]["asana"] = "T1"
        task = {"gid": "T1", "completed": True, "due_on": "2026-11-20", "modified_at": "2026-11-21T10:00:00.000Z",
                "memberships": [{"project": {"gid": "P"}, "section": {"name": "Done"}}],
                "custom_fields": [{"gid": "fk", "display_value": "Acme, Beta"}]}
        index = {"tasks": {"T1": {"key": "w:bulk-move", "section": "New"}}}
        saved = {}
        with mock.patch.object(core, "config", return_value=self.cfg), \
                mock.patch.object(self.sync, "project_meta", return_value=self.meta), \
                mock.patch.object(self.sync, "ledgers", return_value=self.ledgers), \
                mock.patch.object(self.sync, "tasks", return_value=[task]), \
                mock.patch.object(self.sync, "load", return_value=index), \
                mock.patch.object(self.sync, "save", side_effect=lambda p, d: saved.__setitem__(p, d)), \
                mock.patch.object(self.sync, "api") as api, mock.patch("builtins.print"):
            self.sync.sync(set())
        self.assertEqual([d["wishes"][0]["status"] for d in self.ledgers.values()], ["shipped", "shipped"])
        api.assert_not_called()

    def test_an_open_item_without_a_task_counts_as_unsynced(self):
        import adapter as asana_adapter
        self.ledgers["a"]["promises"][1]["asana"] = "T2"
        with mock.patch.object(core, "config", return_value=self.cfg), \
                mock.patch.object(self.sync, "ledgers", return_value={"a": self.ledgers["a"]}):
            self.assertEqual(asana_adapter.unsynced_count("a"), 1)  # the wish bulk-move has no task
            self.ledgers["a"]["wishes"][0]["asana"] = "T1"
            self.assertEqual(asana_adapter.unsynced_count("a"), 0)


class NoteUnsynced(unittest.TestCase):
    def test_the_note_names_items_without_a_task(self):
        led = {"customer": {"name": "Acme"}}
        with mock.patch.object(core, "adapter_hook", return_value=[lambda slug: 2]):
            self.assertIn("Not on the task board yet: 2", note.block("a", led, core.now(), False))
        with mock.patch.object(core, "adapter_hook", return_value=[lambda slug: 0]):
            self.assertNotIn("task board", note.block("a", led, core.now(), False))

    def test_a_failing_adapter_does_not_break_the_note(self):
        def boom(slug):
            raise RuntimeError("offline")
        with mock.patch.object(core, "adapter_hook", return_value=[boom]), mock.patch("sys.stderr"):
            self.assertEqual(note.unsynced_count("a"), 0)


if __name__ == "__main__":
    unittest.main()
