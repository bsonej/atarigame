#!/usr/bin/env python3
"""One-off converter: a picture -> assets/splash.txt, the title screen's 160x176 four-colour bitmap.

    python3 tools/make_splash.py assets/splash-source.webp                 # writes assets/splash.txt
    python3 tools/make_splash.py SOURCE -o assets/splash.txt --preview /tmp/splash.png --compare /tmp/side.png
    python3 tools/make_splash.py --show assets/splash.txt /tmp/splash.png   # preview an existing splash.txt (no Pillow)

Converting needs Pillow (`pip install pillow`); the game's normal build does NOT (tools/build_assets.py only reads the
text file splash.txt, which you can edit by hand afterwards). --show and the preview need no Pillow.

How the picture is turned into four flat colours (no dithering):

  1. The window of the source that maps onto the 160 x 176 pixel area is cut out. Mode E pixels are wider than a
     scan line is tall (PIXEL_ASPECT, default 1.5: a 160 pixel wide picture is 4:3-ish on a TV), so the 700 x 538 source
     keeps its proportions when its window is 700 x 513 (a few rows are cropped; --top says how many from the top).
  2. Every source pixel is assigned to the nearest of four reference colours in CIE Lab: background pink, light
     pink (face, nose, 'EST. 1961'), white (eyes, bubble outlines) and navy (title, pupils, grin). The grain of the
     print ends up as specks of the wrong class.
  3. The specks are removed: every connected patch of fewer than SPECK pixels takes the class around it. This is
     done on the SHAPES first (background / pale = light pink or white / navy), so that the broken, grainy outlines
     of the bubbles stay one piece, and afterwards for light pink against white inside the pale areas.
  4. The shapes are shrunk onto 160 x 176 by counting, per target pixel, how much of each falls in it. The pale
     features (outlines, lettering) get a bonus so that they survive as 1-2 pixel lines. A pale pixel is white
     when most of the pale source pixels in it are white, else light pink.
  5. A last pass on the finished bitmap removes isolated pixels and fills one-pixel holes.

The pixel values of the bitmap are those of ANTIC mode E: 0 = background (COLBK, splash_bg), 1 = light pink
(COLPF0, splash_light), 2 = navy (COLPF1, splash_navy), 3 = white (COLPF2, splash_white); see assets/palette.txt.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_assets as ba  # noqa: E402
from render_level import atari_rgb, write_png  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
W, H = ba.SPLASH_W, ba.SPLASH_H
PIXEL_ASPECT = 1.5  # how much wider a mode E pixel is than a scan line is tall on the screen

# source classes: reference colours of the picture (RGB), measured from the print (face and nose are the same pink)
BG, LIGHT, WHITE, NAVY = range(4)
REFERENCE = {BG: (230, 140, 161), LIGHT: (250, 208, 218), WHITE: (253, 248, 246), NAVY: (6, 48, 87)}
# bitmap value of each class (0 background, 1 light pink, 2 navy, 3 white)
VALUE = {BG: 0, LIGHT: 1, WHITE: 3, NAVY: 2}
PALE = 4  # light pink or white: the shape class used first
# when shrinking, a shape wins with (share of the target pixel) * WEIGHT: the thin pale features get a bonus
WEIGHT = {BG: 0.8, PALE: 1.35, NAVY: 1.0}
SPECK = 40  # source patches smaller than this many pixels are print grain
SPECK_TONE = 150  # ... and light pink / white patches inside the pale areas


def lab(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    def lin(v: float) -> float:
        v /= 255
        return ((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92

    r, g, b = (lin(v) for v in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def classify(pixels: list[tuple[int, int, int]]) -> list[int]:
    """The nearest reference colour (in Lab) of every pixel."""
    ref = {k: lab(v) for k, v in REFERENCE.items()}
    cache: dict[tuple[int, int, int], int] = {}
    out = []
    for p in pixels:
        c = cache.get(p)
        if c is None:
            lp = lab(p)
            c = min(ref, key=lambda k: math.dist(lp, ref[k]))
            cache[p] = c
        out.append(c)
    return out


def remove_specks(cls: list[int], w: int, h: int, limit: int, diagonal: bool = False, only: tuple[int, ...] | None = None) -> list[int]:
    """Give every connected patch of fewer than `limit` pixels the class that surrounds it most (among `only`)."""
    cls = cls[:]
    seen = bytearray(w * h)
    steps = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    if diagonal:
        steps += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
    for start in range(w * h):
        if seen[start]:
            continue
        c = cls[start]
        patch = [start]
        seen[start] = 1
        i = 0
        while i < len(patch):
            p = patch[i]
            i += 1
            x, y = p % w, p // w
            for dx, dy in steps:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h:
                    q = ny * w + nx
                    if not seen[q] and cls[q] == c:
                        seen[q] = 1
                        patch.append(q)
        if len(patch) >= limit:
            continue
        around: dict[int, int] = {}
        for p in patch:
            x, y = p % w, p // w
            for dx, dy in steps:
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and cls[ny * w + nx] != c and (only is None or cls[ny * w + nx] in only):
                    k = cls[ny * w + nx]
                    around[k] = around.get(k, 0) + 1
        if around:
            new = max(around, key=lambda k: around[k])
            for p in patch:
                cls[p] = new
    return cls


def embolden(shape: list[int], w: int, h: int, max_area: int = 700) -> list[int]:
    """Make the small pale shapes (the lettering of 'EST. 1961', the little bubbles) one pixel wider on each side, so
    that their thin strokes survive the shrinking as whole pixels. Big shapes (the face, the large bubbles) are left."""
    out = shape[:]
    seen = bytearray(w * h)
    for start in range(w * h):
        if seen[start] or shape[start] != PALE:
            continue
        patch = [start]
        seen[start] = 1
        i = 0
        while i < len(patch) and len(patch) <= max_area:
            p = patch[i]
            i += 1
            x, y = p % w, p // w
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < w and 0 <= ny < h:
                    q = ny * w + nx
                    if not seen[q] and shape[q] == PALE:
                        seen[q] = 1
                        patch.append(q)
        if len(patch) > max_area:  # a big shape: finish marking it, but leave it alone
            while i < len(patch):
                p = patch[i]
                i += 1
                x, y = p % w, p // w
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    if 0 <= nx < w and 0 <= ny < h:
                        q = ny * w + nx
                        if not seen[q] and shape[q] == PALE:
                            seen[q] = 1
                            patch.append(q)
            continue
        for p in patch:
            x, y = p % w, p // w
            for nx in (x - 1, x + 1):
                if 0 <= nx < w and shape[y * w + nx] == BG:
                    out[y * w + nx] = PALE
    return out


def shrink(shape: list[int], tone: list[int], sw: int, sh: int) -> list[list[int]]:
    """The shape map (BG / PALE / NAVY) and the tone map (LIGHT or WHITE) onto W x H bitmap values."""
    rows = []
    for ty in range(H):
        y0, y1 = int(ty * sh / H), max(int(ty * sh / H) + 1, int((ty + 1) * sh / H))
        row = []
        for tx in range(W):
            x0, x1 = int(tx * sw / W), max(int(tx * sw / W) + 1, int((tx + 1) * sw / W))
            count = {BG: 0, PALE: 0, NAVY: 0}
            white = 0
            for y in range(y0, y1):
                base = y * sw
                for x in range(x0, x1):
                    k = shape[base + x]
                    count[k] += 1
                    if k == PALE and tone[base + x] == WHITE:
                        white += 1
            best = max(count, key=lambda k: count[k] * WEIGHT[k])
            if best == PALE:
                row.append(3 if white * 2 >= count[PALE] else 1)
            else:
                row.append(0 if best == BG else 2)
        rows.append(row)
    return rows


def tidy(bitmap: list[list[int]]) -> list[list[int]]:
    """Remove isolated pixels and fill one pixel holes: a pixel whose 8 neighbours (4 for the corners) all agree on
    another value takes it, and patches of one or two pixels of 'light' or 'white' lines are kept only when they
    touch a line (8-connected)."""
    flat = [v for row in bitmap for v in row]
    flat = remove_specks(flat, W, H, 3, diagonal=True)
    out = flat[:]
    for y in range(H):
        for x in range(W):
            v = flat[y * W + x]
            around = [flat[(y + dy) * W + x + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                      if (dx or dy) and 0 <= x + dx < W and 0 <= y + dy < H]
            same = sum(1 for a in around if a == v)
            if same <= 1:
                counts = {a: around.count(a) for a in set(around)}
                out[y * W + x] = max(counts, key=lambda k: counts[k])
    return [out[y * W : (y + 1) * W] for y in range(H)]


def convert(source: Path, top: int, pixel_aspect: float) -> list[list[int]]:
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("make_splash: converting a picture needs Pillow (pip install pillow); --show does not")
    img = Image.open(source).convert("RGB")
    sw = img.width
    sh = round(sw * H / (W * pixel_aspect))  # source rows that map onto the H lines
    sh = min(sh, img.height)
    top = min(top, img.height - sh)
    img = img.crop((0, top, sw, top + sh))
    raw = img.tobytes()
    cls = classify([(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)])
    shape = [PALE if c in (LIGHT, WHITE) else c for c in cls]
    shape = remove_specks(shape, sw, sh, SPECK)
    shape = remove_specks(shape, sw, sh, SPECK)
    shape = embolden(shape, sw, sh)
    # the tone of the pale pixels: light pink or white, with the patches of grain taken out
    tone = [c if c in (LIGHT, WHITE) else LIGHT for c in cls]
    tone = remove_specks(tone, sw, sh, SPECK_TONE)
    return tidy(shrink(shape, tone, sw, sh))


HEADER = """\
# Title splash picture: {w} x {h} pixels, ANTIC mode E (4 colours, no dithering). One character per pixel:
#   0 = background pink   (COLBK,  splash_bg    in assets/palette.txt)
#   1 = light pink        (COLPF0, splash_light)
#   2 = navy              (COLPF1, splash_navy)
#   3 = white             (COLPF2, splash_white)
# Rows are {h} lines of {w} characters; lines that start with '#' are comments. Edit by hand if you like: tools/build_assets.py
# validates the size and the characters. Made from assets/splash-source.webp by tools/make_splash.py; draw a preview with
#   python3 tools/make_splash.py --show assets/splash.txt /tmp/splash.png
"""


def write_text(path: Path, bitmap: list[list[int]]) -> None:
    path.write_text(HEADER.format(w=W, h=H) + "\n".join("".join(map(str, r)) for r in bitmap) + "\n", encoding="utf-8")


def read_bitmap(path: Path) -> list[list[int]]:
    return ba.parse_splash(path)


def colours(pal: dict) -> list[tuple[int, int, int]]:
    return [atari_rgb(pal[k]) for k in ("splash_bg", "splash_light", "splash_navy", "splash_white")]


def preview_rows(bitmap: list[list[int]], rgb: list[tuple[int, int, int]], sx: int = 3, sy: int = 2) -> tuple[int, int, list[bytes]]:
    """The bitmap as it appears on a TV: each pixel sx wide and sy tall (mode E pixels are 1.5 times as wide as a line is tall)."""
    rows = []
    for r in bitmap:
        line = b"".join(bytes(rgb[v]) * sx for v in r)
        rows += [line] * sy
    return W * sx, H * sy, rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("source", nargs="?", help="the picture to convert")
    ap.add_argument("-o", "--output", default=str(ROOT / "assets" / "splash.txt"))
    ap.add_argument("--top", type=int, default=6, help="source rows to cut from the top (default 6)")
    ap.add_argument("--pixel-aspect", type=float, default=PIXEL_ASPECT, help="screen width of a pixel / height of a line")
    ap.add_argument("--preview", help="also write a PNG of the result (palette colours, 3x2 upscale)")
    ap.add_argument("--compare", help="also write the source and the result side by side")
    ap.add_argument("--show", nargs=2, metavar=("SPLASH_TXT", "PNG"), help="draw an existing splash.txt and stop")
    args = ap.parse_args(argv)
    pal = ba.parse_palette(ROOT / "assets" / "palette.txt")
    rgb = colours(pal)
    try:
        if args.show:
            bitmap = read_bitmap(Path(args.show[0]))
            w, h, rows = preview_rows(bitmap, rgb)
            write_png(Path(args.show[1]), w, h, rows)
            print(f"{args.show[1]}: {w}x{h}")
            return 0
        if not args.source:
            ap.error("give the picture to convert (or use --show)")
        bitmap = convert(Path(args.source), args.top, args.pixel_aspect)
    except ba.AssetError as exc:
        print(f"make_splash: {exc}", file=sys.stderr)
        return 1
    write_text(Path(args.output), bitmap)
    print(f"{args.output}: {W}x{H}")
    w, h, rows = preview_rows(bitmap, rgb)
    if args.preview:
        write_png(Path(args.preview), w, h, rows)
    if args.compare:
        from PIL import Image

        src = Image.open(args.source).convert("RGB").resize((w, h))
        out = Image.new("RGB", (w * 2 + 10, h), (40, 40, 40))
        out.paste(src, (0, 0))
        out.paste(Image.frombytes("RGB", (w, h), b"".join(rows)), (w + 10, 0))
        out.save(args.compare)
    return 0


if __name__ == "__main__":
    sys.exit(main())
