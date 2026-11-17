"""Game tests: run the real 6502 code headlessly and check what happens, frame by frame.

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
    CLEAR,
    CLEAR_FRAMES,
    CLIMB,
    COLS,
    DIE_FRAMES,
    DOWN,
    DYING,
    FIRE,
    GROUND,
    LABELS,
    LEFT,
    OVER,
    PLAY,
    RIGHT,
    SPAWN,
    SPAWN_FRAMES,
    TITLE,
    UP,
    XEX,
    Game,
)

T_EMPTY, T_BRICK, T_LADDER, T_ITEM, T_SPIKE = 0, 1, 2, 3, 4
SPAWN_X, SPAWN_Y = 12, 168  # tile (3,21)
FLOOR_Y = {23: 168, 18: 128, 13: 88, 8: 48}  # py of a player standing on the floor in that tile row
ROOT = Path(__file__).resolve().parent.parent

needs_emulator = unittest.skipUnless(shutil.which("atari800") and XEX.exists() and LABELS.exists(), "needs atari800 and `task build-test`")


def hud(score: int = 0, level: int = 1, lives: int = 3, left: int = 8) -> str:
    return f"SCORE {score:05d} LEVEL {level:02d}  LIVES {lives}  LEFT {left:02d}"


def decode(raw: bytes) -> str:
    """Screen bytes as text: font glyphs as characters (lowercase = second colour), # * ^ for tiles."""
    out = []
    for b in raw:
        c = b & 0x7F
        if b == 0:
            out.append(" ")
        elif 16 <= c <= 25:
            out.append(str(c - 16))
        elif 32 <= c <= 57:
            ch = chr(65 + c - 32)
            out.append(ch.lower() if b & 0x80 else ch)
        elif c in (58, 59, 60, 61):
            out.append("-!?:"[c - 58])
        else:
            out.append({T_BRICK: "#", T_LADDER: "H", T_ITEM: "*", T_SPIKE: "^"}.get(b, "."))
    return "".join(out)


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.g = Game()
        self.addCleanup(self.g.close)

    def row(self, r: int) -> str:
        return decode(self.g.mem(self.g.screen_addr + r * COLS, 256)[:COLS])

    def inner(self, r: int) -> str:
        """A row's text between the box borders."""
        return self.row(r)[1:-1].strip()

    def start(self) -> Game:
        self.g.start_game()
        return self.g

    def walk_to(self, px: int) -> None:
        g = self.g
        while g.px != px:
            before = g.px
            g.step(RIGHT if g.px < px else LEFT)
            self.assertNotEqual(g.px, before, f"stuck at {g.px} wanting {px}")

    def wait_for(self, mode: int, limit: int = 400) -> None:
        self.g.run_until(lambda g: g.mode == mode, limit=limit, every=2)

    def kill(self) -> None:
        """Drop the player from far above so the landing kills."""
        g = self.g
        g.poke("state", AIR)
        g.poke("jt", 0xFF)
        g.poke("py", 100)
        g.poke("px", 60)
        g.poke("fall", 100)
        g.step(0, 30)


# ---------------------------------------------------------------------------
@needs_emulator
class TitleScreen(Base):
    def test_boots_to_the_title_screen(self) -> None:
        g = self.g
        self.assertEqual((g.mode, g.demo), (TITLE, 0))
        self.assertIn("mine runner", self.row(4))
        self.assertIn("A SINGLE SCREEN PLATFORMER", self.row(6))
        self.assertIn("HI-SCORE 00000", self.row(18))
        self.assertEqual(self.row(1), "#" * 40)

    def test_press_fire_blinks(self) -> None:
        seen = set()
        for _ in range(36):
            self.g.idle(2)
            seen.add(self.inner(15))
        self.assertEqual(seen, {"", "PRESS FIRE TO START"})

    def test_the_player_is_not_shown_on_the_title(self) -> None:
        g = self.g
        self.assertEqual(g.mem(g.pm0, 256), bytes(256))

    def test_fire_starts_a_game(self) -> None:
        g = self.g
        g.step(FIRE)
        self.assertEqual(g.mode, SPAWN)
        self.assertEqual((g.lives, g.level, g.lvlidx, g.score16, g.demo), (3, 1, 0, 0, 0))
        g.run(SPAWN_FRAMES)
        self.assertEqual(g.mode, PLAY)

    def test_a_held_fire_button_does_not_jump_at_the_start(self) -> None:
        g = self.g
        g.run(SPAWN_FRAMES + 20, FIRE)  # fire held down from the title through the spawn
        self.assertEqual((g.mode, g.py, g.state), (PLAY, SPAWN_Y, GROUND))

    def test_idling_on_the_title_starts_the_attract_mode(self) -> None:
        g = self.g
        self.assertIn(g.word("timer"), (10 * 50 - 1, 10 * 60 - 1), "10 seconds of frames at 50 or 60 Hz")
        g.poke("timer", 3)
        g.poke(g.labels["timer"] + 1, 0)
        g.idle(5)
        self.assertEqual(g.demo, 1)
        self.assertIn(g.mode, (SPAWN, PLAY))


# ---------------------------------------------------------------------------
@needs_emulator
class Spawn(Base):
    def test_player_is_drawn_line_by_line_then_blinks(self) -> None:
        g = self.g
        g.step(FIRE)
        drawn = []
        for _ in range(SPAWN_FRAMES):
            g.idle()
            drawn.append(g.drawn)
        reveal = drawn[: SPAWN_FRAMES // 3 * 2 - 1]
        self.assertEqual(reveal, sorted(reveal))
        self.assertEqual((reveal[0], reveal[-1]), (1, 16))
        self.assertEqual({0, 16}, set(drawn[SPAWN_FRAMES // 3 * 2 :]) | {0, 16}, "then blinks on and off")
        self.assertIn(0, drawn[SPAWN_FRAMES // 3 * 2 :])
        self.assertEqual((g.mode, g.drawn), (PLAY, 16))

    def test_the_sprite_memory_matches_the_revealed_lines(self) -> None:
        g = self.g
        g.step(FIRE)
        g.idle(7)  # a few frames in
        lines = g.drawn
        self.assertTrue(0 < lines < 16)
        sprite = g.sprite()
        self.assertTrue(all(sprite[:lines]), "the revealed lines are lit")
        self.assertEqual(sprite[lines:], bytes(16 - lines), "the rest is still empty")

    def test_player_cannot_move_while_coming_to_life(self) -> None:
        g = self.g
        g.step(FIRE)
        g.run(SPAWN_FRAMES - 5, RIGHT)
        self.assertEqual((g.mode, g.px), (SPAWN, SPAWN_X))

    def test_colour_changes_during_the_animation_and_settles(self) -> None:
        g = self.g
        g.step(FIRE)
        colours = set()
        for _ in range(SPAWN_FRAMES):
            g.idle()
            colours.add(g.mem(0x0200, 256)[0xC0])
        self.assertGreater(len(colours), 4)
        self.assertEqual(g.mem(0x0200, 256)[0xC0], 0x1E)


# ---------------------------------------------------------------------------
@needs_emulator
class Hud(Base):
    def test_score_row_shows_score_level_lives_and_items_left(self) -> None:
        self.start()
        self.assertEqual(self.row(0).rstrip(), hud())

    def test_score_row_updates(self) -> None:
        g = self.start()
        self.walk_to(14 * 4 - 2)
        g.idle()
        self.assertEqual(self.row(0).rstrip(), hud(10, left=7))

    def test_the_player_cannot_rise_into_the_score_row(self) -> None:
        g = self.start()
        g.poke("px", 80)
        g.poke("state", AIR)
        g.poke("jt", 0)
        g.poke("py", 14)
        top = 255
        for _ in range(12):
            g.idle()
            top = min(top, g.py)
        self.assertEqual(top, 8, "the score row acts as a ceiling")


# ---------------------------------------------------------------------------
@needs_emulator
class GameLogic(Base):
    def setUp(self) -> None:
        super().setUp()
        self.start()

    # ---- start ----
    def test_starts_on_the_floor_with_a_full_level(self) -> None:
        g = self.g
        self.assertEqual((g.px, g.py, g.state), (SPAWN_X, SPAWN_Y, GROUND))
        self.assertEqual((g.left, g.score16, g.lives, g.level), (8, 0, 3, 1))
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
        self.walk_to(72)
        g.step(RIGHT | FIRE)  # jump the spikes at column 20
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
        self.assertGreaterEqual(top, 152)
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

    # ---- items ----
    def test_collects_an_item(self) -> None:
        g = self.g
        self.walk_to(14 * 4 - 2)
        g.idle()
        self.assertEqual((g.score16, g.left), (10, 7))
        self.assertEqual(g.tile(14, 22), T_EMPTY)
        self.assertEqual(g.tile(15, 22), T_EMPTY)  # nothing else removed
        g.step(RIGHT, 8)
        self.assertEqual(g.score16, 10, "an item is only collected once")

    def test_jumping_over_spikes_is_safe(self) -> None:
        g = self.g
        self.walk_to(72)  # two tiles before the spikes at column 20 (pixels 80-83)
        g.step(FIRE | RIGHT)
        for _ in range(40):
            g.step(RIGHT)
            if g.state == GROUND:
                break
        self.assertGreater(g.px, 84, "cleared the spikes")
        self.assertEqual(g.mode, PLAY, "still alive")

    def test_small_drops_are_safe(self) -> None:
        g = self.g
        g.poke("px", 80)
        g.poke("py", FLOOR_Y[18])
        g.idle(2)
        self.assertEqual(g.state, GROUND)
        g.step(RIGHT, 40)  # into the hole at columns 24-27
        self.assertEqual((g.state, g.py, g.mode), (GROUND, FLOOR_Y[23], PLAY))  # dropped one floor and survived

    def test_level_data_matches_the_source_file(self) -> None:
        g = self.g
        lines = [
            l for l in (ROOT / "assets" / "levels" / "level1.txt").read_text().splitlines()
            if l and not l.startswith("# ")
        ]
        tiles = {".": 0, "#": 1, "H": 2, "*": 3, "^": 4, "@": 0}
        expected = bytes(tiles[c] for row in lines for c in row)
        self.assertEqual(len(expected), COLS * 24)
        self.assertEqual(g.mem(g.screen_addr, 1024)[COLS : COLS * 24], expected[COLS:])  # ignoring the score row

    # ---- display ----
    def test_player_sprite_is_in_player_memory(self) -> None:
        sprite = self.g.sprite()
        self.assertEqual(len(sprite), 16)
        self.assertEqual(sprite[1], 0xF0)  # the head row of the stand frame

    def test_sprite_follows_the_player_vertically(self) -> None:
        g = self.g
        g.step(FIRE, 3)
        self.assertNotEqual(g.py, SPAWN_Y)
        self.assertEqual(g.sprite()[1], 0xF0)
        raw = g.mem(g.pm0, 256)
        self.assertEqual(raw[32 + SPAWN_Y + 15], 0, "no stale image left at the old position")


# ---------------------------------------------------------------------------
@needs_emulator
class DeathAndLives(Base):
    def setUp(self) -> None:
        super().setUp()
        self.start()

    def die_on_spikes(self) -> None:
        g = self.g
        self.walk_to(76)
        for _ in range(6):
            g.step(RIGHT)
            if g.mode == DYING:
                break

    def test_touching_spikes_starts_the_death_animation(self) -> None:
        g = self.g
        self.walk_to(14 * 4)
        g.idle()
        self.assertEqual(g.score16, 10)
        self.die_on_spikes()
        self.assertEqual((g.mode, g.deaths, g.lives), (DYING, 1, 3), "a life is lost when the animation ends")
        self.assertGreater(g.flash, 0)

    def test_the_player_hops_up_then_falls_off_the_screen(self) -> None:
        g = self.g
        self.die_on_spikes()
        ys, frames = [], set()
        for _ in range(60):
            g.idle()
            ys.append(g.py)
            frames.add(g.frame)
        top = ys.index(min(ys))
        self.assertLess(min(ys), SPAWN_Y - 12, "rises first")
        self.assertEqual(ys[top:], sorted(ys[top:]), "then only falls")
        self.assertGreaterEqual(ys[-1], 200, "ends below the screen")
        self.assertEqual(frames, {5, 6}, "tumbles between the two death frames")

    def test_dying_player_cannot_be_steered_or_pick_things_up(self) -> None:
        g = self.g
        self.die_on_spikes()
        px = g.px
        g.step(LEFT, 20)
        self.assertEqual(g.px, px)
        self.assertEqual(g.mode, DYING)

    def test_after_the_animation_a_life_is_lost_and_the_level_restarts(self) -> None:
        g = self.g
        self.walk_to(14 * 4)  # an item first: 10 points, 7 left
        g.idle()
        self.die_on_spikes()
        g.run(DIE_FRAMES)
        self.assertEqual((g.mode, g.lives), (SPAWN, 2))
        self.assertEqual((g.px, g.py, g.state, g.left, g.score16), (SPAWN_X, SPAWN_Y, GROUND, 8, 10), "the score is kept")
        self.assertEqual(g.tile(14, 22), T_ITEM, "the level is restored")
        self.assertEqual(self.row(0).rstrip(), hud(10, lives=2))
        g.run(SPAWN_FRAMES)
        self.assertEqual(g.mode, PLAY)

    def test_a_long_fall_kills(self) -> None:
        g = self.g
        self.kill()
        self.assertEqual((g.mode, g.deaths), (DYING, 1))

    def test_the_last_life_ends_the_game(self) -> None:
        g = self.g
        g.poke("lives", 1)
        self.kill()
        g.run(DIE_FRAMES)
        self.assertEqual(g.mode, OVER)
        self.assertIn("game over", self.row(7))
        self.assertIn("SCORE    00000", self.row(10))
        self.assertEqual(g.mem(g.pm0, 256), bytes(256), "no player on the game over screen")

    def test_game_over_shows_and_records_the_score_earned(self) -> None:
        g = self.g
        self.walk_to(14 * 4 - 2)  # 10 points
        g.idle()
        g.poke("lives", 1)
        self.kill()
        g.run(DIE_FRAMES)
        self.assertEqual(g.mode, OVER)
        self.assertEqual(g.word("hiscore"), 10)
        self.assertIn("SCORE    00010", self.row(10))
        self.assertIn("NEW HIGH SCORE!", self.row(15))

    def test_no_new_hiscore_message_when_the_score_is_not_a_record(self) -> None:
        g = self.g
        g.poke(g.labels["hiscore"], 50)
        self.walk_to(14 * 4 - 2)
        g.idle()
        g.poke("lives", 1)
        self.kill()
        g.run(DIE_FRAMES)
        self.assertEqual((g.mode, g.word("hiscore")), (OVER, 50))
        self.assertNotIn("NEW HIGH SCORE", self.row(15))
        self.assertIn("HI-SCORE 00050", self.row(12))

    def test_a_new_hiscore_is_announced_and_kept(self) -> None:
        g = self.g
        g.poke("lives", 1)
        g.poke(g.labels["score"], 0xE8)  # 0x03E8 = 1000
        g.poke(g.labels["score"] + 1, 0x03)
        self.kill()
        g.run(DIE_FRAMES)
        self.assertEqual(g.mode, OVER)
        self.assertEqual(g.word("hiscore"), 1000)
        self.assertIn("SCORE    01000", self.row(10))
        self.assertIn("HI-SCORE 01000", self.row(12))
        self.assertIn("NEW HIGH SCORE!", self.row(15))
        # Back on the title, the hi-score is shown.
        g.poke("timer", 2)
        g.poke(g.labels["timer"] + 1, 0)
        g.idle(3)
        self.assertEqual(g.mode, TITLE)
        self.assertIn("HI-SCORE 01000", self.row(18))

    def test_game_over_waits_a_second_then_fire_returns_to_the_title(self) -> None:
        g = self.g
        g.poke("lives", 1)
        self.kill()
        g.run(DIE_FRAMES)
        self.assertEqual(g.mode, OVER)
        g.step(FIRE)  # too early
        g.idle()
        self.assertEqual(g.mode, OVER)
        g.run(70)
        seen = set()
        for _ in range(30):
            g.idle(2)
            seen.add(self.inner(18))
        self.assertEqual(seen, {"", "PRESS FIRE"})
        g.step(FIRE)
        g.idle()
        self.assertEqual(g.mode, TITLE)

    def test_game_over_returns_to_the_title_by_itself(self) -> None:
        g = self.g
        g.poke("lives", 1)
        self.kill()
        g.run(DIE_FRAMES)
        g.poke("timer", 2)
        g.poke(g.labels["timer"] + 1, 0)
        g.idle(3)
        self.assertEqual(g.mode, TITLE)

    def test_a_new_game_after_game_over_starts_fresh(self) -> None:
        g = self.g
        g.poke("lives", 1)
        self.kill()
        g.run(DIE_FRAMES)
        g.run(70)
        g.step(FIRE)
        g.idle(2)
        self.assertEqual(g.mode, TITLE)
        g.step(FIRE)
        self.assertEqual((g.mode, g.lives, g.level, g.score16), (SPAWN, 3, 1, 0))


# ---------------------------------------------------------------------------
@needs_emulator
class LevelClear(Base):
    def setUp(self) -> None:
        super().setUp()
        self.start()

    def finish_level(self) -> None:
        g = self.g
        g.step(RIGHT, 20)
        g.poke("left", 1)
        for _ in range(40):
            g.step(RIGHT)
            if g.mode == CLEAR:
                break
        self.assertEqual(g.mode, CLEAR)

    def test_clearing_the_last_item_gives_a_bonus_and_celebrates(self) -> None:
        g = self.g
        self.finish_level()
        self.assertEqual(g.score16, 10 + 100)
        self.assertGreater(g.flash, 0)
        self.assertEqual(g.left, 0)
        px = g.px
        g.step(LEFT, 10)
        self.assertEqual(g.px, px, "no steering during the celebration")

    def test_then_the_next_level_begins_with_the_come_to_life_animation(self) -> None:
        g = self.g
        self.finish_level()
        g.run(CLEAR_FRAMES + 1)
        self.assertEqual(g.mode, SPAWN)
        self.assertEqual((g.level, g.lvlidx, g.left, g.lives, g.score16), (2, 1, 11, 3, 110))
        self.assertEqual(self.row(0).rstrip(), hud(110, level=2, left=11))
        self.assertEqual(g.tile(4, 7), T_ITEM, "level 2's map")
        g.run(SPAWN_FRAMES)
        self.assertEqual(g.mode, PLAY)

    def test_dying_on_level_two_restarts_level_two_and_keeps_the_score(self) -> None:
        g = self.g
        self.finish_level()
        g.run(CLEAR_FRAMES + 1 + SPAWN_FRAMES)
        g.step(RIGHT, 30)  # picks up level 2's first item, at column 8
        self.assertEqual(g.score16, 120)
        self.kill()
        g.run(DIE_FRAMES)
        self.assertEqual((g.mode, g.level, g.lives, g.score16, g.left), (SPAWN, 2, 2, 120, 11))

    def test_levels_wrap_around_but_the_counter_keeps_counting(self) -> None:
        g = self.g
        g.poke("level", 3)
        g.poke("lvlidx", 2)  # the last map
        g.step(RIGHT, 20)
        g.poke("left", 1)
        g.run(40, RIGHT)
        g.run(CLEAR_FRAMES + 2)
        self.assertEqual((g.mode, g.level, g.lvlidx), (SPAWN, 4, 0))
        self.assertEqual(self.row(0)[18:20], "04")


# ---------------------------------------------------------------------------
@needs_emulator
class AttractMode(Base):
    def begin_demo(self, which: int = 0) -> None:
        g = self.g
        g.poke("demo_n", which)
        g.poke("timer", 2)
        g.poke(g.labels["timer"] + 1, 0)
        g.idle(3)
        self.assertEqual(g.demo, 1)

    def test_the_demo_shows_a_blinking_demo_marker_instead_of_lives(self) -> None:
        self.begin_demo()
        seen = set()
        for _ in range(30):
            self.g.idle(2)
            seen.add(self.row(0)[22:27])
        self.assertEqual(seen, {"DEMO ", "     "})

    def test_the_demo_lasts_thirty_seconds_and_returns_to_the_title(self) -> None:
        g = self.g
        self.begin_demo()
        total = g.word("timer")
        self.assertIn(total, (30 * 50 - 2, 30 * 50 - 1, 30 * 60 - 2, 30 * 60 - 1), "30 seconds of frames at 50 or 60 Hz")
        g.run(total // 2)
        self.assertEqual((g.mode in (PLAY, SPAWN, CLEAR, DYING), g.demo), (True, 1))
        g.run_until(lambda g: g.mode == TITLE, limit=total, every=5)
        self.assertEqual(g.demo, 0)
        self.assertEqual(g.mem(g.pm0, 256), bytes(256), "the player is gone from the title")
        self.assertIn("mine runner", self.row(4))

    def test_the_demo_plays_and_never_dies_on_the_first_level(self) -> None:
        g = self.g
        self.begin_demo()
        g.run(300)
        self.assertEqual(g.deaths, 0)
        self.assertLess(g.left, 8, "it collected items")
        self.assertGreater(g.score16, 0)
        self.assertEqual(g.lives, 3, "a demo does not use up lives")

    def test_fire_during_the_demo_starts_a_real_game(self) -> None:
        g = self.g
        self.begin_demo()
        g.run(100)
        g.step(FIRE)
        self.assertEqual((g.mode, g.demo, g.lives, g.level, g.score16), (SPAWN, 0, 3, 1, 0))
        self.assertIn("LIVES 3", self.row(0))
        g.run(SPAWN_FRAMES)
        self.assertEqual(g.mode, PLAY)
        g.step(RIGHT, 5)
        self.assertEqual(g.px, SPAWN_X + 5, "under your control now")

    def test_each_demo_uses_the_next_level(self) -> None:
        g = self.g
        self.begin_demo(0)
        self.assertEqual((g.level, g.lvlidx), (1, 0))
        g.poke("timer", 2)
        g.poke(g.labels["timer"] + 1, 0)
        g.idle(3)
        self.assertEqual(g.mode, TITLE)
        self.begin_demo(g.demo_n)
        self.assertEqual((g.level, g.lvlidx), (2, 1))

    def test_a_hold_on_the_stick_does_not_affect_the_demo(self) -> None:
        g = self.g
        self.begin_demo()
        g.run(120, LEFT | UP)  # the real joystick is ignored (only fire counts)
        self.assertEqual(g.demo, 1)
        self.assertEqual(g.deaths, 0)


@needs_emulator
class AiPlaysEveryLevel(Base):
    """The AI clears each map without dying; also proves the maps can be completed."""

    def clear(self, which: int) -> int:
        g = self.g
        g.poke("demo_n", which)
        g.poke("timer", 2)
        g.poke(g.labels["timer"] + 1, 0)
        g.idle(3)
        self.assertEqual((g.demo, g.lvlidx), (1, which))
        # Give the demo a long timer so it cannot end the run.
        g.poke("timer", 0xFF)
        g.poke(g.labels["timer"] + 1, 0xFF)
        start_level = g.level
        frames = g.run_until(lambda g: g.mode == CLEAR, limit=2400, every=10)
        self.assertEqual(g.deaths, 0, f"the AI died on map {which}")
        self.assertEqual(g.left, 0)
        self.assertEqual(g.level, start_level)
        return frames

    def test_level_1(self) -> None:
        self.clear(0)

    def test_level_2(self) -> None:
        self.clear(1)

    def test_level_3(self) -> None:
        self.clear(2)


if __name__ == "__main__":
    unittest.main()
