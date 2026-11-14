#!/usr/bin/env python3
"""customer-watch next step: the next best personal step with each contact of a customer.

Usage: nextstep.py <slug> [<contact name>]      prints JSON, one object per contact

It reads the ledger and my trust log and computes, with no model:
  signals   what the history says about this contact
  ask       whether an ask fits now (and why not), and which one: visit, meeting, referral
  call      whether a phone call beats a message now, and why
  step      one line: the step to put in the next message to this contact
The model runs this before every draft and puts `step` in it, worded in my own voice (me.md).
"""
import datetime as dt
import json
import re
import sys

import core
import note
from note import parse, when, working_hours

ME = core.me()
ASK_EVERY_DAYS = ME.get("ask_every_days", 28)
OPEN_ASK_DAYS = 14           # an ask without an answer blocks a new one this long
VALUE_DAYS = 7               # a fix or a told fix this recent is a value moment
UNANSWERED_WORKING_DAYS = 5  # no answer to us this long: call instead of a third mail
KNOWN = {"worked together", "would take my call"}


def is_me(name):
    mine = {n.lower() for n in [ME.get("name"), ME.get("first_name")] if n}
    return bool(name) and any(m in name.lower() for m in mine)


COMMERCIAL = re.compile(r"commercial|sales|deal|renewal|account", re.I)


def commercial_owner(ledger):
    """A teammate who owns the customer commercially, when that is not me: check with them before a visit.

    Owners are free text ("Luc", "Luc (sales)", "Luc van Poll (commercial)"). An owner counts when the
    role names sales work, or when the name is in me.json -> commercial_team.
    """
    team = [n.lower() for n in ME.get("commercial_team") or []]
    for o in (ledger.get("customer") or {}).get("owners", []):
        person = o.split("(")[0].strip()
        if is_me(person):
            continue
        if COMMERCIAL.search(o) or any(person.lower() == t or person.lower().startswith(t + " ") for t in team):
            return person
    return None


def signals(ledger, contact, now):
    name = contact.get("name")
    log = note.touches(ledger, name)
    t = contact.get("trust") or {}
    asks = [e for e in log if e.get("kind") == "ask"]
    open_ask = next((e for e in asks if not e.get("outcome")), None)
    convs = [c for c in ledger.get("conversations", []) if c.get("status") == "open" and c.get("their_person") == name]
    ours = [c for c in convs if c.get("ball") == "us" and not note.delegated(c)]
    theirs = [c for c in convs if c.get("ball") == "them" and parse(c.get("waiting_since"))]
    shipped = [w for w in ledger.get("wishes", []) if w.get("status") == "shipped" and w.get("reporter") == name
               and parse(w.get("shipped_at"))]
    recent_value = [w for w in shipped if (now - parse(w["shipped_at"])).days <= VALUE_DAYS] + [
        e for e in log if e.get("kind") in ("told", "help") and (now - parse(e["at"])).days <= VALUE_DAYS]
    usage = ledger.get("usage") or {}
    drop = (usage.get("active_users_prev_14d") or 0) >= 2 and (usage.get("active_users_14d") or 0) < 0.5 * usage["active_users_prev_14d"]
    mine = (lambda p: p.get("their_person") == name
            or (not p.get("their_person") and "champion" in (contact.get("role") or "").lower()))
    late_to_them = [p for p in ledger.get("promises", []) if p.get("status") == "open" and parse(p.get("due"))
                    and parse(p["due"]) < now and not note.delegated(p) and mine(p)]
    # A late promise is worth a call once it is 2 working days late, to that one person.
    late_promises = [p for p in late_to_them if working_hours(parse(p["due"]), now) >= 48]
    late_answers = [c for c in ours if parse(c.get("waiting_since"))
                    and working_hours(parse(c["waiting_since"]), now) > note.LATE_HOURS]
    return {
        "name": name, "role": contact.get("role"), "phone": (contact.get("phones") or [None])[0],
        "last_touch": {"at": log[0]["at"], "how": log[0].get("how") or log[0].get("kind")} if log else None,
        "met_in_person": any(e.get("kind") == "visit" for e in log),
        "last_meeting_or_call": next((e["at"] for e in log if e.get("kind") in ("visit", "call", "booked")), None),
        "calls_with_me": sum(1 for e in log if e.get("kind") == "call" or e.get("how") == "phone"),
        "linkedin_connected": t.get("linkedin_connected"),
        "knows_me": t.get("knows_me") or "no",
        "open_ask": {"at": open_ask["at"], "ask": open_ask.get("ask")} if open_ask else None,
        "last_ask_at": asks[0]["at"] if asks else None,
        "their_open_problems": [c.get("todo") or c.get("subject") for c in ours],
        "unanswered_by_them": [{"what": c.get("todo") or c.get("subject"),
                                "working_days": round(working_hours(parse(c["waiting_since"]), now) / 24, 1)} for c in theirs],
        "untold_fixes": [w.get("name") for w in shipped if not w.get("told_at")],
        "value_moment": [x.get("name") or x.get("kind") for x in recent_value],
        "late_to_them": [p.get("what") for p in late_to_them] + [c.get("todo") or c.get("subject") for c in late_answers],
        "late_promises": [p.get("what") for p in late_promises],
        "usage_drop": drop,
        "commercial_owner": commercial_owner(ledger),
        "key": core.is_key(contact.get("role")),
    }


def decide(s, now):
    """The ask, the call and the one step, from the signals."""
    blocked = []
    if not s["key"]:
        blocked.append("not a key contact")
    if s["late_to_them"]:
        blocked.append(f"we owe them something late ({s['late_to_them'][0][:60]}): deliver first")
    if s["open_ask"] and (now - parse(s["open_ask"]["at"])).days < OPEN_ASK_DAYS:
        blocked.append(f"the {s['open_ask']['ask']} ask of {when(s['open_ask']['at'])[:10].rstrip()} has no answer yet")
    elif s["last_ask_at"] and (now - parse(s["last_ask_at"])).days < ASK_EVERY_DAYS:
        blocked.append(f"last ask {(now - parse(s['last_ask_at'])).days} days ago (every {ASK_EVERY_DAYS})")

    kind = None
    if not s["met_in_person"]:
        kind = "visit"
    elif not s["last_meeting_or_call"] or (now - parse(s["last_meeting_or_call"])).days > 30:
        kind = "meeting"
    elif s["knows_me"] in KNOWN and s["value_moment"]:
        kind = "referral"
    strength = "main" if s["value_moment"] else "soft"
    ask = {"allowed": not blocked and kind is not None, "kind": kind, "strength": strength,
           "blocked_by": blocked, "after_resolving": bool(s["their_open_problems"]),
           "check_with": s["commercial_owner"] if kind in ("visit", "referral") else None}

    reasons = []
    for u in s["unanswered_by_them"]:
        if u["working_days"] >= UNANSWERED_WORKING_DAYS:
            reasons.append(f"no answer for {u['working_days']:.0f} working days: {u['what']}")
    if s["late_promises"]:
        reasons.append(f"a promise is 2+ working days late ({s['late_promises'][0][:60]}): bring the new date by phone")
    if s["usage_drop"] and "champion" in (s["role"] or "").lower():
        reasons.append("usage fell by more than half: ask how it goes")
    if s["calls_with_me"] >= 2 and s["their_open_problems"]:
        reasons.append("they talk by phone with me, and a problem is open")
    if len(s["their_open_problems"]) >= 3:
        reasons.append(f"{len(s['their_open_problems'])} open problems: one call clears more than three mails")
    call = {"suggest": bool(reasons) and bool(s["phone"]), "reasons": reasons, "phone": s["phone"]}

    if s["untold_fixes"]:
        step = f"tell them yourself that {', '.join(s['untold_fixes'])} is live (a short video works best)"
    elif call["suggest"]:
        step = f"call {s['phone']}: {reasons[0]}"
    elif ask["allowed"]:
        step = {"visit": "invite them for a coffee at the office, or offer to come to them",
                "meeting": "propose 15 minutes through the booking link",
                "referral": "ask whether they know another agency owner with the same problem"}[kind]
        if strength == "soft":
            step = "a light P.S.: " + step
        if ask["check_with"]:
            step += f" (check with {ask['check_with']} first)"
        if ask["after_resolving"]:
            step += ", only in a message that resolves their open problem"
    elif s["key"] and not s["last_touch"]:
        step = "a short personal message from you: no ask yet"
    else:
        step = "no ask: answer well, and sign as yourself"
    extra = "connect on LinkedIn (not in the message)" if s["key"] and s["linkedin_connected"] is not True else None
    return {"ask": ask, "call": call, "step": step, "also": extra}


def contact_steps(ledger, now=None, only=None):
    now = now or core.now()
    out = []
    for contact in (ledger.get("customer") or {}).get("contacts", []):
        if not contact.get("name") or (only and contact["name"].lower() != only.lower()):
            continue
        s = signals(ledger, contact, now)
        out.append({"contact": contact["name"], **decide(s, now), "signals": s})
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    ledger = core.load(core.ledger_path(sys.argv[1]), None)
    if not ledger:
        sys.exit(f"no ledger for {sys.argv[1]}")
    only = " ".join(sys.argv[2:]) or None
    print(json.dumps(contact_steps(ledger, only=only), indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
