# Adapters

| Adapter | Reads | Status |
|---|---|---|
| [`imap`](imap/ADAPTER.md) | email over IMAP; drafts to your Drafts folder | unit-tested against a fake server |
| [`ical`](ical/ADAPTER.md) | meetings from a secret iCal address | unit-tested on repeating, moved and cancelled events |
| [`hubspot`](hubspot/ADAPTER.md) | emails, calls, meetings and notes in HubSpot | untested against a live portal |
| [`asana`](asana/ADAPTER.md) | one task per open promise and wish, synced both ways | tested on one live project |

To use one, add it to `config.json`: `"adapter": ["adapters/imap"]`, plus its settings (see its
`ADAPTER.md`). No copying needed.

To share one: a folder here with:

- `adapter.py`: the probes, following the contract in [`../examples/adapter/adapter.py`](../examples/adapter/adapter.py);
- `ADAPTER.md`: the instructions for the model (sources, how to resolve a customer, how to draft);
- a short note at the top of `ADAPTER.md`: which MCP server it needs, and what you tested it on.

Wanted: Gmail API, Microsoft Graph, Attio, Pipedrive, Front, Zendesk, Salesforce, Aircall,
Fireflies, Gong, Linear (customer issues).
