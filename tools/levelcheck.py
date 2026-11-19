#!/usr/bin/env python3
"""Check that every item, every dot and the exit door in a level can be reached (an approximation, not a playtest).

    python3 tools/levelcheck.py [level files...]     (default: assets/levels/*.txt)

The level is treated as a graph of "standing cells" (the tile under the player's feet). From each
cell the player can walk, climb ladders (steps are jumped up onto), ride chutes (walking into a down chute
carries him to its bottom, into an up chute to its top, where he hops out to the platform beside it), fall off
edges (at most 8 tiles) and jump (up 3 tiles, over gaps up to 6 tiles wide; nothing above him stops a jump).
Bomb blocks and vanishing blocks count as solid, belts and ice do not change where you can go, and pegs and spikes
are ignored (the player is expected to jump them, so spikes are only checked for headroom). So "reachable" here
means "reachable by a competent player"; it cannot tell you the level is fun or fair. Chutes must be isolated,
single-wide vertical runs of one kind (`\\` down, `/` up); diagonal or side-by-side chutes are rejected.
An item is collected only at HIS level (never by jumping up into it from below), so it counts as reachable only if he
can stand in the row of the item (feet on the row under it, in its column or a neighbour); the door is entered by any
overlap and keeps the old reach (up to 3 tiles above a standing cell).
Exit status is 1 if any item, dot or the door (or the start) is unreachable or a chute is laid out wrongly.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_assets as ba  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ROWS, COLS = 24, 40
SOLID = set("#W ~oXv>)]<([{}".replace(" ", ""))
ONEWAY = set("=S")  # thin platforms and steps: stand on top, walk and jump up through
CHUTE_DOWN, CHUTE_UP = "\\", "/"  # chutes are not solid and not standable: they carry a walker along their column
MAX_FALL_TILES = 8  # 64 pixels
# widest jump by number of tiles risen: up 0 / 1 / 2 / 3 tiles (the jump rises 26 pixels and takes 13 frames to the top,
# then falls 2 pixels a frame; he walks 1 pixel a frame = a tile per 4 frames). Keep in step with jump_dy in main.s.
JUMP_REACH = {0: 7, 1: 6, 2: 5, 3: 4}
CHUTE_NEAR = (-1, 1)


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

    def ride(self, n: int, r: int, d: int):
        """What walking (in direction d) from a standing cell at row r into column n does when a chute is there: a chute
        up chute at his body rows (r-1), or a chute of either kind under his feet (r), catches him (a down chute at the
        body rows alone does not: it has nowhere to take him). None if there is none; else the cells he ends in."""
        kind = CHUTE_UP if self.t(n, r - 1) == CHUTE_UP else self.t(n, r)
        if kind == CHUTE_DOWN:  # carried down while a chute is under his feet, then released
            s = r
            while self.t(n, s) == CHUTE_DOWN:
                s += 1
            land = self.fall_to(n, s)
            return [land] if land else []
        if kind == CHUTE_UP:  # carried up while a chute is at his feet row, then he hops out beside the top
            q = r
            while self.t(n, q - 1) == CHUTE_UP:
                q -= 1
            n2 = n + d
            if not 0 < n2 < COLS - 1 or self.solid(n2, q - 1) or self.solid(n2, q - 2):
                return []
            land = self.fall_to(n2, q)
            return [land] if land else []
        return None

    def moves(self, c: int, r: int):
        out = []
        # walking (into a chute: it carries him)
        for d in (-1, 1):
            n = c + d
            if not 0 < n < COLS - 1:
                continue
            ride = self.ride(n, r, d)
            if ride is not None:
                out.extend(ride)
            elif self.valid(n, r):
                out.append((n, r))
            elif not self.solid(n, r - 1) and not self.solid(n, r - 2):
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
        for dy, reach in JUMP_REACH.items():  # nothing above him stops a jump: he overlays blocks on the way up
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
            if self.t(ic, ir) == "D":  # the door is entered by any overlap, a jump up into it included
                if any(abs(c - ic) <= 1 and r - 4 <= ir <= r - 1 for c, r in spots):
                    got.add((ic, ir))
            elif any(abs(c - ic) <= 1 and r == ir + 1 for c, r in spots):  # an item: he must stand at its level
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
    problems += chute_problems(lv.rows)
    cells = lv.reachable()
    for ic, ir in sorted(set(lv.items) - lv.collectable(cells)):
        what = "door" if lv.t(ic, ir) == "D" else "item"
        problems.append(f"{what} at column {ic}, row {ir} looks unreachable")
    for c, r in dotted_cells(lv.rows):
        if not any((c + d, r) in cells for d in (-1, 0, 1)):
            problems.append(f"the dot on the platform at column {c}, row {r} looks unreachable")
    return problems


def chute_problems(rows: list[str]) -> list[str]:
    """Chutes are isolated single-wide vertical runs of one kind: no chute in the neighbouring columns (rows r-1..r+1:
    that is a diagonal or side-by-side layout), and no up chute directly above or below a down chute."""
    out = []
    chute = lambda c, r: 0 <= r < len(rows) and 0 <= c < len(rows[r]) and rows[r][c] in (CHUTE_DOWN, CHUTE_UP)  # noqa: E731
    for r, line in enumerate(rows):
        for c, ch in enumerate(line):
            if ch not in (CHUTE_DOWN, CHUTE_UP):
                continue
            if any(chute(c + dc, r + dr) for dc in CHUTE_NEAR for dr in (-1, 0, 1)):
                out.append(f"the chute at column {c}, row {r} has another chute beside it: chutes must be single-wide vertical runs (no diagonals)")
            elif any(0 <= r + dr < len(rows) and rows[r + dr][c] in (CHUTE_DOWN, CHUTE_UP) and rows[r + dr][c] != ch for dr in (-1, 1)):
                out.append(f"the chute at column {c}, row {r} is next to a chute of the other kind (a run is all down or all up)")
    return out


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
