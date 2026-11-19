"""Game tests: run the real 6502 code headlessly and check what happens, frame by frame.

Requires atari800 and the TEST build (``task build-test``); skipped when either is missing.
Level 1 reference (tile column, row): spawn (3,21); floors at rows 23, 18, 13, 8; ladders at
(8, rows 18-22), (31, 18-22), (20, 13-17), (33, 8-12), (5, 8-12); a hole in row 18 at columns 24-27;
items at (14,22) (26,22) (12,17) (30,17) (10,12) (28,12) (12,7) (24,7); spikes at (20,22) (16,17) (15,12).
"""

from __future__ import annotations

import re
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

sys.path.insert(0, str(ROOT / "tools"))
import build_assets as _ba  # noqa: E402
from tools.headless import BOB_RANGE, PLAYER_FLOAT, PM_YOFF  # noqa: E402

_TILES = _ba.parse_tiles(ROOT / "assets" / "tiles.txt")
TILE = {t["name"]: t["byte"] for t in _TILES}
FR_STAND, FR_LEAN, FR_SQUASH, FR_STRETCH, FR_DIE_A = 0, 3, 5, 8, 11  # the frame families of assets/sprites.txt
DOOR_NAMES = _ba.DOOR_NAMES
TILE_ROWS = {t["name"]: t["rows"] for t in _TILES}
DOOR_GLYPHS = 0x6000 + (TILE["DOOR_BL"] & 0x7F) * 8  # where the door's six glyphs are in the character set


def door_glyphs(phase: int) -> bytes:
    """What the door's 48 glyph bytes hold when `phase` of its 16 fade steps have passed (see door_thr)."""
    thr = _ba.fade_thresholds()
    out = bytearray()
    for k, name in enumerate(DOOR_NAMES):
        for y, row in enumerate(TILE_ROWS[name]):
            byte = 0
            for x, ch in enumerate(row):
                byte = (byte << 2) | (int(ch) if thr[(k * 8 + y) * 4 + x] < phase else 0)
            out.append(byte)
    return bytes(out)
CHAR_BYTE = {t["char"]: t["byte"] for t in _TILES if t["char"] is not None}
_DOTTED = {dotted: plain for plain, dotted in _ba.dot_families(_TILES).items()}  # a dotted twin -> its plain tile
LEVEL_ITEMS = [int(x) for x in re.findall(r"LEVEL\d+_ITEMS = (\d+)", (ROOT / "src" / "gen" / "levels.inc").read_text())]
_CANON = {b: fam for fam, caps in _ba.cap_families(_ba.parse_tiles(ROOT / "assets" / "tiles.txt")).items() for b in caps.values()}


def canon(b: int) -> int:
    """The plain tile a map byte stands for (a platform end cap stands for its tile)."""
    return _CANON.get(_DOTTED.get(b, b), _DOTTED.get(b, b))


needs_emulator = unittest.skipUnless(shutil.which("atari800") and XEX.exists() and LABELS.exists(), "needs atari800 and `task build-test`")


def hud(score: int = 0, level: int = 1, lives: int = 3, left: int = 8) -> str:
    return f"SCORE {score:05d} LEVEL {level:02d}  LIVES {lives}  LEFT {left:03d}"


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

    def strip_dots(self) -> int:
        """Take every dot off the screen (and out of the count), so a test about items or the door sees only those.
        Returns how many there were."""
        g = self.g
        raw = bytearray(g.mem(g.screen_addr, 1024))
        n = 0
        for i in range(COLS, COLS * 24):
            if raw[i] in _DOTTED:
                raw[i] = _DOTTED[raw[i]]
                n += 1
        g.poke_bytes(g.screen_addr, raw[: COLS * 24])
        g.poke("left", g.left - n)
        g.idle()
        return n

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
        self.assertEqual(g.mem(g.pm0 - 0x100, 256), bytes(256), "nor his third colour (the missiles)")

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
        want = [a | b | c for a, b, c in zip(*_ba.parse_sprite_frames(ROOT / "assets" / "sprites.txt")[g.frame][1:])]
        lit = [a | b | c for a, b, c in zip(sprite, g.eyes(), g.third())]
        self.assertEqual(lit[:lines], want[:lines], "the revealed lines are the frame's own (blank rows stay blank)")
        for layer in (sprite, g.eyes(), g.third()):
            self.assertEqual(layer[lines:], bytes(16 - lines), "the rest is still empty, in every layer")

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
        pal = _ba.parse_palette(ROOT / "assets" / "palette.txt")
        self.assertEqual(g.mem(0x0200, 256)[0xC0], pal["player"], "the body colour of assets/palette.txt (pink)")
        self.assertEqual(g.mem(0x0200, 256)[0xC3], pal["eyes"], "the eyes colour of assets/palette.txt (white)")
        self.assertEqual(g.mem(0x0200, 256)[0xC7], pal["ice"], "the third colour is playfield colour 3: the ice colour")


# ---------------------------------------------------------------------------
@needs_emulator
class Hud(Base):
    def test_score_row_shows_score_level_lives_and_items_left(self) -> None:
        self.start()
        self.assertEqual(self.row(0).rstrip(), hud(left=LEVEL_ITEMS[0]), "everything to collect: dots and items")
        self.strip_dots()
        self.assertEqual(self.row(0).rstrip(), hud())

    def test_score_row_updates(self) -> None:
        g = self.start()
        self.strip_dots()
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
        self.strip_dots()  # (the dots have their own tests below)

    # ---- start ----
    def test_starts_on_the_floor_with_a_full_level(self) -> None:
        g = self.g
        self.assertEqual((g.px, g.py, g.state), (SPAWN_X, SPAWN_Y, GROUND))
        self.assertEqual((g.left, g.score16, g.lives, g.level), (8, 0, 3, 1))
        self.assertEqual(g.tile(8, 20), T_LADDER)
        self.assertEqual(g.tile(14, 22), T_ITEM)
        self.assertEqual(g.tile(20, 22), T_SPIKE)
        self.assertEqual(g.tile(0, 10), TILE["WALL"])
        self.assertEqual(canon(g.tile(10, 23)), T_BRICK)  # the floor, perhaps with a dot or an end cap

    def test_idle_player_does_not_move(self) -> None:
        self.g.idle(30)
        self.assertEqual((self.g.px, self.g.py, self.g.state), (SPAWN_X, SPAWN_Y, GROUND))

    # ---- which frame he is drawn with ----
    def frames_seen(self, buttons: int, frames: int) -> set[int]:
        seen = set()
        for _ in range(frames):
            self.g.step(buttons)
            seen.add(self.g.frame)
        return seen

    def test_he_looks_at_you_until_he_first_moves(self) -> None:
        self.g.idle(10)
        self.assertEqual(self.g.frame, FR_STAND)

    def test_he_leans_and_looks_the_way_he_walks(self) -> None:
        g = self.g
        self.assertEqual(self.frames_seen(RIGHT, 20), {FR_STAND + 1, FR_LEAN})
        g.idle(5)
        self.assertEqual(g.frame, FR_STAND + 1, "stopped: still looking right")
        self.assertEqual(self.frames_seen(LEFT, 20), {FR_STAND + 2, FR_LEAN + 1})
        g.idle(5)
        self.assertEqual(g.frame, FR_STAND + 2)

    def test_he_squashes_to_jump_stretches_in_the_air_and_squashes_on_landing(self) -> None:
        g = self.g
        g.step(RIGHT, 2)
        g.step(FIRE | RIGHT)
        self.assertEqual(g.frame, FR_SQUASH + 1, "taking off")
        g.run(3, RIGHT)
        self.assertEqual(g.frame, FR_STRETCH + 1, "rising")
        g.run_until(lambda g: g.state == GROUND, limit=60, every=1)
        for _ in range(4):
            self.assertEqual(g.frame, FR_SQUASH + 1, "landing")
            g.step()
        self.assertEqual(g.frame, FR_STAND + 1, "back to normal")

    def test_a_jump_straight_up_from_the_start_is_all_front_on(self) -> None:
        g = self.g
        g.step(FIRE)
        self.assertEqual(g.frame, FR_SQUASH)
        g.run(4)
        self.assertEqual(g.frame, FR_STRETCH)

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
    def test_jump_rises_26_pixels_and_lands(self) -> None:
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
        self.assertEqual(min(ys), FLOOR_Y[8] - 26)
        self.assertEqual((g.py, g.state), (FLOOR_Y[8], GROUND))
        self.assertEqual(ys[apex:], sorted(ys[apex:]), "no bouncing after the apex")

    def test_he_floats_down_slower_than_he_rises_and_the_fall_still_counts_pixels(self) -> None:
        g = self.g
        g.poke("px", 80)
        g.poke("py", FLOOR_Y[8])
        g.idle(2)
        g.step(FIRE)
        ys, falls = [g.py], [g.fall]
        for _ in range(60):
            g.idle()
            ys.append(g.py)
            falls.append(g.fall)
            if g.state == GROUND:
                break
        apex = ys.index(min(ys))
        down = ys[apex:]
        steps = [b - a for a, b in zip(down, down[1:]) if b != a]  # (not the frame at the apex, nor the landing one)
        self.assertEqual(sum(steps), 26)
        self.assertTrue(set(steps) <= {1, 2} and steps[0] == 1, f"1 pixel a frame to begin with, never more than 2: {steps}")
        self.assertEqual(steps[-1], 2, "full speed at the end of a fall of 26")
        self.assertGreaterEqual(len(steps), apex + 4, f"the way down takes longer than the way up: {apex} frames up, {len(steps)} down")
        self.assertEqual(falls[-1], 0, "`fall` counts the pixels fallen (the lethal distance is unchanged) and is zero on the ground")
        self.assertEqual(max(falls), 26)

    def test_a_jump_goes_up_through_the_floor_overhead_on_lower_floors(self) -> None:
        g = self.g
        g.step(FIRE)
        ys = []
        for _ in range(40):
            g.idle()
            ys.append(g.py)
            if g.state == GROUND:
                break
        self.assertEqual(min(ys), SPAWN_Y - 26)  # nothing above him stops the rise (row 18's bricks are just overlaid)
        self.assertEqual((g.py, g.state), (SPAWN_Y, GROUND))

    def test_holding_fire_does_not_bunny_hop(self) -> None:
        g = self.g
        g.step(FIRE, 80)
        self.assertEqual(g.state, GROUND)  # one jump, then it waits for a fresh press

    def test_can_steer_in_the_air(self) -> None:
        g = self.g
        g.poke("px", 80)  # the top floor, open air above (under the floors below a jump now goes up through them,
        g.poke("py", FLOOR_Y[8])  # and sideways moves are blocked while his body is inside a brick)
        g.idle(2)
        g.step(FIRE | RIGHT)
        g.step(RIGHT, 10)
        self.assertGreater(g.px, 80 + 8)
        g.idle(30)
        self.assertEqual(g.state, GROUND)

    def test_no_head_bump_under_a_floor(self) -> None:
        g = self.g
        self.walk_to(40)  # open floor under row 18 (the ladder at column 8 is behind us)
        g.step(FIRE)
        top = min([g.py] + [(g.step(0) or g.py) for _ in range(50)])  # (the way down takes longer than the way up)
        self.assertEqual(top, FLOOR_Y[23] - 26)
        self.assertEqual((g.state, g.py), (GROUND, FLOOR_Y[23]), "fell back down through the floor above")

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
        g.step(RIGHT, 60)  # into the hole at columns 24-27 (and the slow way down)
        self.assertEqual((g.state, g.py, g.mode), (GROUND, FLOOR_Y[23], PLAY))  # dropped one floor and survived

    def test_level_data_matches_the_source_file(self) -> None:
        g = self.g
        lines = [
            l for l in (ROOT / "assets" / "levels" / "level1.txt").read_text().splitlines()
            if l and not l.startswith("# ")
        ]
        tiles = {**CHAR_BYTE, "@": 0}
        expected = bytearray(tiles[c] for row in lines for c in row)
        self.assertEqual(len(expected), COLS * 24)
        for i, ch in enumerate("".join(lines)):
            if ch == "D":  # the compiler adds the rest of the door (2 tiles wide, 3 tall) to its bottom left tile
                for name, (dc, dr) in zip(DOOR_NAMES, _ba.DOOR_CELLS):
                    expected[i + dc - dr * COLS] = TILE[name]
        expected = bytes(expected)
        got = bytes(canon(b) for b in g.mem(g.screen_addr, 1024)[COLS : COLS * 24])  # ignoring the score row
        self.assertEqual(got, expected[COLS:])
        # ...and the build really did put end caps on the floor where it meets something else
        self.assertTrue(any(b != canon(b) for b in g.mem(g.screen_addr, 1024)[COLS : COLS * 24]))

    # ---- display ----
    def test_player_sprite_is_in_player_memory(self) -> None:
        sprite = self.g.sprite()
        self.assertEqual(len(sprite), 16)
        self.assertEqual(sprite[1], 0x7E)  # the second row of the stand frame: .######.

    def test_he_floats_above_the_floor_and_the_physics_box_stays_put(self) -> None:
        g = self.g
        self.assertEqual(g.py, SPAWN_Y, "his box is where it always was: standing on the floor")
        for page in (g.mem(g.pm0, 256), g.mem(g.pm0 + 0x300, 256), g.mem(g.pm0 - 0x100, 256)):
            first = PM_YOFF + g.py - g.pfloat
            self.assertEqual(page[:first], bytes(first), "nothing above the image")
            self.assertEqual(page[first + 16 :], bytes(256 - first - 16), "and nothing below it")
        body = g.sprite()
        want = _ba.parse_sprite_frames(ROOT / "assets" / "sprites.txt")[g.frame][1]
        self.assertEqual(list(body), want)
        # the lowest picture line is pfloat (the hover plus the bob, 1 to 3) scan lines above the bottom of his box (the surface)
        feet = PM_YOFF + g.py + 16  # the first PM line of the surface
        self.assertTrue(BOB_RANGE[0] <= g.pfloat <= BOB_RANGE[1], g.pfloat)
        self.assertEqual(g.mem(g.pm0, 256)[feet - g.pfloat : feet], bytes(g.pfloat), "a gap below him")
        self.assertEqual(list(g.mem(g.pm0, 256)[feet - g.pfloat - 16 : feet - g.pfloat]), want, "and his picture right above the gap")

    def test_he_bobs_between_one_and_three_lines_above_the_surface_never_below_it(self) -> None:
        g = self.g
        seen = set()
        for _ in range(70):  # a bit more than one period (64 frames)
            g.idle()
            seen.add(g.pfloat)
            self.assertEqual(g.py, SPAWN_Y, "purely visual: the physics box never moves")
            self.assertTrue(BOB_RANGE[0] <= g.pfloat <= BOB_RANGE[1], g.pfloat)
            feet = PM_YOFF + g.py + 16
            raw = g.mem(g.pm0, 256)
            self.assertEqual(raw[feet - g.pfloat : feet], bytes(g.pfloat), "a gap below him, never into the floor")
            want = _ba.parse_sprite_frames(ROOT / "assets" / "sprites.txt")[g.frame][1]
            self.assertEqual(list(raw[feet - g.pfloat - 16 : feet - g.pfloat]), want, "and his picture right above it")
            for page in (g.mem(g.pm0 + 0x300, 256), g.mem(g.pm0 - 0x100, 256)):
                top = PM_YOFF + g.py - g.pfloat
                self.assertEqual(page[:top], bytes(top))  # eyes and missiles move with the body
                self.assertEqual(page[top + 16 :], bytes(256 - top - 16))
        self.assertEqual(seen, {1, 2, 3}, "he drifts through all three heights")

    def test_float_is_the_same_in_the_game_the_editor_and_the_tools(self) -> None:
        import re

        asm = int(re.search(r"^PLAYER_FLOAT\s*=\s*(\d+)", (ROOT / "src" / "main.s").read_text(), re.M).group(1))
        js = int(re.search(r"export const FLOAT = (\d+);", (ROOT / "web" / "spritemodel.js").read_text()).group(1))
        render = int(re.search(r"^PLAYER_FLOAT = (\d+)", (ROOT / "tools" / "render_level.py").read_text(), re.M).group(1))
        self.assertEqual((asm, js, render), (PLAYER_FLOAT,) * 3)
        self.assertIn(PLAYER_FLOAT, (1, 2), "a pixel or two")
        table = [int(v) for v in re.search(r"^bob_float:\n((?:\s+\.byte [\d,]+\n)+)", (ROOT / "src" / "main.s").read_text(), re.M).group(1).replace(".byte", "").replace("\n", ",").split(",") if v.strip()]
        self.assertEqual(len(table), 64)
        self.assertEqual((min(table), max(table)), BOB_RANGE, "the bob stays within 1 to 3 lines above the surface")
        self.assertTrue(all(abs(a - b) <= 1 for a, b in zip(table, table[1:] + table[:1])), "smooth: one line at a time")
        self.assertIn(PLAYER_FLOAT, set(table))

    def test_his_third_colour_is_the_missile_page_with_the_same_float_and_position(self) -> None:
        g = self.g
        top = PM_YOFF + g.py - g.pfloat
        page = g.mem(g.pm0 - 0x100, 256)  # the four missiles: PMBASE + $300 in single-line resolution
        want = _ba.parse_sprite_frames(ROOT / "assets" / "sprites.txt")[g.frame][3]
        self.assertEqual(list(page[top : top + 16]), want)
        self.assertEqual(page[:top], bytes(top), "nothing above the image")
        self.assertEqual(page[top + 16 :], bytes(256 - top - 16), "nothing below it")
        eyes, body = g.eyes(), g.sprite()
        px_third = [_ba.third_pixels(b) for b in g.third()]
        self.assertTrue(all(not (t & (e | b)) for t, e, b in zip(px_third, eyes, body)), "the third colour only where body and eyes have holes")

    def test_the_missiles_are_enabled_and_form_a_fifth_player_behind_the_others(self) -> None:
        g = self.g
        shadow = g.mem(0x0200, 256)
        self.assertEqual(shadow[0x6F], 0x11, "GPRIOR: players in front of the playfield, missiles as a fifth player (bit 4)")
        self.assertEqual(shadow[0x2F] & 0x3E, 0x3E, "SDMCTL: display list, single line, missile and player DMA")

    def test_his_eyes_are_player_3(self) -> None:
        g = self.g
        top = PM_YOFF + g.py - g.pfloat
        eyes = g.mem(g.pm0 + 0x300, 512)[top : top + 16]
        want = _ba.parse_sprite_frames(ROOT / "assets" / "sprites.txt")[0][2]
        self.assertEqual(list(eyes), want)
        self.assertTrue(any(want), "the stand frame has eyes")
        body = g.sprite()
        self.assertTrue(all(not (e & b) for e, b in zip(eyes, body)), "an eye is never where the body is")

    def test_sprite_follows_the_player_vertically(self) -> None:
        g = self.g
        g.step(FIRE, 3)
        self.assertNotEqual(g.py, SPAWN_Y)
        want = _ba.parse_sprite_frames(ROOT / "assets" / "sprites.txt")[g.frame][1]
        self.assertEqual(list(g.sprite()), want, "the body of the frame he is on")
        raw = g.mem(g.pm0, 256)
        self.assertEqual(raw[PM_YOFF + SPAWN_Y - BOB_RANGE[1] + 15], 0, "no stale image left at the old position")


# ---------------------------------------------------------------------------
@needs_emulator
class DeathAndLives(Base):
    def setUp(self) -> None:
        super().setUp()
        self.start()
        self.strip_dots()

    def die_on_spikes(self) -> None:
        g = self.g
        self.walk_to(76)
        for _ in range(6):
            g.step(RIGHT)
            if g.mode == DYING:
                break

    def test_the_image_never_leaves_its_player_page_wherever_the_death_hop_puts_him(self) -> None:
        g = self.g
        self.die_on_spikes()
        self.assertEqual(g.mode, DYING)
        pegs = g.mem(g.pm0 + 0x100, 256)
        for py in (0, 1, 2, 3, 40, 198, 199, 200, 201, 202, 230, 253, 254, 255):
            g.poke("py", py)
            g.idle()
            top = g.py - g.pfloat  # where the image starts: a wrapped value is off the screen
            for page in (g.mem(g.pm0, 256), g.mem(g.pm0 + 0x300, 256), g.mem(g.pm0 - 0x100, 256)):
                lit = [i for i, b in enumerate(page) if b]
                if 0 <= top < 200:
                    self.assertTrue(all(PM_YOFF + top <= i < PM_YOFF + top + 16 for i in lit), (py, g.py, lit))
                else:
                    self.assertEqual(lit, [], f"py {py} -> {g.py}: hidden")
            self.assertEqual(g.mem(g.pm0 + 0x100, 256), pegs, "the pegs' player is not scribbled on")
            self.assertEqual(g.mem(g.pm0 + 0x200, 256), bytes(256))

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
        self.assertEqual(frames, {FR_DIE_A, FR_DIE_A + 1}, "tumbles between the two death frames")

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
        self.assertEqual((g.px, g.py, g.state, g.left, g.score16), (SPAWN_X, SPAWN_Y, GROUND, LEVEL_ITEMS[0], 10), "the score is kept")
        self.assertEqual(g.tile(14, 22), T_ITEM, "the level is restored")
        self.assertIn(TILE["BRICK_DOT"], g.mem(g.screen_addr + 23 * COLS, 256)[:COLS], "...dots and all")
        self.assertEqual(self.row(0).rstrip(), hud(10, lives=2, left=LEVEL_ITEMS[0]))
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
        self.assertEqual(g.mem(g.pm0 - 0x100, 256), bytes(256), "and no missiles")

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
        self.strip_dots()

    DOOR = (36, 7)  # level 1's exit: its bottom left tile (2 wide, 3 tall), on the top floor

    def glyphs(self) -> bytes:
        return self.g.mem(DOOR_GLYPHS, 256)[:48]

    def door_phase(self) -> int:
        return self.g.bss("door_phase")[0]

    def take_the_last_item(self) -> None:
        """Pick up one item with only that one left, which makes the door appear."""
        g = self.g
        g.step(RIGHT, 20)
        g.poke("left", 1)
        for _ in range(40):
            g.step(RIGHT)
            if g.left == 0:
                break
        self.assertEqual(g.left, 0)

    def walk_into_the_door(self) -> None:
        g = self.g
        g.poke("px", self.DOOR[0] * 4 - 12)
        g.poke("py", FLOOR_Y[8])
        g.poke("state", GROUND)
        g.idle(2)
        for _ in range(40):
            g.step(RIGHT)
            if g.mode == CLEAR:
                break

    def finish_level(self) -> None:
        self.take_the_last_item()
        self.walk_into_the_door()
        self.assertEqual(self.g.mode, CLEAR)

    def test_the_door_is_in_the_map_but_not_on_the_screen_until_everything_is_collected(self) -> None:
        g = self.g
        col, row = self.DOOR
        cells = [g.tile(col + dc, row - dr) for dc, dr in _ba.DOOR_CELLS]
        self.assertEqual(cells, [TILE[n] for n in DOOR_NAMES], "six tiles, 2 wide and 3 tall")
        self.assertEqual(self.glyphs(), bytes(48), "their glyphs are blank")
        self.walk_into_the_door()
        self.assertEqual(g.mode, PLAY, "an unopened door lets you walk through where it will be")
        self.assertEqual(g.score16, 0)

    def test_taking_the_last_thing_fades_the_door_in(self) -> None:
        g = self.g
        self.take_the_last_item()
        self.assertEqual((g.mode, g.bss("door_open")[0]), (PLAY, 1), "the level is not over until you walk through")
        self.assertGreater(g.flash, 0)
        self.assertEqual(g.score16, 10, "no bonus yet")
        seen = {self.door_phase()}
        for _ in range(40):
            g.step()
            phase = self.door_phase()
            self.assertIn(phase - max(seen), (0, 1), "one step at a time")
            self.assertEqual(self.glyphs(), door_glyphs(phase), f"at step {phase} exactly those pixels are there")
            seen.add(phase)
        self.assertEqual(max(seen), 16)
        self.assertEqual(self.glyphs(), door_glyphs(16))
        art = bytes(int(row, 4) for name in DOOR_NAMES for row in TILE_ROWS[name])
        self.assertEqual(self.glyphs(), art, "all of it is the art in assets/tiles.txt")

    def test_walking_into_the_door_takes_him_through_and_the_door_fades_out(self) -> None:
        g = self.g
        self.take_the_last_item()
        g.run(40)
        self.walk_into_the_door()
        self.assertEqual(g.mode, CLEAR)
        self.assertEqual(g.mem(g.pm0, 256), bytes(256), "he is gone from the screen")
        self.assertEqual(g.mem(g.pm0 - 0x100, 256), bytes(256), "and so are his missiles")
        phases = [self.door_phase()]
        for _ in range(40):
            g.step()
            self.assertEqual(g.mode, CLEAR)
            phases.append(self.door_phase())
            self.assertEqual(self.glyphs(), door_glyphs(phases[-1]), f"at step {phases[-1]} exactly those pixels are there")
        self.assertEqual(phases, sorted(phases, reverse=True), "only ever fading out")
        self.assertEqual((phases[0], phases[-1]), (16, 0), "from all of it to none")
        self.assertEqual(self.glyphs(), bytes(48))

    def test_clearing_the_level_gives_a_bonus_and_celebrates(self) -> None:
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
        self.assertEqual((g.level, g.lvlidx, g.left, g.lives, g.score16), (2, 1, LEVEL_ITEMS[1], 3, 110))
        self.assertEqual(self.row(0).rstrip(), hud(110, level=2, left=LEVEL_ITEMS[1]))
        self.assertEqual(g.tile(4, 7), T_ITEM, "level 2's map")
        g.run(SPAWN_FRAMES)
        self.assertEqual(g.mode, PLAY)

    def test_dying_on_level_two_restarts_level_two_and_keeps_the_score(self) -> None:
        g = self.g
        self.finish_level()
        g.run(CLEAR_FRAMES + 1 + SPAWN_FRAMES)
        self.strip_dots()
        base = g.score16  # (he may have eaten the dot he spawned on before it was stripped)
        g.step(RIGHT, 30)  # picks up level 2's first item, at column 8
        self.assertEqual(g.score16, base + 10)
        self.kill()
        g.run(DIE_FRAMES)
        self.assertEqual((g.mode, g.level, g.lives, g.score16, g.left), (SPAWN, 2, 2, base + 10, LEVEL_ITEMS[1]))

    def test_levels_wrap_around_but_the_counter_keeps_counting(self) -> None:
        g = self.g
        g.poke("level", 5)
        g.poke("lvlidx", 4)  # the last map (there are five)
        g.poke("mtimer", 0)
        g.poke("mode", CLEAR)
        g.run(CLEAR_FRAMES + 2)
        self.assertEqual((g.mode, g.level, g.lvlidx), (SPAWN, 6, 0))
        self.assertEqual(self.row(0)[18:20], "06")


# ---------------------------------------------------------------------------
@needs_emulator
class Dots(Base):
    def cells(self, *tiles: int) -> list[tuple[int, int]]:
        raw = self.g.mem(self.g.screen_addr, 1024)
        return [(i % COLS, i // COLS) for i in range(COLS, COLS * 24) if raw[i] in tiles]

    def test_the_level_starts_with_the_count_of_its_dots_and_items(self) -> None:
        g = self.start()
        dotted = self.cells(*_DOTTED)
        self.assertGreater(len(dotted), 20)
        self.assertEqual(g.left, len(dotted) + len(self.cells(T_ITEM)))
        self.assertEqual(g.left, LEVEL_ITEMS[0])

    def test_walking_over_dots_eats_them_one_point_each(self) -> None:
        g = self.start()
        before = set(self.cells(*_DOTTED))
        left = g.left
        g.step(RIGHT, 30)
        g.idle()
        eaten = before - set(self.cells(*_DOTTED))
        self.assertGreaterEqual(len(eaten), 3)
        self.assertTrue(all(row == 23 for _, row in eaten), "the ones on the floor he walked along")
        self.assertEqual(g.score16, len(eaten))
        self.assertEqual(g.left, left - len(eaten))
        for col, row in eaten:
            self.assertEqual(g.tile(col, row), TILE["BRICK"], "the tile is a plain tile again, and still solid")
        self.assertEqual(g.state, GROUND)

    def test_a_dot_is_eaten_only_once(self) -> None:
        g = self.start()
        g.step(RIGHT, 30)
        g.idle()
        score = g.score16
        g.step(LEFT, 12)
        g.step(RIGHT, 12)
        self.assertEqual(g.score16, score)

    def test_a_dotted_tile_is_solid_and_walkable_like_a_plain_one(self) -> None:
        g = self.start()
        g.step(RIGHT, 40)  # (the spikes are at column 20)
        self.assertEqual((g.state, g.py, g.mode), (GROUND, FLOOR_Y[23], PLAY))

    def test_a_dot_is_not_eaten_by_jumping_over_it(self) -> None:
        g = self.start()
        g.poke("px", 30 * 4)  # a clear stretch of the floor (the spikes are at column 20)
        g.poke("py", FLOOR_Y[23])
        g.idle(2)
        g.step(FIRE | RIGHT)  # take-off (it may eat the one it stood on)
        dots = set(self.cells(*_DOTTED))
        flying = 0
        while g.state == AIR and flying < 40:
            g.step(RIGHT)
            flying += 1
            if g.state == AIR:
                self.assertEqual(set(self.cells(*_DOTTED)), dots, "nothing is eaten in the air")
        self.assertGreater(flying, 5, "it jumped")


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
        self.assertLess(g.left, LEVEL_ITEMS[0] - 20, "it ate dots and collected items")
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
