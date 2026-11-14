#!/usr/bin/env python3
"""Renders docs/loop.svg: the loop customer-watch closes around your pipeline, as a circle.

Run: python3 docs/make-loop-svg.py
"""
import math
import os

W, H = 1200, 880
CX, CY, R = 600, 450, 290
NODE = 62

GREEN, BLUE, VIOLET = "#4fd18b", "#5fa8ff", "#a78bfa"

# Clockwise from the top: the customer, customer-watch on the way in, the pipeline, customer-watch on the way out.
NODES = [
    (-90, "Customer", "person", GREEN, None),
    (-30, "customer-watch", "eye", BLUE, ("knows every", "conversation")),
    (30, "Ticket", "ticket", VIOLET, None),
    (90, "PR", "merge", VIOLET, None),
    (150, "Production", "bolt", VIOLET, None),
    (210, "customer-watch", "eye", BLUE, ("drafts “it’s live”", "+ the next step")),
]
ARCS = [  # (from, to, colour from, colour to, label, label side)
    (0, 1, GREEN, BLUE, "contact", "start"),
    (1, 2, BLUE, VIOLET, "wish → ticket", "start"),
    (2, 3, VIOLET, VIOLET, None, None),
    (3, 4, VIOLET, VIOLET, None, None),
    (4, 5, VIOLET, BLUE, "merged", "end"),
    (5, 0, BLUE, GREEN, "told, same day", "end"),
]


def at(deg, r=R):
    a = math.radians(deg)
    return CX + r * math.cos(a), CY + r * math.sin(a)


def icon(kind, color):
    s = f'stroke="{color}" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"'
    return {
        "person": f'<circle cx="0" cy="-20" r="10" {s}/><path d="M-19,10 C-19,-6 19,-6 19,10" {s}/>',
        "eye": f'<path d="M-24,-10 C-12,-26 12,-26 24,-10 C12,6 -12,6 -24,-10 Z" {s}/>'
               f'<circle cx="0" cy="-10" r="6" fill="{color}"/>',
        "ticket": f'<path d="M-20,-24 H20 V-16 A5,5 0 0 0 20,-6 V2 H-20 V-6 A5,5 0 0 0 -20,-16 Z" {s}/>'
                  f'<path d="M-8,-14 H8 M-8,-8 H4" {s}/>',
        "merge": f'<circle cx="-10" cy="-24" r="4.5" {s}/><circle cx="-10" cy="6" r="4.5" {s}/>'
                 f'<circle cx="12" cy="-6" r="4.5" {s}/><path d="M-10,-19 V1 M-10,-17 C-10,-6 12,-14 12,-11" {s}/>',
        "bolt": f'<path d="M4,-28 L-12,-6 H0 L-4,12 L12,-12 H0 Z" {s}/>',
    }[kind]


def main():
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           "font-family=\"system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif\">", "<defs>",
           '<radialGradient id="bg" cx="50%" cy="50%" r="65%"><stop offset="0" stop-color="#1d1d2a"/>'
           '<stop offset="1" stop-color="#121218"/></radialGradient>',
           '<filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="7" result="b"/>'
           '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
           f'<linearGradient id="brand" x1="0" x2="1"><stop offset="0" stop-color="{GREEN}"/>'
           f'<stop offset="1" stop-color="{BLUE}"/></linearGradient>']
    for i, (a, b, c1, c2, _, _) in enumerate(ARCS):
        (x1, y1), (x2, y2) = at(NODES[a][0]), at(NODES[b][0])
        out.append(f'<linearGradient id="arc{i}" gradientUnits="userSpaceOnUse" x1="{x1:.0f}" y1="{y1:.0f}" '
                   f'x2="{x2:.0f}" y2="{y2:.0f}"><stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/></linearGradient>')
    out.append("</defs>")
    out.append(f'<rect width="{W}" height="{H}" rx="20" fill="url(#bg)"/>')

    # The pipeline: a soft violet sector under the bottom of the ring.
    ro, ri = R + 78, R - 78
    (ox1, oy1), (ox2, oy2) = at(30, ro), at(150, ro)
    (ix1, iy1), (ix2, iy2) = at(150, ri), at(30, ri)
    out.append(f'<path d="M{ox1:.1f},{oy1:.1f} A{ro},{ro} 0 0 1 {ox2:.1f},{oy2:.1f} L{ix1:.1f},{iy1:.1f} '
               f'A{ri},{ri} 0 0 0 {ix2:.1f},{iy2:.1f} Z" fill="{VIOLET}" fill-opacity="0.09" stroke="{VIOLET}" '
               'stroke-opacity="0.25" stroke-dasharray="4 8"/>')
    out.append(f'<text x="{CX}" y="{CY + R + 118}" font-size="15" fill="{VIOLET}" text-anchor="middle" '
               'letter-spacing="2">YOUR PIPELINE · ALREADY FAST WITH CLAUDE CODE</text>')

    # The ring, one gradient arc per step, with a chevron halfway.
    for i, (a, b, _, _, label, side) in enumerate(ARCS):
        a1, a2 = NODES[a][0], NODES[b][0] + (360 if NODES[b][0] < NODES[a][0] else 0)
        (x1, y1), (x2, y2) = at(a1), at(a2)
        out.append(f'<path d="M{x1:.1f},{y1:.1f} A{R},{R} 0 0 1 {x2:.1f},{y2:.1f}" stroke="url(#arc{i})" '
                   'stroke-width="6" fill="none" stroke-linecap="round" opacity="0.9"/>')
        mid = (a1 + a2) / 2
        mx, my = at(mid)
        out.append(f'<path d="M-9,-11 L5,0 L-9,11" transform="translate({mx:.1f},{my:.1f}) rotate({mid + 90:.1f})" '
                   'stroke="#ffffff" stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')
        if label:
            lx, ly = at(mid, R + 34)
            out.append(f'<text x="{lx + (10 if side == "start" else -10):.1f}" y="{ly + 6:.1f}" font-size="19" '
                       f'font-weight="700" fill="#ffffff" text-anchor="{side}">{label}</text>')

    # A dot that travels the loop, again and again.
    (tx, ty), (bx, by) = at(-90), at(90)
    loop = f"M{tx:.1f},{ty:.1f} A{R},{R} 0 0 1 {bx:.1f},{by:.1f} A{R},{R} 0 0 1 {tx:.1f},{ty:.1f}"
    out.append(f'<circle r="8" fill="#ffffff" filter="url(#glow)"><animateMotion dur="9s" repeatCount="indefinite" path="{loop}"/></circle>')

    # The stations.
    for deg, title, kind, color, caption in NODES:
        x, y = at(deg)
        out.append(f'<g transform="translate({x:.1f},{y:.1f})">')
        out.append(f'<circle r="{NODE + 10}" fill="{color}" opacity="0.10" filter="url(#glow)"/>')
        out.append(f'<circle r="{NODE}" fill="#191924" stroke="{color}" stroke-width="3"/>')
        out.append(icon(kind, color))
        size = 13 if len(title) > 10 else 15
        out.append(f'<text y="34" font-size="{size}" font-weight="700" fill="#ffffff" text-anchor="middle">{title}</text>')
        out.append("</g>")
        if caption:
            cx_, cy_ = at(deg, R + NODE + 22)
            anchor = "start" if math.cos(math.radians(deg)) > 0 else "end"
            for n, line in enumerate(caption):
                out.append(f'<text x="{cx_:.1f}" y="{cy_ - 8 + n * 22:.1f}" font-size="16" fill="#c9d6f0" '
                           f'text-anchor="{anchor}">{line}</text>')

    # The middle: what it is, and why it matters.
    out.append(f'<text x="{CX}" y="{CY - 44}" font-size="40" font-weight="800" fill="url(#brand)" text-anchor="middle">customer-watch</text>')
    out.append(f'<text x="{CX}" y="{CY - 10}" font-size="17" fill="#a9a9b8" text-anchor="middle">one Claude Code session per customer</text>')
    out.append(f'<text x="{CX}" y="{CY + 40}" font-size="17" fill="#ff8f8f" text-anchor="middle">before: fixed in hours, told in days or never</text>')
    out.append(f'<text x="{CX}" y="{CY + 68}" font-size="17" font-weight="700" fill="{GREEN}" text-anchor="middle">now: told the same day</text>')
    out.append(f'<text x="{W - 32}" y="{H - 26}" font-size="13" fill="#6a6a7a" text-anchor="end">github.com/janwilmake/customer-watch</text>')
    out.append("</svg>")

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "loop.svg")
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")
    print(f"{path}")


if __name__ == "__main__":
    main()
