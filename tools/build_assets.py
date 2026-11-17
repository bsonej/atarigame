#!/usr/bin/env python3
"""Turn the plain-text assets into ca65 include files in src/gen/.

    assets/tiles.txt         -> gen/tiles.inc    (T_<NAME> constants)  gen/charset.inc (1 KB character set)
                                gen/tileflags.inc (a 256-byte table: solid / one-way, indexed by map byte)
    assets/font.txt          -> merged into the character set; gen/font.inc (.charmap lines so that
                                .byte "TEXT" in the source produces glyph ids)
    assets/sprites.txt       -> gen/sprites.inc  (player frames)
    assets/levels/*.txt      -> gen/levels.inc   (tile maps, start positions, item counts, pegs, level tables)
    assets/screens/*.txt     -> gen/screens.inc  (full-screen maps such as the title: screen_<name>)

Usage: build_assets.py [--out src/gen]   (run from the project root)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

COLS, ROWS = 40, 24
LEVEL_BYTES = 1024  # 960 tiles padded so the loader can copy whole pages
TILE_W, TILE_H = 4, 8
SPRITE_W, SPRITE_H = 4, 16
FONT_W, FONT_H = 3, 5
# Which of the 8 lines of a tile each font row is drawn on (None = blank): one blank line on top, then
# rows 0, 2 and 4 repeated so the 3x5 glyph fills an 8-line cell with roughly square-looking pixels.
FONT_LINES = [None, 0, 0, 1, 2, 2, 3, 4]
GLYPHS = 128  # ANTIC mode 4 uses a 128-glyph, 1 KB character set
F_SOLID, F_ONEWAY = 1, 2
MAX_PEGS = 2


class AssetError(Exception):
    pass


def _bytes_block(values: list[int], per_line: int = 16) -> str:
    rows = []
    for i in range(0, len(values), per_line):
        rows.append("        .byte " + ",".join(f"${v:02X}" for v in values[i : i + per_line]))
    return "\n".join(rows)


def _is_comment(line: str) -> bool:
    """Comments are '# ' (hash and a space) or a lone '#': map and pixel rows never contain a space."""
    text = line.strip()
    return text == "#" or text.startswith("# ") or text.startswith("#!")


# ---------------------------------------------------------------- tiles


def parse_tiles(path: Path) -> list[dict]:
    tiles: list[dict] = []
    cur: dict | None = None
    for n, text in (
        (n, t) for n, t in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) if t.strip() and not t.strip().startswith("#")
    ):
        text = text.strip()
        if text.startswith("tile "):
            parts = text.split()
            if len(parts) < 4:
                raise AssetError(f"{path}:{n}: expected 'tile <id> <NAME> <char> [solid] [oneway] [alt]'")
            flags = parts[4:]
            for f in flags:
                if f not in ("solid", "oneway", "alt"):
                    raise AssetError(f"{path}:{n}: unknown tile flag {f!r} (use solid, oneway, alt)")
            if "solid" in flags and "oneway" in flags:
                raise AssetError(f"{path}:{n}: a tile cannot be both solid and oneway")
            try:
                tid = int(parts[1])
            except ValueError:
                raise AssetError(f"{path}:{n}: tile id must be a number")
            if not 0 <= tid < GLYPHS:
                raise AssetError(f"{path}:{n}: tile id {tid} must be 0-{GLYPHS - 1}")
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", parts[2]):
                raise AssetError(f"{path}:{n}: name {parts[2]!r} must be UPPER_CASE")
            char = None if parts[3] == "none" else parts[3]
            if char is not None and (len(char) != 1 or char in "@ p"):
                raise AssetError(f"{path}:{n}: map character must be one visible character other than '@' and 'p' (or 'none')")
            if any(t["id"] == tid for t in tiles):
                raise AssetError(f"{path}:{n}: duplicate tile id {tid}")
            if char is not None and any(t["char"] == char for t in tiles):
                raise AssetError(f"{path}:{n}: duplicate map character {char!r}")
            cur = {
                "id": tid,
                "byte": tid | 0x80 if "alt" in flags else tid,  # what the map holds
                "name": parts[2],
                "char": char,
                "solid": "solid" in flags,
                "oneway": "oneway" in flags,
                "rows": [],
            }
            tiles.append(cur)
        else:
            if cur is None:
                raise AssetError(f"{path}:{n}: pixel row before any 'tile' line")
            if not re.fullmatch(rf"[0-3]{{{TILE_W}}}", text):
                raise AssetError(f"{path}:{n}: tile rows are {TILE_W} digits 0-3, got {text!r}")
            cur["rows"].append(text)
            if len(cur["rows"]) > TILE_H:
                raise AssetError(f"{path}:{n}: tile {cur['name']} has more than {TILE_H} rows")
    for t in tiles:
        if len(t["rows"]) != TILE_H:
            raise AssetError(f"{path}: tile {t['name']} has {len(t['rows'])} rows, needs {TILE_H}")
    if not any(t["id"] == 0 for t in tiles):
        raise AssetError(f"{path}: tile 0 (the empty tile) is required")
    return tiles


# ----------------------------------------------------------------- font


def parse_font(path: Path) -> list[dict]:
    """Glyphs as {'char', 'id', 'rows'}; digits get ids 16-25, A-Z 32-57, the rest follow from 58."""
    glyphs: list[dict] = []
    cur: dict | None = None
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = raw.strip()
        if not text or _is_comment(raw):
            continue
        if text.startswith("glyph "):
            ch = raw.split(None, 1)[1].strip()
            if len(ch) != 1 or ch == " ":
                raise AssetError(f"{path}:{n}: 'glyph' needs one visible character, got {ch!r}")
            if ch.islower():
                raise AssetError(f"{path}:{n}: glyph {ch!r}: use uppercase letters (lowercase is the second colour)")
            if any(g["char"] == ch for g in glyphs):
                raise AssetError(f"{path}:{n}: duplicate glyph {ch!r}")
            cur = {"char": ch, "rows": []}
            glyphs.append(cur)
            continue
        if cur is None:
            raise AssetError(f"{path}:{n}: pixel row before any 'glyph' line")
        if not re.fullmatch(rf"[#.]{{{FONT_W}}}", text):
            raise AssetError(f"{path}:{n}: font rows are {FONT_W} characters of '#' and '.', got {text!r}")
        cur["rows"].append(text)
        if len(cur["rows"]) > FONT_H:
            raise AssetError(f"{path}:{n}: glyph {cur['char']!r} has more than {FONT_H} rows")
    for g in glyphs:
        if len(g["rows"]) != FONT_H:
            raise AssetError(f"{path}: glyph {g['char']!r} has {len(g['rows'])} rows, needs {FONT_H}")
    nxt = 58
    for g in glyphs:
        c = g["char"]
        if c.isdigit():
            g["id"] = 16 + int(c)
        elif "A" <= c <= "Z":
            g["id"] = 32 + ord(c) - 65
        else:
            g["id"] = nxt
            nxt += 1
        if g["id"] >= GLYPHS:
            raise AssetError(f"{path}: too many glyphs (no room for {c!r})")
    return glyphs


def font_charmap(glyphs: list[dict]) -> dict[str, int]:
    """Character -> screen byte. Lowercase letters give the same glyph with bit 7 set (COLOR3 for pixel value 3)."""
    cmap = {" ": 0}
    for g in glyphs:
        cmap[g["char"]] = g["id"]
        if g["char"].isalpha():
            cmap[g["char"].lower()] = g["id"] | 0x80
    return cmap


def render_tile_flags(tiles: list[dict]) -> str:
    """tile_flags[map byte]: bit 0 solid, bit 1 one-way. Indexed by the byte stored on the screen."""
    table = [0] * 256
    for t in tiles:
        table[t["byte"]] = (F_SOLID if t["solid"] else 0) | (F_ONEWAY if t["oneway"] else 0)
    return "; Generated by tools/build_assets.py - do not edit.\ntile_flags:\n" + _bytes_block(table) + "\n"


def render_font_include(glyphs: list[dict]) -> str:
    cmap = font_charmap(glyphs)
    out = [
        "; Generated by tools/build_assets.py - do not edit.",
        "; After this, .byte \"TEXT\" produces glyph ids (lowercase = second colour, $FF is never a glyph).",
    ]
    for ch, val in cmap.items():
        out.append(f"        .charmap {ord(ch)}, {val}")
    return "\n".join(out) + "\n"


# ----------------------------------------------------- tiles + font -> charset


def render_tiles(tiles: list[dict], font: list[dict] | None = None) -> tuple[str, str]:
    font = font or []
    consts = ["; Generated by tools/build_assets.py - do not edit."]
    for t in sorted(tiles, key=lambda t: t["byte"]):
        consts.append(f"T_{t['name']:<12} = {t['byte']}")
    glyphs = [[0] * TILE_H for _ in range(GLYPHS)]
    used = {}
    for t in tiles:
        used[t["id"]] = f"tile {t['name']}"
        for y, row in enumerate(t["rows"]):
            p = [int(c) for c in row]
            glyphs[t["id"]][y] = (p[0] << 6) | (p[1] << 4) | (p[2] << 2) | p[3]
    for g in font:
        if g["id"] in used:
            raise AssetError(f"font glyph {g['char']!r} (id {g['id']}) collides with {used[g['id']]}")
        used[g["id"]] = f"glyph {g['char']!r}"
        for line, src in enumerate(FONT_LINES):
            if src is None:
                continue
            bits = 0
            for x, ch in enumerate(g["rows"][src]):
                if ch == "#":
                    bits |= 3 << (6 - 2 * x)
            glyphs[g["id"]][line] = bits
        if g["char"] == "0":
            consts.append(f"T_{'DIGIT0':<12} = {g['id']}")
    flat = [b for g in glyphs for b in g]
    charset = ["; Generated by tools/build_assets.py - do not edit.", '        .segment "CHARSET"', _bytes_block(flat, 8)]
    return "\n".join(consts) + "\n", "\n".join(charset) + "\n"


# -------------------------------------------------------------- sprites


def parse_sprites(path: Path) -> list[tuple[str, list[int]]]:
    frames: list[tuple[str, list[int]]] = []
    name, rows = None, []

    def close(lineno: int) -> None:
        if name is None:
            return
        if len(rows) != SPRITE_H:
            raise AssetError(f"{path}:{lineno}: frame {name} has {len(rows)} rows, needs {SPRITE_H}")
        frames.append((name, rows[:]))

    last = 0
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = raw.strip()
        last = n
        if not text or _is_comment(raw):
            continue
        if text.startswith("frame "):
            close(n)
            name, rows = text.split(None, 1)[1], []
            continue
        if not re.fullmatch(rf"[#.]{{{SPRITE_W}}}", text):
            raise AssetError(f"{path}:{n}: sprite rows are {SPRITE_W} characters of '#' and '.', got {text!r}")
        if name is None:
            raise AssetError(f"{path}:{n}: sprite row before any 'frame' line")
        rows.append(sum(0x80 >> i for i, c in enumerate(text) if c == "#"))
    close(last)
    if not frames:
        raise AssetError(f"{path}: no frames")
    return frames


def render_sprites(frames: list[tuple[str, list[int]]]) -> str:
    out = ["; Generated by tools/build_assets.py - do not edit.", f"SPR_COUNT = {len(frames)}", "spr_frames:"]
    for name, rows in frames:
        out.append(f"        ; {name}")
        out.append(_bytes_block(rows, SPRITE_H))
    return "\n".join(out) + "\n"


# --------------------------------------------------------------- levels


def parse_level(path: Path, tile_chars: dict[str, int], solid_bytes: set[int] | None = None) -> dict:
    solid_bytes = solid_bytes if solid_bytes is not None else {1}
    grid = [line.rstrip("\n") for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not _is_comment(line)]
    # Lines starting with '#' are map rows (walls); header comments start with '# '.
    if len(grid) != ROWS:
        raise AssetError(f"{path}: has {len(grid)} map rows, needs {ROWS}")
    data, spawn, items, peg_marks = [], None, 0, []
    for r, line in enumerate(grid):
        if len(line) != COLS:
            raise AssetError(f"{path}: row {r} is {len(line)} wide, needs {COLS}")
        for c, ch in enumerate(line):
            if ch == "@":
                if spawn is not None:
                    raise AssetError(f"{path}: more than one '@' start (second at row {r}, column {c})")
                spawn = (c, r)
                data.append(0)
                continue
            if ch == "p":
                peg_marks.append((c, r))
                data.append(0)
                continue
            if ch not in tile_chars:
                raise AssetError(f"{path}: unknown character {ch!r} at row {r}, column {c}")
            data.append(tile_chars[ch])
    if spawn is None:
        raise AssetError(f"{path}: no '@' player start")
    items = sum(1 for b in data if b == tile_chars.get("*", -1))
    if items == 0:
        raise AssetError(f"{path}: no items ('*') to collect")
    if items > 99:
        raise AssetError(f"{path}: too many items (the display shows two digits)")
    pegs = [peg_for(path, data, c, r, solid_bytes) for c, r in peg_marks]
    if len(pegs) > MAX_PEGS:
        raise AssetError(f"{path}: {len(pegs)} pegs, at most {MAX_PEGS} per level")
    data += [0] * (LEVEL_BYTES - len(data))
    return {"name": path.stem, "data": data, "spawn": spawn, "items": items, "pegs": pegs}


def peg_for(path: Path, data: list[int], c: int, r: int, solid: set[int]) -> tuple[int, int, int, int, int]:
    """A peg ('p') sits on a platform and sweeps along the solid blocks under it.

    Returns (x, y, min x, max x, direction) in pixels: it starts at the end of the block nearer the
    marker and moves towards the other end (direction +1 right, 255 left).
    """
    if r + 1 >= ROWS or data[(r + 1) * COLS + c] not in solid:
        raise AssetError(f"{path}: peg at row {r}, column {c} needs a solid block under it")

    def free(col: int) -> bool:  # the platform continues, and the peg has room above it
        return 0 <= col < COLS and data[(r + 1) * COLS + col] in solid and data[r * COLS + col] not in solid

    lo = hi = c
    while free(lo - 1):
        lo -= 1
    while free(hi + 1):
        hi += 1
    if lo == hi:
        raise AssetError(f"{path}: peg at row {r}, column {c} has a platform only one tile wide")
    if c - lo <= hi - c:
        return lo * 4, r * 8, lo * 4, hi * 4, 1
    return hi * 4, r * 8, lo * 4, hi * 4, 255


def render_levels(levels: list[dict]) -> str:
    out = ["; Generated by tools/build_assets.py - do not edit."]
    for lv in levels:
        n = lv["name"]
        out += [
            f"{n}:",
            _bytes_block(lv["data"]),
            f"{n}_spawn:",
            f"        .byte {lv['spawn'][0]},{lv['spawn'][1]}",
            f"{n.upper()}_ITEMS = {lv['items']}",
            f"{n}_pegs:",
            f"        .byte {len(lv['pegs'])}" + "".join(f",{x},{y},{lo},{hi},{d}" for x, y, lo, hi, d in lv["pegs"]),
        ]
    names = [lv["name"] for lv in levels]
    out += [
        f"LEVEL_COUNT = {len(levels)}",
        "level_lo:    .byte " + ",".join(f"<{n}" for n in names),
        "level_hi:    .byte " + ",".join(f">{n}" for n in names),
        "level_items: .byte " + ",".join(f"{n.upper()}_ITEMS" for n in names),
        "level_pg_lo: .byte " + ",".join(f"<{n}_pegs" for n in names),
        "level_pg_hi: .byte " + ",".join(f">{n}_pegs" for n in names),
        "level_sx:    .byte " + ",".join(str(lv["spawn"][0] * 4) for lv in levels),  # start px
        "level_sy:    .byte " + ",".join(str(lv["spawn"][1] * 8) for lv in levels),  # start py
    ]
    return "\n".join(out) + "\n"


def natural_key(p: Path) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", p.stem)]


# -------------------------------------------------------------- screens


def parse_screen(path: Path, charmap: dict[str, int], tile_chars: dict[str, int]) -> list[int]:
    """A full 40x24 text screen. Font characters win over tile characters (so H is a letter, not a ladder)."""
    # Rows may start with '# ' (a brick followed by a space), so only '#!' lines are comments here.
    rows = [line.rstrip("\n") for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("#!")]
    if len(rows) > ROWS:
        raise AssetError(f"{path}: has {len(rows)} rows, at most {ROWS}")
    rows += [""] * (ROWS - len(rows))
    data = []
    for r, line in enumerate(rows):
        if len(line) > COLS:
            raise AssetError(f"{path}: row {r} is {len(line)} wide, at most {COLS}")
        for c, ch in enumerate(line.ljust(COLS)):
            if ch in charmap:
                data.append(charmap[ch])
            elif ch in tile_chars:
                data.append(tile_chars[ch])
            else:
                raise AssetError(f"{path}: unknown character {ch!r} at row {r}, column {c}")
    return data + [0] * (LEVEL_BYTES - len(data))


def render_screens(screens: list[tuple[str, list[int]]]) -> str:
    out = ["; Generated by tools/build_assets.py - do not edit."]
    for name, data in screens:
        out += [f"screen_{name}:", _bytes_block(data)]
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------- main


def build(root: Path, out: Path) -> None:
    assets = root / "assets"
    tiles = parse_tiles(assets / "tiles.txt")
    font = parse_font(assets / "font.txt") if (assets / "font.txt").exists() else []
    consts, charset = render_tiles(tiles, font)
    frames = parse_sprites(assets / "sprites.txt")
    chars = {t["char"]: t["byte"] for t in tiles if t["char"] is not None}
    solid_bytes = {t["byte"] for t in tiles if t["solid"]}
    paths = sorted((assets / "levels").glob("*.txt"), key=natural_key)
    if not paths:
        raise AssetError("no levels in assets/levels/")
    levels = [parse_level(p, chars, solid_bytes) for p in paths]
    cmap = font_charmap(font)
    screens = [(p.stem, parse_screen(p, cmap, chars)) for p in sorted((assets / "screens").glob("*.txt"))]
    out.mkdir(parents=True, exist_ok=True)
    (out / "tiles.inc").write_text(consts)
    (out / "charset.inc").write_text(charset)
    (out / "tileflags.inc").write_text(render_tile_flags(tiles))
    (out / "font.inc").write_text(render_font_include(font))
    (out / "sprites.inc").write_text(render_sprites(frames))
    (out / "levels.inc").write_text(render_levels(levels))
    (out / "screens.inc").write_text(render_screens(screens))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".", help="project root (default: current directory)")
    ap.add_argument("--out", default="src/gen", help="output directory (default: src/gen)")
    args = ap.parse_args(argv)
    root = Path(args.root)
    try:
        build(root, root / args.out if not Path(args.out).is_absolute() else Path(args.out))
    except AssetError as exc:
        print(f"asset error: {exc}", file=sys.stderr)
        return 1
    print(f"assets built into {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
