"""Tests for tools/build_assets.py: the real assets convert, and bad assets are rejected clearly."""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import build_assets as ba  # noqa: E402

TILE = "\n".join(["tile {id} {name} {ch}"] + ["0000"] * 8)
EMPTY_TILE = TILE.format(id=0, name="EMPTY", ch=".")
BRICK_TILE = TILE.format(id=1, name="BRICK", ch="#")
ITEM_TILE = TILE.format(id=3, name="ITEM", ch="*")
SPRITE = "frame stand\n" + "\n".join(["#..#"] * 16)


def level(rows: list[str]) -> str:
    return "\n".join(rows) + "\n"


def good_rows() -> list[str]:
    rows = ["." * 40 for _ in range(24)]
    rows[23] = "#" * 40
    rows[22] = "..@" + "." * 35 + "*."
    return rows


class Project:
    """A throwaway project directory with a minimal set of valid assets."""

    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "assets" / "levels").mkdir(parents=True)
        self.write("assets/tiles.txt", "\n".join([EMPTY_TILE, BRICK_TILE, ITEM_TILE]) + "\n")
        self.write("assets/sprites.txt", SPRITE + "\n")
        self.write("assets/levels/level1.txt", level(good_rows()))

    def write(self, rel: str, text: str) -> None:
        (self.dir / rel).write_text(text)

    def build(self) -> Path:
        out = self.dir / "gen"
        ba.build(self.dir, out)
        return out

    def cleanup(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


class RealAssets(unittest.TestCase):
    def test_project_assets_convert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ba.build(ROOT, Path(tmp))
            names = {p.name for p in Path(tmp).iterdir()}
            self.assertEqual(names, {"tiles.inc", "charset.inc", "sprites.inc", "levels.inc"})
            self.assertIn("T_BRICK", (Path(tmp) / "tiles.inc").read_text())
            self.assertIn("level1_spawn", (Path(tmp) / "levels.inc").read_text())


class Validation(unittest.TestCase):
    def setUp(self) -> None:
        self.p = Project()
        self.addCleanup(self.p.cleanup)

    def rejects(self, rel: str, text: str, message: str) -> None:
        self.p.write(rel, text)
        with self.assertRaises(ba.AssetError) as cm:
            self.p.build()
        self.assertIn(message, str(cm.exception))

    def test_minimal_project_builds(self) -> None:
        out = self.p.build()
        self.assertEqual((out / "charset.inc").read_text().count(".byte") > 0, True)

    def test_level_needs_24_rows(self) -> None:
        self.rejects("assets/levels/level1.txt", level(good_rows()[:23]), "map rows")

    def test_level_rows_must_be_40_wide(self) -> None:
        rows = good_rows()
        rows[5] = "." * 39
        self.rejects("assets/levels/level1.txt", level(rows), "wide")

    def test_level_needs_a_start(self) -> None:
        rows = [r.replace("@", ".") for r in good_rows()]
        self.rejects("assets/levels/level1.txt", level(rows), "'@'")

    def test_level_needs_items(self) -> None:
        rows = [r.replace("*", ".") for r in good_rows()]
        self.rejects("assets/levels/level1.txt", level(rows), "no items")

    def test_level_rejects_unknown_characters(self) -> None:
        rows = good_rows()
        rows[3] = "?" + rows[3][1:]
        self.rejects("assets/levels/level1.txt", level(rows), "unknown character")

    def test_level_rejects_two_starts(self) -> None:
        rows = good_rows()
        rows[3] = "@" + rows[3][1:]
        self.rejects("assets/levels/level1.txt", level(rows), "more than one")

    def test_tiles_need_the_empty_tile(self) -> None:
        self.rejects("assets/tiles.txt", BRICK_TILE + "\n" + ITEM_TILE + "\n", "tile 0")

    def test_tile_rows_must_be_four_digits(self) -> None:
        bad = EMPTY_TILE.replace("0000", "000", 1)
        self.rejects("assets/tiles.txt", bad + "\n" + BRICK_TILE + "\n" + ITEM_TILE + "\n", "4 digits")

    def test_duplicate_tile_ids_rejected(self) -> None:
        dup = EMPTY_TILE + "\n" + TILE.format(id=0, name="OTHER", ch="x") + "\n"
        self.rejects("assets/tiles.txt", dup, "duplicate tile id")

    def test_sprite_rows_must_be_four_wide(self) -> None:
        bad = SPRITE.replace("#..#", "#..", 1)
        self.rejects("assets/sprites.txt", bad + "\n", "sprite rows are 4")


if __name__ == "__main__":
    unittest.main()
