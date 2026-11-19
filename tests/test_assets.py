"""Tests for tools/build_assets.py: the real assets convert, and bad assets are rejected clearly."""

from __future__ import annotations

import re
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
SPRITE = "frame stand\n" + "\n".join(["#......#"] * 16)


FONT_A = "glyph A\n.#.\n#.#\n###\n#.#\n#.#\n"
FONT_0 = "glyph 0\n###\n#.#\n#.#\n#.#\n###\n"
FONT_DASH = "glyph -\n...\n...\n###\n...\n...\n"


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


class Font(unittest.TestCase):
    def setUp(self) -> None:
        self.p = Project()
        self.addCleanup(self.p.cleanup)

    def build_with(self, font: str) -> Path:
        self.p.write("assets/font.txt", font)
        return self.p.build()

    def test_ids_digits_16_letters_32_others_from_58(self) -> None:
        self.p.write("assets/font.txt", FONT_0 + FONT_A + FONT_DASH)
        glyphs = {g["char"]: g["id"] for g in ba.parse_font(self.p.dir / "assets" / "font.txt")}
        self.assertEqual(glyphs, {"0": 16, "A": 32, "-": 58})

    def test_charmap_maps_text_and_lowercase_is_the_second_colour(self) -> None:
        out = self.build_with(FONT_0 + FONT_A)
        text = (out / "font.inc").read_text()
        self.assertIn(".charmap 65, 32", text)  # A
        self.assertIn(".charmap 97, 160", text)  # a = same glyph, bit 7 set
        self.assertIn(".charmap 48, 16", text)  # 0
        self.assertIn(".charmap 32, 0", text)  # space is the empty tile
        self.assertNotIn(".charmap 111", text)

    def test_glyph_pixels_are_drawn_in_the_tile_with_value_3(self) -> None:
        out = self.build_with(FONT_A)
        flat = [int(v, 16) for v in re.findall(r"\$([0-9A-F]{2})", (out / "charset.inc").read_text())]
        glyph = flat[32 * 8 : 33 * 8]
        # rows .#. #.# ### #.# #.# placed on lines 1..7 as [r0, r0, r1, r2, r2, r3, r4], blank first line
        row = {".#.": 0b00110000, "#.#": 0b11001100, "###": 0b11111100}
        self.assertEqual(glyph, [0, row[".#."], row[".#."], row["#.#"], row["###"], row["###"], row["#.#"], row["#.#"]])

    def test_font_must_not_collide_with_tiles(self) -> None:
        self.p.write("assets/tiles.txt", self.p.dir.joinpath("assets/tiles.txt").read_text() + "\n" + TILE.format(id=32, name="CLASH", ch="~") + "\n")
        self.p.write("assets/font.txt", FONT_A)
        with self.assertRaises(ba.AssetError) as cm:
            self.p.build()
        self.assertIn("collides", str(cm.exception))

    def test_bad_glyphs_are_rejected(self) -> None:
        for text, message in (
            ("glyph A\n.#.\n#.#\n", "needs 5"),
            ("glyph A\n.#.\n#.#\n###\n#.#\n#.\n", "3 characters"),
            ("glyph a\n.#.\n#.#\n###\n#.#\n#.#\n", "uppercase"),
            (FONT_A + FONT_A, "duplicate glyph"),
            (".#.\n", "before any 'glyph'"),
        ):
            with self.subTest(message):
                self.p.write("assets/font.txt", text)
                with self.assertRaises(ba.AssetError) as cm:
                    self.p.build()
                self.assertIn(message, str(cm.exception))


class Screens(unittest.TestCase):
    def setUp(self) -> None:
        self.p = Project()
        self.addCleanup(self.p.cleanup)
        self.p.write("assets/font.txt", FONT_0 + FONT_A + FONT_DASH + "glyph H\n#.#\n#.#\n###\n#.#\n#.#\n")
        (self.p.dir / "assets" / "screens").mkdir()

    def build_screen(self, rows: list[str], name: str = "title") -> list[int]:
        self.p.write(f"assets/screens/{name}.txt", "\n".join(rows) + "\n")
        out = self.p.build()
        text = (out / "screens.inc").read_text()
        body = text.split(f"screen_{name}:")[1]
        return [int(v, 16) for v in re.findall(r"\$([0-9A-F]{2})", body)][:960]

    def test_text_tiles_and_blanks_become_bytes(self) -> None:
        data = self.build_screen(["A0-aH #*"])
        self.assertEqual(data[:8], [32, 16, 58, 32 | 0x80, 39, 0, 1, 3])

    def test_letters_win_over_tile_characters(self) -> None:
        data = self.build_screen(["H"])
        self.assertEqual(data[0], 32 + 7)  # the letter H, not the ladder tile

    def test_short_screens_are_padded_to_24_rows_of_40(self) -> None:
        data = self.build_screen(["A"])
        self.assertEqual(len(data), 960)
        self.assertEqual(data[1:], [0] * 959)

    def test_a_row_starting_with_hash_space_is_data_not_a_comment(self) -> None:
        data = self.build_screen(["#  A", "#! a comment"])
        self.assertEqual(data[:4], [1, 0, 0, 32])
        self.assertEqual(data[40:44], [0, 0, 0, 0], "the comment is not a row")

    def test_screens_are_named_after_their_files(self) -> None:
        self.build_screen(["A"], name="gameover")
        self.assertIn("screen_gameover:", (self.p.dir / "gen" / "screens.inc").read_text())

    def test_bad_screens_are_rejected(self) -> None:
        for rows, message in (
            (["?"], "unknown character"),
            (["A" * 41], "wide"),
            (["A"] * 25, "at most 24"),
        ):
            with self.subTest(message):
                self.p.write("assets/screens/title.txt", "\n".join(rows) + "\n")
                with self.assertRaises(ba.AssetError) as cm:
                    self.p.build()
                self.assertIn(message, str(cm.exception))


class LevelTables(unittest.TestCase):
    def setUp(self) -> None:
        self.p = Project()
        self.addCleanup(self.p.cleanup)

    def test_levels_are_ordered_naturally_and_tabulated(self) -> None:
        for n in (10, 2):
            self.p.write(f"assets/levels/level{n}.txt", level(good_rows()))
        text = self.p.build().joinpath("levels.inc").read_text()
        self.assertIn("LEVEL_COUNT = 3", text)
        self.assertIn("level_lo:    .byte <level1,<level2,<level10", text)
        self.assertIn("level_items: .byte LEVEL1_ITEMS,LEVEL2_ITEMS,LEVEL10_ITEMS", text)
        self.assertIn("level_sx:    .byte 8,8,8", text)  # spawn column 2 -> pixel 8
        self.assertIn("level_sy:    .byte 176,176,176", text)  # row 22 -> line 176

    def test_levels_may_have_at_most_250_things_to_collect(self) -> None:
        rows = good_rows()
        for r in range(3, 10):
            rows[r] = "*" * 40
        self.p.write("assets/levels/level1.txt", level(rows))
        with self.assertRaises(ba.AssetError) as cm:
            self.p.build()
        self.assertIn("too much to collect", str(cm.exception))


def flagged(id: int, name: str, ch: str, flags: str = "") -> str:
    """A tile definition with flags on its header line."""
    return "\n".join([f"tile {id} {name} {ch} {flags}".rstrip()] + ["0000"] * 8)


SOLID_BRICK = flagged(1, "BRICK", "#", "solid")


class Components(unittest.TestCase):
    """Tile flags, alt-colour tiles, and pegs."""

    def setUp(self) -> None:
        self.p = Project()
        self.addCleanup(self.p.cleanup)

    def tiles(self, *extra: str) -> None:
        self.p.write("assets/tiles.txt", "\n".join([EMPTY_TILE, SOLID_BRICK, ITEM_TILE, *extra]) + "\n")

    def flags(self) -> list[int]:
        text = self.p.build().joinpath("tileflags.inc").read_text().split("tile_canon:")[0]
        return [int(x.strip("$"), 16) for x in re.findall(r"\$[0-9A-Fa-f]{2}", text)]

    def test_flags_land_in_the_table_at_the_map_byte(self) -> None:
        self.tiles(flagged(5, "PLAT", "=", "oneway"),
                   flagged(7, "ICE", "~", "solid alt"))
        flags = self.flags()
        self.assertEqual(len(flags), 256)
        self.assertEqual((flags[0], flags[1], flags[3]), (0, 1, 0))
        self.assertEqual(flags[5], 2)  # one-way
        self.assertEqual(flags[7 | 0x80], 1)  # alt tiles are stored with bit 7 set
        self.assertEqual(flags[7], 0)

    def test_alt_tiles_are_stored_with_bit_7_but_drawn_from_the_base_glyph(self) -> None:
        self.tiles(flagged(7, "ICE", "~", "solid alt"))
        out = self.p.build()
        self.assertIn("T_ICE", out.joinpath("tiles.inc").read_text())
        self.assertIn("= 135", out.joinpath("tiles.inc").read_text())
        rows = [r for r in self.p.dir.joinpath("assets/levels/level1.txt").read_text().splitlines()]
        rows[10] = "~" + rows[10][1:]
        self.p.write("assets/levels/level1.txt", level(rows))
        text = self.p.build().joinpath("levels.inc").read_text()
        self.assertIn("$87", text)

    def test_none_gives_a_tile_no_map_character(self) -> None:
        self.tiles(flagged(10, "SPARK", "none"))
        self.assertIn("T_SPARK", self.p.build().joinpath("tiles.inc").read_text())
        rows = good_rows()
        rows[5] = "?" + rows[5][1:]
        self.p.write("assets/levels/level1.txt", level(rows))
        with self.assertRaises(ba.AssetError):
            self.p.build()

    def test_unknown_or_conflicting_flags_are_rejected(self) -> None:
        for extra, message in (
            (flagged(5, "X", "=", "sticky"), "unknown tile flag"),
            (flagged(5, "X", "=", "solid oneway"), "both solid and oneway"),
            (flagged(5, "X", "p"), "map character"),
        ):
            with self.subTest(message):
                self.tiles(extra)
                with self.assertRaises(ba.AssetError) as cm:
                    self.p.build()
                self.assertIn(message, str(cm.exception))

    def peg_level(self, rows: dict[int, str]) -> str:
        base = good_rows()
        for r, text in rows.items():
            base[r] = text
        self.tiles()
        self.p.write("assets/levels/level1.txt", level(base))
        return self.p.build().joinpath("levels.inc").read_text()

    def test_a_peg_sweeps_the_block_it_stands_on(self) -> None:
        text = self.peg_level({
            19: "." * 10 + "#" * 8 + "." * 22,
            18: "." * 11 + "p" + "." * 28,
        })
        # block columns 10-17; the marker at column 11 is nearer the left end, so it starts there going right
        self.assertIn("level1_pegs:\n        .byte 1,40,144,40,68,1", text)

    def test_a_peg_nearer_the_right_end_starts_there_and_goes_left(self) -> None:
        text = self.peg_level({
            19: "." * 10 + "#" * 8 + "." * 22,
            18: "." * 16 + "p" + "." * 23,
        })
        self.assertIn("level1_pegs:\n        .byte 1,68,144,40,68,255", text)

    def test_a_platform_ends_where_something_stands_on_it(self) -> None:
        text = self.peg_level({
            19: "." * 10 + "#" * 8 + "." * 22,
            18: "." * 14 + "#" + "." * 2 + "p" + "." * 22,
        })
        self.assertIn(".byte 1,68,144,60,68,255", text)  # columns 15-17 only (pixels 60-68)

    def test_a_peg_sweeps_the_whole_platform_whatever_its_tiles_are(self) -> None:
        # brick, belt, spike, step, one-way platform, ladder, brick: columns 10-16 are one platform
        self.tiles(flagged(5, "PLAT", "=", "oneway"), flagged(6, "STAIR", "S", "oneway"), flagged(4, "SPIKE", "^"),
                   flagged(2, "LADDER", "H"), flagged(64, "BELT", ">", "solid"))
        rows = good_rows()
        rows[19] = "." * 10 + "#>^S=H#" + "." * 23
        rows[18] = "." * 11 + "p" + "." * 28
        self.p.write("assets/levels/level1.txt", level(rows))
        text = self.p.build().joinpath("levels.inc").read_text()
        self.assertIn("level1_pegs:\n        .byte 1,40,144,40,64,1", text)
        # a solid thing in the peg's own row (a wall) ends the run; a ladder, step or spike standing on it does not
        rows[18] = "." * 11 + "p" + "." * 2 + "#" + "." * 25
        self.p.write("assets/levels/level1.txt", level(rows))
        self.assertIn(".byte 1,40,144,40,52,1", self.p.build().joinpath("levels.inc").read_text())
        rows[18] = "." * 11 + "p" + "." * 2 + "S^H" + "." * 23
        self.p.write("assets/levels/level1.txt", level(rows))
        self.assertIn(".byte 1,40,144,40,64,1", self.p.build().joinpath("levels.inc").read_text())

    def test_levels_without_pegs_have_an_empty_peg_list(self) -> None:
        self.tiles()
        text = self.p.build().joinpath("levels.inc").read_text()
        self.assertIn("level1_pegs:\n        .byte 0", text)
        self.assertIn("level_pg_lo:", text)

    def test_bad_pegs_are_rejected(self) -> None:
        cases = (
            ({18: "." * 11 + "p" + "." * 28}, "platform tile under"),
            ({19: "." * 10 + "#" + "." * 29, 18: "." * 10 + "p" + "." * 29}, "only one tile wide"),
            ({19: "#" * 40, 18: "p" + "." * 5 + "p" + "." * 5 + "p" + "." * 27}, "at most 2"),
        )
        for rows, message in cases:
            with self.subTest(message):
                with self.assertRaises(ba.AssetError) as cm:
                    self.peg_level(rows)
                self.assertIn(message, str(cm.exception))


class EndCaps(unittest.TestCase):
    """Left/right/both-ends variants of platform tiles."""

    def setUp(self) -> None:
        self.p = Project()
        self.addCleanup(self.p.cleanup)

    def tiles(self, *extra: str) -> None:
        self.p.write("assets/tiles.txt", "\n".join([EMPTY_TILE, SOLID_BRICK, ITEM_TILE, *extra]) + "\n")

    def test_auto_cap_rounds_the_end_and_draws_an_edge(self) -> None:
        rows = ["1111", "2232", "2232", "3333", "2322", "2322", "3333", "2222"]
        left = ba.auto_cap(rows, "L", None, None, 3)
        self.assertEqual(left[0], "0111")  # corners cut
        self.assertEqual(left[7], "0222")
        self.assertEqual(left[1], "3232")  # the outermost column becomes the edge colour
        self.assertEqual([r[1:] for r in left[1:7]], [r[1:] for r in rows[1:7]], "the rest is untouched")
        right = ba.auto_cap(rows, "R", None, None, 3)
        self.assertEqual((right[0], right[7]), ("1110", "2220"))
        both = ba.auto_cap(rows, "LR", None, None, 1)
        self.assertEqual((both[0], both[1]), ("0110", "1231"))

    def test_auto_cap_leaves_alone_the_rows_outside_its_range(self) -> None:
        rows = ["3222", "3222", "2222", "2222", "2222", "2222", "2222", "1111"]
        cap = ba.auto_cap(rows, "L", 2, 7, 3)
        self.assertEqual(cap[:2], rows[:2], "the animated surface rows are not touched")
        self.assertEqual(cap[2], "3222")  # not a corner: the top of the range is not the top of the art
        self.assertEqual(cap[7], "0111")

    def test_empty_rows_stay_empty_in_a_cap(self) -> None:
        rows = ["3333", "2222", "0000", "0000", "0000", "0000", "0000", "0000"]
        self.assertEqual(ba.auto_cap(rows, "L", None, None, 3)[2:], rows[2:])

    def test_caps_get_ids_names_and_inherit_flags(self) -> None:
        self.tiles(
            flagged(7, "ICE", "~", "solid alt"),
            "cap 20 BRICK L\n" + "\n".join(["0000"] * 8),
            "cap 21 ICE R",
        )
        tiles = {t["name"]: t for t in ba.parse_tiles(self.p.dir / "assets" / "tiles.txt")}
        self.assertEqual((tiles["BRICK_L"]["id"], tiles["BRICK_L"]["solid"], tiles["BRICK_L"]["char"]), (20, True, None))
        self.assertEqual(tiles["ICE_R"]["byte"], 21 | 0x80, "a cap of an alt tile is alt too")
        self.assertEqual(tiles["BRICK_L"]["rows"], ["0000"] * 8, "typed art is used as written")
        self.assertEqual(len(tiles["ICE_R"]["rows"]), 8, "no art: made from the plain tile")

    def test_bad_caps_are_rejected(self) -> None:
        for line, message in (
            ("cap 20 NOPE L", "unknown tile"),
            ("cap 20 BRICK X", "L, R or LR"),
            ("cap 1 BRICK L", "duplicate tile id"),
            ("cap 20 BRICK L rows=5-2", "backwards"),
            ("cap 20 BRICK L color=3", "unknown cap option"),
            ("cap 200 BRICK L", "must be 0-127"),
            ("cap 20 BRICK", "expected"),
        ):
            with self.subTest(line):
                self.tiles(line)
                with self.assertRaises(ba.AssetError) as cm:
                    self.p.build()
                self.assertIn(message, str(cm.exception))
        self.tiles("cap 20 BRICK L", "cap 21 BRICK L")
        with self.assertRaises(ba.AssetError) as cm:
            self.p.build()
        self.assertIn("defined twice", str(cm.exception))

    def test_apply_caps_picks_the_end_variant_from_the_neighbours(self) -> None:
        caps = {1: {"L": 20, "R": 21, "LR": 22}}
        row = [0, 1, 1, 1, 0, 1, 0] + [0] * (ba.COLS - 7)
        out = ba.apply_caps(row, caps)
        self.assertEqual(out[:7], [0, 20, 1, 21, 0, 22, 0])

    def test_the_edge_of_the_screen_is_not_an_end(self) -> None:
        caps = {1: {"L": 20, "R": 21, "LR": 22}}
        row = [1] * ba.COLS
        self.assertEqual(ba.apply_caps(row, caps), row, "a floor that runs wall to wall has no ends")
        row = [1, 1, 0] + [0] * (ba.COLS - 3)
        self.assertEqual(ba.apply_caps(row, caps)[:3], [1, 21, 0])
        self.assertEqual(ba.apply_caps(row, caps)[0], 1, "no cap on the screen edge side")

    def test_a_different_neighbour_counts_as_an_end(self) -> None:
        caps = {1: {"L": 20, "R": 21, "LR": 22}}
        row = [5, 1, 1, 6] + [0] * (ba.COLS - 4)
        self.assertEqual(ba.apply_caps(row, caps)[:4], [5, 20, 21, 6])

    def test_a_missing_variant_leaves_the_plain_tile(self) -> None:
        caps = {1: {"L": 20}}
        row = [0, 1, 0] + [0] * (ba.COLS - 3)
        self.assertEqual(ba.apply_caps(row, caps)[1], 1)

    def test_canon_table_maps_caps_back_to_their_tile(self) -> None:
        self.tiles(flagged(7, "ICE", "~", "solid alt"), "cap 20 BRICK L", "cap 21 ICE LR")
        text = self.p.build().joinpath("tileflags.inc").read_text()
        canon = [int(x[1:], 16) for x in re.findall(r"\$[0-9A-F]{2}", text.split("tile_canon:")[1])]
        self.assertEqual(len(canon), 256)
        self.assertEqual((canon[20], canon[21 | 0x80], canon[1], canon[7 | 0x80], canon[99]), (1, 7 | 0x80, 1, 7 | 0x80, 99))
        flags = [int(x[1:], 16) for x in re.findall(r"\$[0-9A-F]{2}", text.split("tile_canon:")[0])]
        self.assertEqual((flags[20], flags[21 | 0x80]), (1, 1), "caps are as solid as their tile")

    def test_levels_are_built_with_the_caps_in_place(self) -> None:
        self.tiles("cap 20 BRICK L", "cap 21 BRICK R", "cap 22 BRICK LR")
        rows = good_rows()
        rows[10] = "." * 3 + "###" + "." * 3 + "#" + "." * 30
        self.p.write("assets/levels/level1.txt", level(rows))
        text = self.p.build().joinpath("levels.inc").read_text()
        self.assertIn("$14,$01,$15,$00,$00,$00,$16", text)  # L, plain, R, gap, single

    def test_pegs_are_found_before_caps_are_applied(self) -> None:
        self.tiles("cap 20 BRICK L", "cap 21 BRICK R", "cap 22 BRICK LR")
        rows = good_rows()
        rows[19] = "." * 10 + "#" * 8 + "." * 22
        rows[18] = "." * 11 + "p" + "." * 28
        self.p.write("assets/levels/level1.txt", level(rows))
        self.assertIn("level1_pegs:\n        .byte 1,40,144,40,68,1", self.p.build().joinpath("levels.inc").read_text())


class DotsAndDoors(unittest.TestCase):
    """The dots in the platforms, the exit door, the palette file."""

    def setUp(self) -> None:
        self.p = Project()
        self.addCleanup(self.p.cleanup)

    def tiles(self, *extra: str) -> None:
        self.p.write("assets/tiles.txt", "\n".join([EMPTY_TILE, SOLID_BRICK, ITEM_TILE, *extra]) + "\n")

    DOT = "dot 30 BRICK\n" + "\n".join(["0330"] * 8)
    CAPS = ["cap 20 BRICK L", "cap 21 BRICK R", "cap 22 BRICK LR"]

    def plain_row(self, text: str) -> list[int]:
        return [{".": 0, "#": 1}[c] for c in text.ljust(ba.COLS, ".")]

    def put(self, plain: list[int], rows: dict[int, str]) -> tuple[list[int], list[int]]:
        grid = [0] * (ba.COLS * ba.ROWS)
        for r, text in rows.items():
            grid[r * ba.COLS : (r + 1) * ba.COLS] = self.plain_row(text)
        caps = ba.apply_caps(grid, {1: {"L": 20, "R": 21, "LR": 22}})
        return grid, caps

    def test_a_dot_goes_in_every_second_middle_tile_of_a_run(self) -> None:
        grid, capped = self.put([], {10: ".###########"})  # 11 tiles in columns 1-11: L, nine middles, R
        out = ba.apply_dots(grid, capped, {1: 30}, {1})
        row = out[10 * ba.COLS : 11 * ba.COLS]
        # the 2nd, 4th, 6th... tile of the run (offsets 1, 3, 5, ... from its first tile), never an end cap
        self.assertEqual([i for i, b in enumerate(row) if b == 30], [2, 4, 6, 8, 10])
        self.assertEqual((row[1], row[11]), (20, 21), "the end caps stay caps")
        self.assertEqual([row[3], row[5], row[7], row[9]], [1, 1, 1, 1], "the tiles between are plain")

    def test_a_short_platform_has_a_dot_if_it_has_a_middle(self) -> None:
        grid, capped = self.put([], {10: "..###", 12: "..##", 14: "..#"})
        out = ba.apply_dots(grid, capped, {1: 30}, {1})
        self.assertEqual(out[10 * ba.COLS + 3], 30, "three tiles: end, middle, end")
        self.assertNotIn(30, out[12 * ba.COLS : 13 * ba.COLS], "two tiles are all ends")
        self.assertNotIn(30, out[14 * ba.COLS : 15 * ba.COLS], "one tile is all end")

    def test_a_floor_that_runs_off_the_screen_has_dots_all_along(self) -> None:
        grid, capped = self.put([], {23: "#" * 40})
        out = ba.apply_dots(grid, capped, {1: 30}, {1})
        row = out[23 * ba.COLS : 24 * ba.COLS]
        self.assertEqual([i for i, b in enumerate(row) if b == 30], list(range(1, 40, 2)))

    def test_no_dot_where_the_player_could_not_stand(self) -> None:
        # a platform in columns 3-9 would have dots in columns 4, 6 and 8
        grid, capped = self.put([], {10: "..." + "#" * 7})
        out = ba.apply_dots(grid, capped, {1: 30}, {1})
        self.assertEqual([c for c in range(40) if out[10 * ba.COLS + c] == 30], [4, 6, 8])
        grid, capped = self.put([], {10: "..." + "#" * 7, 9: "......#"})  # solid right above column 6
        out = ba.apply_dots(grid, capped, {1: 30}, {1})
        self.assertEqual([c for c in range(40) if out[10 * ba.COLS + c] == 30], [4, 8], "nothing to stand on at 6")
        grid, capped = self.put([], {10: "..." + "#" * 7, 8: "........#"})  # solid two above column 8
        out = ba.apply_dots(grid, capped, {1: 30}, {1})
        self.assertEqual([c for c in range(40) if out[10 * ba.COLS + c] == 30], [4, 6], "the player is two tiles tall")

    def test_no_dot_under_spikes(self) -> None:
        self.tiles(*self.CAPS, self.DOT, "tile 5 SPIKE ^\n" + "\n".join(["1111"] * 8))
        rows = good_rows()
        rows[10] = "." * 3 + "#" * 7 + "." * 30  # dots would be at columns 4, 6 and 8
        rows[9] = "." * 6 + "^" + "." * 33
        self.p.write("assets/levels/level1.txt", level(rows))
        text = (self.p.build() / "levels.inc").read_text()
        floor_dots = len(range(1, 40, 2))
        self.assertEqual(int(re.search(r"LEVEL1_ITEMS = (\d+)", text).group(1)), 1 + 2 + floor_dots)  # 1 item, 2 dots, the floor

    def test_dots_are_counted_with_the_items(self) -> None:
        self.tiles(*self.CAPS, self.DOT)
        rows = good_rows()
        rows[10] = "." * 3 + "#" * 9 + "." * 28
        self.p.write("assets/levels/level1.txt", level(rows))
        out = self.p.build()
        text = (out / "levels.inc").read_text()
        self.assertIn("LEVEL1_ITEMS = ", text)
        floor_dots = len(range(1, 40, 2))
        self.assertEqual(int(re.search(r"LEVEL1_ITEMS = (\d+)", text).group(1)), 1 + 4 + floor_dots)  # 1 item + 4 dots + the floor

    def test_the_dotted_tile_is_the_plain_tile_to_the_game(self) -> None:
        self.tiles(*self.CAPS, self.DOT)
        text = self.p.build().joinpath("tileflags.inc").read_text()
        canon = [int(x[1:], 16) for x in re.findall(r"\$[0-9A-F]{2}", text.split("tile_canon:")[1])]
        flags = [int(x[1:], 16) for x in re.findall(r"\$[0-9A-F]{2}", text.split("tile_canon:")[0])]
        self.assertEqual(canon[30], 1)
        self.assertEqual(flags[30], ba.F_SOLID | ba.F_DOT)
        self.assertEqual(flags[1], ba.F_SOLID, "only the dotted twin carries the dot flag")

    def test_a_dotted_twin_of_an_alt_tile_is_alt(self) -> None:
        self.tiles(flagged(7, "ICE", "~", "solid alt"), "dot 30 ICE\n" + "\n".join(["0000"] * 8))
        tiles = {t["name"]: t for t in ba.parse_tiles(self.p.dir / "assets" / "tiles.txt")}
        self.assertEqual((tiles["ICE_DOT"]["byte"], tiles["ICE_DOT"]["solid"]), (30 | 0x80, True))
        self.assertEqual(ba.dot_families(list(tiles.values())), {7 | 0x80: 30 | 0x80})

    def test_bad_dot_lines_are_rejected(self) -> None:
        for line, message in (
            ("dot 30 NOPE", "unknown tile"),
            ("dot 1 BRICK", "duplicate tile id"),
            ("dot 200 BRICK", "must be 0-127"),
            ("dot 30", "expected"),
        ):
            with self.subTest(line):
                self.tiles(line + "\n" + "\n".join(["0000"] * 8))
                with self.assertRaises(ba.AssetError) as cm:
                    self.p.build()
                self.assertIn(message, str(cm.exception))

    DOOR_NAMES = ["DOOR_BL", "DOOR_BR", "DOOR_ML", "DOOR_MR", "DOOR_TL", "DOOR_TR"]

    def door_tiles(self, first: int = 40) -> str:
        return "\n".join(
            f"tile {first + i} {name} {'D' if i == 0 else 'none'} alt\n" + "\n".join(["1111"] * 8)
            for i, name in enumerate(self.DOOR_NAMES)
        )

    def test_a_door_is_six_tiles_from_its_bottom_left_one(self) -> None:
        self.tiles(self.door_tiles())
        rows = good_rows()
        rows[22] = "..@" + "." * 34 + "D.*"
        self.p.write("assets/levels/level1.txt", level(rows))
        text = self.p.build().joinpath("levels.inc").read_text()
        data = [int(x[1:], 16) for x in re.findall(r"\$[0-9A-F]{2}", text.split("level1_spawn:")[0])]
        got = [data[r * 40 + c] for r in (22, 21, 20) for c in (37, 38)]
        self.assertEqual(got, [40 + 128 + i for i in range(6)], "bottom row, middle row, top row, left to right")

    def test_a_level_needs_a_door_and_room_for_it(self) -> None:
        self.tiles(self.door_tiles())
        with self.assertRaises(ba.AssetError) as cm:
            self.p.build()
        self.assertIn("no exit door", str(cm.exception))
        for where in ((21, 37), (20, 38), (22, 38)):
            with self.subTest(where):
                rows = good_rows()
                rows[22] = "..@" + "." * 34 + "D.*"
                line = list(rows[where[0]])
                line[where[1]] = "#"
                rows[where[0]] = "".join(line)
                self.p.write("assets/levels/level1.txt", level(rows))
                with self.assertRaises(ba.AssetError) as cm:
                    self.p.build()
                self.assertIn("empty space", str(cm.exception))

    def test_the_door_tiles_need_consecutive_ids(self) -> None:
        self.tiles(self.door_tiles().replace("tile 43 DOOR_MR", "tile 50 DOOR_MR"))
        with self.assertRaises(ba.AssetError) as cm:
            self.p.build()
        self.assertIn("consecutive", str(cm.exception))

    def test_the_door_fade_order_shows_the_same_number_of_pixels_at_every_step(self) -> None:
        thr = ba.fade_thresholds()
        self.assertEqual(len(thr), 6 * 8 * 4)
        for step in range(ba.FADE_STEPS + 1):
            self.assertEqual(sum(1 for t in thr if t < step), 12 * step)
        text = self.p.build().joinpath("fade.inc").read_text()
        self.assertEqual([int(x[1:], 16) for x in re.findall(r"\$[0-9A-F]{2}", text)], thr)

    def test_the_palette_file_is_checked_and_turned_into_an_include(self) -> None:
        good = "hues 1E 2C 4C 5C 7C 9C AC CC\ngrey 0A\nwhite 0E\nice AC\nhud 2A\nbackground 00\n"
        self.p.write("assets/palette.txt", good)
        text = self.p.build().joinpath("palette.inc").read_text()
        self.assertIn("PAL_GREY  = $0A", text)
        self.assertIn(".byte $1E,$2C,$4C,$5C,$7C,$9C,$AC,$CC", text)
        for bad, message in (
            (good.replace("hues 1E 2C 4C 5C 7C 9C AC CC", "hues 1E 2C"), "needs 8 colours"),
            (good.replace("grey 0A", "grey ZZ"), "hex bytes"),
            (good.replace("grey 0A", "gray 0A"), "unknown palette entry"),
            (good.replace("ice AC\n", ""), "missing palette entries"),
            (good.replace("hud 2A", "hud 1FF"), "00-FF"),
        ):
            with self.subTest(message):
                self.p.write("assets/palette.txt", bad)
                with self.assertRaises(ba.AssetError) as cm:
                    self.p.build()
                self.assertIn(message, str(cm.exception))


class Twins(unittest.TestCase):
    """Tiles whose art is two tiles tall: the twin goes on every odd screen row."""

    CHUTE = flagged(14, "SLIDE_R", "\\", "oneway")
    TWIN = "twin 123 SLIDE_R\n" + "\n".join(["0110"] * 8)

    def setUp(self) -> None:
        self.p = Project()
        self.addCleanup(self.p.cleanup)

    def tiles(self, *extra: str) -> None:
        self.p.write("assets/tiles.txt", "\n".join([EMPTY_TILE, SOLID_BRICK, ITEM_TILE, *extra]) + "\n")

    def test_a_twin_is_a_tile_of_its_own_with_the_flags_of_its_family(self) -> None:
        self.tiles(self.CHUTE, self.TWIN)
        tiles = {t["name"]: t for t in ba.parse_tiles(self.p.dir / "assets" / "tiles.txt")}
        twin = tiles["SLIDE_R_B"]
        self.assertEqual((twin["id"], twin["byte"], twin["char"], twin["oneway"], twin["solid"]), (123, 123, None, True, False))
        self.assertEqual(twin["rows"], ["0110"] * 8)
        self.assertEqual(ba.twin_families(list(tiles.values())), {14: 123})

    def test_the_twin_of_an_alt_tile_is_alt(self) -> None:
        self.tiles(flagged(14, "SLIDE_R", "\\", "oneway alt"), self.TWIN)
        tiles = ba.parse_tiles(self.p.dir / "assets" / "tiles.txt")
        self.assertEqual(ba.twin_families(tiles), {14 | 0x80: 123 | 0x80})

    def test_the_twin_goes_on_odd_screen_rows_only(self) -> None:
        grid = [0] * (ba.COLS * ba.ROWS)
        for r in range(4, 12):  # a stack
            grid[r * ba.COLS + 5] = 14
        grid[4 * ba.COLS + 6] = 1  # something that has no twin
        grid[5 * ba.COLS + 6] = 1
        out = ba.apply_twins(grid, {14: 123})
        self.assertEqual([out[r * ba.COLS + 5] for r in range(4, 12)], [14, 123, 14, 123, 14, 123, 14, 123])
        self.assertEqual((out[4 * ba.COLS + 6], out[5 * ba.COLS + 6]), (1, 1))
        self.assertEqual(grid[5 * ba.COLS + 5], 14, "the input is left alone")

    def test_a_diagonal_run_alternates_too(self) -> None:
        grid = [0] * (ba.COLS * ba.ROWS)
        for k in range(6):
            grid[(4 + k) * ba.COLS + 5 + k] = 14
        out = ba.apply_twins(grid, {14: 123})
        self.assertEqual([out[(4 + k) * ba.COLS + 5 + k] for k in range(6)], [14, 123] * 3)

    def test_a_level_gets_its_twins_and_the_game_sees_the_plain_tile(self) -> None:
        self.tiles(self.CHUTE, self.TWIN)
        rows = good_rows()
        for r in range(15, 21):
            rows[r] = rows[r][:10] + "\\" + rows[r][11:]
        self.p.write("assets/levels/level1.txt", level(rows))
        out = self.p.build()
        text = (out / "levels.inc").read_text()
        data = [int(x[1:], 16) for x in re.findall(r"\$[0-9A-F]{2}", text.split("level1:")[1].split("level1_spawn:")[0])]
        self.assertEqual([data[r * ba.COLS + 10] for r in range(15, 21)], [123, 14, 123, 14, 123, 14])
        flags = (out / "tileflags.inc").read_text()
        canon = [int(x[1:], 16) for x in re.findall(r"\$[0-9A-F]{2}", flags.split("tile_canon:")[1])]
        table = [int(x[1:], 16) for x in re.findall(r"\$[0-9A-F]{2}", flags.split("tile_canon:")[0])]
        self.assertEqual(canon[123], 14)
        self.assertEqual((table[14], table[123]), (ba.F_ONEWAY, ba.F_ONEWAY), "a twin is as one-way as its tile")

    def test_the_dot_flag_and_caps_leave_twins_alone(self) -> None:
        self.tiles(self.CHUTE, self.TWIN)
        self.assertEqual(ba.cap_families(ba.parse_tiles(self.p.dir / "assets" / "tiles.txt")), {})

    def test_bad_twin_lines_are_rejected(self) -> None:
        for lines, message in (
            (["twin 123 NOPE"], "unknown tile"),
            ([self.CHUTE, "twin 14 SLIDE_R"], "duplicate tile id"),
            ([self.CHUTE, "twin 200 SLIDE_R"], "must be 0-127"),
            ([self.CHUTE, "twin x SLIDE_R"], "must be a number"),
            ([self.CHUTE, "twin 123"], "expected 'twin"),
            ([self.CHUTE, self.TWIN, "twin 124 SLIDE_R\n" + "\n".join(["0000"] * 8)], "defined twice"),
            ([self.CHUTE, "twin 123 SLIDE_R\n" + "\n".join(["0000"] * 7)], "needs 8"),
        ):
            with self.subTest(message):
                self.tiles(*lines)
                with self.assertRaises(ba.AssetError) as cm:
                    self.p.build()
                self.assertIn(message, str(cm.exception))

    def test_a_chute_without_a_twin_cannot_be_animated(self) -> None:
        self.tiles(self.CHUTE)
        tiles = ba.parse_tiles(self.p.dir / "assets" / "tiles.txt")
        with self.assertRaises(ba.AssetError):
            ba.helix_rows(tiles, "SLIDE_R")

    def test_a_tile_set_without_chutes_has_an_empty_helix_file(self) -> None:
        self.assertNotIn("helix_r", self.p.build().joinpath("helix.inc").read_text())


class ChuteThread(unittest.TestCase):
    """The real chutes: a screw thread that joins up from tile to tile and turns."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tiles = {t["name"]: t for t in ba.parse_tiles(ROOT / "assets" / "tiles.txt")}
        cls.right = ba.helix_rows(list(cls.tiles.values()), "SLIDE_R")
        cls.left = ba.helix_rows(list(cls.tiles.values()), "SLIDE_L")

    def pixels(self, name: str) -> list[list[int]]:
        out = []
        for t in (self.tiles[name], self.tiles[f"{name}_B"]):
            out += [[int(c) for c in row] for row in t["rows"]]
        return out

    def test_the_chutes_have_twins_that_are_chutes(self) -> None:
        for name in ("SLIDE_R", "SLIDE_L"):
            plain, twin = self.tiles[name], self.tiles[f"{name}_B"]
            self.assertEqual((twin["twin_of"], twin["oneway"], twin["solid"], twin["char"]), (name, False, False, None))  # not solid, not a one-way surface
            self.assertEqual(ba.twin_families(list(self.tiles.values()))[plain["byte"]], twin["byte"])

    def test_the_thread_is_one_diagonal_that_lines_up_from_tile_to_tile(self) -> None:
        # four rows further down the thread is one pixel further across: also over the join of the two tiles
        # and of the twin with the next plain tile (the thread is 16 rows, then it starts again)
        right, left = self.pixels("SLIDE_R"), self.pixels("SLIDE_L")
        for y in range(16):
            for x in range(3):
                self.assertEqual(right[(y + 4) % 16][x], right[y][x + 1], f"right chute, row {y}, column {x}")
                self.assertEqual(left[(y + 4) % 16][x + 1], left[y][x], f"left chute, row {y}, column {x}")

    def test_the_left_chute_is_the_right_one_mirrored(self) -> None:
        r, l = self.pixels("SLIDE_R"), self.pixels("SLIDE_L")
        for y in range(16):
            self.assertEqual(l[y], r[y][::-1])

    def test_the_thread_has_no_gaps_and_no_solid_rows(self) -> None:
        for name in ("SLIDE_R", "SLIDE_L"):
            px = self.pixels(name)
            for y, row in enumerate(px):
                self.assertTrue(any(row), f"{name} row {y} is empty: the thread would break")
                self.assertTrue(0 in row, f"{name} row {y} is solid: it would not look like a thread")
            self.assertTrue(all(any(row[x] for row in px) for x in range(4)), "the thread reaches every column")

    def test_the_thread_is_drawn_with_grey_white_and_the_row_colour(self) -> None:
        used = {v for name in ("SLIDE_R", "SLIDE_L") for row in self.pixels(name) for v in row}
        self.assertEqual(used, {0, 1, 2, 3})

    def test_the_helix_file_is_the_thread_twice_over(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ba.build(ROOT, Path(tmp))
            text = (Path(tmp) / "helix.inc").read_text()
        for label, rows in (("helix_r", self.right), ("helix_l", self.left)):
            body = text.split(label + ":")[1].split("helix_")[0]
            self.assertEqual([int(x[1:], 16) for x in re.findall(r"\$[0-9A-F]{2}", body)], rows * 2)
        self.assertEqual(self.right[:8], [sum(int(c) << (6 - 2 * x) for x, c in enumerate(r)) for r in self.tiles["SLIDE_R"]["rows"]])

    def test_the_thread_moves_one_row_down_every_second_frame_and_comes_round_in_32(self) -> None:
        h = self.right
        for t in range(0, 64):
            a, b = ba.chute_frame(h, t)
            self.assertEqual(a + b, [h[(y + ((t >> 1) & 15 ^ 15)) % 16] for y in range(16)])
            if t % 2 == 0:
                na, nb = ba.chute_frame(h, t + 2)
                self.assertEqual((na + nb)[1:], (a + b)[:-1], "everything moves down by one row")
                self.assertEqual(ba.chute_frame(h, t + 32), (a, b))
            else:
                self.assertEqual(ba.chute_frame(h, t), ba.chute_frame(h, t - 1))

    def test_a_stack_is_one_unbroken_thread_at_every_moment(self) -> None:
        for name, h in (("SLIDE_R", self.right), ("SLIDE_L", self.left)):
            for t in range(0, 32, 2):
                a, b = ba.chute_frame(h, t, name == "SLIDE_L")
                tile = [[(r >> (6 - 2 * x)) & 3 for x in range(4)] for r in a + b]
                for y in range(16):
                    for x in range(3):
                        if name == "SLIDE_R":
                            self.assertEqual(tile[(y + 4) % 16][x], tile[y][x + 1])
                        else:
                            self.assertEqual(tile[(y + 4) % 16][x + 1], tile[y][x])

    def test_the_up_chute_thread_travels_up_the_stack(self) -> None:
        h = self.left
        for t in range(0, 64, 2):
            a, b = ba.chute_frame(h, t, up=True)
            self.assertEqual(a + b, [h[(y + ((t >> 1) & 15)) % 16] for y in range(16)])
            na, nb = ba.chute_frame(h, t + 2, up=True)
            self.assertEqual((na + nb)[:-1], (a + b)[1:], "everything moves up by one row")
            self.assertEqual(ba.chute_frame(h, t + 32, up=True), (a, b))
            self.assertEqual(ba.chute_frame(h, t + 1, up=True), (a, b), "odd frames change nothing")


class RealAssets(unittest.TestCase):
    def test_project_assets_convert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ba.build(ROOT, Path(tmp))
            names = {p.name for p in Path(tmp).iterdir()}
            self.assertEqual(names, {"tiles.inc", "tileflags.inc", "helix.inc", "charset.inc", "font.inc", "palette.inc", "fade.inc", "sprites.inc", "levels.inc", "screens.inc"})
            self.assertIn("T_BRICK", (Path(tmp) / "tiles.inc").read_text())
            self.assertIn("T_DIGIT0       = 16", (Path(tmp) / "tiles.inc").read_text())
            self.assertIn("level1_spawn", (Path(tmp) / "levels.inc").read_text())
            self.assertIn("screen_title", (Path(tmp) / "screens.inc").read_text())
            self.assertIn("screen_gameover", (Path(tmp) / "screens.inc").read_text())

    def test_the_project_has_end_caps_for_every_platform_type(self) -> None:
        tiles = ba.parse_tiles(ROOT / "assets" / "tiles.txt")
        caps = ba.cap_families(tiles)
        by_char = {t["char"]: t for t in tiles if t["char"]}
        for ch in "#=~oXv}>)]{<([":
            with self.subTest(ch):
                self.assertEqual(set(caps[by_char[ch]["byte"]]), {"L", "R", "LR"}, f"{by_char[ch]['name']} needs both ends")
        for ch in "HS\\/":  # ladders, stairs and chutes have no ends
            self.assertNotIn(by_char[ch]["byte"], caps)
        ids = [t["id"] for t in tiles]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertLess(max(ids), 128)

    def test_belt_caps_sit_at_the_ids_the_game_animates(self) -> None:
        by_name = {t["name"]: t["id"] for t in ba.parse_tiles(ROOT / "assets" / "tiles.txt")}
        belts = ["CONV_R_SLOW", "CONV_R", "CONV_R_FAST", "CONV_R_ACC", "CONV_L_SLOW", "CONV_L", "CONV_L_FAST", "CONV_L_ACC"]
        for i, b in enumerate(belts):
            self.assertEqual(by_name[b], 64 + i)
            self.assertEqual((by_name[b + "_L"], by_name[b + "_R"], by_name[b + "_LR"]), (72 + i, 80 + i, 88 + i))

    def test_belt_caps_keep_the_moving_surface_rows(self) -> None:
        tiles = {t["name"]: t for t in ba.parse_tiles(ROOT / "assets" / "tiles.txt")}
        for b in ("CONV_R", "CONV_L_FAST"):
            for kind in ("L", "R", "LR"):
                self.assertEqual(tiles[f"{b}_{kind}"]["rows"][:2], tiles[b]["rows"][:2])

    def test_every_project_level_is_listed_in_the_level_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ba.build(ROOT, Path(tmp))
            text = (Path(tmp) / "levels.inc").read_text()
            n = len(list((ROOT / "assets" / "levels").glob("*.txt")))
            self.assertIn(f"LEVEL_COUNT = {n}", text)
            self.assertIn("level_lo:    .byte <level1,<level2", text)
            self.assertIn("level_sx:", text)

    def test_the_project_font_covers_the_text_the_game_uses(self) -> None:
        glyphs = ba.parse_font(ROOT / "assets" / "font.txt")
        chars = {g["char"] for g in glyphs}
        for needed in set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-!"):
            self.assertIn(needed, chars)


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

    def test_sprite_rows_must_be_eight_wide(self) -> None:
        bad = SPRITE.replace("#......#", "#..#", 1)
        self.rejects("assets/sprites.txt", bad + "\n", "sprite rows are 8")

    def test_sprite_eyes_are_a_second_player(self) -> None:
        self.p.write("assets/sprites.txt", "frame stand\n" + "\n".join(["#ee....#"] * 16) + "\n")
        ((_name, body, eyes, third),) = ba.parse_sprite_frames(self.p.dir / "assets" / "sprites.txt")
        self.assertEqual((body[0], eyes[0], third[0]), (0x81, 0x60, 0))

    def test_the_third_colour_is_the_missiles_in_aligned_pairs(self) -> None:
        # cell k (columns 2k, 2k+1) is missile k: M0 bits 1-0, M1 bits 3-2, M2 bits 5-4, M3 bits 7-6
        rows = ["oo......", "..oo....", "....oo..", "......oo", "oooooooo", "#eoo..e#"] + ["........"] * 10
        self.p.write("assets/sprites.txt", "frame stand\n" + "\n".join(rows) + "\n")
        ((_name, body, eyes, third),) = ba.parse_sprite_frames(self.p.dir / "assets" / "sprites.txt")
        self.assertEqual(third[:6], [0x03, 0x0C, 0x30, 0xC0, 0xFF, 0x0C])
        self.assertEqual((body[5], eyes[5]), (0x81, 0x42), "an 'o' is its own pixel: never body or eye as well")
        self.assertEqual([ba.third_pixels(b) for b in third[:6]], [0xC0, 0x30, 0x0C, 0x03, 0xFF, 0x30])
        out = self.p.build().joinpath("sprites.inc").read_text()
        self.assertIn("spr_third:", out)
        self.assertIn("$03,$0C,$30,$C0,$FF,$0C", out)

    def test_a_lone_third_colour_pixel_is_refused(self) -> None:
        for bad in ("o.......", ".o......", "..o.oo..", "#.oo.o.."):
            with self.subTest(bad):
                self.p.write("assets/sprites.txt", "frame stand\n" + "\n".join([bad] + ["#......#"] * 15) + "\n")
                with self.assertRaises(ba.AssetError) as cm:
                    ba.parse_sprite_frames(self.p.dir / "assets" / "sprites.txt")
                self.assertIn("pairs of pixels", str(cm.exception))
        self.rejects("assets/sprites.txt", "frame stand\n" + "\n".join(["x......."] + ["#......#"] * 15) + "\n", "'#', 'e', 'o' and '.'")

    def test_the_players_colours_come_from_the_palette_file(self) -> None:
        good = "hues 1E 2C 4C 5C 7C 9C AC CC\ngrey 0A\nwhite 0E\nice AC\nhud 2A\nbackground 00\n"
        self.p.write("assets/palette.txt", good)
        text = self.p.build().joinpath("palette.inc").read_text()
        self.assertIn("PAL_PLAYER = $4E", text, "the defaults when the file does not say")
        self.assertIn("PAL_EYES   = $0E", text)
        self.p.write("assets/palette.txt", good + "player 36\neyes 1E\n")
        text = self.p.build().joinpath("palette.inc").read_text()
        self.assertIn("PAL_PLAYER = $36", text)
        self.assertIn("PAL_EYES   = $1E", text)
        self.assertIn("PAL_THIRD  = PAL_ICE", text, "the third colour is the ice colour")
        self.p.write("assets/palette.txt", good + "player 1FF\n")
        with self.assertRaises(ba.AssetError):
            self.p.build()


if __name__ == "__main__":
    unittest.main()
