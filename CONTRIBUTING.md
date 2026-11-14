# Contributing

Thanks for helping product engineers and FDEs keep their customers close.

## What helps most

1. **Adapters** for a system of record (`adapters/<name>/`). Keep company data out: no real
   names, addresses, ids or channel ids. Say which MCP server it needs.
2. **Rules** in `note.py` (Late) and `nextstep.py` (the next step). A rule change comes with a test
   in `tests/test_rules.py`, and a demo ledger change when the demo should show it.
3. **Playbooks**: a `me.md` that works for you, with the names taken out, as an example in `examples/`.

## Ground rules

- The core never names a company, a person or a channel. Those belong in the watch home.
- Draft, never send. A change that sends a message on its own will not be merged.
- Python 3.9+, standard library only (Pillow for `picture.py` only).
- Run `python3 -m unittest discover tests` and `python3 docs/make-note-svg.py` (when the note
  changes) before a PR.
