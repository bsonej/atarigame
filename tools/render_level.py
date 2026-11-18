#!/usr/bin/env python3
"""Draw a level as a PNG the way the game's tile art looks (with end caps), for a quick look.

    python3 tools/render_level.py assets/levels/level4.txt out.png [--scale 6]

The colours are rough stand-ins for the Atari palette values in game_colors (src/main.s).
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
PALETTE = {0: (0, 0, 0), 1: (0xE8, 0x8A, 0x28), 2: (0x9C, 0x5A, 0x20), 3: (0xF0, 0xF0, 0xF0)}
ALT3 = (0x40, 0xD0, 0xF0)
PLAYER = (0xF8, 0xE0, 0x30)
PEG = (0xE0, 0x30, 0x30)


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


def render(level: Path, out: Path, scale: int = 6, root: Path = ROOT) -> None:
    tiles = ba.parse_tiles(root / "assets" / "tiles.txt")
    chars = {t["char"]: t["byte"] for t in tiles if t["char"] is not None}
    solid = {t["byte"] for t in tiles if t["solid"]}
    lv = ba.parse_level(level, chars, solid, ba.cap_families(tiles))
    by_byte = {t["byte"]: t for t in tiles}
    w, h = ba.COLS * ba.TILE_W, ba.ROWS * ba.TILE_H
    pix = [[(0, 0, 0)] * w for _ in range(h)]
    for i, b in enumerate(lv["data"][: ba.COLS * ba.ROWS]):
        t = by_byte.get(b)
        if not t:
            continue
        x0, y0 = (i % ba.COLS) * ba.TILE_W, (i // ba.COLS) * ba.TILE_H
        for y, row in enumerate(t["rows"]):
            for x, ch in enumerate(row):
                v = int(ch)
                pix[y0 + y][x0 + x] = ALT3 if (v == 3 and b & 0x80) else PALETTE[v]
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
