"""Tests for the factory components: platforms, stairs, belts, ice and rollers, chutes, bomb blocks,
vanishing blocks and pegs. Each one runs the real 6502 code in the emulator.

The tests build their own little arenas: they start a game, wipe the map above the bottom floor
(floor row 23, so a player standing on it has py = 168), and poke the tiles under test straight
into screen RAM. Requires atari800 and ``task build-test``.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from test_game import Base, decode, needs_emulator  # noqa: E402
from tools.headless import (  # noqa: E402
    AIR,
    CLEAR,
    CLEAR_FRAMES,
    DYING,
    FIRE,
    GROUND,
    LEFT,
    PLAY,
    RIGHT,
    SPAWN,
)

T = {m.group(1): int(m.group(2)) for m in re.finditer(r"^T_(\w+)\s*=\s*(\d+)", (ROOT / "src/gen/tiles.inc").read_text(), re.M)}
FLOOR_Y = 168  # py of a player standing on the bottom floor (tile row 23)
PEG_WAIT = 40  # frames a peg rests at each end of its block


class Arena(Base):
    """A started game with an empty room above the floor."""

    def arena(self) -> None:
        g = self.g
        if g.mode == 0:  # still on the title screen (a test may build a second arena)
            g.start_game()
        for r in range(1, 23):
            g.put_tiles(1, r, [0] * 38)
        g.put_tiles(1, 23, [T["BRICK"]] * 38)

    def stand(self, px: int, py: int = FLOOR_Y) -> None:
        g = self.g
        g.poke("px", px)
        g.poke("py", py)
        g.poke("state", GROUND)
        g.poke("fall", 0)
        g.poke("vx", 0)
        g.poke("vfrac", 0)

    def floor(self, col0: int, col1: int, tile: str) -> None:
        self.g.put_tiles(col0, 23, [T[tile]] * (col1 - col0 + 1))

    def goto(self, index: int) -> None:
        """Start a game and go straight to map ``index`` (0-based) the way the game itself does, via the clear screen."""
        g = self.start()
        g.poke("level", index)
        g.poke("lvlidx", index - 1)
        g.poke("mode", CLEAR)
        g.poke("mtimer", CLEAR_FRAMES - 1)
        g.step()
        self.assertEqual((g.mode, g.lvlidx), (SPAWN, index))
        g.run_until(lambda g: g.mode == PLAY, limit=100, every=1)

    def peg(self, i: int = 0) -> tuple[int, int, int]:
        """(x, direction, rest frames left) of peg ``i``."""
        g = self.g
        return g.bss("pg_x", 2)[i], g.bss("pg_dir", 2)[i], g.bss("pg_wait", 2)[i]

    def moved(self, frames: int, buttons: int = 0) -> int:
        before = self.g.px
        self.g.run(frames, buttons)
        return self.g.px - before


@needs_emulator
class OneWayPlatforms(Arena):
    def jump(self) -> None:
        self.g.step(FIRE)
        self.g.run(40)

    def test_you_can_jump_up_through_a_platform_and_land_on_it(self) -> None:
        self.arena()
        self.g.put_tiles(10, 21, [T["PLATFORM"]] * 5)  # top surface 16 pixels above the floor
        self.stand(44)
        self.jump()
        self.assertEqual((self.g.py, self.g.state), (FLOOR_Y - 16, GROUND))

    def highest(self, tile: str) -> int:
        """The smallest py reached by a standing jump under a block of ``tile`` at head height."""
        self.arena()
        self.g.put_tiles(10, 20, [T[tile]] * 5)
        self.stand(44)
        self.g.step(FIRE)
        best = self.g.py
        for _ in range(30):
            self.g.step()
            best = min(best, self.g.py)
        return best

    def test_a_brick_block_over_your_head_stops_the_jump_but_a_platform_does_not(self) -> None:
        self.assertEqual(self.highest("BRICK"), FLOOR_Y, "hit your head at once")
        self.assertLess(self.highest("PLATFORM"), FLOOR_Y - 14, "went up through it")

    def test_you_can_walk_through_a_platform_at_body_height(self) -> None:
        self.arena()
        self.g.put_tiles(10, 21, [T["PLATFORM"]] * 5)
        self.stand(30)
        self.assertEqual(self.moved(20, RIGHT), 20)
        self.assertEqual(self.g.py, FLOOR_Y)

    def test_you_can_walk_along_the_top_of_a_platform_and_off_the_end(self) -> None:
        self.arena()
        self.g.put_tiles(10, 21, [T["PLATFORM"]] * 5)
        self.stand(44, FLOOR_Y - 16)
        self.g.run(10, RIGHT)
        self.assertEqual((self.g.py, self.g.state), (FLOOR_Y - 16, GROUND))
        self.g.run(30, RIGHT)  # walks off the right end (column 14 ends at pixel 60) and drops
        self.assertEqual(self.g.py, FLOOR_Y)


@needs_emulator
class Stairs(Arena):
    def build(self) -> None:
        self.arena()
        for col, row in ((12, 22), (13, 21), (14, 20)):
            self.g.put_tiles(col, row, [T["STAIR"]])

    def test_walk_up_and_down_a_staircase(self) -> None:
        g = self.g
        self.build()
        self.stand(36)
        g.run_until(lambda g: g.py == 144, limit=80, buttons=RIGHT, every=1)  # on the third step
        self.assertEqual(g.state, GROUND)
        self.assertIn(g.px, range(52, 57), "on the top step")
        g.run_until(lambda g: g.py == FLOOR_Y, limit=80, buttons=LEFT, every=1)
        g.run(3)
        self.assertEqual(g.state, GROUND)
        self.assertLess(g.px, 12 * 4)

    def test_each_step_is_one_tile_high(self) -> None:
        g = self.g
        self.build()
        self.stand(36)
        heights = []
        for _ in range(40):
            g.step(RIGHT)
            if not heights or g.py != heights[-1]:
                heights.append(g.py)
        self.assertEqual(heights[:4], [168, 160, 152, 144])

    def test_stairs_do_not_climb_into_a_ceiling(self) -> None:
        g = self.g
        self.build()
        g.put_tiles(13, 19, [T["BRICK"]])  # the second step would put your head in this
        self.stand(36)
        g.run(40, RIGHT)
        self.assertEqual((g.px, g.py), (48, 160))

    def test_stairs_cannot_be_climbed_in_mid_air(self) -> None:
        g = self.g
        self.build()
        g.poke("px", 44)  # the right edge is against the first step
        g.poke("py", 164)  # feet level with it, rising
        g.poke("state", AIR)
        g.poke("jt", 0)
        g.step(RIGHT)
        self.assertEqual(g.px, 44, "blocked by the side of the step, not carried up it")


@needs_emulator
class Belts(Arena):
    def on_belt(self, tile: str, start: int, frames: int = 20, buttons: int = 0) -> int:
        self.arena()
        self.floor(8, 38, tile)
        self.stand(start)
        return self.moved(frames, buttons)

    def test_belt_speeds_to_the_right(self) -> None:
        self.assertEqual(self.on_belt("CONV_R_SLOW", 60), 10)
        self.assertEqual(self.on_belt("CONV_R", 60), 20)
        self.assertEqual(self.on_belt("CONV_R_FAST", 60), 40)

    def test_belt_speeds_to_the_left(self) -> None:
        self.assertEqual(self.on_belt("CONV_L_SLOW", 100), -10)
        self.assertEqual(self.on_belt("CONV_L", 100), -20)
        self.assertEqual(self.on_belt("CONV_L_FAST", 100), -40)

    def test_walking_against_a_belt_goes_nowhere_and_walking_with_it_doubles_your_speed(self) -> None:
        self.assertLessEqual(abs(self.on_belt("CONV_R", 60, buttons=LEFT)), 2)
        self.assertEqual(self.on_belt("CONV_R", 60, buttons=RIGHT), 40)

    def test_an_accelerating_belt_gets_faster(self) -> None:
        self.arena()
        self.floor(1, 38, "CONV_R_ACC")
        self.stand(8)
        first = self.moved(20)
        self.g.run(20)
        self.assertGreaterEqual(self.g.cacc, 4 + 40 // 4 - 1)
        later = self.moved(20)
        self.assertGreater(later, 2 * first)
        self.assertLessEqual(self.g.cacc, 32)

    def test_leaving_an_accelerating_belt_resets_it(self) -> None:
        self.arena()
        self.floor(20, 30, "CONV_R_ACC")
        self.stand(100)
        self.g.run(10)
        self.assertGreater(self.g.cacc, 4, "speeding up on the belt")
        self.g.run_until(lambda g: g.px >= 122, limit=200, every=1)  # the middle of the feet is off the belt
        self.g.run(3)
        self.assertEqual(self.g.cacc, 4)

    def test_a_belt_does_not_move_you_in_the_air(self) -> None:
        self.arena()
        self.floor(8, 38, "CONV_R_FAST")
        self.stand(60)
        self.g.step(FIRE)
        self.assertEqual(self.g.state, AIR)
        before = self.g.px
        self.g.run(10)
        self.assertEqual(self.g.px, before)

    def test_a_belt_cannot_push_you_through_a_wall(self) -> None:
        self.arena()
        self.floor(8, 38, "CONV_R_FAST")
        self.g.put_tiles(20, 21, [T["BRICK"]] * 2)
        self.g.put_tiles(20, 22, [T["BRICK"]] * 2)
        self.stand(60)
        self.g.run(60)
        self.assertEqual(self.g.px, 20 * 4 - 4)

    def test_belt_art_runs_in_the_direction_of_the_belt(self) -> None:
        g = self.g  # on the title screen: the belts animate in every mode
        base = 0x6000 + T["CONV_R"] * 8
        right, left = [], []
        for _ in range(24):
            g.idle()
            page = g.mem(0x6200, 256)
            right.append(page[T["CONV_R"] * 8 - 0x200])
            left.append(page[T["CONV_L"] * 8 - 0x200])
        self.assertEqual(base, 0x6208)
        self.assertEqual(set(right), {0xEA, 0xBA, 0xAE, 0xAB})
        self.assertEqual(set(left), {0xEA, 0xBA, 0xAE, 0xAB})

        def changes(seq):
            return [(a, b) for a, b in zip(seq, seq[1:]) if a != b]

        self.assertIn((0xEA, 0xBA), changes(right))  # right: the bright pixel moves 1 -> 2 -> 3 -> 4 along the tile
        self.assertNotIn((0xEA, 0xAB), changes(right))
        self.assertIn((0xEA, 0xAB), changes(left))  # left: the other way round
        self.assertNotIn((0xEA, 0xBA), changes(left))


@needs_emulator
class Slick(Arena):
    def glide(self, tile: str, run: int = 12) -> int:
        """Walk right for ``run`` frames, let go, and report how far you slide."""
        self.arena()
        self.floor(1, 38, tile)
        self.stand(20)
        self.g.run(run, RIGHT)
        at_release = self.g.px
        self.g.run(80)
        return self.g.px - at_release

    def test_ordinary_floor_stops_you_at_once(self) -> None:
        self.assertEqual(self.glide("BRICK"), 0)

    def test_ice_and_rollers_make_you_slide(self) -> None:
        ice, roller = self.glide("ICE"), self.glide("ROLLER")
        self.assertGreater(roller, 3)
        self.assertGreater(ice, roller + 5, "ice is the more slippery of the two")

    def test_you_build_up_speed_gradually(self) -> None:
        self.arena()
        self.floor(1, 38, "ICE")
        self.stand(20)
        positions = []
        for _ in range(30):
            self.g.step(RIGHT)
            positions.append(self.g.px)
        steps = [b - a for a, b in zip(positions, positions[1:])]
        self.assertEqual(positions[0], 20, "no movement on the first frame")
        self.assertLessEqual(sum(steps[:6]), 3)
        self.assertGreaterEqual(sum(steps[-6:]), 6)
        self.assertLessEqual(max(steps), 2)

    def test_turning_round_takes_a_while(self) -> None:
        g = self.g
        self.arena()
        self.floor(1, 38, "ICE")
        self.stand(20)
        g.run(14, RIGHT)
        at_turn = g.px
        g.run(4, LEFT)
        self.assertGreater(g.px, at_turn, "still sliding right")
        g.run(60, LEFT)
        self.assertLess(g.px, at_turn)

    def test_sliding_into_a_wall_stops_you(self) -> None:
        g = self.g
        self.arena()
        self.floor(1, 38, "ICE")
        g.put_tiles(20, 21, [T["BRICK"]] * 2)
        g.put_tiles(20, 22, [T["BRICK"]] * 2)
        self.stand(60)
        g.run(40, RIGHT)
        self.assertEqual(g.px, 20 * 4 - 4)
        self.assertLessEqual(g.vx, 2, "the wall takes all your speed")

    def test_ice_is_solid_and_you_can_stand_and_jump_on_it(self) -> None:
        g = self.g
        self.arena()
        self.floor(1, 38, "ICE")
        self.stand(60)
        g.run(3)
        self.assertEqual((g.py, g.state), (FLOOR_Y, GROUND))
        g.step(FIRE)
        self.assertEqual(g.state, AIR)
        g.run(40)
        self.assertEqual((g.py, g.state), (FLOOR_Y, GROUND))

    def test_the_slide_ends_at_the_edge_of_the_ice(self) -> None:
        g = self.g
        self.arena()
        self.floor(1, 38, "BRICK")
        self.floor(5, 12, "ICE")
        self.stand(24)
        g.run(15, RIGHT)
        g.run(80)
        px = g.px
        g.run(20)
        self.assertEqual(g.px, px, "came to rest")


@needs_emulator
class Chutes(Arena):
    def test_a_chute_carries_you_down_to_the_floor_without_any_input(self) -> None:
        g = self.g
        self.arena()
        g.put_tiles(5, 20, [T["BRICK"]] * 5)
        g.put_tiles(10, 21, [T["SLIDE_R"]])
        g.put_tiles(11, 22, [T["SLIDE_R"]])
        self.stand(24, 144)
        g.run_until(lambda g: g.under == T["SLIDE_R"], limit=60, buttons=RIGHT, every=1)
        g.run(40)
        self.assertGreaterEqual(g.px, 48)
        self.assertEqual((g.py, g.state), (FLOOR_Y, GROUND))

    def test_a_chute_to_the_left(self) -> None:
        g = self.g
        self.arena()
        g.put_tiles(30, 20, [T["BRICK"]] * 5)
        g.put_tiles(29, 21, [T["SLIDE_L"]])
        g.put_tiles(28, 22, [T["SLIDE_L"]])
        self.stand(130, 144)
        g.run_until(lambda g: g.under == T["SLIDE_L"], limit=60, buttons=LEFT, every=1)
        g.run(40)
        self.assertLessEqual(g.px, 108)
        self.assertEqual((g.py, g.state), (FLOOR_Y, GROUND))

    def test_you_cannot_walk_up_a_chute(self) -> None:
        g = self.g
        self.arena()
        g.put_tiles(12, 22, [T["SLIDE_R"]])
        self.stand(36)
        g.run(30, RIGHT)
        self.assertEqual((g.px, g.py), (44, FLOOR_Y))  # stopped by it; only stairs can be climbed


@needs_emulator
class VanishingBlocks(Arena):
    def build(self) -> None:
        self.arena()
        self.g.put_tiles(10, 20, [T["VANISH"]] * 3)
        self.stand(40, 144)

    def test_a_vanishing_block_goes_after_a_while_and_only_the_one_you_stood_on(self) -> None:
        g = self.g
        self.build()
        g.run(10)
        self.assertIn(g.tile(10, 20), (T["VANISH"], T["VANISH_B"]))
        g.run(10)
        self.assertEqual(g.py, 144, "still standing on it")
        g.run(25)
        self.assertEqual(g.tile(10, 20), 0)
        self.assertEqual((g.tile(11, 20), g.tile(12, 20)), (T["VANISH"], T["VANISH"]))
        g.run(15)
        self.assertEqual((g.py, g.state), (FLOOR_Y, GROUND), "fell to the floor")

    def test_it_flickers_while_the_fuse_burns(self) -> None:
        g = self.g
        self.build()
        seen = set()
        for _ in range(28):
            g.step()
            seen.add(g.tile(10, 20))
        self.assertEqual(seen, {T["VANISH"], T["VANISH_B"]})

    def test_it_comes_back(self) -> None:
        g = self.g
        self.build()
        g.run(40)
        self.assertEqual(g.tile(10, 20), 0)
        g.run(150)
        self.assertEqual(g.tile(10, 20), 0, "back only after about three seconds")
        g.run(60)
        self.assertEqual(g.tile(10, 20), T["VANISH"])

    def test_you_can_run_across_a_row_of_them(self) -> None:
        g = self.g
        self.arena()
        g.put_tiles(10, 20, [T["VANISH"]] * 6)
        g.put_tiles(4, 20, [T["BRICK"]] * 6)
        g.put_tiles(16, 20, [T["BRICK"]] * 6)
        self.stand(30, 144)
        g.run(50, RIGHT)
        self.assertEqual((g.py, g.state), (144, GROUND))
        self.assertGreater(g.px, 16 * 4)


@needs_emulator
class BombBlocks(Arena):
    def build(self, px: int) -> None:
        self.arena()
        self.g.put_tiles(10, 20, [T["EXPLOSIVE"]] * 3)
        self.stand(px, 144)

    def test_stay_on_a_bomb_block_and_it_kills_you(self) -> None:
        g = self.g
        self.build(40)
        frames = g.run_until(lambda g: g.mode == DYING, limit=80, every=1)
        self.assertTrue(40 <= frames <= 50, frames)
        self.assertEqual(g.tile(10, 20), T["BOOM"])

    def test_the_fuse_is_visible(self) -> None:
        g = self.g
        self.build(40)
        seen = set()
        for _ in range(30):
            g.step()
            seen.add(g.tile(10, 20))
        self.assertEqual(seen, {T["EXPLOSIVE"], T["EXPLOSIVE_B"]})

    def test_run_away_and_the_whole_row_goes_off_in_a_chain(self) -> None:
        g = self.g
        self.build(48)  # on the right-hand block
        lives = g.lives
        g.run_until(lambda g: g.tile(12, 20) == T["BOOM"], limit=80, buttons=RIGHT, every=1)
        self.assertIn(g.tile(11, 20), (T["EXPLOSIVE"], T["EXPLOSIVE_B"]), "the next one is lit but has not gone yet")
        g.run(90, RIGHT)
        self.assertEqual([g.tile(c, 20) for c in (10, 11, 12)], [0, 0, 0])
        self.assertEqual((g.mode, g.lives), (PLAY, lives), "you got clear")

    def test_a_blast_takes_out_bomb_blocks_above_and_below_it_too(self) -> None:
        g = self.g
        self.arena()
        g.put_tiles(10, 20, [T["EXPLOSIVE"]])
        g.put_tiles(10, 19, [T["EXPLOSIVE"]])
        g.put_tiles(14, 20, [T["EXPLOSIVE"]])  # not adjacent: unaffected
        self.stand(40, 144)
        g.run(80, LEFT)  # step off and run
        self.assertEqual((g.tile(10, 20), g.tile(10, 19)), (0, 0))
        self.assertEqual(g.tile(14, 20), T["EXPLOSIVE"])

    def test_the_blast_does_not_reach_far(self) -> None:
        g = self.g
        self.build(48)
        g.run_until(lambda g: g.tile(12, 20) == T["BOOM"], limit=80, buttons=RIGHT, every=1)
        self.assertEqual(g.mode, PLAY)
        self.assertGreater(g.px, 60)

    def test_only_standing_on_a_block_lights_it(self) -> None:
        g = self.g
        self.build(100)  # elsewhere on the floor
        g.run(100)
        self.assertEqual([g.tile(c, 20) for c in (10, 11, 12)], [T["EXPLOSIVE"]] * 3)
        self.assertEqual(g.mode, PLAY)

    def test_jumping_over_a_bomb_block_does_not_light_it(self) -> None:
        g = self.g
        self.arena()
        g.put_tiles(10, 22, [T["EXPLOSIVE"]])
        self.stand(28)
        g.step(FIRE | RIGHT)
        g.run(30, RIGHT)
        g.run(80)
        self.assertEqual(g.mode, PLAY)


@needs_emulator
class Pegs(Arena):
    """Map 5 (index 4) has one peg on a floating block in tile columns 24-31, row 11."""

    def test_the_peg_starts_at_the_end_of_its_block_nearest_where_it_was_placed(self) -> None:
        self.goto(4)
        self.assertEqual(self.g.pg_n, 1)
        x, d, _ = self.peg()
        self.assertEqual((x, d), (31 * 4, 255), "starts at the right end, heading left")
        self.assertEqual(bytes(self.g.bss("pg_y", 1)), bytes([80]))
        page = self.g.mem(self.g.pm0 + 0x100, 256)  # Player 1
        self.assertEqual(page[32 + 80 : 32 + 88], bytes([0x60, 0xF0, 0xF0, 0xF0, 0xF0, 0xF0, 0xF0, 0x90]))

    def test_the_peg_sweeps_its_block_end_to_end_and_rests_at_each_end(self) -> None:
        self.goto(4)
        g = self.g
        xs = []
        for _ in range(60):
            g.run(10)
            xs.append(self.peg())
        lo, hi = 23 * 4, 31 * 4  # the stair at column 23 is part of the platform it walks on
        self.assertTrue(all(lo <= x <= hi for x, _, _ in xs), [x for x, _, _ in xs])
        self.assertEqual((min(x for x, _, _ in xs), max(x for x, _, _ in xs)), (lo, hi))
        self.assertEqual({d for _, d, _ in xs}, {1, 255})
        self.assertTrue(any(w > 0 for _, _, w in xs), "it rests at the ends")

    def test_the_peg_moves_half_a_pixel_a_frame_after_its_rest(self) -> None:
        self.goto(4)
        g = self.g
        g.run(PEG_WAIT + 1)
        x0 = self.peg()[0]
        g.run(40)
        self.assertEqual(x0 - self.peg()[0], 20)

    def test_the_peg_pushes_you_along_ahead_of_it(self) -> None:
        self.goto(4)
        g = self.g
        self.stand(100, 72)  # on the block
        g.run(150)
        self.assertEqual(g.mode, PLAY)
        self.assertLess(g.px, 100 - 8)

    def test_the_peg_leaves_you_alone_when_you_are_behind_it(self) -> None:
        self.goto(4)
        g = self.g
        self.stand(126, 72)
        g.run(PEG_WAIT - 5)
        self.assertEqual((g.px, g.py), (126, 72))

    def test_you_can_jump_over_a_peg(self) -> None:
        self.goto(4)
        g = self.g
        self.stand(100, 72)
        g.run_until(lambda g: self.peg()[0] <= g.px + 14, limit=200, every=1)
        g.step(FIRE | RIGHT)
        g.run(21, RIGHT)
        g.run(8)
        peg_x = self.peg()[0]
        self.assertEqual((g.mode, g.state), (PLAY, GROUND))
        self.assertGreater(g.px, peg_x + 3, "got to the other side")
        self.assertEqual(g.py, 72, "still on the block")

    def test_pegs_do_not_exist_in_levels_without_them(self) -> None:
        self.goto(1)
        self.assertEqual(self.g.pg_n, 0)
        self.assertEqual(self.g.mem(self.g.pm0 + 0x100, 256), bytes(256))


@needs_emulator
class FactoryLevels(Arena):
    def count_items(self, n: int) -> int:
        text = (ROOT / "assets" / "levels" / f"level{n}.txt").read_text()
        return sum(line.count("*") for line in text.splitlines() if not line.startswith("# "))

    def test_map_4_loads(self) -> None:
        self.goto(3)
        g = self.g
        self.assertEqual((g.level, g.lvlidx, g.left), (4, 3, self.count_items(4)))
        self.assertEqual(g.pg_n, 0)
        self.assertEqual((g.px, g.py, g.state), (8, 168, GROUND))
        self.assertIn("LEVEL 04", self.hud_text())

    def test_map_5_loads(self) -> None:
        self.goto(4)
        g = self.g
        self.assertEqual((g.level, g.lvlidx, g.left), (5, 4, self.count_items(5)))
        self.assertEqual((g.px, g.py, g.state), (8, 168, GROUND))

    def hud_text(self) -> str:
        return decode(self.g.mem(self.g.screen_addr, 256)[:40])

    def test_map_4_has_belts_that_animate_and_ice(self) -> None:
        self.goto(3)
        row = self.g.mem(self.g.screen_addr + 23 * 40, 256)[:40]
        self.assertIn(T["CONV_R_FAST"], row)
        self.assertIn(T["ICE"], row)

    def test_after_the_last_map_a_game_goes_back_to_map_1(self) -> None:
        g = self.start()
        g.poke("lvlidx", 4)
        g.poke("mode", CLEAR)
        g.poke("mtimer", CLEAR_FRAMES - 1)
        g.step()
        self.assertEqual(g.lvlidx, 0)

    def test_the_attract_mode_stays_on_the_maps_the_ai_can_play(self) -> None:
        g = self.start()
        g.poke("demo", 1)
        g.poke("lvlidx", 2)
        g.poke("mode", CLEAR)
        g.poke("mtimer", CLEAR_FRAMES - 1)
        g.step()
        self.assertEqual(g.lvlidx, 0)
        g.poke("demo", 0)


if __name__ == "__main__":
    import unittest

    unittest.main()
