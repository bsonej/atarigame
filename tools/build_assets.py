#!/usr/bin/env python3
"""Turn the plain-text assets into ca65 include files in src/gen/.

    assets/tiles.txt         -> gen/tiles.inc    (T_<NAME> constants)  gen/charset.inc (1 KB character set)
                                gen/tileflags.inc (256-byte tables indexed by map byte: tile_flags = solid / one-way,
                                tile_canon = the plain tile a platform end cap, dotted tile or twin stands for)
                                gen/helix.inc (the chutes' thread, which the game scrolls)
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
SPRITE_W, SPRITE_H = 8, 16
FONT_W, FONT_H = 3, 5
# Which of the 8 lines of a tile each font row is drawn on (None = blank): one blank line on top, then
# rows 0, 2 and 4 repeated so the 3x5 glyph fills an 8-line cell with roughly square-looking pixels.
FONT_LINES = [None, 0, 0, 1, 2, 2, 3, 4]
GLYPHS = 128  # ANTIC mode 4 uses a 128-glyph, 1 KB character set
F_SOLID, F_ONEWAY, F_DOT = 1, 2, 4
MAX_PEGS = 2
MAX_COLLECT = 250  # items + dots: the game counts them in one byte


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
        elif text.startswith("cap "):
            cur = parse_cap(path, n, text, tiles)
            tiles.append(cur)
        elif text.startswith("dot "):
            cur = parse_dot(path, n, text, tiles)
            tiles.append(cur)
        elif text.startswith("twin "):
            cur = parse_twin(path, n, text, tiles)
            tiles.append(cur)
        else:
            if cur is None:
                raise AssetError(f"{path}:{n}: pixel row before any 'tile' line")
            if not re.fullmatch(rf"[0-3]{{{TILE_W}}}", text):
                raise AssetError(f"{path}:{n}: tile rows are {TILE_W} digits 0-3, got {text!r}")
            cur["rows"].append(text)
            cur["auto"] = None  # (only caps have this; art that is typed in is used as written)
            if len(cur["rows"]) > TILE_H:
                raise AssetError(f"{path}:{n}: tile {cur['name']} has more than {TILE_H} rows")
    by_name = {t["name"]: t for t in tiles}
    for t in tiles:
        if t.get("auto") is not None:  # a cap with no art of its own: derive it from its family
            fam = by_name[t["family"]]
            if len(fam["rows"]) != TILE_H:
                raise AssetError(f"{path}: tile {fam['name']} has {len(fam['rows'])} rows, needs {TILE_H}")
            t["rows"] = auto_cap(fam["rows"], t["cap"], *t["auto"])
        if len(t["rows"]) != TILE_H:
            raise AssetError(f"{path}: tile {t['name']} has {len(t['rows'])} rows, needs {TILE_H}")
    if not any(t["id"] == 0 for t in tiles):
        raise AssetError(f"{path}: tile 0 (the empty tile) is required")
    return tiles


def parse_cap(path: Path, n: int, text: str, tiles: list[dict]) -> dict:
    """``cap <id> <FAMILY> <L|R|LR> [rows=a-b] [outline=n]``: the left end, right end, or both ends of a
    platform tile. The 8 rows of art follow; without them the cap is made from the family's art."""
    parts = text.split()
    if len(parts) < 4:
        raise AssetError(f"{path}:{n}: expected 'cap <id> <FAMILY> <L|R|LR> [rows=a-b] [outline=n]'")
    try:
        tid = int(parts[1])
    except ValueError:
        raise AssetError(f"{path}:{n}: tile id must be a number")
    if not 0 <= tid < GLYPHS:
        raise AssetError(f"{path}:{n}: tile id {tid} must be 0-{GLYPHS - 1}")
    if any(t["id"] == tid for t in tiles):
        raise AssetError(f"{path}:{n}: duplicate tile id {tid}")
    fam = next((t for t in tiles if t["name"] == parts[2] and not t.get("family")), None)
    if fam is None:
        raise AssetError(f"{path}:{n}: cap of unknown tile {parts[2]!r} (define the tile first)")
    if parts[3] not in ("L", "R", "LR"):
        raise AssetError(f"{path}:{n}: cap kind must be L, R or LR, got {parts[3]!r}")
    name = f"{fam['name']}_{parts[3]}"
    if any(t["name"] == name for t in tiles):
        raise AssetError(f"{path}:{n}: {name} is defined twice")
    lo, hi, outline = None, None, 3
    for opt in parts[4:]:
        m = re.fullmatch(r"rows=([0-7])-([0-7])", opt)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            if lo > hi:
                raise AssetError(f"{path}:{n}: rows={lo}-{hi} is backwards")
        elif re.fullmatch(r"outline=[0-3]", opt):
            outline = int(opt[-1])
        else:
            raise AssetError(f"{path}:{n}: unknown cap option {opt!r}")
    return {
        "id": tid,
        "byte": tid | 0x80 if fam["byte"] & 0x80 else tid,
        "name": name,
        "char": None,
        "solid": fam["solid"],
        "oneway": fam["oneway"],
        "rows": [],
        "family": fam["name"],
        "cap": parts[3],
        "auto": (lo, hi, outline),  # cleared if the art is given
    }


def parse_dot(path: Path, n: int, text: str, tiles: list[dict]) -> dict:
    """``dot <id> <FAMILY>``: the plain tile with a dot in it. The 8 rows of art follow."""
    parts = text.split()
    if len(parts) != 3:
        raise AssetError(f"{path}:{n}: expected 'dot <id> <FAMILY>'")
    try:
        tid = int(parts[1])
    except ValueError:
        raise AssetError(f"{path}:{n}: tile id must be a number")
    if not 0 <= tid < GLYPHS:
        raise AssetError(f"{path}:{n}: tile id {tid} must be 0-{GLYPHS - 1}")
    if any(t["id"] == tid for t in tiles):
        raise AssetError(f"{path}:{n}: duplicate tile id {tid}")
    fam = next((t for t in tiles if t["name"] == parts[2] and not t.get("family") and not t.get("dot_of")), None)
    if fam is None:
        raise AssetError(f"{path}:{n}: dot of unknown tile {parts[2]!r} (define the tile first)")
    name = f"{fam['name']}_DOT"
    if any(t["name"] == name for t in tiles):
        raise AssetError(f"{path}:{n}: {name} is defined twice")
    return {
        "id": tid,
        "byte": tid | 0x80 if fam["byte"] & 0x80 else tid,
        "name": name,
        "char": None,
        "solid": fam["solid"],
        "oneway": fam["oneway"],
        "rows": [],
        "dot_of": fam["name"],
    }


def parse_twin(path: Path, n: int, text: str, tiles: list[dict]) -> dict:
    """``twin <id> <FAMILY>``: the tile that goes on every odd screen row in place of the plain one, for art that is
    16 rows tall and so has to alternate from one tile of a stack to the next. The 8 rows of art follow."""
    parts = text.split()
    if len(parts) != 3:
        raise AssetError(f"{path}:{n}: expected 'twin <id> <FAMILY>'")
    try:
        tid = int(parts[1])
    except ValueError:
        raise AssetError(f"{path}:{n}: tile id must be a number")
    if not 0 <= tid < GLYPHS:
        raise AssetError(f"{path}:{n}: tile id {tid} must be 0-{GLYPHS - 1}")
    if any(t["id"] == tid for t in tiles):
        raise AssetError(f"{path}:{n}: duplicate tile id {tid}")
    fam = next((t for t in tiles if t["name"] == parts[2] and not t.get("family") and not t.get("dot_of") and not t.get("twin_of")), None)
    if fam is None:
        raise AssetError(f"{path}:{n}: twin of unknown tile {parts[2]!r} (define the tile first)")
    name = f"{fam['name']}_B"
    if any(t["name"] == name for t in tiles):
        raise AssetError(f"{path}:{n}: {name} is defined twice (a tile has one twin)")
    return {
        "id": tid,
        "byte": tid | 0x80 if fam["byte"] & 0x80 else tid,
        "name": name,
        "char": None,
        "solid": fam["solid"],
        "oneway": fam["oneway"],
        "rows": [],
        "twin_of": fam["name"],
    }


def auto_cap(rows: list[str], cap: str, lo: int | None, hi: int | None, outline: int) -> list[str]:
    """Round off the end(s) of a tile: the outermost pixel column becomes a solid ``outline`` edge, and the
    corners are cut. ``lo``..``hi`` is the range of rows to change (default: the rows that have any art)."""
    used = [y for y, r in enumerate(rows) if r != "0" * TILE_W]
    first, last = (used[0], used[-1]) if used else (0, TILE_H - 1)
    a = first if lo is None else lo
    b = last if hi is None else hi
    out = [list(r) for r in rows]
    for col in ([0] if "L" in cap else []) + ([TILE_W - 1] if "R" in cap else []):
        for y in range(a, b + 1):
            if y == b or (y == a and a == first):
                out[y][col] = "0"
            elif rows[y][col] != "0":
                out[y][col] = str(outline)
    return ["".join(r) for r in out]


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


def tile_tables(tiles: list[dict]) -> tuple[list[int], list[int]]:
    """(tile_flags, tile_canon), both indexed by the byte stored on the screen.

    tile_flags: bit 0 solid, bit 1 one-way, bit 2 a tile with a dot in it. tile_canon: the tile that byte stands
    for (a platform end cap or a dotted tile stands for its plain tile, every other byte for itself), so the
    game's rules never need to know about caps and dots."""
    flags = [0] * 256
    canon = list(range(256))
    for t in tiles:
        flags[t["byte"]] = (F_SOLID if t["solid"] else 0) | (F_ONEWAY if t["oneway"] else 0) | (F_DOT if t.get("dot_of") else 0)
    for fam_byte, caps in cap_families(tiles).items():
        for byte in caps.values():
            canon[byte] = fam_byte
    for fam_byte, dotted in dot_families(tiles).items():
        canon[dotted] = fam_byte
    for fam_byte, twin in twin_families(tiles).items():
        canon[twin] = fam_byte
    return flags, canon


def render_tile_flags(tiles: list[dict]) -> str:
    """The two tables of tile_tables() as an include file."""
    table, canon = tile_tables(tiles)
    return (
        "; Generated by tools/build_assets.py - do not edit.\ntile_flags:\n"
        + _bytes_block(table)
        + "\ntile_canon:\n"
        + _bytes_block(canon)
        + "\n"
    )


def cap_families(tiles: list[dict]) -> dict[int, dict[str, int]]:
    """{map byte of a plain tile: {'L': byte, 'R': byte, 'LR': byte}} for the tiles that have end caps."""
    by_name = {t["name"]: t for t in tiles if not t.get("family")}
    fams: dict[int, dict[str, int]] = {}
    for t in tiles:
        if t.get("family"):
            fams.setdefault(by_name[t["family"]]["byte"], {})[t["cap"]] = t["byte"]
    return fams


def dot_families(tiles: list[dict]) -> dict[int, int]:
    """{map byte of a plain tile: map byte of the same tile with a dot in it}."""
    by_name = {t["name"]: t for t in tiles}
    return {by_name[t["dot_of"]]["byte"]: t["byte"] for t in tiles if t.get("dot_of")}


def twin_families(tiles: list[dict]) -> dict[int, int]:
    """{map byte of a plain tile: map byte of its twin (the tile drawn on odd screen rows)}."""
    by_name = {t["name"]: t for t in tiles}
    return {by_name[t["twin_of"]]["byte"]: t["byte"] for t in tiles if t.get("twin_of")}


def apply_twins(data: list[int], twins: dict[int, int]) -> list[int]:
    """Swap the twin in for the plain tile on every odd screen row, so that a tile whose art is two tiles tall lines
    up with itself in a stack and along a diagonal run (each step of a diagonal is one row down)."""
    out = list(data)
    for i, b in enumerate(data):
        if (i // COLS) % 2 and b in twins:
            out[i] = twins[b]
    return out


def helix_rows(tiles: list[dict], name: str) -> list[int]:
    """The 16 rows (as screen bytes) of the thread of a chute tile: its own art, then its twin's, which the game
    scrolls down a stack of them (animate_chutes)."""
    by_name = {t["name"]: t for t in tiles}
    twin = by_name.get(f"{name}_B")
    if name not in by_name or twin is None or not twin.get("twin_of"):
        raise AssetError(f"the chute {name} needs a twin (a 'twin <id> {name}' entry in tiles.txt)")
    out = []
    for t in (by_name[name], twin):
        out += [sum(int(c) << (6 - 2 * x) for x, c in enumerate(row)) for row in t["rows"]]
    return out


def chute_frame(helix: list, tick: int, up: bool = False) -> tuple[list, list]:
    """The thread of a chute ``tick`` frames (50 Hz) into the game, as the game's animate_chutes draws it: every second
    frame it moves one row along the stack - down for a down chute (SLIDE_R), up for an up chute (``up``, SLIDE_L).
    Returns (the 8 rows of the plain tile, the 8 rows of its twin); ``helix`` is the 16 rows of the thread
    (helix_rows, or the rows as text). web/render.js has the same function."""
    ph = (tick >> 1) & 15
    if not up:
        ph ^= 15
    return [helix[(y + ph) & 15] for y in range(8)], [helix[(y + 8 + ph) & 15] for y in range(8)]


def render_helix(tiles: list[dict]) -> str:
    """helix_r / helix_l: the 16 rows of the down (SLIDE_R) and up (SLIDE_L) chute's thread, twice over (32 bytes each) so the game
    can read 8 rows (or the 8 after them) from any of the 16 starting places without wrapping."""
    out = ["; Generated by tools/build_assets.py - do not edit."]
    names = {t["name"] for t in tiles}
    for label, name in (("helix_r", "SLIDE_R"), ("helix_l", "SLIDE_L")):
        if name not in names:  # a tile set without chutes (the asset tests') has nothing to turn
            continue
        rows = helix_rows(tiles, name)
        out += [f"{label}:", _bytes_block(rows * 2, 16)]
    return "\n".join(out) + "\n"


def apply_dots(plain: list[int], capped: list[int], dots: dict[int, int], solid: set[int]) -> list[int]:
    """Put a dot in every second middle tile of each run of a dotted tile (the 2nd, 4th, ... tile of the run), so
    every platform with a middle has some. ``plain`` is the map before end caps, ``capped`` after. A tile only
    gets a dot when the player can stand on it: the two cells above must not be solid (callers also pass the spikes)
    and must be on screen."""
    out = list(capped)
    for r in range(3, ROWS):
        c = 0
        while c < COLS:
            b = plain[r * COLS + c]
            if b not in dots:
                c += 1
                continue
            start = c
            while c < COLS and plain[r * COLS + c] == b:
                c += 1
            for k in range(start + 1, c, 2):  # offsets 1, 3, 5, ...
                i = r * COLS + k
                if capped[i] != b:  # an end cap, never a dot
                    continue
                if plain[i - COLS] in solid or plain[i - 2 * COLS] in solid:
                    continue
                out[i] = dots[b]
    return out


def apply_caps(data: list[int], caps: dict[int, dict[str, int]]) -> list[int]:
    """Put the left/right/both-ends variant on every tile whose left or right neighbour is a different tile.
    The edges of the screen count as more of the same, so a floor that runs into a wall has no cap there."""
    out = list(data)
    for i, b in enumerate(data):
        variants = caps.get(b)
        if not variants:
            continue
        col = i % COLS
        left = col > 0 and data[i - 1] != b
        right = col < COLS - 1 and i + 1 < len(data) and data[i + 1] != b
        kind = "LR" if left and right else "L" if left else "R" if right else None
        if kind in variants:
            out[i] = variants[kind]
    return out


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
    """(name, the 16 body rows) of each frame; see parse_sprite_frames."""
    return [(name, body) for name, body, _eyes, _third in parse_sprite_frames(path)]


def third_cells(text: str) -> int:
    """The missile byte of one row's third layer. A missile is a 2-bit-wide 'player' (one colour clock per bit at
    SIZEM=0), its bits shifted out with the high bit on the left. Missile k (HPOSM0..3 sit at HPOS, +2, +4, +6) reads
    bits 2k+1 and 2k of a byte of the missile page (M0 bits 1-0, M1 bits 3-2, M2 bits 5-4, M3 bits 7-6), so column c
    is bit 2*(c//2) + 1 - (c%2): every single pixel can be 'o'."""
    out = 0
    for c, ch in enumerate(text[:SPRITE_W]):
        if ch == "o":
            out |= 1 << (2 * (c // 2) + 1 - c % 2)
    return out


def third_pixels(byte: int) -> int:
    """A missile byte of a third layer (see third_cells) as a row of pixels, leftmost pixel in bit 7, like the body."""
    return sum(0x80 >> c for c in range(SPRITE_W) if byte >> (2 * (c // 2) + 1 - c % 2) & 1)


def parse_sprite_frames(path: Path) -> list[tuple[str, list[int], list[int], list[int]]]:
    """(name, body rows, eye rows, third rows) of each frame. A row is 8 characters, one per pixel:

      '#'  a pixel of the body (hardware Player 0, colour ``player`` of assets/palette.txt)
      'e'  a pixel of an eye (Player 3, colour ``eyes``; it sits behind the body, so it shows only where the body has none)
      'o'  a pixel of the third colour: the four missiles, used as a fifth 8-clock-wide sprite whose colour is the
           playfield colour 3 (``ice`` in the palette file). It sits behind the body and the eyes, so it shows through
           their holes (and in front of the background). Every single pixel can be 'o' (a missile is a 2-bit-wide
           player; see third_cells)
      '.'  nothing (the playfield shows through)

    A pixel is one character, so it is one of these (no pixel is both body and third): where a frame wants the third
    colour the body and eyes must have a hole, which is exactly what an 'o' is. Third rows are the missile bytes."""
    frames: list[tuple[str, list[int], list[int], list[int]]] = []
    name, rows, eyes, third = None, [], [], []

    def close(lineno: int) -> None:
        if name is None:
            return
        if len(rows) != SPRITE_H:
            raise AssetError(f"{path}:{lineno}: frame {name} has {len(rows)} rows, needs {SPRITE_H}")
        frames.append((name, rows[:], eyes[:], third[:]))

    last = 0
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = raw.strip()
        last = n
        if not text or _is_comment(raw):
            continue
        if text.startswith("frame "):
            close(n)
            name, rows, eyes, third = text.split(None, 1)[1], [], [], []
            continue
        if not re.fullmatch(rf"[#.eo]{{{SPRITE_W}}}", text):
            raise AssetError(f"{path}:{n}: sprite rows are {SPRITE_W} characters of '#', 'e', 'o' and '.', got {text!r}")
        if name is None:
            raise AssetError(f"{path}:{n}: sprite row before any 'frame' line")
        third.append(third_cells(text))
        rows.append(sum(0x80 >> i for i, c in enumerate(text) if c == "#"))
        eyes.append(sum(0x80 >> i for i, c in enumerate(text) if c == "e"))
    close(last)
    if not frames:
        raise AssetError(f"{path}: no frames")
    return frames


def render_sprites(frames: list[tuple[str, list[int], list[int], list[int]]]) -> str:
    out = ["; Generated by tools/build_assets.py - do not edit.", f"SPR_COUNT = {len(frames)}", "spr_frames:"]
    for name, rows, _eyes, _third in frames:
        out.append(f"        ; {name}")
        out.append(_bytes_block(rows, SPRITE_H))
    out.append("spr_eyes:")
    for name, _rows, eyes, _third in frames:
        out.append(f"        ; {name}")
        out.append(_bytes_block(eyes, SPRITE_H))
    out.append("spr_third:             ; the missile page (see third_cells)")
    for name, _rows, _eyes, third in frames:
        out.append(f"        ; {name}")
        out.append(_bytes_block(third, SPRITE_H))
    return "\n".join(out) + "\n"


# --------------------------------------------------------------- levels


def parse_level(path: Path, tile_chars: dict[str, int], solid_bytes: set[int] | None = None,
                caps: dict[int, dict[str, int]] | None = None, text: str | None = None,
                dots: dict[int, int] | None = None, door: tuple[int, ...] | None = None,
                twins: dict[int, int] | None = None) -> dict:
    """Compile one level file (or `text`, with `path` only naming it in messages). ``dots`` maps a platform tile
    to its dotted twin; ``twins`` maps a tile to the one drawn in its place on odd rows; ``door`` is the bytes of the six tiles of the exit door (see ``door_bytes``). A ``D`` in the map
    is the door's bottom left tile; the compiler fills in the other five."""
    solid_bytes = solid_bytes if solid_bytes is not None else {1}
    if text is None:
        text = path.read_text(encoding="utf-8")
    grid = [line.rstrip("\n") for line in text.splitlines() if line.strip() and not _is_comment(line)]
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
    stars = sum(1 for b in data if b == tile_chars.get("*", -1))
    if stars == 0:
        raise AssetError(f"{path}: no items ('*') to collect")
    doors = []
    if door is not None:
        for i, b in enumerate(data):
            if b == door[0]:
                c, r = i % COLS, i // COLS
                cells = [i + dc - dr * COLS for dc, dr in DOOR_CELLS]
                if c + 1 >= COLS or r < 3 or any(data[k] != 0 for k in cells[1:]):
                    raise AssetError(
                        f"{path}: the door at row {r}, column {c} needs an empty space above and to the right of it "
                        f"({DOOR_W} columns by {DOOR_H} rows, not touching the score row or the screen edge)"
                    )
                doors.append((c, r))
        if not doors:
            raise AssetError(f"{path}: no exit door ('D')")
        for c, r in doors:
            for tile, (dc, dr) in zip(door, DOOR_CELLS):
                data[(r - dr) * COLS + c + dc] = tile
    platform = platform_bytes(tile_chars, solid_bytes, door)
    pegs = [peg_for(path, data, c, r, solid_bytes, platform) for c, r in peg_marks]
    if len(pegs) > MAX_PEGS:
        raise AssetError(f"{path}: {len(pegs)} pegs, at most {MAX_PEGS} per level")
    plain = data
    if caps:
        data = apply_caps(plain, caps)
    ndots = 0
    if dots:
        # no dot where standing to eat it would put the player in spikes
        data = apply_dots(plain, data, dots, set(solid_bytes or ()) | ({tile_chars['^']} if '^' in tile_chars else set()))
        ndots = sum(1 for b in data if b in dots.values())
    if stars + ndots > MAX_COLLECT:
        raise AssetError(f"{path}: {stars} items and {ndots} dots is too much to collect (at most {MAX_COLLECT} in all)")
    if twins:
        data = apply_twins(data, twins)
    data += [0] * (LEVEL_BYTES - len(data))
    return {"name": path.stem, "data": data, "spawn": spawn, "items": stars + ndots, "stars": stars, "dots": ndots,
            "doors": doors, "pegs": pegs}


def platform_bytes(tile_chars: dict[str, int], solid: set[int], door: tuple[int, ...] | None) -> set[int]:
    """The map bytes that count as part of a platform when a peg looks along the line under its feet: every tile you
    can put in a map (bricks, one-way platforms, stairs, belts, ice, rollers, bomb and vanishing blocks, spikes, ladders,
    chutes, walls, ...) except empty space, items and the exit door's pieces. What the tile is makes no difference."""
    skip = {tile_chars.get(".", 0), tile_chars.get("*", -1)} | set(door or ())
    return (set(tile_chars.values()) | set(solid)) - skip


def peg_for(path: Path, data: list[int], c: int, r: int, solid: set[int],
            platform: set[int] | None = None) -> tuple[int, int, int, int, int]:
    """A peg ('p') sits on a platform and sweeps the whole of it: the run of tiles of any kind (``platform``: see
    platform_bytes; default just the solid ones) on the line under it, from the gap before to the gap after, however
    many belts, steps, spikes or chutes are in it. Only a solid tile in the peg's own row ends the run (a wall).

    Returns (x, y, min x, max x, direction) in pixels: it starts at the end of the block nearer the
    marker and moves towards the other end (direction +1 right, 255 left).
    """
    platform = platform if platform is not None else solid
    if r + 1 >= ROWS or data[(r + 1) * COLS + c] not in platform:
        raise AssetError(f"{path}: peg at row {r}, column {c} needs a platform tile under it")

    def free(col: int) -> bool:  # the platform continues, and the peg has room above it
        return 0 <= col < COLS and data[(r + 1) * COLS + col] in platform and data[r * COLS + col] not in solid

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


DOOR_W, DOOR_H = 2, 3
# the exit door's six tiles as (column, rows up) from the bottom left one, in the order of DOOR_NAMES
DOOR_CELLS = [(0, 0), (1, 0), (0, 1), (1, 1), (0, 2), (1, 2)]
DOOR_NAMES = ["DOOR_BL", "DOOR_BR", "DOOR_ML", "DOOR_MR", "DOOR_TL", "DOOR_TR"]
FADE_STEPS = 16  # the door fades in and out in this many steps


def door_bytes(tiles: list[dict]) -> tuple[int, ...] | None:
    """The map bytes of the exit door's tiles (bottom left, bottom right, middle left, middle right, top left,
    top right) if the tile set has a door. The game draws them from the character set one step at a time, so their ids
    must be consecutive."""
    by_name = {t["name"]: t for t in tiles}
    if not all(n in by_name for n in DOOR_NAMES):
        return None
    ids = [by_name[n]["id"] for n in DOOR_NAMES]
    if ids != list(range(ids[0], ids[0] + len(ids))):
        raise AssetError(f"the door's tiles {', '.join(DOOR_NAMES)} need consecutive ids, got {ids}")
    return tuple(by_name[n]["byte"] for n in DOOR_NAMES)


def fade_thresholds() -> list[int]:
    """For each of the door's 192 pixels (index = 4 * the byte's place in the door's tiles + the pixel's place in the
    byte) the fade step, 0-15, from which it shows. Every run of 16 pixels has each step once, so the door appears
    evenly, in an order that looks random. (A fixed generator, so the game and the editor agree.)"""
    state = 1980
    out: list[int] = []
    for _ in range(len(DOOR_NAMES) * 8 * 4 // 16):
        perm = list(range(FADE_STEPS))
        for i in range(FADE_STEPS - 1, 0, -1):
            state = (state * 75 + 74) % 65537
            j = state % (i + 1)
            perm[i], perm[j] = perm[j], perm[i]
        out += perm
    return out


def render_fade() -> str:
    return "; Generated by tools/build_assets.py - do not edit.\ndoor_thr:\n" + _bytes_block(fade_thresholds()) + "\n"


# -------------------------------------------------------------- palette


PALETTE_DEFAULTS = {"player": 0x4E, "eyes": 0x0E}  # the player's own colours: optional in the file


def parse_palette(path: Path) -> dict:
    """assets/palette.txt: {'hues': [8 colour bytes], 'grey', 'white', 'ice', 'hud', 'background', 'player', 'eyes'}.
    ``player`` (Mr. Bubble's body, Player 0) and ``eyes`` (Player 3) default to $4E and $0E when missing. His third
    colour (the missiles) is the playfield's colour 3, i.e. ``ice``."""
    out: dict = {}
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = raw.split("#", 1)[0].strip()
        if not text:
            continue
        key, *vals = text.split()
        try:
            nums = [int(v, 16) for v in vals]
        except ValueError:
            raise AssetError(f"{path}:{n}: colours are hex bytes, got {vals!r}")
        if any(not 0 <= v <= 255 for v in nums):
            raise AssetError(f"{path}:{n}: colour bytes are 00-FF")
        if key == "hues":
            if len(nums) != 8:
                raise AssetError(f"{path}:{n}: 'hues' needs 8 colours (one per row of the cycle), got {len(nums)}")
            out[key] = nums
        elif key in ("grey", "white", "ice", "hud", "background", "player", "eyes"):
            if len(nums) != 1:
                raise AssetError(f"{path}:{n}: {key!r} takes one colour")
            out[key] = nums[0]
        else:
            raise AssetError(f"{path}:{n}: unknown palette entry {key!r}")
    for key, default in PALETTE_DEFAULTS.items():
        out.setdefault(key, default)
    missing = {"hues", "grey", "white", "ice", "hud", "background"} - out.keys()
    if missing:
        raise AssetError(f"{path}: missing palette entries: {', '.join(sorted(missing))}")
    return out


def render_palette(pal: dict) -> str:
    return (
        "; Generated by tools/build_assets.py - do not edit.\n"
        f"PAL_GREY  = ${pal['grey']:02X}\nPAL_WHITE = ${pal['white']:02X}\nPAL_ICE   = ${pal['ice']:02X}\n"
        f"PAL_HUD   = ${pal['hud']:02X}\nPAL_BG    = ${pal['background']:02X}\n"
        f"PAL_PLAYER = ${pal['player']:02X}          ; Mr. Bubble: body (Player 0)\n"
        f"PAL_EYES   = ${pal['eyes']:02X}          ; his eyes (Player 3)\n"
        "PAL_THIRD  = PAL_ICE          ; his third colour (the missiles) is the playfield's colour 3\n"
        "pal_hues:\n" + _bytes_block(pal["hues"], 8) + "\n"
    )


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
    frames = parse_sprite_frames(assets / "sprites.txt")
    chars = {t["char"]: t["byte"] for t in tiles if t["char"] is not None}
    solid_bytes = {t["byte"] for t in tiles if t["solid"]}
    paths = sorted((assets / "levels").glob("*.txt"), key=natural_key)
    if not paths:
        raise AssetError("no levels in assets/levels/")
    caps = cap_families(tiles)
    dots = dot_families(tiles)
    twins = twin_families(tiles)
    door = door_bytes(tiles)
    levels = [parse_level(p, chars, solid_bytes, caps, dots=dots, door=door, twins=twins) for p in paths]
    cmap = font_charmap(font)
    screens = [(p.stem, parse_screen(p, cmap, chars)) for p in sorted((assets / "screens").glob("*.txt"))]
    out.mkdir(parents=True, exist_ok=True)
    (out / "tiles.inc").write_text(consts)
    (out / "charset.inc").write_text(charset)
    (out / "tileflags.inc").write_text(render_tile_flags(tiles))
    if (assets / "palette.txt").exists():
        (out / "palette.inc").write_text(render_palette(parse_palette(assets / "palette.txt")))
    (out / "fade.inc").write_text(render_fade())
    (out / "helix.inc").write_text(render_helix(tiles))
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
