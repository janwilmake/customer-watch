# IMAP adapter (email)

Needs: an IMAP host and an app password. No MCP server. Tested with: unit tests against a fake
server (`tests/test_adapters.py`); try it against your own mailbox and report.

## Setup (5 minutes)

1. Make an app password:
   - Gmail / Google Workspace: turn on 2-Step Verification, then <https://myaccount.google.com/apppasswords>.
   - Microsoft 365: an app password, or ask your admin to allow IMAP with OAuth (not supported here yet).
   - Fastmail: Settings → Privacy & Security → App passwords (IMAP).
2. Store it in the macOS Keychain, so it never sits in a file. It asks for the password itself:
   `security add-generic-password -s customer-watch-imap -a you@company.com -w`
3. In `config.json`: `"adapter": ["adapters/imap"]` and
   `"imap": {"host": "imap.gmail.com", "user": "you@company.com", "password": {"keychain": "customer-watch-imap"}}`.
   Hosts: `imap.gmail.com`, `outlook.office365.com`, `imap.fastmail.com`, `imap.mail.me.com`.
4. Check: `python3 gate.py <session> --once` prints no `imap:` error.

## Sources

- The gate reads headers only: From, To, Cc, Date, Subject, Message-ID. A `NEW` email item carries
  `message_id` and `folder`. To read the body, use the mail connector your session has (for
  example Gmail: search `rfc822msgid:<message_id>`), or ask the user.
- `my_messages` reads the `\Sent` folder, for `trust.py --backfill`.

## Drafting

```bash
python3 ~/.claude/skills/customer-watch/adapters/imap/draft.py --to a@customer.com \
  --subject "Re: ..." --body-file /tmp/body.txt --in-reply-to "<message-id of the mail you answer>"
```

It saves the draft in the user's own Drafts folder and never sends. With
`imap.signature_html` (a path to an HTML file) the draft gets the user's signature. Record the
printed Message-ID as the draft's `link`, and tell the user to open their Drafts.

## Trust facts

- `from_me`: the From address is one of `me.json` → `emails`.
