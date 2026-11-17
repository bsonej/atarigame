"""Game-logic tests: run the real 6502 code headlessly and check what the player does.

Requires atari800 and the TEST build (``task build-test``); skipped when either is missing.
Level 1 reference (tile column, row): spawn (3,21); floors at rows 23, 18, 13, 8; ladders at
(8, rows 18-22), (31, 18-22), (20, 13-17), (33, 8-12), (5, 8-12); a hole in row 18 at columns 24-27;
items at (14,22) (26,22) (12,17) (30,17) (10,12) (28,12) (12,7) (24,7); spikes at (20,22) (16,17) (15,12).
"""

from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.headless import (  # noqa: E402
    AIR,
    CLIMB,
    COLS,
    DOWN,
    FIRE,
    GROUND,
    LABELS,
    LEFT,
    RIGHT,
    UP,
    XEX,
    Game,
)

T_EMPTY, T_BRICK, T_LADDER, T_ITEM, T_SPIKE = 0, 1, 2, 3, 4
SPAWN_X, SPAWN_Y = 12, 168  # tile (3,21)
FLOOR_Y = {23: 168, 18: 128, 13: 88, 8: 48}  # py of a player standing on the floor in that tile row


@unittest.skipUnless(shutil.which("atari800") and XEX.exists() and LABELS.exists(), "needs atari800 and `task build-test`")
class GameLogic(unittest.TestCase):
    def setUp(self) -> None:
        self.g = Game()
        self.addCleanup(self.g.close)

    # ---- helpers ----
    def walk_to(self, px: int) -> None:
        g = self.g
        while g.px != px:
            before = g.px
            g.step(RIGHT if g.px < px else LEFT)
            self.assertNotEqual(g.px, before, f"stuck at {g.px} wanting {px}")

    # ---- start ----
    def test_starts_on_the_floor_with_a_full_level(self) -> None:
        g = self.g
        self.assertEqual((g.px, g.py, g.state), (SPAWN_X, SPAWN_Y, GROUND))
        self.assertEqual((g.left, g.score), (8, 0))
        self.assertEqual(g.tile(8, 20), T_LADDER)
        self.assertEqual(g.tile(14, 22), T_ITEM)
        self.assertEqual(g.tile(20, 22), T_SPIKE)
        self.assertEqual(g.tile(0, 10), T_BRICK)

    def test_idle_player_does_not_move(self) -> None:
        self.g.idle(30)
        self.assertEqual((self.g.px, self.g.py, self.g.state), (SPAWN_X, SPAWN_Y, GROUND))

    # ---- walking ----
    def test_walks_one_pixel_per_frame_and_animates(self) -> None:
        g = self.g
        g.step(RIGHT, 10)
        self.assertEqual(g.px, SPAWN_X + 10)
        self.assertEqual(g.moved, 1)
        a = g.sprite()
        g.step(RIGHT, 4)
        self.assertNotEqual(g.sprite(), a, "walk frames should alternate every 4 pixels")
        g.step(LEFT, 14)
        self.assertEqual(g.px, SPAWN_X)

    def test_left_wall_stops_the_player(self) -> None:
        g = self.g
        g.step(LEFT, 40)
        self.assertEqual(g.px, 4)  # the wall tile fills pixels 0-3
        self.assertEqual(g.state, GROUND)

    def test_right_wall_stops_the_player(self) -> None:
        g = self.g
        # Walk along the floor to the right wall (jumping the spikes at tile 20 first).
        self.walk_to(72)
        g.step(RIGHT | FIRE)
        g.step(RIGHT, 30)
        g.step(RIGHT, 80)
        self.assertEqual(g.px, 152)  # wall tile at column 39 fills pixels 156-159
        self.assertEqual(g.state, GROUND)

    # ---- jumping ----
    def test_jump_rises_18_pixels_and_lands(self) -> None:
        g = self.g
        g.poke("px", 80)  # top floor, open air above
        g.poke("py", FLOOR_Y[8])
        g.idle(2)
        self.assertEqual((g.py, g.state), (FLOOR_Y[8], GROUND))
        g.step(FIRE)
        self.assertEqual(g.state, AIR)
        ys = []
        for _ in range(40):
            g.idle()
            ys.append(g.py)
            if g.state == GROUND:
                break
        apex = ys.index(min(ys))
        self.assertEqual(min(ys), FLOOR_Y[8] - 18)
        self.assertEqual((g.py, g.state), (FLOOR_Y[8], GROUND))
        self.assertEqual(ys[apex:], sorted(ys[apex:]), "no bouncing after the apex")

    def test_jump_is_limited_by_the_ceiling_on_lower_floors(self) -> None:
        g = self.g
        g.step(FIRE)
        ys = []
        for _ in range(40):
            g.idle()
            ys.append(g.py)
            if g.state == GROUND:
                break
        self.assertEqual(min(ys), 152)  # row 18's bricks end at line 151
        self.assertEqual((g.py, g.state), (SPAWN_Y, GROUND))

    def test_holding_fire_does_not_bunny_hop(self) -> None:
        g = self.g
        g.step(FIRE, 80)
        self.assertEqual(g.state, GROUND)  # one jump, then it waits for a fresh press

    def test_can_steer_in_the_air(self) -> None:
        g = self.g
        g.step(FIRE | RIGHT)
        g.step(RIGHT, 10)
        self.assertGreater(g.px, SPAWN_X + 8)
        g.idle(30)
        self.assertEqual((g.py, g.state), (SPAWN_Y, GROUND))

    def test_head_bump_under_a_floor(self) -> None:
        g = self.g
        self.walk_to(40)  # open floor under row 18 (the ladder at column 8 is behind us)
        g.step(FIRE)
        top = min([g.py] + [(g.step(0) or g.py) for _ in range(30)])
        # Row 18 is brick down to line 151; a 16-line player can rise at most to py=152 (+ ceiling)
        self.assertGreaterEqual(top, 152 - 0)
        self.assertEqual(g.state, GROUND)

    # ---- ladders ----
    def climb_ladder_8(self):
        g = self.g
        self.walk_to(32)  # column 8
        g.step(UP)
        return g

    def test_climbs_a_ladder_to_the_floor_above(self) -> None:
        g = self.climb_ladder_8()
        self.assertEqual(g.state, CLIMB)
        self.assertEqual(g.px, 32)
        for _ in range(80):
            g.step(UP)
            if g.state == GROUND:
                break
        self.assertEqual((g.state, g.py), (GROUND, FLOOR_Y[18]))

    def test_climbs_back_down_and_stops_on_the_floor(self) -> None:
        g = self.climb_ladder_8()
        g.step(UP, 80)
        self.assertEqual((g.state, g.py), (GROUND, FLOOR_Y[18]))
        g.step(DOWN)  # standing on top of the ladder: down grabs it again
        self.assertEqual(g.state, CLIMB)
        g.step(DOWN, 80)
        self.assertEqual((g.state, g.py), (GROUND, FLOOR_Y[23]))

    def test_cannot_climb_without_a_ladder(self) -> None:
        g = self.g
        g.step(UP, 20)
        self.assertEqual((g.state, g.py), (GROUND, SPAWN_Y))

    def test_steps_off_a_ladder_onto_a_floor_but_not_into_the_void(self) -> None:
        g = self.climb_ladder_8()
        g.step(UP, 20)  # partway up, nothing to stand on at the sides
        self.assertEqual(g.state, CLIMB)
        g.step(RIGHT, 10)
        self.assertEqual((g.state, g.px), (CLIMB, 32))
        g.step(UP, 80)
        g.step(RIGHT, 10)  # on the floor above: walking resumes
        self.assertEqual(g.state, GROUND)
        self.assertGreater(g.px, 32)

    def test_cannot_walk_off_the_end_of_a_ladder_into_a_wall(self) -> None:
        g = self.climb_ladder_8()
        g.step(UP, 80)
        g.step(LEFT, 60)
        self.assertEqual(g.state, GROUND)
        self.assertGreaterEqual(g.px, 4)

    # ---- items, spikes, falling ----
    def test_collects_an_item(self) -> None:
        g = self.g
        self.walk_to(14 * 4 - 2)
        g.idle()
        self.assertEqual((g.score, g.left), (1, 7))
        self.assertEqual(g.tile(14, 22), T_EMPTY)
        self.assertEqual(g.tile(15, 22), T_EMPTY)  # nothing else removed
        g.step(RIGHT, 8)
        self.assertEqual(g.score, 1, "an item is only collected once")

    def test_hud_shows_the_score_in_digit_tiles(self) -> None:
        g = self.g
        raw = g.mem(0x4500, 256)
        self.assertEqual(raw[1:4], bytes([16, 16, 16]))  # 000
        self.assertEqual(raw[36:39], bytes([16, 16, 24]))  # 008 items to go
        self.walk_to(14 * 4 - 2)
        g.idle()
        raw = g.mem(0x4500, 256)
        self.assertEqual(raw[1:4], bytes([16, 16, 17]))  # 001
        self.assertEqual(raw[36:39], bytes([16, 16, 23]))  # 007

    def test_spikes_kill_and_reset_the_level(self) -> None:
        g = self.g
        self.walk_to(14 * 4)  # pick up the item at column 14 first
        g.idle()
        self.assertEqual(g.score, 1)
        self.walk_to(76)
        for _ in range(6):
            g.step(RIGHT)
            if g.score == 0:
                break
        self.assertEqual((g.score, g.left, g.px, g.py, g.state), (0, 8, SPAWN_X, SPAWN_Y, GROUND))
        self.assertEqual(g.tile(14, 22), T_ITEM, "the level is restored after dying")
        self.assertGreater(g.flash, 0)

    def test_jumping_over_spikes_is_safe(self) -> None:
        g = self.g
        self.walk_to(14 * 4)
        self.walk_to(72)  # two tiles before the spikes at column 20 (pixels 80-83)
        g.step(FIRE | RIGHT)
        for _ in range(40):
            g.step(RIGHT)
            if g.state == GROUND:
                break
        self.assertGreater(g.px, 84, "cleared the spikes")
        self.assertGreater(g.score, 0, "still alive")

    def test_small_drops_are_safe(self) -> None:
        g = self.g
        g.step(UP, 0)
        # Poke the player onto the row-18 floor, then walk into the hole at columns 24-27.
        g.poke("px", 80)
        g.poke("py", FLOOR_Y[18])
        g.idle(2)
        self.assertEqual(g.state, GROUND)
        g.step(RIGHT, 40)
        self.assertEqual((g.state, g.py), (GROUND, FLOOR_Y[23]))  # dropped one floor and survived
        self.assertGreater(g.score + g.left, 0)

    def test_long_fall_kills(self) -> None:
        g = self.g
        g.poke("state", AIR)
        g.poke("jt", 0xFF)
        g.poke("py", 100)
        g.poke("px", 60)
        g.poke("fall", 100)  # already fallen a long way when we touch down
        g.step(0, 30)
        self.assertEqual((g.px, g.py, g.state, g.score), (SPAWN_X, SPAWN_Y, GROUND, 0))
        self.assertGreater(g.flash + 0, -1)

    def test_clearing_all_items_restarts_the_level(self) -> None:
        g = self.g
        g.step(RIGHT, 20)  # pick up nothing yet; then make the next item the last one
        g.poke("left", 1)
        for _ in range(40):
            g.step(RIGHT)
            if g.left != 1:
                break
        self.assertEqual(g.left, 8, "level reloaded")
        self.assertEqual((g.px, g.py), (SPAWN_X, SPAWN_Y))
        self.assertGreater(g.score, 0, "the score survives a cleared level")

    # ---- display ----
    def test_player_sprite_is_in_player_memory(self) -> None:
        g = self.g
        sprite = g.sprite()
        self.assertEqual(len(sprite), 16)
        self.assertEqual(sprite[1], 0xF0)  # the head/hat row of the stand frame
        g.step(UP | RIGHT, 0)

    def test_sprite_follows_the_player_vertically(self) -> None:
        g = self.g
        before = g.sprite()
        g.step(FIRE, 3)
        self.assertNotEqual(g.py, SPAWN_Y)
        self.assertEqual(g.sprite()[1], 0xF0)
        raw = g.mem(0x5400, 256)
        old = (0x5420 & 0xFF) + SPAWN_Y
        self.assertEqual(raw[old + 15], 0, "no stale image left at the old position")
        self.assertEqual(before[1], 0xF0)

    def test_level_data_matches_the_source_file(self) -> None:
        g = self.g
        lines = [
            l for l in (Path(__file__).resolve().parent.parent / "assets" / "levels" / "level1.txt").read_text().splitlines()
            if l and not l.startswith("# ")
        ]
        tiles = {".": 0, "#": 1, "H": 2, "*": 3, "^": 4, "@": 0}
        expected = bytes(tiles[c] for row in lines for c in row)
        self.assertEqual(len(expected), COLS * 24)
        self.assertEqual(g.mem(0x4500, 1024)[: COLS * 24][COLS:], expected[COLS:])  # ignoring the HUD row


if __name__ == "__main__":
    unittest.main()
