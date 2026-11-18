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
            self.assertEqual((by_name[twin]["twinOf"], by_name[twin]["oneway"], by_name[twin]["char"]), (plain, True, None))
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
