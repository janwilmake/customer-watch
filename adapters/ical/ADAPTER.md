# iCal adapter (meetings)

Needs: the secret iCal address of your calendar. No MCP server. Tested with: unit tests on
recurring, moved and cancelled events (`tests/test_adapters.py`).

## Setup (2 minutes)

1. Copy the secret address:
   - Google Calendar: Settings → your calendar → Integrate calendar → Secret address in iCal format.
   - Outlook: Settings → Calendar → Shared calendars → Publish a calendar → ICS link.
2. It is a password: anyone with it reads your calendar. Keep it in the Keychain:
   `security add-generic-password -s customer-watch-ical -a calendar -w`
3. In `config.json`: add `"adapters/ical"` to `"adapter"`, and
   `"ical": {"url": {"keychain": "customer-watch-ical"}}`.

## Sources

- A `NEW` meeting item: `at`, `title`, `attendees` (addresses), `upcoming`. Every meeting with a
  customer wakes the session once, so it can set `meetings.next` and prepare it (Trust layer).
  A moved meeting wakes it again.
- The gate reads the calendar every 5 minutes; Google refreshes the secret address every few
  hours, so a meeting made a minute ago can take that long to show.
- Transcripts are not in a calendar: use your meeting recorder's connector at the full check.
