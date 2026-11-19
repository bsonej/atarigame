"""Tests for the factory components: platforms, stairs, belts, ice and rollers, chutes (vertical lifts), bomb blocks,
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
from tools import build_assets as ba  # noqa: E402
from tools.headless import (  # noqa: E402
    AIR,
    CLEAR,
    CLEAR_FRAMES,
    DIE_FRAMES,
    DYING,
    FIRE,
    GROUND,
    LEFT,
    PLAY,
    RIDE,
    RIGHT,
    SPAWN,
)

T = {m.group(1): int(m.group(2)) for m in re.finditer(r"^T_(\w+)\s*=\s*(\d+)", (ROOT / "src/gen/tiles.inc").read_text(), re.M)}
FLOOR_Y = 168  # py of a player standing on the bottom floor (tile row 23)
TILES = ba.parse_tiles(ROOT / "assets" / "tiles.txt")
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

    def test_neither_a_brick_block_nor_a_platform_over_your_head_stops_the_jump(self) -> None:
        self.assertEqual(self.highest("BRICK"), FLOOR_Y - 26, "went up through it: no head bump any more")
        self.assertEqual(self.highest("PLATFORM"), FLOOR_Y - 26, "went up through it")

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
class ItemsAtHisLevel(Arena):
    """An item is collected only at HIS level: it must be in the row his feet are in (py+13) and he must not be rising
    (jumping up, hopping out of a chute, riding up). Walking or jumping up under it does not take it."""

    ITEM_ROW_FEET = 22  # on the floor (py = 168) his body is rows 21 (head) and 22 (feet)

    def setUp(self) -> None:
        super().setUp()
        self.arena()
        self.g.poke("left", 9)  # never the last one: the door must not open

    def test_walking_under_an_item_at_head_height_does_not_collect_it(self) -> None:
        g = self.g
        g.put_tiles(10, 21, [T["ITEM"]])
        self.stand(30)
        g.run(40, RIGHT)  # right through its column (pixels 40-43)
        self.assertGreater(g.px, 50)
        self.assertEqual((g.left, g.score16), (9, 0))
        self.assertEqual(g.tile(10, 21), T["ITEM"], "still there")

    def test_walking_into_an_item_at_his_level_collects_it(self) -> None:
        g = self.g
        g.put_tiles(10, self.ITEM_ROW_FEET, [T["ITEM"]])
        self.stand(30)
        g.run(40, RIGHT)
        self.assertEqual((g.left, g.score16), (8, 10))
        self.assertEqual(g.tile(10, self.ITEM_ROW_FEET), T["EMPTY"])

    def test_jumping_up_under_an_item_does_not_collect_it_but_standing_at_its_level_does(self) -> None:
        g = self.g
        g.put_tiles(10, 20, [T["PLATFORM"]] * 5)  # a ledge 3 tiles up (reached by the jump) ...
        g.put_tiles(12, 19, [T["ITEM"]])  # ... with an item on it (tile column 12 = pixels 48-51)
        self.stand(48)
        g.step(FIRE)
        while g.state == AIR and g.jt != 0xFF:  # the whole rise, through the head row, the body row ...
            self.assertEqual((g.left, g.score16), (9, 0), f"nothing collected while rising (py {g.py})")
            g.step()
        self.assertLess(g.py, FLOOR_Y - 20, "he did rise")
        g.run(40)  # ... then the fall onto the ledge: now his feet are at the item's level
        self.assertEqual((g.py, g.state), (FLOOR_Y - 24, GROUND))
        self.assertEqual((g.left, g.score16), (8, 10), "collected when he is on its level")

    def test_an_item_above_the_ledge_head_row_is_not_collected_by_standing_on_the_ledge(self) -> None:
        g = self.g
        g.put_tiles(10, 20, [T["PLATFORM"]] * 5)
        g.put_tiles(12, 18, [T["ITEM"]])  # two tiles above the ledge: at his head, not his feet
        self.stand(48, FLOOR_Y - 24)
        g.run(30)
        self.assertEqual((g.left, g.score16), (9, 0))

    def test_falling_past_an_item_at_feet_level_collects_it(self) -> None:
        g = self.g
        g.put_tiles(12, 16, [T["ITEM"]])
        self.stand(48, 110)  # (a fall of 58 pixels: under MAX_FALL)
        g.poke("state", AIR)
        g.poke("jt", 0xFF)
        g.run(50)  # drops 2 pixels a frame down to the floor (34 frames)
        self.assertEqual((g.py, g.state), (FLOOR_Y, GROUND))
        self.assertEqual((g.left, g.score16), (8, 10))


@needs_emulator
class Stairs(Arena):
    """Steps are thin ledges: you walk straight past them and jump up onto them."""

    def build(self) -> None:
        self.arena()
        for col, row in ((12, 22), (13, 21), (14, 20)):
            self.g.put_tiles(col, row, [T["STAIR"]])

    def test_you_walk_straight_past_a_step(self) -> None:
        g = self.g
        self.build()
        self.stand(36)
        g.run(40, RIGHT)
        self.assertGreater(g.px, 60)
        self.assertEqual((g.py, g.state), (FLOOR_Y, GROUND), "not carried up it")

    def test_you_jump_up_through_a_step_and_land_on_it(self) -> None:
        g = self.g
        self.build()
        self.stand(48)  # under the first step (column 12)
        g.step(FIRE)
        g.run_until(lambda g: g.state == GROUND, limit=60, every=1)
        self.assertEqual((g.px, g.py), (48, FLOOR_Y - 8))

    def test_a_step_is_walked_off_at_its_end(self) -> None:
        g = self.g
        self.build()
        self.stand(48, FLOOR_Y - 8)  # on the first step
        g.run(40, LEFT)
        self.assertEqual((g.py, g.state), (FLOOR_Y, GROUND), "dropped to the floor")

    def test_a_flight_of_steps_is_climbed_by_jumping(self) -> None:
        g = self.g
        self.build()
        self.stand(50, FLOOR_Y - 8)  # on the first step, at its right hand end
        g.step(FIRE)
        g.run(6)  # rising straight up, through the second step, which is beside him
        while g.px < 53:
            g.step(RIGHT)
        g.run_until(lambda g: g.state == GROUND, limit=60, every=1)
        self.assertIn(g.py, (FLOOR_Y - 16, FLOOR_Y - 24), "up on the second or third step")

    def test_a_step_does_not_hold_you_up_when_you_bump_into_it_in_the_air(self) -> None:
        g = self.g
        self.build()
        g.poke("px", 44)
        g.poke("py", 164)  # beside the first step, rising
        g.poke("state", AIR)
        g.poke("jt", 0)
        g.step(RIGHT)
        self.assertEqual(g.px, 45, "it is not solid")


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

    def test_walking_with_a_belt_adds_its_speed_to_yours(self) -> None:
        self.assertEqual(self.on_belt("CONV_R", 60, buttons=RIGHT), 40)
        self.assertEqual(self.on_belt("CONV_L", 100, buttons=LEFT), -40)

    def test_walking_against_a_belt_is_slowed_by_it_not_stopped(self) -> None:
        # a pixel a frame, less 3/8 of the belt's speed: 20 frames of a normal belt cost 7 or 8 pixels
        self.assertIn(self.on_belt("CONV_R", 100, buttons=LEFT), (-12, -13))
        self.assertIn(self.on_belt("CONV_L", 60, buttons=RIGHT), (12, 13))
        fast = self.on_belt("CONV_R_FAST", 100, buttons=LEFT)  # 3/8 of two pixels a frame: a quarter of a pixel net
        self.assertIn(fast, (-5, -6, -4))

    def test_you_can_walk_onto_and_across_a_fast_belt_turning_against_you(self) -> None:
        g = self.g
        self.arena()
        self.floor(20, 29, "CONV_R_FAST")
        self.stand(130)
        g.run(260, LEFT)
        self.assertLess(g.px, 20 * 4 - 2, "right across it, off its far end")
        self.arena()
        self.floor(20, 29, "CONV_L_FAST")
        self.stand(40)
        g.run(260, RIGHT)
        self.assertGreater(g.px, 30 * 4 + 2)

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

    def test_a_roller_picks_you_up_faster_the_longer_it_is(self) -> None:
        g = self.g
        for n in (1, 2, 4, 8, 12):
            self.arena()
            g.put_tiles(10, 23, [T["ROLLER"]] * n)
            self.stand(40)
            g.step(RIGHT)
            self.assertEqual(g.vx, min(n, 8), f"a roller {n} long")

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
    """Chutes are vertical lifts: only walking into one catches you, and then you are carried to its end."""

    def test_walking_into_a_down_chute_carries_you_to_the_bottom(self) -> None:
        g = self.g
        self.arena()
        g.put_tiles(5, 12, [T["BRICK"]] * 5)  # a platform whose gap is filled by the chute (column 10, rows 12-16)
        for r in range(12, 17):
            g.put_tiles(10, r, [T["SLIDE_R_B" if r % 2 else "SLIDE_R"]])
        self.stand(24, 80)
        g.run_until(lambda g: g.state == RIDE, limit=40, buttons=RIGHT, every=1)
        self.assertEqual(g.px, 40, "snapped to the chute's column")
        rode, py0 = 0, g.py
        while g.state == RIDE and rode < 60:
            g.step(LEFT)  # the joystick is ignored while riding
            rode += 1
            self.assertEqual(g.px, 40)
        self.assertGreaterEqual(g.py - py0, 2 * (rode - 1), "2 pixels a frame down")
        self.assertEqual(g.state, AIR, "released below the last tile")
        g.run_until(lambda g: g.state == GROUND, limit=60, every=1)
        self.assertEqual((g.px, g.py), (40, FLOOR_Y))

    def test_an_up_chute_carries_you_to_its_top_and_you_hop_out_beside_it(self) -> None:
        g = self.g
        self.arena()
        g.put_tiles(11, 18, [T["BRICK"]] * 7)  # a platform level with the top of the chute (column 10, rows 18-22)
        for r in range(18, 23):
            g.put_tiles(10, r, [T["SLIDE_L_B" if r % 2 else "SLIDE_L"]])
        self.stand(24)
        g.run_until(lambda g: g.state == RIDE, limit=40, buttons=RIGHT, every=1)
        self.assertEqual(g.px, 40)
        top = g.py
        while g.state == RIDE:
            g.step(LEFT)  # ignored
            top = min(top, g.py)
            self.assertEqual(g.px, 40)
        self.assertEqual(top, 128 + 2 * 0, "rode up until his feet were level with the top tile")
        self.assertEqual(g.state, AIR, "the hop out")
        g.run_until(lambda g: g.state == GROUND, limit=60, every=1)
        self.assertEqual(g.py, 128, "landed on the platform beside the top")
        self.assertGreaterEqual(g.px, 44)

    def test_chutes_do_not_carry_you_sideways_and_in_the_air_you_pass_through(self) -> None:
        g = self.g
        self.arena()
        for r in (21, 22):
            g.put_tiles(10, r, [T["SLIDE_L"]])  # an up chute: jump over/through it
            g.put_tiles(20, r, [T["SLIDE_R"]])  # a down chute standing on the floor: walk through it
        self.stand(32)
        g.step(RIGHT | FIRE)
        for _ in range(18):
            g.step(RIGHT)
            self.assertNotEqual(g.state, RIDE, "not caught in the air")
        self.assertGreater(g.px, 44)
        g.run_until(lambda g: g.state == GROUND, limit=60, every=1)
        self.stand(60)
        g.run(40, RIGHT)
        self.assertEqual((g.px, g.py), (100, FLOOR_Y), "walked straight through the down chute standing on the floor")
        g.run(30)
        self.assertEqual((g.px, g.py), (100, FLOOR_Y), "nothing carries him")

    def test_the_thread_of_the_chutes_turns_down_and_up_the_stack(self) -> None:
        g = self.g  # on the title screen: the chutes turn in every mode
        helix = {name: ba.helix_rows(TILES, name) for name in ("SLIDE_R", "SLIDE_L")}
        states = {name: [] for name in helix}
        for _ in range(40):
            g.idle()
            charset = g.mem(0x6000, 0x400)
            for name in helix:
                a, b = T[name] * 8, T[name + "_B"] * 8
                states[name].append(list(charset[a : a + 8] + charset[b : b + 8]))
        for name, seen in states.items():
            valid = [[helix[name][(y + ph) % 16] for y in range(16)] for ph in range(16)]
            for st in seen:
                self.assertIn(st, valid, f"{name}: the glyphs always show the thread, scrolled by whole rows")
            changes = [(valid.index(a), valid.index(b)) for a, b in zip(seen, seen[1:]) if a != b]
            self.assertGreaterEqual(len(changes), 15, f"{name} keeps turning")
            for before, after in changes:  # row y shows helix[y + phase]: the phase falls for a thread going down, rises going up
                self.assertEqual((before - after) % 16, 1 if name == "SLIDE_R" else 15, f"{name}: one row {'down' if name == 'SLIDE_R' else 'up'} at a time")


@needs_emulator
class JumpingThroughThings(Arena):
    def test_rising_in_a_jump_ignores_what_is_overhead(self) -> None:
        g = self.g
        self.arena()
        g.put_tiles(4, 20, [T["BRICK"]] * 6)  # a ledge just over his head (its top is at y 160)
        self.stand(24)
        g.step(FIRE)
        top = g.py
        for _ in range(60):
            g.step()
            top = min(top, g.py)
        self.assertEqual(FLOOR_Y - top, 26, "no head bump: the full jump, 8 pixels higher than before")
        self.assertEqual((g.py, g.state), (144, GROUND), "landed on top of the ledge")
        self.stand(24)
        g.put_tiles(4, 19, [T["BRICK"]] * 6)  # two thick: the apex is inside it, and he must come out of the bottom
        g.step(FIRE)
        g.run(80)
        self.assertEqual((g.py, g.state), (FLOOR_Y, GROUND), "fell back out of it rather than standing in it")
        self.stand(24)  # inside the slab he can still move sideways (a wall beside him would still stop him)
        g.step(FIRE | RIGHT)
        x0 = g.px
        g.run(14, RIGHT)
        self.assertEqual(g.px, x0 + 14, "not stuck in the block")


@needs_emulator
class SlowFall(Arena):
    def test_the_lethal_fall_is_still_64_pixels(self) -> None:
        g = self.g
        self.arena()
        for dist, dies in ((64, False), (65, True)):
            self.stand(60, FLOOR_Y - dist)
            g.poke("state", AIR)
            g.poke("jt", 0xFF)
            g.run(80)
            self.assertEqual((g.deaths, g.mode == DYING), (int(dies), dies), f"a fall of {dist} pixels")


@needs_emulator
class Trampolines(Arena):
    """A trampoline is a platform to walk on; landing on it from the air bounces him up to the next surface above him."""

    def build(self, ledge_row: int | None = None, tile: str = "BRICK") -> None:
        self.arena()
        g = self.g
        g.put_tiles(10, 23, [T["TRAMPOLINE_L"], T["TRAMPOLINE"], T["TRAMPOLINE"], T["TRAMPOLINE_R"]])  # (with its end caps)
        if ledge_row is not None:
            g.put_tiles(8, ledge_row, [T[tile]] * 8)

    def jump(self, px: int = 44) -> tuple[int, int]:
        """Jump on the spot, and return the highest point (smallest py) and the frames spent off the ground."""
        g = self.g
        self.stand(px)
        g.step(FIRE)
        top, air = g.py, 1
        for _ in range(150):
            g.step()
            top = min(top, g.py)
            air += g.state == AIR
        return top, air

    def test_walking_over_it_does_nothing(self) -> None:
        g = self.g
        self.build(18)
        self.stand(30)
        for _ in range(40):
            g.step(RIGHT)
            self.assertEqual((g.py, g.state), (FLOOR_Y, GROUND))
        self.assertGreater(g.px, 66)
        self.assertEqual(g.tile(11, 23), T["TRAMPOLINE"], "nothing was eaten or changed")

    def test_landing_on_it_from_a_jump_bounces_him_up_to_the_platform_above(self) -> None:
        g = self.g
        self.build(18)  # the ledge's top is 5 tiles above the trampoline's
        top, _ = self.jump()
        self.assertEqual(FLOOR_Y - top, 17 + 3 * 11, "rose 50 pixels: 8*5+8, in steps of 3")
        self.assertEqual((g.py, g.state), (18 * 8 - 16, GROUND), "then fell onto the ledge")

    def test_a_one_way_platform_above_is_a_target_too_and_a_far_one_is_reached(self) -> None:
        g = self.g
        self.build(9, "PLATFORM")  # 14 tiles up: the farthest
        self.jump()
        self.assertEqual((g.py, g.state), (9 * 8 - 16, GROUND))

    def test_nothing_above_him_means_no_bounce(self) -> None:
        g = self.g
        self.build(None)
        top, _ = self.jump()
        self.assertEqual(FLOOR_Y - top, 26, "an ordinary jump")
        self.assertEqual((g.py, g.state, g.jt, g.bn), (FLOOR_Y, GROUND, 0xFF, 0))
        self.build(8)  # 15 tiles up: out of range
        top, _ = self.jump()
        self.assertEqual(FLOOR_Y - top, 26)
        self.assertEqual((g.py, g.state), (FLOOR_Y, GROUND))

    def test_a_long_fall_onto_it_bounces_instead_of_killing(self) -> None:
        g = self.g
        self.build(12)
        self.stand(44, 100)  # 68 pixels above the floor: more than MAX_FALL
        g.poke("state", AIR)
        g.poke("jt", 0xFF)
        g.run(200)
        self.assertEqual((g.py, g.state, g.deaths), (12 * 8 - 16, GROUND, 0))

    def test_the_whole_run_sags_like_a_rubber_band_and_ends_restored(self) -> None:
        g = self.g
        self.arena()
        L, M, R = T["TRAMPOLINE_L"], T["TRAMPOLINE"], T["TRAMPOLINE_R"]
        sags = [M, T["TRAMPOLINE_S1"], T["TRAMPOLINE_S2"], T["TRAMPOLINE_S3"]]
        g.put_tiles(5, 23, [L] + [M] * 6 + [R])  # the run he bounces on: columns 5-12 (the posts at both ends)
        g.put_tiles(20, 23, [L, M, M, R])  # a second one, which must not move
        g.put_tiles(6, 18, [T["BRICK"]] * 8)  # the ledge he is thrown up to
        self.stand(32)  # column 8
        g.step(FIRE)
        frames = []
        for _ in range(110):
            g.step()
            row = list(g.mem(g.screen_addr + 23 * 40, 256))
            frames.append((row[5:13], row[20:24], g.tr_t))
        self.assertEqual((g.py, g.state), (18 * 8 - 16, GROUND), "he still bounced up onto the ledge")
        self.assertTrue(all(run[0] == L and run[-1] == R for run, _, _ in frames), "the end caps are the posts: never redrawn")
        self.assertTrue(all(other == [L, M, M, R] for _, other, _ in frames), "another trampoline on the screen does not move")
        moving = [i for i, (run, _, _) in enumerate(frames) if run != [L] + [M] * 6 + [R]]
        self.assertTrue(20 <= len(moving) <= 30, f"the wobble lasts {len(moving)} frames")
        self.assertEqual(moving, list(range(moving[0], moving[-1] + 1)), "in one go")
        seen = {t for run, _, _ in frames for t in run[1:-1]}
        self.assertEqual(seen, {*sags, T["TRAMPOLINE_TAUT"]}, "sags 1, 2, 3 and back up taut")
        for col in range(1, 7):
            self.assertTrue(any(run[col] != M for run, _, _ in frames), f"tile {col} of the run moves too")
        deepest = next(run for run, _, _ in frames if run[3] == sags[3])  # (the middle of his feet: column 8)
        self.assertTrue(sags.index(deepest[3]) > sags.index(deepest[1]) and sags.index(deepest[3]) > sags.index(deepest[6]),
                        "deepest where he landed, tapering towards the ends")
        self.assertEqual(frames[-1][0], [L] + [M] * 6 + [R], "plain again")
        self.assertEqual((frames[-1][2], g.tr_t), (0, 0))

    def test_a_restart_in_the_middle_of_the_wobble_puts_the_plain_tiles_back(self) -> None:
        g = self.g
        self.build(18)
        self.stand(44)
        g.step(FIRE)
        g.run_until(lambda g: g.tr_t > 6, limit=60, every=1)
        self.assertGreater(g.tr_t, 6)
        g.poke("px", 100)  # (the brick floor) and a fall that kills
        g.poke("py", 60)
        g.poke("state", AIR)
        g.poke("jt", 0xFF)
        g.poke("bn", 0)
        g.poke("fall", 100)
        g.run_until(lambda g: g.mode == DYING, limit=100, every=1)
        g.run_until(lambda g: g.mode == SPAWN, limit=DIE_FRAMES + 20, every=1)
        self.assertEqual(g.tr_t, 0)
        screen = g.mem(g.screen_addr, 1024)
        self.assertFalse({T["TRAMPOLINE_S1"], T["TRAMPOLINE_S2"], T["TRAMPOLINE_S3"], T["TRAMPOLINE_TAUT"]} & set(screen))

    def test_he_bounces_again_off_a_trampoline_on_the_upper_level(self) -> None:
        g = self.g
        self.build(12)
        g.put_tiles(8, 18, [T["TRAMPOLINE"]] * 8)
        self.stand(44)
        g.step(FIRE)
        g.run(250)
        self.assertEqual((g.py, g.state), (12 * 8 - 16, GROUND), "first to the upper trampoline, then on to the ledge above it")


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

    def arm(self, col: int, row: int, fuse: int = 2) -> None:
        """A bomb block at (col, row) with its fuse already burning."""
        g = self.g
        g.put_tiles(col, row, [T["EXPLOSIVE"]])
        for name, value in (("tt_col", col), ("tt_row", row), ("tt_t", fuse), ("tt_ph", 0), ("tt_kind", 0), ("tt_orig", T["EXPLOSIVE"])):
            g.poke_bytes(g.labels[name], [value])

    def test_a_bomb_going_off_just_over_your_head_does_not_hurt(self) -> None:
        g = self.g
        self.arena()
        self.stand(40)  # head at y 168; the block's bottom is at 167
        self.arm(10, 20)
        g.run(8)
        self.assertEqual(g.tile(10, 20), T["BOOM"])
        self.assertEqual(g.mode, PLAY)

    def test_a_bomb_going_off_beside_your_knees_does_not_hurt_but_beside_your_feet_does(self) -> None:
        g = self.g
        self.arena()
        self.stand(36)
        self.arm(10, 21)  # a tile above his feet
        g.run(8)
        self.assertEqual(g.mode, PLAY)
        self.arena()
        self.stand(36)
        self.arm(10, 22)  # level with his feet
        g.run(8)
        self.assertEqual(g.mode, DYING)

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
class EndCaps(Arena):
    """Platform end caps look different but behave exactly like the plain tile."""

    def test_caps_are_solid_and_stand_for_their_tile(self) -> None:
        self.arena()
        self.g.put_tiles(10, 20, [T["BRICK_L"], T["BRICK"], T["BRICK_R"]])
        self.stand(40, 144)
        self.g.run(10)
        self.assertEqual((self.g.py, self.g.state), (144, GROUND), "stands on a cap")
        self.g.run(30, RIGHT)  # walks off the right end onto the floor
        self.assertEqual(self.g.py, FLOOR_Y)

    def test_you_cannot_walk_through_a_cap(self) -> None:
        self.arena()
        self.g.put_tiles(20, 21, [T["BRICK_L"]] * 1)
        self.g.put_tiles(20, 22, [T["BRICK_L"]] * 1)
        self.stand(60)
        self.g.run(40, RIGHT)
        self.assertEqual(self.g.px, 20 * 4 - 4)

    def test_a_belt_end_cap_drifts_you_like_the_belt(self) -> None:
        self.arena()
        self.g.put_tiles(8, 23, [T["CONV_R_FAST_L"]] + [T["CONV_R_FAST"]] * 29 + [T["CONV_R_FAST_R"]])
        self.stand(60)
        self.assertEqual(self.moved(20), 40)
        self.stand(32)  # on the left cap itself (column 8)
        self.assertEqual(self.moved(5), 10)

    def test_an_ice_cap_is_slippery_too(self) -> None:
        self.arena()
        self.g.put_tiles(1, 23, [T["ICE_L"]] + [T["ICE"]] * 36 + [T["ICE_R"]])
        self.stand(8)  # on the left cap
        self.g.run(12, RIGHT)
        at = self.g.px
        self.g.run(40)
        self.assertGreater(self.g.px - at, 8)

    def test_a_one_way_cap_is_still_one_way(self) -> None:
        self.arena()
        self.g.put_tiles(10, 21, [T["PLATFORM_L"]] + [T["PLATFORM"]] * 3 + [T["PLATFORM_R"]])
        self.stand(44)
        self.g.step(FIRE)
        self.g.run(40)
        self.assertEqual((self.g.py, self.g.state), (FLOOR_Y - 16, GROUND))

    def test_a_vanishing_cap_keeps_its_end_when_it_flickers_and_comes_back(self) -> None:
        g = self.g
        self.arena()
        g.put_tiles(10, 20, [T["VANISH_L"], T["VANISH"], T["VANISH_R"]])
        self.stand(40, 144)
        seen = set()
        for _ in range(28):
            g.step()
            seen.add(g.tile(10, 20))
        self.assertEqual(seen, {T["VANISH_L"], T["VANISH_B"]})
        g.run(15)
        self.assertEqual(g.tile(10, 20), 0)
        g.run(200)
        self.assertEqual(g.tile(10, 20), T["VANISH_L"], "back with its end intact")

    def test_a_bomb_block_end_goes_off_and_sets_off_its_neighbours(self) -> None:
        g = self.g
        self.arena()
        g.put_tiles(10, 20, [T["EXPLOSIVE_L"], T["EXPLOSIVE"], T["EXPLOSIVE_R"]])
        self.stand(48, 144)  # on the right end
        g.run_until(lambda g: g.tile(12, 20) == T["BOOM"], limit=80, buttons=RIGHT, every=1)
        g.run(90, RIGHT)
        self.assertEqual([g.tile(c, 20) for c in (10, 11, 12)], [0, 0, 0])
        self.assertEqual(g.mode, PLAY)

    def test_the_end_caps_of_a_belt_animate_with_the_belt(self) -> None:
        g = self.g  # the title screen: belts animate in every mode
        seen = []
        for _ in range(20):
            g.idle()
            page = g.mem(0x6200, 256)  # glyph ids 64-95 live in $6200-$62FF
            row = lambda name: page[T[name] * 8 - 0x200]
            seen.append((row("CONV_R"), row("CONV_R_L"), row("CONV_R_R"), row("CONV_R_LR")))
        for sample in seen:
            self.assertEqual(len(set(sample)), 1, f"the caps show the same moving surface as the belt: {sample}")
        self.assertGreater(len({s[0] for s in seen}), 1)

    def test_the_caps_art_is_drawn_below_the_moving_surface(self) -> None:
        g = self.g
        page = g.mem(0x6200, 256)
        plain = page[T["CONV_R"] * 8 - 0x200 + 2 : T["CONV_R"] * 8 - 0x200 + 8]
        cap = page[T["CONV_R_L"] * 8 - 0x200 + 2 : T["CONV_R_L"] * 8 - 0x200 + 8]
        self.assertNotEqual(plain, cap)


@needs_emulator
class Pegs(Arena):
    """Map 5 (index 4) has one peg on a floating block in tile columns 24-31, row 11."""

    def test_the_peg_starts_at_the_end_of_its_block_nearest_where_it_was_placed(self) -> None:
        self.goto(4)
        self.assertEqual(self.g.pg_n, 1)
        x, d, _ = self.peg()
        self.assertEqual((x, d), (32 * 4, 255), "starts at the right end (the chute head after the bricks), heading left")
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
        # the whole platform of row 11, whatever it is made of: the step at column 23 before the bricks (24-31) and the
        # head of the down chute at column 32 after them are part of it
        lo, hi = 23 * 4, 32 * 4
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
        self.assertLess(g.px, 23 * 4, "pushed back to the end of the platform, past the step at its end, and off")

    def test_the_peg_runs_the_whole_platform_and_carries_you_to_its_end_whatever_is_in_it(self) -> None:
        self.goto(4)
        g = self.g
        self.assertEqual(g.bss("pg_min", 1)[0], 23 * 4)
        self.assertEqual(g.bss("pg_max", 1)[0], 32 * 4)
        # fast belts running against the push, a ladder and a step standing on the platform
        g.put_tiles(25, 11, [T["CONV_L_FAST"]] * 3)
        g.put_tiles(27, 10, [T["LADDER"]])
        g.put_tiles(29, 10, [T["STAIR"]])
        g.poke_bytes(g.labels["pg_x"], [96])
        g.poke_bytes(g.labels["pg_dir"], [1])
        g.poke_bytes(g.labels["pg_wait"], [0])
        self.stand(104, 72)
        far, states = 0, set()
        for _ in range(400):
            g.step()
            far = max(far, g.px)
            states.add(g.state)
            if g.state == RIDE:
                break
        self.assertEqual(g.mode, PLAY)
        self.assertGreaterEqual(far, 31 * 4, f"carried to the far end of the platform (got to {far})")
        self.assertIn(RIDE, states, "and off it: onto the down chute that starts at its end")

    def test_pushed_over_a_spike_he_still_dies_of_it(self) -> None:
        self.goto(4)
        g = self.g
        g.put_tiles(28, 10, [T["SPIKE"]])
        g.poke_bytes(g.labels["pg_x"], [96])
        g.poke_bytes(g.labels["pg_dir"], [1])
        g.poke_bytes(g.labels["pg_wait"], [0])
        self.stand(104, 72)
        g.run_until(lambda g: g.mode != PLAY, limit=300, every=1)
        self.assertEqual(g.mode, DYING)

    def test_a_peg_only_pushes_a_player_whose_feet_are_beside_it(self) -> None:
        g = self.g
        self.goto(4)
        # the peg is 8 lines tall at y 80: his feet (py + 15) must be on one of those lines
        for py, pushed in ((72, True), (64, False), (80, False)):
            g.poke_bytes(g.labels["pg_x"], [100])
            g.poke_bytes(g.labels["pg_wait"], [0])
            g.poke_bytes(g.labels["pg_dir"], [255])
            g.poke("px", 100)
            g.poke("py", py)
            g.poke("state", AIR)
            g.poke("jt", 0xFF)
            g.poke("fall", 0)
            g.step()
            self.assertEqual(g.px < 100, pushed, f"py {py}: px is {g.px}")

    def test_the_peg_leaves_you_alone_when_you_are_behind_it(self) -> None:
        self.goto(4)
        g = self.g
        g.poke_bytes(g.labels["pg_x"], [100])  # the peg is to his left, heading left: he is behind it (not at column 31-32: the chute there would catch him)
        self.stand(110, 72)
        g.run(PEG_WAIT - 5)
        self.assertEqual((g.px, g.py), (110, 72))

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
        """Everything to collect in map n: its dots and its items, as the asset tool counted them."""
        text = (ROOT / "src" / "gen" / "levels.inc").read_text()
        return int(re.search(rf"LEVEL{n}_ITEMS = (\d+)", text).group(1))

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
