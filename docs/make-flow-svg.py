#!/usr/bin/env python3
"""Renders docs/flow.svg: a triangle with the customer on top and your software factory as its base.

"Message in" sits halfway down the left side, "message out" halfway up the right side: both are
customer-watch. One loop of 10 s: the customer (sad, waiting) sends a message, it comes in, little
agents build the wish in the factory (ticket, PR, production), and "it's live" goes back up to the
customer, who smiles. An animated SVG (SMIL), no script.
Run: python3 docs/make-flow-svg.py
"""
import math
import os

W, H = 1200, 840
DUR = 10.0
GREEN, BLUE, VIOLET, CORAL, GOLD, INK = "#4fd18b", "#5fa8ff", "#a78bfa", "#e8845c", "#ffd166", "#16161d"
FONT = "system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"

CUST = (600, 128)
FAC = (300, 520, 900, 708)          # the factory box, the base of the triangle: x0, y0, x1, y1
BELT_Y = 632
ENTER, EXIT = (FAC[0], BELT_Y), (FAC[2], BELT_Y)
MIN = ((CUST[0] + ENTER[0]) / 2, (CUST[1] + ENTER[1]) / 2)    # halfway down the left side
MOUT = ((CUST[0] + EXIT[0]) / 2, (CUST[1] + EXIT[1]) / 2)     # halfway up the right side
STATIONS = [(440, "Ticket", "ticket"), (600, "PR", "merge"), (760, "Production", "bolt")]
AT_STATION = [(0.34, 0.40), (0.44, 0.50), (0.54, 0.60)]
HAPPY = [0, 0.885, 0.9, 0.985, 1]   # when the customer's face changes: sad, then happy, then sad again


def dist(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


def kt(times):
    return ";".join(f"{t:.4f}" for t in times)


def anim(attr, values, times, begin=0.0):
    return (f'<animate attributeName="{attr}" values="{";".join(map(str, values))}" keyTimes="{kt(times)}" '
            f'dur="{DUR}s" begin="{begin:.2f}s" repeatCount="indefinite"/>')


def anim_t(kind, values, times):
    return (f'<animateTransform attributeName="transform" type="{kind}" values="{";".join(values)}" keyTimes="{kt(times)}" '
            f'dur="{DUR}s" repeatCount="indefinite"/>')


def window(on, off, begin=0.0, peak=1, fade=0.01):
    """Visible from `on` to `off`, as fractions of the loop."""
    return anim("opacity", [0, 0, peak, peak, 0, 0], [0, max(on - fade, 0.0001), on, off, min(off + fade, 0.9999), 1], begin)


def motion(path, points, times, begin=0.0):
    return (f'<animateMotion path="{path}" keyPoints="{kt(points)}" keyTimes="{kt(times)}" calcMode="linear" '
            f'dur="{DUR}s" begin="{begin:.2f}s" repeatCount="indefinite"/>')


def spin(seconds, reverse=False):
    return (f'<animateTransform attributeName="transform" type="rotate" from="0" to="{-360 if reverse else 360}" '
            f'dur="{seconds}s" repeatCount="indefinite"/>')


def icon(kind, color):
    s = f'stroke="{color}" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"'
    return {
        "in": f'<rect x="-20" y="-13" width="40" height="28" rx="5" {s}/><path d="M-18,-10 L0,4 L18,-10" {s}/>'
              f'<path d="M-34,-29 L-23,-18 M-23,-25 V-18 H-30" {s}/>',
        "out": f'<rect x="-20" y="-13" width="40" height="28" rx="5" {s}/><path d="M-18,-10 L0,4 L18,-10" {s}/>'
               f'<path d="M23,-18 L34,-29 M27,-29 H34 V-22" {s}/>',
        "ticket": f'<path d="M-15,-11 H15 V-4 A4,4 0 0 0 15,4 V11 H-15 V4 A4,4 0 0 0 -15,-4 Z" {s}/>',
        "merge": f'<circle cx="-8" cy="-11" r="4" {s}/><circle cx="-8" cy="11" r="4" {s}/><circle cx="9" cy="0" r="4" {s}/>'
                 f'<path d="M-8,-7 V7 M-8,-5 C-8,4 9,-6 9,-4" {s}/>',
        "bolt": f'<path d="M3,-15 L-8,2 H0 L-3,15 L8,-2 H0 Z" {s}/>',
    }[kind]


def gear(x, y, r, teeth, color, seconds, reverse=False):
    pts = []
    for i in range(teeth * 2):
        a = math.pi * i / teeth
        rr = r if i % 2 == 0 else r * 0.76
        for d in (-0.22, 0.22):
            b = a + d * math.pi / teeth
            pts.append(f"{rr * math.cos(b):.1f},{rr * math.sin(b):.1f}")
    return (f'<g transform="translate({x},{y})"><g>{spin(seconds, reverse)}<polygon points="{" ".join(pts)}" '
            f'fill="{color}" fill-opacity="0.12" stroke="{color}" stroke-width="2" stroke-linejoin="round"/>'
            f'<circle r="{r * 0.32:.1f}" fill="#1a1726" stroke="{color}" stroke-width="2"/></g></g>')


def agent(x, y, busy):
    """A small agent at a station: it bobs, and hammers away (with sparks) while the wish is there."""
    on, off = busy
    bob = '<animateTransform attributeName="transform" type="translate" values="0,0;0,-3;0,0" dur="1.6s" repeatCount="indefinite"/>'
    hops, times = ["0,0", "0,0"], [0, on]
    t = on
    while t + 0.02 < off:
        hops += ["0,-7", "0,0"]
        times += [t + 0.01, t + 0.02]
        t += 0.02
    hops.append("0,0")
    times.append(1)
    sparks = "".join(f'<path d="M{dx},{dy - 5} L{dx},{dy + 5} M{dx - 5},{dy} L{dx + 5},{dy}" stroke="{GOLD}" stroke-width="2.5" '
                     f'stroke-linecap="round" opacity="0">{window(on + 0.005, off - 0.005)}</path>'
                     for dx, dy in [(-16, -26), (16, -30), (0, -38)])
    return (f'<g transform="translate({x},{y})"><g>{bob}<g>{anim_t("translate", hops, times)}'
            f'<line x1="0" y1="-14" x2="0" y2="-20" stroke="{CORAL}" stroke-width="2.5"/><circle cy="-22" r="3" fill="{CORAL}"/>'
            f'<rect x="-12" y="-14" width="24" height="18" rx="6" fill="{CORAL}"/>'
            f'<circle cx="-5" cy="-6" r="2.4" fill="{INK}"/><circle cx="5" cy="-6" r="2.4" fill="{INK}"/>'
            f'<rect x="-8" y="5" width="16" height="9" rx="3" fill="{CORAL}" opacity="0.75"/>{sparks}</g></g></g>')


def face(x, y, r):
    """The customer: sad while waiting, with a tear; happy, with sparkles, when "it's live" arrives."""
    sad_mouth, happy_mouth = "M-15,17 Q0,7 15,17", "M-15,9 Q0,25 15,9"
    sad_l, happy_l = "M-19,-13 Q-12,-19 -6,-17", "M-19,-18 Q-12,-23 -6,-20"
    sad_r, happy_r = "M6,-17 Q12,-19 19,-13", "M6,-20 Q12,-23 19,-18"
    stroke = f'stroke="{GREEN}" stroke-width="3.2" fill="none" stroke-linecap="round"'

    def morph(a, b):
        return anim("d", [a, a, b, b, a], HAPPY)

    o = [f'<g transform="translate({x},{y})">',
         f'<circle r="{r + 18}" fill="{GREEN}" opacity="0" filter="url(#glow)">{window(0.885, 0.985, peak=0.55)}</circle>',
         f'<circle r="{r}" fill="#1b2e25" stroke="{GREEN}" stroke-width="3">'
         f'{anim("fill", ["#1b2e25", "#1b2e25", "#235c40", "#235c40", "#1b2e25"], HAPPY)}</circle>',
         # eyes, with a blink
         f'<g>{anim_t("scale", ["1 1", "1 1", "1 0.15", "1 1", "1 1", "1 0.15", "1 1", "1 1"], [0, 0.2, 0.21, 0.22, 0.6, 0.61, 0.62, 1])}'
         f'<ellipse cx="-11" cy="-5" rx="3.6" ry="4.4" fill="{GREEN}"/><ellipse cx="11" cy="-5" rx="3.6" ry="4.4" fill="{GREEN}"/></g>',
         f'<path d="{sad_l}" {stroke}>{morph(sad_l, happy_l)}</path>',
         f'<path d="{sad_r}" {stroke}>{morph(sad_r, happy_r)}</path>',
         f'<path d="{sad_mouth}" {stroke}>{morph(sad_mouth, happy_mouth)}</path>',
         # a tear rolls down while they wait
         f'<path d="M-13,2 Q-16,8 -13,10 Q-10,8 -13,2 Z" fill="{BLUE}" opacity="0">{window(0.32, 0.8, peak=0.9)}'
         f'{anim_t("translate", ["0,0", "0,0", "0,14", "0,14"], [0, 0.32, 0.8, 1])}</path>',
         f'<circle cx="-24" cy="10" r="5" fill="#ff8fa3" opacity="0">{window(0.9, 0.985, peak=0.5)}</circle>',
         f'<circle cx="24" cy="10" r="5" fill="#ff8fa3" opacity="0">{window(0.9, 0.985, peak=0.5)}</circle>']
    for i, (sx, sy, size) in enumerate([(-62, -40, 9), (64, -46, 11), (-70, 22, 7), (74, 18, 8), (0, -80, 10)]):
        d = (f"M{sx},{sy - size} Q{sx},{sy} {sx + size},{sy} Q{sx},{sy} {sx},{sy + size} "
             f"Q{sx},{sy} {sx - size},{sy} Q{sx},{sy} {sx},{sy - size} Z")
        o.append(f'<path d="{d}" fill="{GOLD}" opacity="0">{window(0.9 + i * 0.008, 0.98, peak=0.95)}</path>')
    o.append("</g>")
    return "".join(o)


def station_node(at, r, color, kind, title, sub, glow, side):
    x, y = at
    lx, anchor = (x - r - 34, "end") if side == "left" else (x + r + 34, "start")
    return (f'<g transform="translate({x},{y})">'
            f'<circle r="{r + 10}" fill="{color}" opacity="0" filter="url(#glow)">{glow}</circle>'
            f'<g>{spin(24)}<circle r="{r + 13}" fill="none" stroke="{color}" stroke-opacity="0.45" stroke-width="2" '
            f'stroke-dasharray="3 9" stroke-linecap="round"/></g>'
            f'<circle r="{r}" fill="url(#node)" stroke="{color}" stroke-width="3"/>{icon(kind, color)}</g>'
            f'<text x="{lx}" y="{y}" font-size="24" font-weight="800" fill="#ffffff" text-anchor="{anchor}">{title}</text>'
            f'<text x="{lx}" y="{y + 28}" font-size="17" fill="{color}" text-anchor="{anchor}">{sub}</text>')


def edge(a, b, c1, c2, gid):
    return (f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}">'
            f'<stop offset="0" stop-color="{c1}"/><stop offset="1" stop-color="{c2}"/></linearGradient>'
            f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="url(#{gid})" stroke-width="7" stroke-linecap="round" opacity="0.85"/>'
            f'<line x1="{a[0]}" y1="{a[1]}" x2="{b[0]}" y2="{b[1]}" stroke="#ffffff" stroke-width="3" stroke-linecap="round" '
            f'stroke-dasharray="1 17" opacity="0.55"><animate attributeName="stroke-dashoffset" from="18" to="0" dur="0.9s" '
            f'repeatCount="indefinite"/></line>')


def token(body, path, points, times, on, off, color):
    """The moving thing, with a comet trail of fading copies behind it."""
    trail = "".join(f'<g opacity="0">{window(on, off, begin=d, peak=p)}{motion(path, points, times, begin=d)}'
                    f'<circle r="{rr}" fill="{color}" filter="url(#soft)"/></g>'
                    for d, p, rr in [(0.06, 0.55, 9), (0.12, 0.38, 7), (0.18, 0.24, 5.5), (0.24, 0.12, 4)])
    return trail + f'<g opacity="0">{window(on, off)}{motion(path, points, times)}{body}</g>'


def main():
    p_in = f"M{CUST[0]},{CUST[1]} L{MIN[0]},{MIN[1]} L{ENTER[0]},{ENTER[1]}"
    p_fac = f"M{ENTER[0]},{ENTER[1]} L{EXIT[0]},{EXIT[1]}"
    p_out = f"M{EXIT[0]},{EXIT[1]} L{MOUT[0]},{MOUT[1]} L{CUST[0]},{CUST[1]}"
    at_in = dist(CUST, MIN) / (dist(CUST, MIN) + dist(MIN, ENTER))
    at_out = dist(EXIT, MOUT) / (dist(EXIT, MOUT) + dist(MOUT, CUST))
    belt = [(x - ENTER[0]) / (EXIT[0] - ENTER[0]) for x, _, _ in STATIONS]
    x0, y0, x1, y1 = FAC

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">',
         "<defs>",
         '<radialGradient id="bg" cx="50%" cy="42%" r="78%"><stop offset="0" stop-color="#20203a"/><stop offset="0.6" stop-color="#15151f"/>'
         '<stop offset="1" stop-color="#0d0d12"/></radialGradient>',
         '<pattern id="dots" width="26" height="26" patternUnits="userSpaceOnUse"><circle cx="13" cy="13" r="1.3" fill="#ffffff" fill-opacity="0.07"/></pattern>',
         '<radialGradient id="node" cx="50%" cy="35%" r="70%"><stop offset="0" stop-color="#262638"/><stop offset="1" stop-color="#15151f"/></radialGradient>',
         '<linearGradient id="fac" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a2342"/><stop offset="1" stop-color="#16131f"/></linearGradient>',
         '<filter id="glow" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="10" result="b"/>'
         '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
         '<filter id="soft" x="-100%" y="-100%" width="300%" height="300%"><feGaussianBlur stdDeviation="3"/></filter>',
         "</defs>",
         f'<rect width="{W}" height="{H}" rx="22" fill="url(#bg)"/>',
         f'<rect width="{W}" height="{H}" rx="22" fill="url(#dots)"/>']

    # The triangle, with dots flowing along it: customer → in → factory → out → customer.
    o.append(edge(CUST, MIN, GREEN, BLUE, "e1"))
    o.append(edge(MIN, ENTER, BLUE, VIOLET, "e2"))
    o.append(edge(EXIT, MOUT, VIOLET, BLUE, "e3"))
    o.append(edge(MOUT, CUST, BLUE, GREEN, "e4"))

    # The software factory: the base.
    o.append(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" rx="26" fill="url(#fac)" stroke="{VIOLET}" stroke-width="3"/>')
    o.append(f'<rect x="{x0 + 8}" y="{y0 + 8}" width="{x1 - x0 - 16}" height="{y1 - y0 - 16}" rx="20" fill="none" stroke="{VIOLET}" stroke-opacity="0.18"/>')
    o.append(f'<text x="{(x0 + x1) / 2}" y="{y0 + 36}" font-size="15" font-weight="800" letter-spacing="4" fill="{VIOLET}" '
             'text-anchor="middle">YOUR SOFTWARE FACTORY</text>')
    o.append(gear(x0 + 46, y0 + 40, 17, 9, VIOLET, 7))
    o.append(gear(x0 + 80, y0 + 26, 11, 7, VIOLET, 4.5, reverse=True))
    o.append(gear(x1 - 46, y0 + 40, 17, 9, VIOLET, 7, reverse=True))
    o.append(gear(x1 - 80, y0 + 26, 11, 7, VIOLET, 4.5))
    # the belt: a track with moving rollers
    o.append(f'<rect x="{x0 + 18}" y="{BELT_Y - 7}" width="{x1 - x0 - 36}" height="14" rx="7" fill="#0f0d17" stroke="{VIOLET}" stroke-opacity="0.35"/>')
    o.append(f'<line x1="{x0 + 26}" y1="{BELT_Y}" x2="{x1 - 26}" y2="{BELT_Y}" stroke="{VIOLET}" stroke-width="4" stroke-dasharray="6 14" '
             f'stroke-linecap="round" opacity="0.6"><animate attributeName="stroke-dashoffset" from="20" to="0" dur="0.5s" repeatCount="indefinite"/></line>')
    for (x, name, kind), (on, off) in zip(STATIONS, AT_STATION):
        o.append(f'<g transform="translate({x},{BELT_Y})"><circle r="36" fill="{VIOLET}" opacity="0" filter="url(#glow)">'
                 f'{window(on, off, peak=0.8)}</circle><circle r="28" fill="url(#node)" stroke="{VIOLET}" stroke-width="2.5"/>'
                 f'{icon(kind, VIOLET)}</g>')
        o.append(f'<text x="{x}" y="{BELT_Y + 52}" font-size="13" font-weight="700" fill="#c9c3e6" text-anchor="middle">{name}</text>')
        o.append(agent(x + 46, BELT_Y - 30, (on, off)))
    # Production ships: a flash.
    px = STATIONS[2][0]
    o.append(f'<circle cx="{px}" cy="{BELT_Y}" r="28" fill="none" stroke="{GOLD}" stroke-width="4" opacity="0">'
             f'{anim("r", [28, 28, 28, 90, 90], [0, 0.6, 0.601, 0.67, 1])}{anim("opacity", [0, 0, 0.9, 0, 0], [0, 0.6, 0.601, 0.67, 1])}</circle>')

    # message in, message out (customer-watch), and the customer.
    o.append(station_node(MIN, 56, BLUE, "in", "message in", "customer-watch reads it", window(0.12, 0.19, peak=0.8), "left"))
    o.append(station_node(MOUT, 56, BLUE, "out", "message out", "customer-watch drafts it", window(0.72, 0.79, peak=0.8), "right"))
    o.append(face(CUST[0], CUST[1], 56))

    # The token: a message, then a wish, then "it's live", each with a comet trail.
    envelope = (f'<rect x="-18" y="-13" width="36" height="26" rx="4" fill="{BLUE}"/>'
                f'<path d="M-16,-10 L0,3 L16,-10" stroke="{INK}" stroke-width="2.5" fill="none" stroke-linejoin="round"/>')
    o.append(token(envelope, p_in, [0, 0, at_in, at_in, 1, 1], [0, 0.03, 0.12, 0.19, 0.29, 1], 0.02, 0.29, BLUE))
    wish = (f'<g transform="translate(0,-48)"><rect x="-30" y="-15" width="60" height="30" rx="9" fill="{VIOLET}"/>'
            f'<text y="5" font-size="14" font-weight="800" fill="{INK}" text-anchor="middle">wish</text></g>')
    o.append(f'<g opacity="0">{window(0.29, 0.63)}'
             f'{motion(p_fac, [0, 0, belt[0], belt[0], belt[1], belt[1], belt[2], belt[2], 1, 1], [0, 0.29, 0.34, 0.40, 0.44, 0.50, 0.54, 0.60, 0.63, 1])}{wish}</g>')
    live = (f'<circle r="17" fill="{GREEN}"/><path d="M-7,0 L-2,6 L8,-6" stroke="{INK}" stroke-width="3.5" fill="none" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
            f'<g transform="translate(-58,-62)"><rect width="116" height="34" rx="17" fill="#ffffff"/>'
            f'<text x="58" y="23" font-size="16" font-weight="800" fill="{INK}" text-anchor="middle">it’s live!</text></g>')
    o.append(token(live, p_out, [0, 0, at_out, at_out, 1, 1], [0, 0.63, 0.72, 0.79, 0.88, 1], 0.63, 0.9, GREEN))

    # One caption per step.
    for (on, off), text, color in [((0.0, 0.29), "1 · a customer writes, calls or meets you", BLUE),
                                    ((0.29, 0.63), "2 · your software factory builds it", VIOLET),
                                    ((0.63, 1.0), "3 · they hear it’s live, the same day", GREEN)]:
        o.append(f'<text x="{W / 2}" y="782" font-size="26" font-weight="800" fill="{color}" text-anchor="middle" opacity="0">'
                 f'{text}{window(on + 0.005, off - 0.005)}</text>')
    o.append(f'<text x="{W - 32}" y="{H - 22}" font-size="13" fill="#6a6a7a" text-anchor="end">github.com/janwilmake/customer-watch</text>')
    o.append("</svg>")

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flow.svg")
    with open(path, "w") as f:
        f.write("\n".join(o) + "\n")
    print(path)


if __name__ == "__main__":
    main()
