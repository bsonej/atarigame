"""Tests for tools/levelcheck.py: the shipped maps pass, and obviously broken maps are caught."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import levelcheck as lc  # noqa: E402


def make(edits: dict[tuple[int, int], str], base: list[str] | None = None) -> Path:
    """A level file: a floor at row 23, the player at (2,21), plus the given (col,row) -> char edits."""
    rows = base or ["." * 40 for _ in range(24)]
    rows = [list(r) for r in rows]
    for c in range(40):
        rows[23][c] = "#"
    for r in range(1, 24):
        rows[r][0] = rows[r][39] = "#"
    rows[21][2] = "@"
    for (c, r), ch in edits.items():
        rows[r][c] = ch
    tmp = Path(tempfile.mkdtemp()) / "level.txt"
    tmp.write_text("\n".join("".join(r) for r in rows) + "\n")
    return tmp


class LevelCheck(unittest.TestCase):
    def test_every_shipped_level_passes(self) -> None:
        for path in sorted((ROOT / "assets" / "levels").glob("*.txt")):
            with self.subTest(path.name):
                self.assertEqual(lc.check(path), [])

    def test_an_item_on_the_floor_is_reachable(self) -> None:
        self.assertEqual(lc.check(make({(20, 22): "*"})), [])

    def test_an_item_on_a_ledge_out_of_reach_is_reported(self) -> None:
        problems = lc.check(make({(20, 12): "*", **{(c, 13): "#" for c in range(18, 23)}}))
        items = [p for p in problems if p.startswith("item")]
        self.assertEqual(len(items), 1)
        self.assertIn("column 20, row 12", items[0])
        self.assertTrue(all("dot" in p for p in problems if p not in items), "the ledge's dots can't be reached either")

    def test_a_trampoline_makes_a_high_ledge_reachable_but_not_one_out_of_range(self) -> None:
        ledge = lambda row: {(c, row): "#" for c in range(9, 15)}  # noqa: E731
        plain = {(11, 15): "*", **ledge(16)}  # 7 tiles above the floor: more than a jump
        self.assertTrue([p for p in lc.check(make(plain)) if p.startswith("item")])
        bounce = {**plain, **{(c, 23): "T" for c in (10, 11, 12)}}
        self.assertEqual(lc.check(make(bounce)), [])
        far = {(11, 7): "*", **ledge(8), **{(c, 23): "T" for c in (10, 11, 12)}}  # 15 tiles up
        self.assertTrue([p for p in lc.check(make(far)) if p.startswith("item")])

    def test_a_ladder_makes_the_ledge_reachable(self) -> None:
        edits = {(20, 12): "*", **{(c, 13): "#" for c in range(18, 23)}}
        edits.update({(10, r): "H" for r in range(13, 23)})
        edits.update({(c, 13): "#" for c in range(5, 18)})
        edits[(10, 13)] = "H"
        self.assertEqual(lc.check(make(edits)), [])

    def test_stairs_make_a_ledge_reachable(self) -> None:
        edits = {(c, 18): "#" for c in range(12, 30)}  # a floor 5 tiles up
        edits.update({(8, 22): "S", (9, 21): "S", (10, 20): "S", (11, 19): "S", (12, 18): "S"})
        edits[(20, 17)] = "*"
        self.assertEqual(lc.check(make(edits)), [])
        del edits[(8, 22)], edits[(9, 21)], edits[(10, 20)]
        self.assertTrue(lc.check(make(edits)), "with its bottom steps missing the stairs start too high to jump onto")

    def test_a_pit_too_deep_to_fall_into_is_not_a_route(self) -> None:
        # the only way to the item is by dropping 10 tiles
        edits = {(c, 5): "#" for c in range(15, 25)}
        edits[(20, 4)] = "*"
        self.assertTrue(lc.check(make(edits)))

    def test_a_spike_needs_headroom_to_be_jumped(self) -> None:
        edits = {(20, 22): "^", **{(c, 19): "#" for c in range(15, 26)}}
        problems = lc.check(make(edits))
        self.assertTrue(any("headroom" in p for p in problems), problems)
        edits = {(20, 22): "^", **{(c, 18): "#" for c in range(15, 26)}}
        self.assertEqual(lc.check(make(edits)), [])

    def test_the_dots_on_a_ledge_out_of_reach_are_reported(self) -> None:
        problems = lc.check(make({(30, 22): "*", **{(c, 13): "#" for c in range(18, 23)}}))  # five tiles: end, 3 middles, end -> dots at 19 and 21
        self.assertEqual(sorted(problems), ["the dot on the platform at column 19, row 13 looks unreachable",
                                            "the dot on the platform at column 21, row 13 looks unreachable"])

    def test_the_floor_dots_are_reachable(self) -> None:
        self.assertEqual(lc.check(make({(30, 22): "*"})), [])

    def test_the_door_must_be_reachable_too(self) -> None:
        self.assertEqual(lc.check(make({(30, 22): "D"})), [])
        problems = lc.check(make({(20, 12): "D", **{(c, 13): "#" for c in range(18, 23)}}))
        self.assertTrue(any(p.startswith("door at column 20, row 12") for p in problems), problems)

    def test_a_jump_reaches_three_tiles_up_and_no_further(self) -> None:
        self.assertEqual(lc.check(make({(20, 19): "*", **{(c, 20): "#" for c in range(19, 24)}})), [])  # a ledge 3 up
        self.assertTrue(lc.check(make({(20, 18): "*", **{(c, 19): "#" for c in range(19, 24)}})), "4 tiles up is too high")

    def test_an_item_he_could_only_hit_from_below_is_reported(self) -> None:
        # it floats at head height over the floor (row 21; he stands in rows 21-22): walking and jumping under it
        # never collect it, he must be at its level
        problems = lc.check(make({(20, 21): "*"}))
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("item at column 20, row 21", problems[0])
        # with a block under it to stand on (row 22) it is fine
        self.assertEqual(lc.check(make({(20, 21): "*", (20, 22): "#"})), [])

    def test_an_up_chute_makes_a_high_ledge_reachable(self) -> None:
        ledge = {(20, 12): "*", **{(c, 13): "#" for c in range(16, 23)}}
        self.assertTrue(lc.check(make(ledge)))
        up = {**ledge, **{(15, r): "/" for r in range(13, 23)}}
        self.assertEqual(lc.check(make(up)), [])
        down = {**ledge, **{(15, r): "\\" for r in range(13, 23)}}
        self.assertTrue(lc.check(make(down)), "a down chute does not take him up")

    def test_diagonal_and_side_by_side_chutes_are_rejected(self) -> None:
        diag = lc.check(make({(10 + i, 15 + i): "\\" for i in range(4)}))
        self.assertEqual(len([p for p in diag if "chute" in p]), 4, diag)
        side = lc.check(make({(10, 20): "/", (11, 20): "/"}))
        self.assertEqual(len([p for p in side if "chute" in p]), 2, side)
        step = lc.check(make({(10, 20): "/", (11, 21): "\\"}))
        self.assertEqual(len([p for p in step if "chute" in p]), 2, step)
        mixed = lc.check(make({(10, 20): "/", (10, 21): "\\"}))
        self.assertEqual(len([p for p in mixed if "other kind" in p]), 2, mixed)

    def test_single_wide_vertical_runs_are_fine(self) -> None:
        edits = {**{(10, r): "\\" for r in range(15, 20)}, **{(14, r): "/" for r in range(15, 20)}}
        self.assertEqual([p for p in lc.check(make(edits)) if "chute" in p], [])

    def test_a_missing_start_is_reported(self) -> None:
        path = make({(2, 21): "."})
        self.assertEqual(lc.check(path), ["no player start (@)"])


if __name__ == "__main__":
    unittest.main()
