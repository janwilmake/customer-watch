# Linear adapter (a done ticket brings the fix back to the customer)

Needs: the Linear MCP server (`https://mcp.linear.app/mcp`) added to Claude Code and signed in, so
`agent-codemode call linear …` works from the shell. Tested with: one live team, 250 issues a page.

## Setup

In `config.json`: add `"adapters/linear"` to `"adapter"`, and:

```json
"linear": {"server": "linear", "team": "<team name or key>", "shipped_statuses": ["Done"]}
```

`shipped_statuses` are the statuses that mean "live for the customer". Use only statuses that come
after the production deploy.

## Sources

- A `NEW` item with `"channel": "release"` and a `ticket`: the ticket of an open wish reached a
  shipped status. Handle it as Tick step 2 says: check that it is live, set the wish `shipped` with
  `shipped_at`, and draft the told message.

## Tick

- **Every ticket you create or find for a wish goes into the wish**: `"ticket": "<id>"` (more than
  one: `"tickets": [...]`). Without it, the release of that wish wakes nobody.
