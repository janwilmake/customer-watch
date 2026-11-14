#!/usr/bin/env python3
"""customer-watch picture: composes the Roost picture of a watch session.

Usage:
  picture.py --face SRC --logo SRC [--post SESSION] [--out FILE]   one customer
  picture.py --logos SRC SRC ... [--post SESSION] [--out FILE]     several customers

SRC is a URL or a file path. Give fallbacks as "a|b|c": every one that loads is a candidate, and
the squarest wins, so a square icon beats a wide wordmark. The face fills the picture and the logo
sits on a badge at the bottom right. Several logos share a grid, with no faces. A logo is always
scaled to fit whole, never cropped; only uniform empty borders around it are trimmed.
"""
import argparse
import base64
import io
import json
import math
import subprocess
import sys
import urllib.request

from PIL import Image, ImageChops, ImageDraw, ImageOps

import core

SIZE = 256
WHITE = (255, 255, 255, 255)


def fetch(src):
    if src.startswith(("http://", "https://")):
        req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = r.read()
    else:
        with open(src, "rb") as f:
            data = f.read()
    img = Image.open(io.BytesIO(data))
    img.load()
    return ImageOps.exif_transpose(img).convert("RGBA")


def best(spec):
    """The squarest image among the sources in "a|b|c" that load."""
    found = []
    for src in spec.split("|"):
        try:
            found.append(fetch(src.strip()))
        except Exception as e:  # a dead URL or an unreadable format is one candidate less
            sys.stderr.write(f"skip {src.strip()[:80]}: {e}\n")
    if not found:
        return None
    return min(found, key=lambda i: (abs(math.log(i.width / i.height)), -i.width))


def trim(img):
    """Cut uniform borders: transparent ones, or ones in the colour of the top-left pixel."""
    box = img.getchannel("A").getbbox()
    if box and box != (0, 0, img.width, img.height):
        img = img.crop(box)
    flat = Image.alpha_composite(Image.new("RGBA", img.size, WHITE), img).convert("RGB")
    diff = ImageChops.difference(flat, Image.new("RGB", img.size, flat.getpixel((0, 0))))
    box = diff.point(lambda v: 255 if v > 18 else 0).getbbox()
    return img.crop(box) if box else img


def fit(img, box, pad):
    """The image scaled to fit whole inside a box x box square, centred, on white."""
    tile = Image.new("RGBA", (box, box), WHITE)
    inner = box - 2 * pad
    img = trim(img)
    scale = min(inner / img.width, inner / img.height)
    img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    tile.alpha_composite(img, ((box - img.width) // 2, (box - img.height) // 2))
    return tile


def rounded(tile, radius):
    mask = Image.new("L", tile.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, tile.width - 1, tile.height - 1), radius, fill=255)
    out = Image.new("RGBA", tile.size, (0, 0, 0, 0))
    out.paste(tile, (0, 0), mask)
    return out


def face_picture(face, logo):
    canvas = Image.new("RGBA", (SIZE, SIZE), WHITE)
    canvas.alpha_composite(ImageOps.fit(face, (SIZE, SIZE), Image.LANCZOS, centering=(0.5, 0.4)))
    if logo is not None:
        badge, margin = 104, 8
        ring = rounded(Image.new("RGBA", (badge + 6, badge + 6), (230, 230, 230, 255)), 24)
        inner = rounded(fit(logo, badge, 10), 21)
        ring.alpha_composite(inner, (3, 3))
        canvas.alpha_composite(ring, (SIZE - badge - 6 - margin, SIZE - badge - 6 - margin))
    return canvas


def logos_picture(logos):
    n = len(logos)
    if n == 1:
        return fit(logos[0], SIZE, 20)
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    gap = 8
    cell = (SIZE - gap * (cols + 1)) // cols
    canvas = Image.new("RGBA", (SIZE, SIZE), (238, 238, 238, 255))
    top = (SIZE - rows * cell - (rows - 1) * gap) // 2
    for i, logo in enumerate(logos):
        r, c = divmod(i, cols)
        in_row = min(cols, n - r * cols)
        left = (SIZE - in_row * cell - (in_row - 1) * gap) // 2
        tile = rounded(fit(logo, cell, max(4, cell // 10)), cell // 6)
        canvas.alpha_composite(tile, (left + c * (cell + gap), top + r * (cell + gap)))
    return canvas


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--face")
    ap.add_argument("--logo")
    ap.add_argument("--logos", nargs="+")
    ap.add_argument("--post", metavar="SESSION")
    ap.add_argument("--out")
    a = ap.parse_args()

    if a.logos:
        logos = [img for img in (best(s) for s in a.logos) if img is not None]
        if not logos:
            sys.exit("no logo loaded")
        pic = logos_picture(logos)
    else:
        face = best(a.face) if a.face else None
        logo = best(a.logo) if a.logo else None
        if face is not None:
            pic = face_picture(face, logo)
        elif logo is not None:
            pic = logos_picture([logo])
        else:
            sys.exit("neither the face nor the logo loaded")

    buf = io.BytesIO()
    pic.convert("RGB").save(buf, "JPEG", quality=88)
    if a.out:
        with open(a.out, "wb") as f:
            f.write(buf.getvalue())
    if a.post and core.roost(a.post):
        photo = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        out = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-X", "POST",
                              "-H", "content-type: application/json", "-d", "@-",
                              core.roost(a.post)],
                             input=json.dumps({"photo": photo}), capture_output=True, text=True)
        print(out.stdout)


if __name__ == "__main__":
    main()
