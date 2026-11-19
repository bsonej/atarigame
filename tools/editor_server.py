#!/usr/bin/env python3
"""Serve the level editor (web/) and let it read and write assets/levels/.

    python3 tools/editor_server.py [--port 8765] [--root .] [--open]

Only standard library. The server listens on 127.0.0.1 and nothing else, answers only requests addressed to
localhost, and refuses to change anything unless the request carries the editor's own header (so another web
page cannot save levels through your browser). A level is only written once the game's own asset tool accepts it.

    GET  /api/tiles          tile art, map characters, flags and end-cap families (from assets/tiles.txt)
    GET  /api/levels         the levels the game will play, in order
    GET  /api/level/<name>   one level file
    PUT  /api/level/<name>   save it (validated first)         body {"text": "..."}
    POST /api/check          validate and reachability-check   body {"text": "..."}
    POST /api/run            build the game and open it in the emulator on a saved level   body {"name": "..."}
    GET  /api/sprites        Mr. Bubble's frames (assets/sprites.txt): the file's text and each frame's rows
    PUT  /api/sprites        save them (validated like build_assets does)   body {"frames": [{"name": "...", "rows": [...]}]}
    GET  /api/palette        the colours of assets/palette.txt
    PUT  /api/palette        change Mr. Bubble's three colours (validated)   body {"player": 78, "eyes": 14, "ice": 138}
                             (Atari colour bytes: hue * 16 + luminance, luminance even; "ice" is his third colour too)
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import build_assets as ba  # noqa: E402
import levelcheck  # noqa: E402

NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,39}")
SPRITE_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*")
SPRITE_ROW_RE = re.compile(rf"[#.eo]{{{ba.SPRITE_W}}}")
PLAYER_COLOURS = ("player", "eyes", "ice")  # the palette entries the sprite editor may change
MAX_BODY = 64 * 1024
EDITOR_HEADER = "X-Editor"


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class Project:
    """The files the editor works on."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self.levels_dir = self.root / "assets" / "levels"
        self.web_dir = (self.root / "web").resolve()
        self.sprites_path = self.root / "assets" / "sprites.txt"
        self._lock = threading.Lock()

    # -- tiles ---------------------------------------------------------------------------------
    def tiles(self) -> list[dict]:
        return ba.parse_tiles(self.root / "assets" / "tiles.txt")

    def tiles_api(self) -> dict:
        tiles = self.tiles()
        caps = ba.cap_families(tiles)
        flags, canon = ba.tile_tables(tiles)
        door = ba.door_bytes(tiles)
        pal_path = self.root / "assets" / "palette.txt"
        sprites = [
            {"name": n, "rows": rows, "eyes": eyes, "third": third, "thirdPx": [ba.third_pixels(b) for b in third]}
            for n, rows, eyes, third in ba.parse_sprite_frames(self.root / "assets" / "sprites.txt")
        ]
        return {
            "cols": ba.COLS,
            "rows": ba.ROWS,
            "tiles": [
                {
                    "id": t["id"],
                    "byte": t["byte"],
                    "name": t["name"],
                    "char": t["char"],
                    "solid": t["solid"],
                    "oneway": t["oneway"],
                    "alt": t["byte"] != t["id"],
                    "family": t.get("family"),
                    "cap": t.get("cap"),
                    "dotOf": t.get("dot_of"),
                    "twinOf": t.get("twin_of"),
                    "rows": t["rows"],
                }
                for t in tiles
            ],
            "caps": {str(k): v for k, v in caps.items()},
            "dots": {str(k): v for k, v in ba.dot_families(tiles).items()},
            "twins": {str(k): v for k, v in ba.twin_families(tiles).items()},
            "door": list(door) if door else None,
            "doorCells": [list(c) for c in ba.DOOR_CELLS],
            "fade": ba.fade_thresholds(),
            "fadeSteps": ba.FADE_STEPS,
            "palette": ba.parse_palette(pal_path) if pal_path.exists() else None,
            "maxCollect": ba.MAX_COLLECT,
            "flags": flags,
            "canon": canon,
            "sprites": sprites,
        }

    # -- sprites -------------------------------------------------------------------------------
    @staticmethod
    def sprite_layout(text: str) -> tuple[list[str], list[dict]]:
        """The lines of sprites.txt and its frames as {"name", "at": [line numbers of the pixel rows], "rows": [...]}."""
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        frames: list[dict] = []
        for i, raw in enumerate(lines):
            t = raw.strip()
            if not t or ba._is_comment(raw):
                continue
            if t.startswith("frame "):
                frames.append({"name": t.split(None, 1)[1], "at": [], "rows": []})
            elif frames and SPRITE_ROW_RE.fullmatch(t):
                frames[-1]["at"].append(i)
                frames[-1]["rows"].append(t)
            else:
                raise ApiError(500, f"assets/sprites.txt line {i + 1} is not something the editor understands: {t!r}")
        return lines, frames

    def sprites_api(self) -> dict:
        text = self.sprites_path.read_text(encoding="utf-8")
        _lines, frames = self.sprite_layout(text)
        built = ba.parse_sprite_frames(self.sprites_path)
        return {
            "path": str(self.sprites_path.relative_to(self.root)),
            "text": text,
            "width": ba.SPRITE_W,
            "height": ba.SPRITE_H,
            "frames": [
                {"name": f["name"], "rows": f["rows"], "body": body, "eyes": eyes, "third": third, "thirdPx": [ba.third_pixels(b) for b in third]}
                for f, (_n, body, eyes, third) in zip(frames, built)
            ],
        }

    def save_sprites(self, frames) -> dict:
        """Write the pixel rows of `frames` into assets/sprites.txt, keeping its comments, frame names and order."""
        text = self.sprites_path.read_text(encoding="utf-8")
        lines, have = self.sprite_layout(text)
        if not isinstance(frames, list) or not all(isinstance(f, dict) for f in frames):
            raise ApiError(400, 'send {"frames": [{"name": "...", "rows": [...]}, ...]}')
        if len(frames) != len(have):
            raise ApiError(400, f"there are {len(frames)} frames but the game has {len(have)}: frames cannot be added or removed here")
        for i, (new, old) in enumerate(zip(frames, have)):
            name = new.get("name")
            if not isinstance(name, str) or not SPRITE_NAME_RE.fullmatch(name):
                raise ApiError(400, f"frame #{i} has no usable name")
            if name != old["name"]:
                raise ApiError(400, f"frame #{i} is called {name}, the game has {old['name']} there: frames cannot be renamed or reordered here")
            rows = new.get("rows")
            if not isinstance(rows, list) or len(rows) != ba.SPRITE_H:
                raise ApiError(400, f"frame {name} has {len(rows) if isinstance(rows, list) else 0} rows, needs {ba.SPRITE_H}")
            for y, row in enumerate(rows):
                if not isinstance(row, str) or not SPRITE_ROW_RE.fullmatch(row):
                    raise ApiError(400, f"frame {name} row {y}: needs {ba.SPRITE_W} characters of '#', 'e', 'o' and '.', got {row!r}")
        for new, old in zip(frames, have):
            for line, row in zip(old["at"], new["rows"]):
                lines[line] = row
        out = "\n".join(lines) + "\n"
        with self._lock:
            fd, tmp = tempfile.mkstemp(dir=self.sprites_path.parent, prefix=".editor-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(out)
                try:  # the asset tool has the last word
                    ba.parse_sprite_frames(Path(tmp))
                except ba.AssetError as e:
                    raise ApiError(400, str(e).replace(tmp, "sprites.txt")) from None
                os.chmod(tmp, self.sprites_path.stat().st_mode & 0o777)
                os.replace(tmp, self.sprites_path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        return {"ok": True, "path": str(self.sprites_path.relative_to(self.root)), "frames": len(frames)}

    # -- palette (Mr. Bubble's three colours) --------------------------------------------------
    def palette_api(self) -> dict:
        path = self.root / "assets" / "palette.txt"
        pal = ba.parse_palette(path)
        return {"path": str(path.relative_to(self.root)), "palette": pal,
                "player": pal["player"], "eyes": pal["eyes"], "third": pal["ice"]}

    def save_palette(self, body: dict) -> dict:
        """Change `player`, `eyes` and/or `ice` (his third colour: the missiles take playfield colour 3) in
        assets/palette.txt, keeping its comments and every other line."""
        path = self.root / "assets" / "palette.txt"
        want: dict[str, int] = {}
        for key in PLAYER_COLOURS:
            if key not in body:
                continue
            v = body[key]
            if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 255:
                raise ApiError(400, f"{key}: an Atari colour is a whole number 0-255 (hue * 16 + luminance), got {v!r}")
            if v & 1:
                raise ApiError(400, f"{key}: the luminance of an Atari colour is even (the lowest bit is not used), got ${v:02X}")
            want[key] = v
        unknown = set(body) - set(PLAYER_COLOURS)
        if unknown:
            raise ApiError(400, f"only {', '.join(PLAYER_COLOURS)} can be changed here, not {', '.join(sorted(unknown))}")
        if not want:
            raise ApiError(400, 'send {"player": 78, "eyes": 14, "ice": 138} (any of them)')
        with self._lock:
            lines = path.read_text(encoding="utf-8").split("\n")
            for key, v in want.items():
                rx = re.compile(rf"^(\s*{key}\s+)[0-9A-Fa-f]+(.*)$")
                for i, line in enumerate(lines):
                    m = rx.match(line)
                    if m:
                        lines[i] = f"{m.group(1)}{v:02X}{m.group(2)}"
                        break
                else:  # an older file without the entry: add it at the end
                    while lines and lines[-1] == "":
                        lines.pop()
                    lines += [f"{key:<10} {v:02X}", ""]
            out = "\n".join(lines)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".editor-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(out)
                try:  # the asset tool has the last word
                    ba.parse_palette(Path(tmp))
                except ba.AssetError as e:
                    raise ApiError(400, str(e).replace(tmp, "palette.txt")) from None
                os.chmod(tmp, path.stat().st_mode & 0o777)
                os.replace(tmp, path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        return {"ok": True, **self.palette_api()}

    # -- levels --------------------------------------------------------------------------------
    def level_paths(self) -> list[Path]:
        return sorted(self.levels_dir.glob("*.txt"), key=ba.natural_key)

    def levels(self) -> list[dict]:
        out = []
        for i, p in enumerate(self.level_paths(), 1):
            first = (p.read_text(encoding="utf-8").splitlines() or [""])[0]
            m = re.match(r"#\s*Level\s+\S+:\s*(.+?)\.(\s|$)", first)
            out.append({"name": p.stem, "title": m.group(1) if m else "", "index": i})
        return out

    @staticmethod
    def check_name(name: str) -> str:
        if not NAME_RE.fullmatch(name):
            raise ApiError(400, "a level name is lowercase letters, digits and underscores, starting with a letter (e.g. level6)")
        return name

    def read_level(self, name: str) -> str:
        path = self.levels_dir / f"{self.check_name(name)}.txt"
        if not path.is_file():
            raise ApiError(404, f"no level called {name}")
        return path.read_text(encoding="utf-8")

    def validate(self, name: str, text: str) -> list[str]:
        """Raise ApiError(400) if the asset tool would refuse the level; else the reachability problems."""
        tiles = self.tiles()
        chars = {t["char"]: t["byte"] for t in tiles if t["char"] is not None}
        solid = {t["byte"] for t in tiles if t["solid"]}
        try:
            ba.parse_level(Path(f"{name}.txt"), chars, solid, ba.cap_families(tiles), text=text,
                           dots=ba.dot_families(tiles), door=ba.door_bytes(tiles), twins=ba.twin_families(tiles))
        except ba.AssetError as e:
            raise ApiError(400, str(e).removeprefix(f"{name}.txt: ")) from None
        rows = [ln for ln in text.splitlines() if ln.strip() and not ba._is_comment(ln)]
        return levelcheck.check_rows(rows)

    def save_level(self, name: str, text: str) -> dict:
        self.check_name(name)
        if not text.endswith("\n"):
            text += "\n"
        problems = self.validate(name, text)
        with self._lock:
            self.levels_dir.mkdir(parents=True, exist_ok=True)
            path = self.levels_dir / f"{name}.txt"
            fd, tmp = tempfile.mkstemp(dir=self.levels_dir, prefix=".editor-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(text)
                os.chmod(tmp, path.stat().st_mode & 0o777 if path.exists() else 0o644)  # mkstemp makes files private
                os.replace(tmp, path)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
        index = [lv["name"] for lv in self.levels()].index(name) + 1
        return {"ok": True, "name": name, "path": str(path.relative_to(self.root)), "index": index, "problems": problems}

    def run_in_emulator(self, name: str) -> dict:
        self.check_name(name)
        names = [lv["name"] for lv in self.levels()]
        if name not in names:
            raise ApiError(404, f"save {name} first: the game only knows saved levels")
        task = shutil.which("task")
        if not task:
            raise ApiError(501, "the `task` command is not installed, so the server cannot build the game for you")
        index = names.index(name) + 1
        subprocess.Popen(  # noqa: S603 - fixed arguments, index is an int
            [task, "run-map", "--", str(index)],
            cwd=self.root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return {"ok": True, "index": index}


def make_handler(project: Project):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FactoryEditor/1"

        def log_message(self, fmt, *args):  # quiet unless asked
            if os.environ.get("EDITOR_VERBOSE"):
                super().log_message(fmt, *args)

        # -- plumbing ----------------------------------------------------------------------
        def send_json(self, status: int, obj) -> None:
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
            return host in ("localhost", "127.0.0.1", "::1")

        def read_json(self) -> dict:
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise ApiError(400, "bad Content-Length") from None
            if n > MAX_BODY:
                raise ApiError(413, "that is too big to be a level")
            try:
                obj = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                raise ApiError(400, "the body is not JSON") from None
            if not isinstance(obj, dict):
                raise ApiError(400, "the body must be a JSON object")
            return obj

        def dispatch(self, method: str) -> None:
            try:
                if not self.host_ok():
                    raise ApiError(403, "this server only answers to localhost")
                path = unquote(urlparse(self.path).path)
                if method != "GET":
                    if not self.headers.get(EDITOR_HEADER):
                        raise ApiError(403, f"missing {EDITOR_HEADER} header")
                    origin = self.headers.get("Origin")
                    if origin and urlparse(origin).netloc != self.headers.get("Host"):
                        raise ApiError(403, "cross-origin request refused")
                if path.startswith("/api/"):
                    self.api(method, path[len("/api/"):])
                elif method == "GET":
                    self.static(path)
                else:
                    raise ApiError(405, "not allowed")
            except ApiError as e:
                self.send_json(e.status, {"error": e.message})
            except Exception as e:  # noqa: BLE001 - never hang the browser
                self.send_json(500, {"error": f"{type(e).__name__}: {e}"})

        do_GET = lambda self: self.dispatch("GET")  # noqa: E731
        do_PUT = lambda self: self.dispatch("PUT")  # noqa: E731
        do_POST = lambda self: self.dispatch("POST")  # noqa: E731

        # -- routes ------------------------------------------------------------------------
        def api(self, method: str, route: str) -> None:
            if route == "tiles" and method == "GET":
                return self.send_json(200, project.tiles_api())
            if route == "levels" and method == "GET":
                return self.send_json(200, project.levels())
            if route == "sprites" and method == "GET":
                return self.send_json(200, project.sprites_api())
            if route == "sprites" and method == "PUT":
                return self.send_json(200, project.save_sprites(self.read_json().get("frames")))
            if route == "palette" and method == "GET":
                return self.send_json(200, project.palette_api())
            if route == "palette" and method == "PUT":
                return self.send_json(200, project.save_palette(self.read_json()))
            if route.startswith("level/"):
                name = route[len("level/"):]
                if method == "GET":
                    return self.send_json(200, {"name": name, "text": project.read_level(name)})
                if method == "PUT":
                    text = self.read_json().get("text")
                    if not isinstance(text, str):
                        raise ApiError(400, "send {\"text\": \"...\"}")
                    return self.send_json(200, project.save_level(name, text))
            if route == "check" and method == "POST":
                text = self.read_json().get("text")
                if not isinstance(text, str):
                    raise ApiError(400, "send {\"text\": \"...\"}")
                try:
                    return self.send_json(200, {"errors": [], "problems": project.validate("check", text)})
                except ApiError as e:
                    if e.status != 400:
                        raise
                    return self.send_json(200, {"errors": [e.message], "problems": []})
            if route == "run" and method == "POST":
                name = self.read_json().get("name")
                if not isinstance(name, str):
                    raise ApiError(400, "send {\"name\": \"...\"}")
                return self.send_json(200, project.run_in_emulator(name))
            raise ApiError(404, "no such API route")

        def static(self, path: str) -> None:
            if path in ("", "/"):
                path = "/index.html"
            target = (project.web_dir / path.lstrip("/")).resolve()
            if project.web_dir not in target.parents or not target.is_file():
                raise ApiError(404, "not found")
            body = target.read_bytes()
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if target.suffix in (".js", ".mjs"):
                ctype = "text/javascript"
            self.send_response(200)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8" if ctype.startswith("text/") else ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def make_server(root: Path, port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), make_handler(Project(root)))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--root", default=str(HERE.parent), help="project root (default: this project)")
    ap.add_argument("--open", action="store_true", help="open the editor in your browser")
    ap.add_argument("--dump-tiles", action="store_true", help="print what /api/tiles would send, and exit (for the JavaScript tests)")
    args = ap.parse_args(argv)
    if args.dump_tiles:
        print(json.dumps(Project(Path(args.root)).tiles_api()))
        return 0
    try:
        server = make_server(Path(args.root), args.port)
    except OSError as e:
        print(f"cannot listen on 127.0.0.1:{args.port}: {e}", file=sys.stderr)
        return 1
    url = f"http://localhost:{server.server_address[1]}/"
    print(f"Level editor at {url}  (Ctrl-C to stop)")
    if args.open:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
