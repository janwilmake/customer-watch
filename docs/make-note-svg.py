#!/usr/bin/env python3
"""Renders docs/note.svg from the demo note, so the picture in the README is the real output.

Run: python3 docs/make-note-svg.py
"""
import html
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env = {**os.environ, "CUSTOMER_WATCH_HOME": os.path.join(ROOT, "examples", "demo"),
       "CUSTOMER_WATCH_NOW": "2026-11-12T15:00:00Z"}
text = subprocess.run([sys.executable, os.path.join(ROOT, "note.py"), "demo"], env=env,
                      capture_output=True, text=True, check=True).stdout
lines = text.split("\n\n")[0].rstrip().split("\n")  # the Acme block

W, LH, TOP, LEFT = 1080, 21, 92, 150
H = TOP + LH * len(lines) + 36
SECTIONS = {"Waiting for you:": "#ff6b6b", "Waiting for team:": "#5fa8ff", "Calls to make:": "#ffb347",
            "Drafts ready:": "#c792ea", "Trust:": "#4fd18b"}


def color(line, section):
    if line.startswith("Acme"):
        return "#ffffff", 700
    if line in SECTIONS:
        return SECTIONS[line], 700
    if "(late:" in line:
        return "#ff8f8f", 400
    if line.startswith("  ·"):
        return "#c9c9d1", 400
    if section:
        return "#e6e6ec", 400
    return "#a9a9b8", 400


out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, monospace">',
       f'<rect width="{W}" height="{H}" rx="16" fill="#16161d"/>',
       # the Roost strip: three session tiles, the first with a red badge
       '<rect x="24" y="24" width="88" height="%d" rx="14" fill="#22222c"/>' % (H - 48)]
for i, (label, badge) in enumerate([("A", "3"), ("N", None), ("≡", None)]):
    y = 40 + i * 84
    fill = "#2f6fed" if i == 0 else "#3a3a48"
    out.append(f'<rect x="40" y="{y}" width="56" height="56" rx="14" fill="{fill}"/>')
    out.append(f'<text x="68" y="{y + 37}" font-size="24" font-weight="700" fill="#fff" text-anchor="middle" font-family="system-ui, sans-serif">{label}</text>')
    if badge:
        out.append(f'<circle cx="94" cy="{y + 2}" r="12" fill="#ff3b30"/>')
        out.append(f'<text x="94" y="{y + 7}" font-size="14" font-weight="700" fill="#fff" text-anchor="middle" font-family="system-ui, sans-serif">{badge}</text>')
out.append(f'<text x="{LEFT}" y="52" font-size="20" font-weight="700" fill="#ffffff" font-family="system-ui, sans-serif">Watch: Acme Staffing</text>')
out.append(f'<text x="{LEFT}" y="74" font-size="13" fill="#8a8a99" font-family="system-ui, sans-serif">customer-watch · rendered by note.py from the ledger and the clock, no model</text>')
section = None
for n, line in enumerate(lines):
    if line in SECTIONS:
        section = line
    fill, weight = color(line, section)
    shown = line if len(line) <= 100 else line[:99] + "…"
    out.append(f'<text x="{LEFT}" y="{TOP + 14 + n * LH}" font-size="13.5" font-weight="{weight}" fill="{fill}" xml:space="preserve">{html.escape(shown)}</text>')
out.append("</svg>")
with open(os.path.join(ROOT, "docs", "note.svg"), "w") as f:
    f.write("\n".join(out) + "\n")
print(f"docs/note.svg: {len(lines)} lines")
