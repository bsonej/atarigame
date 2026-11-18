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
        del edits[(8, 22)], edits[(9, 21)]
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

    def test_a_missing_start_is_reported(self) -> None:
        path = make({(2, 21): "."})
        self.assertEqual(lc.check(path), ["no player start (@)"])


if __name__ == "__main__":
    unittest.main()
