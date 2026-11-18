"""The editor's JavaScript (web/model.js, web/engine.js) against the real thing.

* ``CompileParity``: the editor compiles a level (tile bytes with end caps, start, item count, pegs) exactly
  as tools/build_assets.py does, for every shipped level and for random levels. Needs only node.
* ``EngineMatchesGame``: the same scripted joystick input is played on the real 6502 game in the emulator
  and on web/engine.js, and the player, the screen map and the pegs are compared after every stretch of
  input. A failure is replayed one frame at a time to say which frame first differs. Needs atari800 and
  ``task build-test`` as well.

The random levels are made of every kind of platform, ladder, stair, chute, bomb and spike, so they reach
combinations the five shipped maps do not.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

import build_assets as ba  # noqa: E402
from editor_server import Project  # noqa: E402
from test_factory import Arena  # noqa: E402
from test_game import needs_emulator  # noqa: E402
from tools.headless import DOWN, FIRE, LEFT, OVER, PLAY, RIGHT, UP, Game  # noqa: E402

needs_node = unittest.skipUnless(shutil.which("node"), "needs node")
TRACE = ROOT / "tests" / "js" / "trace.mjs"
API = Project(ROOT).tiles_api()
BYTE = {t["name"]: t["byte"] for t in API["tiles"]}
CHAR = {t["name"]: t["char"] for t in API["tiles"] if t["char"]}
TILES = ba.parse_tiles(ROOT / "assets" / "tiles.txt")
CHARS = {t["char"]: t["byte"] for t in TILES if t["char"] is not None}
SOLID = {t["byte"] for t in TILES if t["solid"]}
CAPS = ba.cap_families(TILES)
LEVELS = sorted((ROOT / "assets" / "levels").glob("*.txt"), key=ba.natural_key)

BELTS = [n for n in CHAR if n.startswith("CONV_")]
PLATFORMS = ["BRICK", "BRICK", "PLATFORM", "ICE", "ICE", "ROLLER", "ROLLER", "EXPLOSIVE", "VANISH"] + BELTS


def node_trace(spec: dict) -> dict:
    out = subprocess.run(["node", str(TRACE)], input=json.dumps({"tiles": API, **spec}), capture_output=True, text=True, timeout=60)
    if out.returncode:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout)


def random_level(seed: int) -> str:
    """A level full of every part, placed without regard for whether it can be played."""
    rnd = random.Random(seed)
    grid = [["."] * 40 for _ in range(24)]
    for r in range(1, 24):
        grid[r][0] = grid[r][39] = "#"
    grid[23] = ["#"] * 40
    rows = [20, 17, 14, 11, 8, 5]
    for r in rows:
        for _ in range(rnd.randint(1, 3)):
            c0 = rnd.randint(1, 30)
            tile = CHAR[rnd.choice(PLATFORMS)]
            for c in range(c0, min(39, c0 + rnd.randint(3, 14))):
                grid[r][c] = tile
    for _ in range(rnd.randint(2, 5)):  # ladders
        c, r0 = rnd.randint(2, 37), rnd.choice(rows) - rnd.randint(2, 4)
        for r in range(max(1, r0), min(23, r0 + rnd.randint(3, 7))):
            grid[r][c] = CHAR["LADDER"]
    for _ in range(rnd.randint(2, 4)):  # stairs and chutes
        name = rnd.choice(["STAIR", "STAIR", "SLIDE_R", "SLIDE_L"])
        c, r, d = rnd.randint(3, 34), rnd.choice(rows), rnd.choice([-1, 1])
        for i in range(rnd.randint(2, 4)):
            if 1 <= r - i < 23 and 1 <= c + d * i < 39:
                grid[r - i][c + d * i] = CHAR[name]
    for _ in range(rnd.randint(6, 12)):  # items and spikes just above something
        c = rnd.randint(1, 38)
        r = rnd.randint(2, 22)
        if grid[r][c] == "." and grid[r + 1][c] != ".":
            grid[r][c] = rnd.choice("**^")
    c0 = rnd.randint(2, 36)
    for r in (20, 21, 22):
        grid[r][c0] = "."
    grid[21][c0] = "@"
    # one guaranteed item, a dozen columns away so the level isn't cleared on the first step
    grid[22][c0 + 12 if c0 + 12 <= 37 else c0 - 12] = "*"
    return (
        "# Level 99. 40 columns x 24 rows.\n"
        + "\n".join("".join(row) for row in grid)
        + "\n"
    )


def random_segments(seed: int, frames: int = 300) -> list[list[int]]:
    rnd = random.Random(seed * 7919 + 1)
    inputs = [0, RIGHT, RIGHT, LEFT, LEFT, RIGHT | FIRE, LEFT | FIRE, FIRE, UP, DOWN, UP | RIGHT, UP | LEFT, DOWN | LEFT, DOWN | RIGHT]
    segs, total = [], 0
    while total < frames:
        n = rnd.choice([1, 1, 2, 3, 5, 8, 8, 13, 21, 34])
        segs.append([rnd.choice(inputs), n])
        total += n
    return segs


@needs_node
class CompileParity(unittest.TestCase):
    def check(self, text: str) -> None:
        got = node_trace({"text": text, "segments": []})["compiled"]
        want = ba.parse_level(Path("x.txt"), CHARS, SOLID, CAPS, text=text)
        self.assertEqual(got["map"], want["data"][:960])
        self.assertEqual(got["spawn"], list(want["spawn"]))
        self.assertEqual(got["items"], want["items"])
        self.assertEqual(got["pegs"], [list(p) for p in want["pegs"]])

    def test_every_shipped_level_compiles_the_same_way(self) -> None:
        for path in LEVELS:
            with self.subTest(path.name):
                self.check(path.read_text())

    def test_random_levels_compile_the_same_way(self) -> None:
        for seed in range(25):
            with self.subTest(seed=seed):
                self.check(random_level(seed))

    def test_the_editor_rejects_what_the_asset_tool_rejects(self) -> None:
        good = LEVELS[0].read_text().splitlines()
        cases = {
            "unknown character": [ln.replace("#", "?", 1) if ln.startswith("#") else ln for ln in good],
            "no start": [ln.replace("@", ".") for ln in good],
            "no items": [ln.replace("*", ".") for ln in good],
            "two starts": [ln.replace(".", "@", 2) if ln.startswith("....") else ln for ln in good],
        }
        for what, lines in cases.items():
            with self.subTest(what):
                text = "\n".join(lines) + "\n"
                with self.assertRaises(ba.AssetError):
                    ba.parse_level(Path("x.txt"), CHARS, SOLID, CAPS, text=text)
                self.assertIn("error", node_trace({"text": text, "segments": []}))


FIELDS = ["mode", "px", "py", "state", "left", "lives", "score", "jt", "fall", "vx", "vfrac"]


@needs_emulator
@needs_node
class EngineMatchesGame(Arena):
    def fresh(self) -> None:
        """A new emulator, so the next scenario starts from a clean boot."""
        self.g.close()
        self.g = Game()
        self.addCleanup(self.g.close)

    def read_game(self) -> dict:
        g = self.g
        snap = {f: getattr(g, f) for f in FIELDS if f != "score"}
        snap["score"] = g.score16
        return snap

    def read_map(self) -> list[int]:
        return list(self.g.mem(self.g.screen_addr, 1024)[:960])

    def read_pegs(self) -> list[list[int]]:
        g, n = self.g, self.g.pg_n
        return [[g.bss("pg_x", 2)[i], g.bss("pg_dir", 2)[i], g.bss("pg_wait", 2)[i]] for i in range(n)]

    def compare(self, label: str, rec: dict) -> None:
        got = self.read_game()
        want = {f: rec["snap"][f] for f in FIELDS}
        self.assertEqual(got, want, f"{label}: player state differs (game vs engine)")
        if want["mode"] == OVER:  # the real game now draws its game-over screen over the map
            return
        gm, wm = self.read_map(), rec["map"]
        diffs = [(i % 40, i // 40, gm[i], wm[i]) for i in range(40, 960) if gm[i] != wm[i]]
        self.assertEqual(diffs[:6], [], f"{label}: map differs at (col, row, game, engine)")
        self.assertEqual(self.read_pegs(), rec["pegs"], f"{label}: pegs differ (x, dir, wait)")

    def play(self, spec: dict, fine: bool) -> int:
        """Replay on the emulator (already set up) and compare after each segment; returns segments compared."""
        segs = spec["segments"]
        if fine:
            segs = [[b, 1] for b, n in segs for _ in range(n)]
        trace = node_trace({**spec, "segments": segs})
        self.assertNotIn("error", trace, trace.get("error"))
        done = 0
        for i, (buttons, frames) in enumerate(segs[: len(trace["records"])]):
            if frames == 1:
                self.g.step(buttons)
            else:
                self.g.run(frames, buttons)
            self.compare(f"segment {i} (buttons {buttons:#04x}, {frames} frames), frame {self.g.frames}", trace["records"][i])
            done += 1
        seen = {(r["snap"]["px"], r["snap"]["py"]) for r in trace["records"]}
        self.assertGreater(len(seen), 3, "the scripted input barely moved the player, so this compared nothing")
        return done

    def check(self, setup, spec: dict) -> None:
        """Run once in big segments; on a mismatch run again a frame at a time to name the first bad frame."""
        setup()
        try:
            self.play(spec, fine=False)
        except AssertionError as coarse:
            self.fresh()
            setup()
            try:
                self.play(spec, fine=True)
            except AssertionError as fine:
                self.fail(f"first difference, found frame by frame:\n{fine}\n\n(coarse run: {coarse})")
            self.fail(f"differs, but not when replayed frame by frame: {coarse}")

    # ---- random levels poked into the running game -------------------------------------------
    def load_random_level(self, text: str) -> None:
        g = self.start()
        lv = ba.parse_level(Path("x.txt"), CHARS, SOLID, CAPS, text=text)
        g.poke_bytes(g.screen_addr + 40, lv["data"][40:960])
        for name, value in dict(
            px=lv["spawn"][0] * 4, py=lv["spawn"][1] * 8, state=0, jt=0xFF, fall=0, vx=0, vfrac=0, cfrac=0, fcount=0,
            gtick=0, cacc_t=0, cacc=4, anim=0, moved=0, joy=0, joyprev=0, left=lv["items"], lives=1, pg_n=0,
        ).items():
            g.poke(name, value)
        g.poke_bytes(g.labels["tt_ph"], [0xFF] * 8)
        g.poke("mode", PLAY)
        self.assertEqual(g.mode, PLAY)

    def test_random_levels(self) -> None:
        for seed in range(12):
            with self.subTest(seed=seed):
                text = random_level(seed)
                self.fresh()
                segs = random_segments(seed)
                self.check(lambda: self.load_random_level(text), {"text": text, "lives": 1, "segments": segs})

    # ---- the shipped levels ------------------------------------------------------------------
    def standing_places(self, path: Path) -> list[tuple[int, int]]:
        data = ba.parse_level(path, CHARS, SOLID, CAPS)["data"]
        out = []
        for r in range(1, 21):
            for c in range(1, 39):
                at = lambda rr, cc=c: data[rr * 40 + cc]  # noqa: E731
                if at(r) == 0 and at(r + 1) == 0 and at(r + 2) in SOLID:
                    out.append((c * 4, r * 8))
        return out

    def run_level(self, index: int, start, seed: int) -> None:
        text = LEVELS[index].read_text()

        def setup() -> None:
            if index == 0:
                self.start()
            else:
                self.goto(index)
            if start:
                self.g.poke("px", start[0])
                self.g.poke("py", start[1])

        spec = {"text": text, "segments": random_segments(seed), "start": {"px": start[0], "py": start[1]} if start else None}
        self.check(setup, spec)

    def test_shipped_levels_from_the_start(self) -> None:
        for index in range(len(LEVELS)):
            with self.subTest(level=index + 1):
                self.fresh()
                self.run_level(index, None, 100 + index)

    def test_shipped_levels_from_random_places(self) -> None:
        for index in range(len(LEVELS)):
            places = self.standing_places(LEVELS[index])
            rnd = random.Random(index)
            for k in range(3):
                start = rnd.choice(places)
                with self.subTest(level=index + 1, start=start):
                    self.fresh()
                    self.run_level(index, start, 200 + index * 10 + k)

    def test_standing_on_the_pegs_block(self) -> None:
        for index, path in enumerate(LEVELS):
            pegs = ba.parse_level(path, CHARS, SOLID, CAPS)["pegs"]
            for n, (x, y, lo, hi, d) in enumerate(pegs):
                for start_x in (lo, (lo + hi) // 2 & ~3, hi):
                    with self.subTest(level=index + 1, peg=n, x=start_x):
                        self.fresh()
                        self.run_level(index, (start_x, y - 8), 300 + n)


if __name__ == "__main__":
    unittest.main()
