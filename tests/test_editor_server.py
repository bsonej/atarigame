"""tools/editor_server.py: the API the level editor talks to, and what it refuses to do.

Each test runs a real server on a free port against a throwaway copy of the project's assets, so nothing
in assets/levels/ is touched.
"""

from __future__ import annotations

import http.client
import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import editor_server  # noqa: E402

LEVEL1 = (ROOT / "assets" / "levels" / "level1.txt").read_text()


class ServerCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(ROOT / "assets", self.tmp / "assets")
        (self.tmp / "web").mkdir()
        (self.tmp / "web" / "index.html").write_text("<!doctype html><title>x</title>")
        (self.tmp / "secret.txt").write_text("not for the web")
        self.server = editor_server.make_server(self.tmp, 0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def req(self, method: str, path: str, body=None, headers=None, raw: bytes | None = None, editor: bool = True):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        self.addCleanup(conn.close)
        hdrs = {"Host": f"localhost:{self.port}"}
        if editor:
            hdrs["X-Editor"] = "1"
        hdrs.update(headers or {})
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        conn.request(method, path, body=data, headers=hdrs)
        res = conn.getresponse()
        payload = res.read()
        try:
            return res.status, json.loads(payload)
        except ValueError:
            return res.status, payload

    def levels_dir(self) -> Path:
        return self.tmp / "assets" / "levels"


class Reading(ServerCase):
    def test_tiles_describe_the_game_s_parts(self) -> None:
        status, api = self.req("GET", "/api/tiles")
        self.assertEqual(status, 200)
        by_name = {t["name"]: t for t in api["tiles"]}
        self.assertEqual((by_name["BRICK"]["char"], by_name["BRICK"]["solid"]), ("#", True))
        self.assertTrue(by_name["PLATFORM"]["oneway"])
        self.assertTrue(by_name["ICE"]["alt"])
        self.assertEqual(len(api["flags"]), 256)
        self.assertEqual(len(api["canon"]), 256)
        brick = str(by_name["BRICK"]["byte"])
        self.assertEqual(set(api["caps"][brick]), {"L", "R", "LR"})
        for byte in api["caps"][brick].values():
            self.assertEqual(api["canon"][byte], by_name["BRICK"]["byte"])
        for plain, twin in (("SLIDE_R", "SLIDE_R_B"), ("SLIDE_L", "SLIDE_L_B")):  # the chutes' twins, for odd rows
            self.assertEqual(api["twins"][str(by_name[plain]["byte"])], by_name[twin]["byte"])
            self.assertEqual(api["canon"][by_name[twin]["byte"]], by_name[plain]["byte"])
            self.assertEqual((by_name[twin]["twinOf"], by_name[twin]["oneway"], by_name[twin]["char"]), (plain, False, None))
        self.assertEqual(len(api["sprites"]), 13)
        self.assertEqual(len(api["sprites"][0]["rows"]), 16)
        for t in api["tiles"]:
            self.assertEqual(len(t["rows"]), 8)

    def test_levels_come_in_the_order_the_game_plays_them(self) -> None:
        (self.levels_dir() / "level10.txt").write_text(LEVEL1)
        status, levels = self.req("GET", "/api/levels")
        self.assertEqual(status, 200)
        names = [lv["name"] for lv in levels]
        self.assertEqual(names, ["level1", "level2", "level3", "level4", "level5", "level10"])
        self.assertEqual([lv["index"] for lv in levels], [1, 2, 3, 4, 5, 6])
        self.assertEqual(levels[3]["title"], "Assembly Line")

    def test_a_level_can_be_read(self) -> None:
        status, res = self.req("GET", "/api/level/level4")
        self.assertEqual(status, 200)
        self.assertEqual(res["text"], (ROOT / "assets/levels/level4.txt").read_text())

    def test_unknown_things_are_not_found(self) -> None:
        self.assertEqual(self.req("GET", "/api/level/level77")[0], 404)
        self.assertEqual(self.req("GET", "/api/nothing")[0], 404)
        self.assertEqual(self.req("GET", "/nothing.html")[0], 404)

    def test_the_page_is_served_and_nothing_outside_web(self) -> None:
        status, body = self.req("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>x</title>", body)
        for path in ("/../secret.txt", "/..%2fsecret.txt", "/%2e%2e/secret.txt", "/../assets/tiles.txt"):
            self.assertEqual(self.req("GET", path)[0], 404, path)


class Saving(ServerCase):
    def test_a_good_level_is_written_where_the_game_reads_it(self) -> None:
        status, res = self.req("PUT", "/api/level/level6", {"text": LEVEL1})
        self.assertEqual(status, 200, res)
        self.assertEqual((res["name"], res["index"], res["path"]), ("level6", 6, "assets/levels/level6.txt"))
        self.assertEqual((self.levels_dir() / "level6.txt").read_text(), LEVEL1)
        self.assertEqual([p.name for p in self.levels_dir().glob(".editor-*")], [], "no temporary files are left")
        self.assertEqual(self.req("GET", "/api/level/level6")[1]["text"], LEVEL1)

    def test_saved_files_are_readable_like_the_others(self) -> None:
        import stat

        self.req("PUT", "/api/level/level6", {"text": LEVEL1})
        self.req("PUT", "/api/level/level1", {"text": LEVEL1})
        for name in ("level6", "level1"):
            mode = stat.S_IMODE((self.levels_dir() / f"{name}.txt").stat().st_mode)
            self.assertEqual(mode, 0o644, name)

    def test_a_saved_level_builds_into_the_game(self) -> None:
        import build_assets as ba

        text = (ROOT / "assets/levels/level5.txt").read_text()
        self.req("PUT", "/api/level/level6", {"text": text})
        out = self.tmp / "gen"
        ba.build(self.tmp, out)
        self.assertIn("LEVEL_COUNT = 6", (out / "levels.inc").read_text())

    def test_a_level_the_asset_tool_would_refuse_is_not_written(self) -> None:
        bad = {
            "unknown character": LEVEL1.replace("#", "?", 3),
            "no start": LEVEL1.replace("@", "."),
            "no items": LEVEL1.replace("*", "."),
            "short": "\n".join(LEVEL1.splitlines()[:10]),
            "wide": LEVEL1.replace("....", ".....", 1),
        }
        for what, text in bad.items():
            with self.subTest(what):
                status, res = self.req("PUT", "/api/level/level6", {"text": text})
                self.assertEqual(status, 400, res)
                self.assertTrue(res["error"])
                self.assertNotIn("level6.txt:", res["error"], "messages should not name a made-up file")
                self.assertFalse((self.levels_dir() / "level6.txt").exists())

    def test_a_refused_save_leaves_the_old_level_alone(self) -> None:
        before = (self.levels_dir() / "level1.txt").read_text()
        self.assertEqual(self.req("PUT", "/api/level/level1", {"text": "nonsense"})[0], 400)
        self.assertEqual((self.levels_dir() / "level1.txt").read_text(), before)

    def test_names_cannot_climb_out_of_the_levels_folder(self) -> None:
        for name in ("../level1", "..%2flevel1", "..%2f..%2fweb%2fx", "Level1", "1level", "a" * 41, "level%201", "level1.txt", "x%00y", ""):
            with self.subTest(name):
                status, _ = self.req("PUT", f"/api/level/{name}", {"text": LEVEL1})
                self.assertIn(status, (400, 404))
        self.assertEqual(sorted(p.name for p in self.levels_dir().iterdir()), [f"level{i}.txt" for i in range(1, 6)])
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["assets", "secret.txt", "web"])

    def test_a_save_that_is_not_the_editors_is_refused(self) -> None:
        body = {"text": LEVEL1}
        self.assertEqual(self.req("PUT", "/api/level/level6", body, editor=False)[0], 403, "no X-Editor header")
        self.assertEqual(self.req("PUT", "/api/level/level6", body, headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.req("PUT", "/api/level/level6", body, headers={"Host": "evil.example"})[0], 403, "DNS rebinding")
        self.assertFalse((self.levels_dir() / "level6.txt").exists())

    def test_a_same_origin_page_may_save(self) -> None:
        status, _ = self.req("PUT", "/api/level/level6", {"text": LEVEL1}, headers={"Origin": f"http://localhost:{self.port}"})
        self.assertEqual(status, 200)

    def test_bodies_must_be_small_json_objects(self) -> None:
        self.assertEqual(self.req("PUT", "/api/level/level6", raw=b"x" * (70 * 1024))[0], 413)
        self.assertEqual(self.req("PUT", "/api/level/level6", raw=b"not json")[0], 400)
        self.assertEqual(self.req("PUT", "/api/level/level6", raw=b"[1,2]")[0], 400)
        self.assertEqual(self.req("PUT", "/api/level/level6", {"text": 5})[0], 400)

    def test_a_missing_final_newline_is_added(self) -> None:
        self.req("PUT", "/api/level/level6", {"text": LEVEL1.rstrip("\n")})
        self.assertTrue((self.levels_dir() / "level6.txt").read_text().endswith("\n"))


class Sprites(ServerCase):
    """assets/sprites.txt through the server: read, save (validated), and never the real file."""

    def sprites_path(self) -> Path:
        return self.tmp / "assets" / "sprites.txt"

    def frames(self) -> list[dict]:
        status, res = self.req("GET", "/api/sprites")
        self.assertEqual(status, 200, res)
        return [{"name": f["name"], "rows": list(f["rows"])} for f in res["frames"]]

    def put(self, frames, **kw):
        return self.req("PUT", "/api/sprites", {"frames": frames}, **kw)

    def test_the_frames_come_with_their_names_rows_and_bytes(self) -> None:
        import build_assets as ba

        status, res = self.req("GET", "/api/sprites")
        self.assertEqual(status, 200)
        self.assertEqual((res["width"], res["height"]), (8, 16))
        self.assertEqual(res["text"], (ROOT / "assets/sprites.txt").read_text())
        built = ba.parse_sprite_frames(ROOT / "assets" / "sprites.txt")
        self.assertEqual(len(res["frames"]), len(built))
        self.assertEqual(res["frames"][0]["name"], "stand")
        self.assertEqual(res["frames"][11]["name"], "pop_a")
        for f, (name, body, eyes, third) in zip(res["frames"], built):
            self.assertEqual((f["name"], f["body"], f["eyes"], f["third"]), (name, body, eyes, third))
            self.assertEqual(f["thirdPx"], [ba.third_pixels(b) for b in third])
            self.assertEqual(len(f["rows"]), 16)
            self.assertTrue(all(len(r) == 8 and set(r) <= set("#.eo") for r in f["rows"]))
        self.assertTrue(any(f["third"] for f in res["frames"]), "the pupils and the grin are the third colour")

    def test_saving_what_was_read_changes_nothing(self) -> None:
        before = self.sprites_path().read_text()
        status, res = self.put(self.frames())
        self.assertEqual((status, res["frames"], res["path"]), (200, 13, "assets/sprites.txt"))
        self.assertEqual(self.sprites_path().read_text(), before)

    def test_a_changed_pixel_is_written_and_the_comments_stay(self) -> None:
        before = self.sprites_path().read_text().splitlines()
        frames = self.frames()
        frames[1]["rows"][0] = "#.####.#"
        self.assertEqual(self.put(frames)[0], 200)
        after = self.sprites_path().read_text().splitlines()
        self.assertEqual(len(after), len(before))
        changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        self.assertEqual(len(changed), 1)
        self.assertEqual(after[changed[0]], "#.####.#")
        self.assertEqual([ln for ln in after if ln.startswith("# ")], [ln for ln in before if ln.startswith("# ")])
        self.assertEqual([ln for ln in after if ln.startswith("frame ")], [ln for ln in before if ln.startswith("frame ")])
        self.assertEqual([p.name for p in self.sprites_path().parent.glob(".editor-*")], [], "no temporary files are left")
        self.assertEqual(self.frames()[1]["rows"][0], "#.####.#")

    def test_a_saved_sprite_is_in_the_level_editor_s_data_and_builds_into_the_game(self) -> None:
        import build_assets as ba

        frames = self.frames()
        frames[2]["rows"][15] = "e#e##e#e"
        self.put(frames)
        status, api = self.req("GET", "/api/tiles")
        self.assertEqual((status, api["sprites"][2]["rows"][15], api["sprites"][2]["eyes"][15]), (200, 0x5A, 0xA5))
        out = self.tmp / "gen"
        ba.build(self.tmp, out)
        self.assertIn("SPR_COUNT = 13", (out / "sprites.inc").read_text())

    def test_the_wrong_number_of_frames_is_refused(self) -> None:
        frames = self.frames()
        before = self.sprites_path().read_text()
        for what, bad in {"one short": frames[:-1], "one more": frames + [frames[-1]], "none": []}.items():
            with self.subTest(what):
                status, res = self.put(bad)
                self.assertEqual(status, 400, res)
                self.assertIn("frames", res["error"])
        self.assertEqual(self.sprites_path().read_text(), before)

    def test_bad_rows_are_refused_with_a_message_that_says_where(self) -> None:
        before = self.sprites_path().read_text()
        cases = {
            "a bad character": ("stand_right", 3, "..#?##..", "frame stand_right row 3"),
            "a short row": ("lean_left", 0, "..###", "needs 8 characters"),
            "a long row": ("squash", 5, "..####...", "needs 8 characters"),
            "a space": ("pop_b", 9, "..## ...", "needs 8 characters"),
            "not text": ("stretch", 2, 7, "needs 8 characters"),
        }
        for what, (name, y, row, message) in cases.items():
            with self.subTest(what):
                frames = self.frames()
                next(f for f in frames if f["name"] == name)["rows"][y] = row
                status, res = self.put(frames)
                self.assertEqual(status, 400, res)
                self.assertIn(message, res["error"])
        with self.subTest("a missing row"):
            frames = self.frames()
            frames[4]["rows"].pop()
            status, res = self.put(frames)
            self.assertEqual(status, 400)
            self.assertIn("15 rows, needs 16", res["error"])
        with self.subTest("an extra row"):
            frames = self.frames()
            frames[4]["rows"].append("........")
            self.assertIn("17 rows, needs 16", self.put(frames)[1]["error"])
        self.assertEqual(self.sprites_path().read_text(), before, "a refused save leaves the file alone")

    def test_frames_cannot_be_renamed_or_reordered(self) -> None:
        before = self.sprites_path().read_text()
        frames = self.frames()
        renamed = [dict(f) for f in frames]
        renamed[3]["name"] = "wobble"
        reordered = frames[1:2] + frames[:1] + frames[2:]
        for what, bad in {"renamed": renamed, "reordered": reordered}.items():
            with self.subTest(what):
                status, res = self.put(bad)
                self.assertEqual(status, 400, res)
                self.assertIn("cannot be renamed or reordered", res["error"])
        self.assertEqual(self.sprites_path().read_text(), before)

    def test_a_row_may_be_blank_even_in_the_first_frame(self) -> None:
        frames = self.frames()
        frames[0]["rows"][7] = "........"
        self.assertEqual(self.put(frames)[0], 200)

    def test_the_third_colour_is_saved_and_must_come_in_pairs(self) -> None:
        import build_assets as ba

        frames = self.frames()
        frames[1]["rows"][0] = "oo.##.oo"
        self.assertEqual(self.put(frames)[0], 200)
        self.assertEqual(ba.parse_sprite_frames(self.sprites_path())[1][3][0], 0x03 | 0xC0)
        before = self.sprites_path().read_text()
        for bad in ("o.......", ".oo.....", "#.o.#.o."):
            with self.subTest(bad):
                frames[2]["rows"][0] = bad
                status, res = self.put(frames)
                self.assertEqual(status, 400, res)
                self.assertIn("pairs of pixels", res["error"])
                self.assertEqual(self.sprites_path().read_text(), before)

    def test_the_players_colours_are_read_and_saved_keeping_the_comments(self) -> None:
        import build_assets as ba

        status, res = self.req("GET", "/api/palette")
        self.assertEqual((status, res["player"], res["eyes"], res["third"]), (200, 0x4E, 0x0E, 0x8A))
        path = self.tmp / "assets" / "palette.txt"
        before = path.read_text().splitlines()
        status, res = self.req("PUT", "/api/palette", {"player": 0x36, "eyes": 0x1E, "ice": 0xAC})
        self.assertEqual((status, res["player"], res["eyes"], res["third"]), (200, 0x36, 0x1E, 0xAC))
        pal = ba.parse_palette(path)
        self.assertEqual((pal["player"], pal["eyes"], pal["ice"]), (0x36, 0x1E, 0xAC))
        after = path.read_text().splitlines()
        self.assertEqual(len(after), len(before))
        self.assertEqual([i for i, (a, b) in enumerate(zip(before, after)) if a != b], [i for i, ln in enumerate(before) if ln.split("#")[0].split()[:1] in (["player"], ["eyes"], ["ice"])])
        self.assertTrue(any(ln.startswith("ice") and "# also" in ln for ln in after), "the comment on the ice line stays")
        self.assertEqual(ba.parse_palette(path)["hues"], ba.parse_palette(ROOT / "assets" / "palette.txt")["hues"])
        status, res = self.req("PUT", "/api/palette", {"eyes": 0x20})  # one at a time is fine
        self.assertEqual((status, ba.parse_palette(path)["eyes"], ba.parse_palette(path)["ice"]), (200, 0x20, 0xAC))

    def test_bad_colours_are_refused_and_nothing_changes(self) -> None:
        path = self.tmp / "assets" / "palette.txt"
        before = path.read_text()
        for body in ({"player": 256}, {"player": -2}, {"eyes": "4E"}, {"ice": 0x4F}, {"ice": 1.5}, {"player": True}, {"grey": 2}, {}):
            with self.subTest(body):
                status, res = self.req("PUT", "/api/palette", body)
                self.assertEqual(status, 400, res)
                self.assertEqual(path.read_text(), before)
        self.assertEqual(self.req("PUT", "/api/palette", {"player": 0x36}, editor=False)[0], 403)
        self.assertEqual(path.read_text(), before)
        self.assertEqual((ROOT / "assets" / "palette.txt").read_text().count("player     4E"), 1, "the real file is not touched")

    def test_the_body_must_be_a_list_of_frames(self) -> None:
        for body in ({"frames": "no"}, {"frames": [1, 2]}, {}, {"frames": None}):
            with self.subTest(body):
                self.assertEqual(self.req("PUT", "/api/sprites", body)[0], 400)

    def test_a_save_that_is_not_the_editors_is_refused(self) -> None:
        frames = self.frames()
        frames[1]["rows"][0] = "#.####.#"
        before = self.sprites_path().read_text()
        self.assertEqual(self.put(frames, editor=False)[0], 403)
        self.assertEqual(self.put(frames, headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.put(frames, headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.sprites_path().read_text(), before)

    def test_the_real_sprites_file_is_untouched_by_all_this(self) -> None:
        self.assertNotEqual(self.sprites_path().resolve(), (ROOT / "assets" / "sprites.txt").resolve())


class Checking(ServerCase):
    def test_a_good_level_has_no_problems(self) -> None:
        status, res = self.req("POST", "/api/check", {"text": LEVEL1})
        self.assertEqual((status, res), (200, {"errors": [], "problems": []}))

    def test_a_level_the_game_would_refuse_comes_back_as_an_error(self) -> None:
        status, res = self.req("POST", "/api/check", {"text": LEVEL1.replace("@", ".")})
        self.assertEqual(status, 200)
        self.assertEqual(len(res["errors"]), 1)
        self.assertIn("'@'", res["errors"][0])

    def test_an_unreachable_item_is_reported_with_its_place(self) -> None:
        grid = [["."] * 40] + [["#"] + ["."] * 38 + ["#"] for _ in range(22)] + [["#"] * 40]
        grid[21][2] = "@"
        grid[22][10] = "*"  # on the floor: fine
        grid[22][36] = "D"  # the exit, on the floor too
        grid[2][30] = "*"  # high in the air with nothing to stand on near it
        text = "\n".join("".join(r) for r in grid) + "\n"
        status, res = self.req("POST", "/api/check", {"text": text})
        self.assertEqual(status, 200, res)
        self.assertEqual(res["errors"], [])
        self.assertEqual(len(res["problems"]), 1, res)
        self.assertIn("column 30, row 2", res["problems"][0])
        self.assertIn("unreachable", res["problems"][0])


class RunningTheGame(ServerCase):
    def test_a_level_that_is_not_saved_cannot_be_run(self) -> None:
        self.assertEqual(self.req("POST", "/api/run", {"name": "level9"})[0], 404)

    def test_without_the_task_command_the_server_says_so(self) -> None:
        with mock.patch("editor_server.shutil.which", return_value=None):
            status, res = self.req("POST", "/api/run", {"name": "level2"})
        self.assertEqual(status, 501)
        self.assertIn("task", res["error"])

    def test_the_map_number_is_its_place_in_the_game(self) -> None:
        with mock.patch("editor_server.shutil.which", return_value="/usr/local/bin/task"), mock.patch("editor_server.subprocess.Popen") as popen:
            status, res = self.req("POST", "/api/run", {"name": "level4"})
        self.assertEqual((status, res["index"]), (200, 4))
        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["/usr/local/bin/task", "run-map", "--", "4"])
        self.assertEqual(Path(kwargs["cwd"]).resolve(), self.tmp.resolve())


if __name__ == "__main__":
    unittest.main()
