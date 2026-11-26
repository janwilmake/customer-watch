# Asana adapter (one task per open item)

Needs: the Asana MCP server (`https://mcp.asana.com/v2/mcp`) added to Claude Code and signed in,
so `agent-codemode call asana …` works from the shell. Tested with: one live project, 25
customers, sections New Requests / In Progress / Client updated / Done.

It keeps one Asana task per open promise and per wish. A wish that several customers share is one
task, with every customer in the customer field. A promise about a wish (`"wish": "<name>"`) uses
the task of that wish. The ledger item holds the task id as `"asana": "<gid>"`.

## Setup

In `config.json`: add `"adapters/asana"` to `"adapter"`, and:

```json
"asana": {
  "project": "<project gid>",
  "sections": {"open": "New Requests", "in_progress": "In Progress", "told": "Client updated", "done": "Done"},
  "fields": {"customer": "Klant", "type": "Type", "source": "Source", "source_url": "Source url", "priority": "Priority"},
  "type_options": {"feature": "Feature request", "bug": "Bug", "promise": "Issue"},
  "source_options": {"email": "Email", "intercom": "Intercom", "meeting": "Meeting", "call": "Call", "other": "Other"},
  "priority_options": {"must-have": "High", "nice-to-have": "Low", "promise": "Medium"},
  "customers": {"<slug>": "<option of the customer field>"},
  "language": "nl"
}
```

The values are the names in your project; `sync.py` reads their ids. A field or option that is
missing is left empty. A customer without an option still gets tasks, with its name in the title.

## Sources

- A `NEW` item with `"channel": "asana"`: a teammate changed a task of this customer (section,
  completion, comment, assignee or due date). `item` names the ledger item, or is `null` for a task
  that a teammate made by hand (`"new": true`).
- The gate reads the project once a minute for every session on this Mac. It skips our own writes.

## Tick

Do this in the Tick step **Task adapter**, on every tick, not only on a full tick.

1. A `NEW` asana item: read the task with `get_task` (its comments too). A comment can hold a
   question or an answer for the customer: treat it like a teammate's Slack message.
2. A hand-made task (`"new": true`) about one of this customer's open items:
   `python3 adapters/asana/sync.py link <key> <gid>` (find the key with `sync.py plan`, or
   `p:<slug>:…` / `w:<wish name>` in `<home>/asana.json`). A task about something new: add the
   promise or wish to the ledger first, then link it.
3. New items without a task: `python3 adapters/asana/sync.py plan <slug>` prints them. Write a
   title and a short description for each in the `language` of the settings, in a file
   `[{"key", "title", "notes"}]`, then `sync.py push <file>`.
   - Title: what must happen, one line, under 80 characters, no customer name (the script puts it in front).
   - Notes: 2 to 4 short lines: what the customer asked, in their words when there are any; who
     promised what by when; the next step. No phone numbers, no email addresses.
4. `python3 adapters/asana/sync.py sync <slug>`: Asana → ledger, then ledger → Asana.
   - A task moved to **done** closes the item: a promise `done`, a wish `shipped`.
   - A task moved to **told** sets a wish's `told_at` and `told_by: "asana"`, and closes a promise.
   - A closed item moves its task to **done**. An item `in_progress` moves it to **in_progress**.
   - The due date follows the earliest open promise; the customer field follows the ledgers.
5. Then `note.py` as usual, so the Roost note shows the new state.

A task that the script cannot find (`gone:` in its output) was deleted or moved out of the
project: ask the user before you remove the `asana` id from the item.
