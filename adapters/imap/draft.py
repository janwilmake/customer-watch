#!/usr/bin/env python3
"""Save a draft in my own Drafts folder over IMAP. It never sends.

Usage:
  draft.py --to a@b.com [--cc c@d.com] --subject "..." --body-file body.txt [--in-reply-to "<message-id>"]

The body is plain text. When config.json -> imap.signature_html names an HTML file, the draft gets
an HTML part too, with that signature under the text. A reply carries In-Reply-To and References,
so the mail client files it in the thread. Prints the folder and the Message-ID of the draft.
"""
import argparse
import email.utils
import html
import imaplib
import os
import sys
import time
from email.message import EmailMessage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import core  # noqa: E402

sys.modules.setdefault("core", core)
from adapters.imap import adapter  # noqa: E402


def build(a, me, s):
    msg = EmailMessage()
    msg["From"] = email.utils.formataddr((me.get("name") or "", s["user"]))
    msg["To"] = a.to
    if a.cc:
        msg["Cc"] = a.cc
    msg["Subject"] = a.subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=s["user"].split("@")[-1])
    if a.in_reply_to:
        msg["In-Reply-To"] = a.in_reply_to
        msg["References"] = a.in_reply_to
    with open(a.body_file) as f:
        body = f.read().rstrip() + "\n"
    msg.set_content(body)
    sig = s.get("signature_html")
    if sig:
        with open(os.path.expanduser(sig)) as f:
            sig_html = f.read()
        msg.add_alternative("<div>" + html.escape(body).replace("\n", "<br>") + "</div><br>" + sig_html, subtype="html")
    return msg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True)
    ap.add_argument("--cc")
    ap.add_argument("--subject", required=True)
    ap.add_argument("--body-file", required=True)
    ap.add_argument("--in-reply-to")
    a = ap.parse_args()
    s = adapter.settings()
    msg = build(a, core.me(), s)
    box = adapter.connect()
    try:
        folder = s.get("drafts_folder") or adapter.folders(box).get("\\Drafts") or "Drafts"
        typ, data = box.append(adapter.quote(folder), "(\\Draft)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
    finally:
        box.logout()
    if typ != "OK":
        sys.exit(f"draft not saved: {data}")
    print(f"draft saved in {folder}: {msg['Message-ID']}")


if __name__ == "__main__":
    main()
