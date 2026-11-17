"""The rules that decide the badge and the next step, run against the demo home at a fixed time.

Run: python3 -m unittest discover tests
"""
import copy
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["CUSTOMER_WATCH_HOME"] = os.path.join(ROOT, "examples", "demo")
os.environ["CUSTOMER_WATCH_NOW"] = "2026-11-12T15:00:00Z"  # a Thursday, 16:00 in Amsterdam
sys.path.insert(0, ROOT)

import core  # noqa: E402
import nextstep  # noqa: E402
import note  # noqa: E402

NOW = core.now()


def ledger(slug):
    return copy.deepcopy(core.load(core.ledger_path(slug), {}))


def step(led, name):
    return next(s for s in nextstep.contact_steps(led, NOW) if s["contact"] == name)


class Late(unittest.TestCase):
    def test_acme_has_three_late_things(self):
        late = note.late_items(ledger("acme-staffing"), NOW)
        self.assertEqual(len(late), 3, late)

    def test_a_handed_over_item_is_not_late(self):
        late = " ".join(note.late_items(ledger("acme-staffing"), NOW))
        self.assertNotIn("invoice", late)

    def test_the_handed_over_item_is_late_again_after_two_working_days(self):
        later = core.dt.datetime(2026, 11, 17, 12, tzinfo=core.dt.timezone.utc)
        late = " ".join(note.late_items(ledger("acme-staffing"), later))
        self.assertIn("Robin has not replied", late)

    def test_a_live_fix_nobody_told_is_late_after_a_working_day(self):
        led = ledger("acme-staffing")
        self.assertTrue(any("not told" in i for i in note.late_items(led, NOW)))
        led["wishes"][0]["told_at"] = "2026-11-11T12:00:00Z"
        self.assertFalse(any("not told" in i for i in note.late_items(led, NOW)))

    def test_weekends_do_not_count(self):
        led = ledger("northwind-recruiting")
        led["conversations"][0].update(ball="us", waiting_since="2026-11-13T15:00:00Z")  # Friday
        monday = core.dt.datetime(2026, 11, 16, 14, tzinfo=core.dt.timezone.utc)
        self.assertEqual(note.late_items(led, monday), [])

    def test_northwind_is_calm(self):
        self.assertEqual(note.late_items(ledger("northwind-recruiting"), NOW), [])


class NextStep(unittest.TestCase):
    def test_the_reporter_of_a_live_fix_hears_it_first(self):
        self.assertIn("is live", step(ledger("acme-staffing"), "Sanne de Vries")["step"])

    def test_a_week_without_an_answer_becomes_a_call(self):
        s = step(ledger("acme-staffing"), "Pieter Jansen")
        self.assertTrue(s["call"]["suggest"])
        self.assertTrue(s["step"].startswith("call "))

    def test_no_ask_while_we_owe_them_something_late(self):
        s = step(ledger("acme-staffing"), "Mo Amrani")
        self.assertFalse(s["ask"]["allowed"])
        self.assertTrue(any("deliver first" in b for b in s["ask"]["blocked_by"]))

    def test_met_but_not_spoken_for_a_month_gets_a_meeting_ask(self):
        s = step(ledger("northwind-recruiting"), "Lisa Bakker")
        self.assertEqual(s["ask"]["kind"], "meeting")
        self.assertEqual(s["ask"]["strength"], "main")  # the told fix of 10 Nov is a value moment

    def test_never_met_gets_a_visit_ask_and_the_commercial_owner_is_asked_first(self):
        led = ledger("acme-staffing")
        led["conversations"] = []
        led["calls_to_make"] = []
        s = step(led, "Pieter Jansen")
        self.assertEqual(s["ask"]["kind"], "visit")
        self.assertEqual(s["ask"]["check_with"], "Robin")

    def test_the_commercial_owner_is_found_in_free_text(self):
        for owners, team, want in ((["Luc (sales)"], [], "Luc"), (["Luc"], ["Luc"], "Luc"),
                                   (["Luc van Poll"], ["Luc"], "Luc van Poll"), (["Robin (onboarding)"], [], None),
                                   (["Alex (deal owner)"], [], None)):
            led = {"customer": {"owners": owners}}
            with mock.patch.dict(nextstep.ME, {"commercial_team": team}):
                self.assertEqual(nextstep.commercial_owner(led), want, owners)

    def test_one_ask_a_month(self):
        led = ledger("northwind-recruiting")
        led["trust_log"].append({"at": "2026-11-01T10:00:00Z", "contact": "Lisa Bakker", "kind": "ask",
                                 "ask": "meeting", "outcome": "no"})
        s = step(led, "Lisa Bakker")
        self.assertFalse(s["ask"]["allowed"])

    def test_an_open_ask_blocks_the_next_one(self):
        led = ledger("northwind-recruiting")
        led["trust_log"].append({"at": "2026-11-11T10:00:00Z", "contact": "Lisa Bakker", "kind": "ask",
                                 "ask": "meeting", "outcome": None})
        self.assertTrue(any("no answer yet" in b for b in step(led, "Lisa Bakker")["ask"]["blocked_by"]))


class Note(unittest.TestCase):
    def test_the_demo_note_stays_under_300_words(self):
        leds = {s: ledger(s) for s in ("acme-staffing", "northwind-recruiting")}
        text = "\n\n".join(note.block(s, l, NOW, prefix=True) for s, l in leds.items())
        self.assertLess(len(text.split()), 300)
        self.assertIn("Calls to make:", text)
        self.assertIn("Drafts ready:", text)



class Deadlines(unittest.TestCase):
    def test_every_late_thing_has_a_deadline_in_the_past(self):
        for slug in ("acme-staffing", "northwind-recruiting"):
            led = ledger(slug)
            past = [at for at, _ in note.deadline_items(led, NOW) if at < NOW]
            self.assertEqual(len(past), len(note.late_items(led, NOW)), slug)

    def test_open_items_beyond_the_note_still_get_a_deadline(self):
        texts = " ".join(t for _, t in note.deadline_items(ledger("acme-staffing"), NOW))
        self.assertIn("onboarding checklist", texts)
        self.assertIn("Robin:", texts)


class Report(unittest.TestCase):
    def setUp(self):
        import report
        self.report = report

    def test_the_daily_report_lists_the_late_items_and_the_call(self):
        text = self.report.daily()
        self.assertIn("3 late at 1 customer", text)
        self.assertIn("Pieter Jansen (Acme Staffing)", text)

    def test_the_team_report_names_no_person_and_no_phone_number(self):
        text = self.report.weekly()
        self.assertIn("**Acme Staffing**", text)
        for private in ("Sanne", "Pieter", "Mo Amrani", "Lisa", "+31", "Robin:"):
            self.assertNotIn(private, text)
        self.assertLess(len(text), 5000)  # one Slack message

    def test_with_names_on_the_team_report_names_the_champion_but_never_a_phone_number(self):
        from unittest import mock
        cfg = {**core.config(), "report": {"names": True}}
        with mock.patch.object(core, "config", return_value=cfg):
            text = self.report.weekly()
        self.assertIn("Acme Staffing** (Sanne de Vries)", text)
        self.assertIn("(Sanne de Vries) — not told yet", text)
        self.assertNotIn("+31", text)


if __name__ == "__main__":
    unittest.main()
