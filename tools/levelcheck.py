#!/usr/bin/env python3
"""Check that every item, every dot and the exit door in a level can be reached (an approximation, not a playtest).

    python3 tools/levelcheck.py [level files...]     (default: assets/levels/*.txt)

The level is treated as a graph of "standing cells" (the tile under the player's feet). From each
cell the player can walk, climb stairs and ladders, step down chutes, fall off edges (at most 8 tiles)
and jump (up 2 tiles, over gaps up to 5 tiles wide). Bomb blocks and vanishing blocks count as
solid, belts and ice do not change where you can go, and pegs and spikes are ignored (the player is
expected to jump them, so spikes are only checked for headroom; and a chute can be reached by a jump from below
like any other solid tile). So "reachable" here means "reachable by a competent player"; it cannot tell
you the level is fun or fair. Exit status is 1 if any item, dot or the door (or the start) is unreachable.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_assets as ba  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ROWS, COLS = 24, 40
SOLID = set("#W S~oXv\\/>)]<([{}".replace(" ", ""))
ONEWAY = set("=")
MAX_FALL_TILES = 8  # 64 pixels
# widest jump by number of tiles risen: up 0 / 1 / 2 tiles
JUMP_REACH = {0: 5, 1: 4, 2: 3}


def load(path: Path) -> list[str]:
    rows = [t for t in path.read_text().splitlines() if not t.startswith("#!") and not t.startswith("# ")]
    rows = [r for r in rows if r.strip() != "" or len(r) == COLS]
    if len(rows) > ROWS:
        raise SystemExit(f"{path}: too many rows")
    return rows + ["." * COLS] * (ROWS - len(rows))


class Level:
    def __init__(self, rows: list[str]) -> None:
        self.rows = rows
        self.start = None
        self.items: list[tuple[int, int]] = []
        for r, line in enumerate(rows):
            for c, ch in enumerate(line):
                if ch == "@":
                    self.start = (c, r + 2)  # standing cell: the tile under the 2-tall player
                elif ch in "*D":  # items, and the door (its bottom half is where the player stands to enter)
                    self.items.append((c, r))

    def t(self, c: int, r: int) -> str:
        if not (0 <= c < COLS and 0 <= r < ROWS):
            return "#"
        return self.rows[r][c]

    def solid(self, c: int, r: int) -> bool:
        return self.t(c, r) in SOLID

    def standable(self, c: int, r: int) -> bool:
        ch = self.t(c, r)
        if ch in SOLID or ch in ONEWAY:
            return True
        return ch == "H" and self.t(c, r - 1) != "H"  # the very top of a ladder

    def valid(self, c: int, r: int) -> bool:
        """Can the player stand with its feet on tile (c,r)?"""
        return (
            0 < c < COLS - 1
            and self.standable(c, r)
            and not self.solid(c, r - 1)
            and not self.solid(c, r - 2)
            and self.t(c, r - 1) != "^"
        )

    def fall_to(self, c: int, r: int):
        """Where a player falling through column c from row r lands, or None (too far or no ground)."""
        for r2 in range(r, min(r + MAX_FALL_TILES + 1, ROWS)):
            if self.t(c, r2) == "^" and not self.standable(c, r2):
                return None
            if self.valid(c, r2) and not (self.t(c, r2) == "H" and self.t(c, r2 - 1) == "H"):
                return (c, r2)
            if self.solid(c, r2) or self.t(c, r2) in ONEWAY:
                return None
        return None

    def ladder_run(self, c: int, r: int):
        """The ladder cells (top, bottom) in column c containing row r, or None."""
        if self.t(c, r) != "H":
            return None
        top = r
        while self.t(c, top - 1) == "H":
            top -= 1
        bot = r
        while self.t(c, bot + 1) == "H":
            bot += 1
        return top, bot

    def moves(self, c: int, r: int):
        out = []
        # walking
        for d in (-1, 1):
            n = c + d
            if self.valid(n, r):
                out.append((n, r))
            elif self.t(n, r - 1) == "S" and self.valid(n, r - 1) and not self.solid(c, r - 3):
                out.append((n, r - 1))  # up a stair
            elif not self.solid(n, r - 1) and not self.solid(n, r - 2) and 0 < n < COLS - 1:
                if self.t(n, r + 1) in "S\\/" and self.valid(n, r + 1):
                    out.append((n, r + 1))  # down a stair or chute
                else:
                    land = self.fall_to(n, r)
                    if land:
                        out.append(land)
        # ladders: up from the foot of one, down from the top of one
        for rr in (r - 1, r):
            run = self.ladder_run(c, rr)
            if run:
                top, bot = run
                for cand in (top, bot + 1):
                    if self.valid(c, cand):
                        out.append((c, cand))
                for k in range(top, bot + 2):  # stepping off sideways part way up
                    for d in (-1, 1):
                        if self.valid(c + d, k):
                            out.append((c + d, k))
        # jumping
        if not self.solid(c, r - 3):
            for dy, reach in JUMP_REACH.items():
                for dc in range(-reach, reach + 1):
                    if dc and self.valid(c + dc, r - dy):
                        out.append((c + dc, r - dy))
            for dc in range(-JUMP_REACH[0], JUMP_REACH[0] + 1):  # jump out and drop down
                land = self.fall_to(c + dc, r + 1) if dc and 0 < c + dc < COLS - 1 else None
                if land and not self.solid(c + dc, r - 1) and not self.solid(c + dc, r - 2):
                    out.append(land)
        return out

    def reachable(self):
        seen = {self.start}
        todo = [self.start]
        while todo:
            c, r = todo.pop()
            for n in self.moves(c, r):
                if n not in seen:
                    seen.add(n)
                    todo.append(n)
        return seen

    def collectable(self, cells) -> set[tuple[int, int]]:
        spots = set(cells)
        for c, r in list(cells):  # on a ladder the player passes every cell of it
            for rr in (r - 1, r):
                run = self.ladder_run(c, rr)
                if run:
                    spots |= {(c, k + 1) for k in range(run[0], run[1] + 1)}
        got = set()
        for ic, ir in self.items:
            if any(abs(c - ic) <= 1 and r - 3 <= ir <= r - 1 for c, r in spots):
                got.add((ic, ir))
        return got


def check(path: Path) -> list[str]:
    return check_rows(load(path))


def check_rows(rows: list[str]) -> list[str]:
    """The problems found in a level given as its map rows (comment lines already removed)."""
    lv = Level(rows + ["." * COLS] * (ROWS - len(rows)))
    problems = []
    if lv.start is None:
        return ["no player start (@)"]
    if not lv.valid(*lv.start):
        problems.append(f"the start {lv.start} is not a place to stand")
    for r, line in enumerate(lv.rows):
        for col, ch in enumerate(line):
            # to jump a spike the player needs about 3 tiles of clear space above it (next to it too)
            if ch == "^" and any(lv.solid(col + dc, r - 3) for dc in (-2, -1, 0, 1, 2)):
                problems.append(f"the spike at column {col}, row {r} has too little headroom to jump over")
    cells = lv.reachable()
    for ic, ir in sorted(set(lv.items) - lv.collectable(cells)):
        what = "door" if lv.t(ic, ir) == "D" else "item"
        problems.append(f"{what} at column {ic}, row {ir} looks unreachable")
    for c, r in dotted_cells(lv.rows):
        if not any((c + d, r) in cells for d in (-1, 0, 1)):
            problems.append(f"the dot on the platform at column {c}, row {r} looks unreachable")
    return problems


def dotted_cells(rows: list[str]) -> list[tuple[int, int]]:
    """(column, row) of every platform tile the asset tool puts a dot in (none if the level does not compile)."""
    tiles = ba.parse_tiles(ROOT / "assets" / "tiles.txt")
    chars = {t["char"]: t["byte"] for t in tiles if t["char"] is not None}
    solid = {t["byte"] for t in tiles if t["solid"]}
    try:
        lv = ba.parse_level(Path("level"), chars, solid, ba.cap_families(tiles), text="\n".join(rows) + "\n",
                            dots=ba.dot_families(tiles))  # (no door: a level without one is reported elsewhere)
    except ba.AssetError:
        return []
    dotted = set(ba.dot_families(tiles).values())
    return [(i % ba.COLS, i // ba.COLS) for i, b in enumerate(lv["data"][: ba.COLS * ba.ROWS]) if b in dotted]


def main(argv: list[str]) -> int:
    paths = [Path(a) for a in argv] or sorted((ROOT / "assets" / "levels").glob("*.txt"))
    bad = 0
    for p in paths:
        problems = check(p)
        print(f"{p.name}: {'ok' if not problems else ''}")
        for line in problems:
            print(f"  {line}")
        bad += bool(problems)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
