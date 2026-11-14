#!/usr/bin/env python3
"""Renders docs/flow.svg: message in, your software factory, message out. An animated SVG (SMIL).

The customer sits on the bottom edge. One loop of 10 s: their message comes in (customer-watch
reads it), the wish goes through the factory (ticket, PR, production), and the message goes out
(customer-watch drafts "it's live"), back to the customer.
Run: python3 docs/make-flow-svg.py
"""
import math
import os

W, H = 1200, 820
DUR = "10s"
GREEN, BLUE, VIOLET, INK = "#4fd18b", "#5fa8ff", "#a78bfa", "#16161d"
FONT = "system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"

CUST, MIN, MOUT = (600, 560), (240, 560), (960, 560)
FAC = (380, 120, 820, 284)          # the factory box: x0, y0, x1, y1
BELT_Y = 224
ENTER, EXIT = (FAC[0], BELT_Y), (FAC[2], BELT_Y)
STATIONS = [(480, "Ticket", "ticket"), (600, "PR", "merge"), (720, "Production", "bolt")]


def dist(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def window(on, off, fade=0.01):
    kt = [0, max(on - fade, 0.0001), on, off, min(off + fade, 0.9999), 1]
    return (f'<animate attributeName="opacity" values="0;0;1;1;0;0" keyTimes="{";".join(f"{k:.4f}" for k in kt)}" '
            f'dur="{DUR}" repeatCount="indefinite"/>')


def motion(path, points, times):
    return (f'<animateMotion path="{path}" keyPoints="{";".join(f"{p:.4f}" for p in points)}" '
            f'keyTimes="{";".join(f"{t:.4f}" for t in times)}" calcMode="linear" dur="{DUR}" repeatCount="indefinite"/>')


def icon(kind, color, scale=1.0):
    s = f'stroke="{color}" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"'
    body = {
        "person": f'<circle cx="0" cy="-9" r="10" {s}/><path d="M-19,20 C-19,3 19,3 19,20" {s}/>',
        "in": f'<rect x="-22" y="-14" width="44" height="30" rx="5" {s}/><path d="M-20,-11 L0,4 L20,-11" {s}/>'
              f'<path d="M-36,-30 L-24,-18 M-24,-26 V-18 H-32" {s}/>',
        "out": f'<rect x="-22" y="-14" width="44" height="30" rx="5" {s}/><path d="M-20,-11 L0,4 L20,-11" {s}/>'
               f'<path d="M24,-18 L36,-30 M28,-30 H36 V-22" {s}/>',
        "ticket": f'<path d="M-15,-11 H15 V-4 A4,4 0 0 0 15,4 V11 H-15 V4 A4,4 0 0 0 -15,-4 Z" {s}/>',
        "merge": f'<circle cx="-8" cy="-11" r="4" {s}/><circle cx="-8" cy="11" r="4" {s}/><circle cx="9" cy="0" r="4" {s}/>'
                 f'<path d="M-8,-7 V7 M-8,-5 C-8,4 9,-6 9,-4" {s}/>',
        "bolt": f'<path d="M3,-15 L-8,2 H0 L-3,15 L8,-2 H0 Z" {s}/>',
    }[kind]
    return f'<g transform="scale({scale})">{body}</g>'


def edge(a, b, c1, c2, gid):
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
    return (f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}">'
            f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/></linearGradient>'
            f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="url(#{gid})" stroke-width="6" stroke-linecap="round"/>'
            f'<path d="M-9,-11 L5,0 L-9,11" transform="translate({mx:.1f},{my:.1f}) rotate({ang:.1f})" stroke="#ffffff" '
            f'stroke-width="4" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')


def node(at, r, color, kind, title, sub, glow):
    x, y = at
    out = [f'<g transform="translate({x},{y})">',
           f'<circle r="{r + 8}" fill="{color}" opacity="0" filter="url(#glow)">{glow}</circle>',
           f'<circle r="{r}" fill="#191924" stroke="{color}" stroke-width="3"/>', icon(kind, color), "</g>",
           f'<text x="{x}" y="{y + r + 36}" font-size="22" font-weight="800" fill="#ffffff" text-anchor="middle">{title}</text>']
    if sub:
        out.append(f'<text x="{x}" y="{y + r + 62}" font-size="16" fill="{color}" text-anchor="middle">{sub}</text>')
    return "".join(out)


def main():
    p_in = f"M{CUST[0]},{CUST[1]} L{MIN[0]},{MIN[1]} L{ENTER[0]},{ENTER[1]}"
    p_fac = f"M{ENTER[0]},{ENTER[1]} L{EXIT[0]},{EXIT[1]}"
    p_out = f"M{EXIT[0]},{EXIT[1]} L{MOUT[0]},{MOUT[1]} L{CUST[0]},{CUST[1]}"
    at_in = dist(CUST, MIN) / (dist(CUST, MIN) + dist(MIN, ENTER))
    at_out = dist(EXIT, MOUT) / (dist(EXIT, MOUT) + dist(MOUT, CUST))
    belt = [(x - ENTER[0]) / (EXIT[0] - ENTER[0]) for x, _, _ in STATIONS]

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">',
         "<defs>",
         '<radialGradient id="bg" cx="50%" cy="45%" r="75%"><stop offset="0" stop-color="#1e1e2c"/><stop offset="1" stop-color="#111117"/></radialGradient>',
         '<filter id="glow" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="9" result="b"/>'
         '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
         "</defs>",
         f'<rect width="{W}" height="{H}" rx="20" fill="url(#bg)"/>']

    # The triangle: customer → message in → factory → message out → customer.
    o.append(edge(CUST, MIN, GREEN, BLUE, "e1"))
    o.append(edge(MIN, ENTER, BLUE, VIOLET, "e2"))
    o.append(edge(EXIT, MOUT, VIOLET, BLUE, "e3"))
    o.append(edge(MOUT, CUST, BLUE, GREEN, "e4"))

    # The software factory.
    x0, y0, x1, y1 = FAC
    o.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" rx="24" fill="#1a1726" stroke="{VIOLET}" stroke-width="3"/>')
    o.append(f'<text x="{(x0 + x1) / 2}" y="{y0 + 34}" font-size="15" font-weight="800" letter-spacing="3" fill="{VIOLET}" '
             'text-anchor="middle">YOUR SOFTWARE FACTORY</text>')
    o.append(f'<line x1="{ENTER[0] + 20}" y1="{BELT_Y}" x2="{EXIT[0] - 20}" y2="{BELT_Y}" stroke="{VIOLET}" stroke-width="3" '
             f'stroke-dasharray="8 8" opacity="0.5"><animate attributeName="stroke-dashoffset" from="16" to="0" dur="0.6s" '
             'repeatCount="indefinite"/></line>')
    for (x, name, kind), (on, off) in zip(STATIONS, [(0.34, 0.40), (0.44, 0.50), (0.54, 0.60)]):
        o.append(f'<g transform="translate({x},{BELT_Y})"><circle r="32" fill="{VIOLET}" opacity="0" filter="url(#glow)">'
                 f'{window(on, off)}</circle><circle r="27" fill="#211d33" stroke="{VIOLET}" stroke-width="2.5"/>'
                 f'{icon(kind, VIOLET)}</g>')
        o.append(f'<text x="{x}" y="{BELT_Y + 48}" font-size="13" font-weight="700" fill="#c9c3e6" text-anchor="middle">{name}</text>')

    # The corners and the customer.
    o.append(node(MIN, 64, BLUE, "in", "message in", "customer-watch reads it", window(0.12, 0.19)))
    o.append(node(MOUT, 64, BLUE, "out", "message out", "customer-watch drafts it", window(0.72, 0.79)))
    o.append(node(CUST, 50, GREEN, "person", "your customer", None, window(0.88, 0.98)))
    o.append(f'<g transform="translate({CUST[0]},{CUST[1]})"><circle r="58" fill="{GREEN}" opacity="0" filter="url(#glow)">'
             f'{window(0.0, 0.05)}</circle></g>')

    # The token: a message, then a wish, then "it's live".
    o.append(f'<g opacity="0">{window(0.02, 0.29)}{motion(p_in, [0, 0, at_in, at_in, 1, 1], [0, 0.03, 0.12, 0.19, 0.29, 1])}'
             f'<rect x="-18" y="-13" width="36" height="26" rx="4" fill="{BLUE}"/>'
             f'<path d="M-16,-10 L0,3 L16,-10" stroke="{INK}" stroke-width="2.5" fill="none" stroke-linejoin="round"/></g>')
    o.append(f'<g opacity="0">{window(0.29, 0.63)}'
             f'{motion(p_fac, [0, 0, belt[0], belt[0], belt[1], belt[1], belt[2], belt[2], 1, 1], [0, 0.29, 0.34, 0.40, 0.44, 0.50, 0.54, 0.60, 0.63, 1])}'
             f'<g transform="translate(0,-46)"><rect x="-30" y="-15" width="60" height="30" rx="9" fill="{VIOLET}"/>'
             f'<text y="5" font-size="14" font-weight="800" fill="{INK}" text-anchor="middle">wish</text></g></g>')
    o.append(f'<g opacity="0">{window(0.63, 0.97)}{motion(p_out, [0, 0, at_out, at_out, 1, 1], [0, 0.63, 0.72, 0.79, 0.88, 1])}'
             f'<circle r="17" fill="{GREEN}"/><path d="M-7,0 L-2,6 L8,-6" stroke="{INK}" stroke-width="3.5" fill="none" '
             f'stroke-linecap="round" stroke-linejoin="round"/>'
             f'<g transform="translate(-58,-62)"><rect width="116" height="34" rx="17" fill="#ffffff"/>'
             f'<text x="58" y="23" font-size="16" font-weight="800" fill="{INK}" text-anchor="middle">it’s live!</text></g></g>')

    # One caption per step.
    for (on, off), text, color in [((0.0, 0.29), "1 · a customer writes, calls or meets you", BLUE),
                                    ((0.29, 0.63), "2 · your software factory builds it", VIOLET),
                                    ((0.63, 1.0), "3 · they hear it’s live, the same day", GREEN)]:
        o.append(f'<text x="{W / 2}" y="752" font-size="26" font-weight="800" fill="{color}" text-anchor="middle" opacity="0">'
                 f'{text}{window(on + 0.005, off - 0.005)}</text>')
    o.append(f'<text x="{W - 32}" y="{H - 22}" font-size="13" fill="#6a6a7a" text-anchor="end">github.com/janwilmake/customer-watch</text>')
    o.append("</svg>")

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flow.svg")
    with open(path, "w") as f:
        f.write("\n".join(o) + "\n")
    print(path)


if __name__ == "__main__":
    main()
