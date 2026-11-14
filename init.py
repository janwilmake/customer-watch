#!/usr/bin/env python3
"""customer-watch init: create the watch home from the templates in examples/.

Usage: init.py            create ~/.customer-watch (or $CUSTOMER_WATCH_HOME); never overwrites a file

Afterwards, fill in me.json and me.md, and point config.json at your Slack, Intercom and adapter.
"""
import json
import os
import shutil

import core

HOME, SKILL = core.HOME, core.SKILL
TEMPLATES = ["config.json", "me.json", "me.md", "adapter/adapter.py", "adapter/ADAPTER.md"]
EMPTY = {"wish-names.json": {}, "internal.json": {"domains": [], "org_ids": []}, "ignore.json": []}


def main():
    made = []
    for d in ("customers", "sessions", "cache", "adapter"):
        os.makedirs(os.path.join(HOME, d), exist_ok=True)
    for rel in TEMPLATES:
        dst = os.path.join(HOME, rel)
        if not os.path.exists(dst):
            shutil.copy(os.path.join(SKILL, "examples", rel), dst)
            made.append(rel)
    for rel, value in EMPTY.items():
        dst = os.path.join(HOME, rel)
        if not os.path.exists(dst):
            with open(dst, "w") as f:
                json.dump(value, f, indent=1)
            made.append(rel)
    print(f"watch home: {HOME}")
    print("created: " + (", ".join(made) if made else "nothing, every file was already there"))
    print("""
Next:
  1. me.json and me.md: who you are, your office, your booking link, how you write.
  2. config.json: your timezone, and your Slack and Intercom MCP servers (or null).
  3. adapter/: your own system of record. Without one, the watch reads Intercom and Slack only.
     Ask Claude Code: "write a customer-watch adapter for <your CRM or inbox> from examples/adapter".
  4. In Claude Code: /customer-watch <customer name>""")


if __name__ == "__main__":
    main()
