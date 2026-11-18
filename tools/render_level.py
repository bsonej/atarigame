#!/usr/bin/env python3
"""Draw a level as a PNG the way the game's tile art looks (with end caps), for a quick look.

    python3 tools/render_level.py assets/levels/level4.txt out.png [--scale 6]

The colours are a rough stand-in for the Atari palette (an approximation: a real TV or emulator differs). Each row
of tiles has its own hue, as in the game (assets/palette.txt, and the display-list interrupt in src/main.s).
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_assets as ba  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# degrees of hue on a colour wheel for Atari hue numbers 1-15 (0 is grey); the web editor uses the same table
HUE_DEG = [0, 45, 28, 12, 350, 325, 295, 265, 235, 215, 192, 170, 135, 95, 70, 45]
PLAYER = (0xF8, 0xE0, 0x30)
PEG = (0xE0, 0x30, 0x30)


def atari_rgb(byte: int) -> tuple[int, int, int]:
    """An approximate RGB for an Atari colour byte (hue in the high nibble, luminance in the low one)."""
    import colorsys

    hue, lum = byte >> 4, byte & 0x0F
    light = 0.04 + 0.88 * lum / 15
    if hue == 0:
        r = g = b = light
    else:
        r, g, b = colorsys.hls_to_rgb(HUE_DEG[hue] / 360.0, light, 0.7)
    return round(r * 255), round(g * 255), round(b * 255)


def row_colours(pal: dict, level_index: int, row: int) -> dict[int, tuple[int, int, int]]:
    """Pixel value -> RGB for tile row `row` (0 = the score row), with value 4 standing for an alt tile's value 3."""
    hue = pal["hud"] if row == 0 else pal["hues"][(row + level_index) % 8]
    return {0: atari_rgb(pal["background"]), 1: atari_rgb(hue), 2: atari_rgb(pal["grey"]), 3: atari_rgb(pal["white"]),
            4: atari_rgb(pal["ice"])}


def write_png(path: Path, width: int, height: int, rows: list[bytes]) -> None:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    raw = b"".join(b"\x00" + r for r in rows)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def render(level: Path, out: Path, scale: int = 6, root: Path = ROOT, level_index: int | None = None) -> None:
    tiles = ba.parse_tiles(root / "assets" / "tiles.txt")
    pal = ba.parse_palette(root / "assets" / "palette.txt")
    chars = {t["char"]: t["byte"] for t in tiles if t["char"] is not None}
    solid = {t["byte"] for t in tiles if t["solid"]}
    lv = ba.parse_level(level, chars, solid, ba.cap_families(tiles), dots=ba.dot_families(tiles), door=ba.door_bytes(tiles))
    if level_index is None:  # its place among the shipped levels
        names = sorted((root / "assets" / "levels").glob("*.txt"), key=ba.natural_key)
        level_index = next((i for i, n in enumerate(names) if n.stem == level.stem), 0)
    by_byte = {t["byte"]: t for t in tiles}
    w, h = ba.COLS * ba.TILE_W, ba.ROWS * ba.TILE_H
    pix = [[(0, 0, 0)] * w for _ in range(h)]
    for i, b in enumerate(lv["data"][: ba.COLS * ba.ROWS]):
        t = by_byte.get(b)
        if not t:
            continue
        x0, y0 = (i % ba.COLS) * ba.TILE_W, (i // ba.COLS) * ba.TILE_H
        pal_row = row_colours(pal, level_index, i // ba.COLS)
        for y, row in enumerate(t["rows"]):
            for x, ch in enumerate(row):
                v = int(ch)
                pix[y0 + y][x0 + x] = pal_row[4 if (v == 3 and b & 0x80) else v]
    sx, sy = lv["spawn"][0] * ba.TILE_W, lv["spawn"][1] * ba.TILE_H
    for y in range(16):
        for x in range(4):
            pix[min(h - 1, sy + y)][min(w - 1, sx + x)] = PLAYER
    for x, y, *_ in lv["pegs"]:
        for yy in range(8):
            for xx in range(4):
                pix[y + yy][x + xx] = PEG
    rows = []
    for y in range(h):
        line = b"".join(bytes(c) * scale for c in pix[y])
        rows.extend([line] * scale)
    write_png(out, w * scale, h * scale, rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("level", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--scale", type=int, default=6)
    a = ap.parse_args()
    render(a.level, a.out, a.scale)
    return 0


if __name__ == "__main__":
    sys.exit(main())
