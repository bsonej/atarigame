#!/usr/bin/env python3
"""Drive the game headlessly in atari800's built-in monitor, one frame at a time.

Needs a TEST build (``task build-test``), where the joystick is read from RAM ($06F0/$06F1)
instead of the hardware, and ``frame_end`` is exported so we can break once per frame.

    from tools.headless import Game, UP, RIGHT
    with Game() as g:
        g.step(RIGHT, n=10)
        print(g.px, g.py, g.state)
"""

from __future__ import annotations

import os
import re
import select
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
XEX = ROOT / "build" / "atarigame-test.xex"
LABELS = ROOT / "build" / "test" / "atarigame.lbl"

# Joystick bits (set = pressed)
UP, DOWN, LEFT, RIGHT, FIRE = 0x01, 0x02, 0x04, 0x08, 0x10

GROUND, AIR, CLIMB = 0, 1, 2
TITLE, PLAY, DYING, SPAWN, CLEAR, OVER = range(6)  # the game's modes
COLS, ROWS = 40, 24
PM_YOFF = 32
SPAWN_FRAMES, DIE_FRAMES, CLEAR_FRAMES = 48, 80, 60


def read_labels(path: Path) -> dict[str, int]:
    out = {}
    for line in path.read_text().splitlines():
        m = re.match(r"^al\s+([0-9A-Fa-f]+)\s+\.(\S+)$", line)
        if m:
            out[m.group(2)] = int(m.group(1), 16)
    return out


class EmulatorError(RuntimeError):
    pass


class Game:
    """One emulator session. Variables of the game are readable as attributes (px, py, state, ...)."""

    def __init__(self, xex: Path = XEX, labels: Path = LABELS, turbo: bool = True) -> None:
        self.labels = read_labels(labels)
        env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
        cmd = ["atari800", "-xl", "-nobasic", "-nosound", "-run", str(xex), "-monitor"]
        if turbo:
            cmd.insert(1, "-turbo")
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, bufsize=0
        )
        self._buf = ""
        self._wait(r"PC=[0-9A-F]{4}:", 20)  # the monitor's first register line
        self.zp: bytes = bytes(256)  # RAM $0080-$017F, refreshed after every step
        # Stop at the program entry (the OS has finished booting), set the joystick to "idle"
        # (a zeroed byte would mean everything is pressed), then run to the end of frame one.
        self._send(f"BPC {self.labels['start']:X}\nCONT\n")
        self._wait(rf"PC={self.labels['start']:04X}", 20)
        self._send("C 6F0 0F\nC 6F1 01\n" + f"BPC {self.labels['frame_end']:X}\nCONT\n")
        self._wait(rf"PC={self.labels['frame_end']:04X}", 20)
        self.frames = 0
        self.screen_addr = self.labels["SCREEN"]
        self.pm0 = self.labels["PM0"]
        self._refresh()

    # ---- plumbing ----------------------------------------------------------
    def _send(self, text: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(text.encode())

    def _wait(self, pattern: str, timeout: float = 10.0) -> re.Match:
        assert self.proc.stdout is not None
        end = time.time() + timeout
        rx = re.compile(pattern)
        while True:
            m = rx.search(self._buf)
            if m:
                self._buf = self._buf[m.end():]
                return m
            left = end - time.time()
            if left <= 0:
                raise EmulatorError(f"timed out waiting for {pattern!r}; got: {self._buf[-300:]!r}")
            ready, _, _ = select.select([self.proc.stdout], [], [], min(left, 0.2))
            if ready:
                data = os.read(self.proc.stdout.fileno(), 65536)
                if not data:
                    raise EmulatorError("emulator exited")
                self._buf += data.decode(errors="replace")

    _ROW = r"([0-9A-F]{4}): ((?:[0-9A-F]{2} ){16})"

    def _dump(self, start: int, count: int) -> bytes:
        """Read ``count`` bytes (a multiple of 256) from RAM through the monitor's M command."""
        pages = count // 256
        self._send(f"M {start:X}\n" + "M\n" * (pages - 1))
        data = bytearray()
        for _ in range(pages * 16):
            m = self._wait(self._ROW)
            data += bytes.fromhex(m.group(2))
        return bytes(data)

    def _refresh(self) -> None:
        self.zp = self._dump(0x80, 256)[: 256]

    # ---- public API --------------------------------------------------------
    def step(self, buttons: int = 0, n: int = 1) -> None:
        """Run ``n`` frames with the given joystick buttons held (UP|FIRE|...)."""
        stick = 0x0F & ~(buttons & 0x0F)
        trig = 0x00 if buttons & FIRE else 0x01
        for _ in range(n):
            self._send(f"C 6F0 {stick:02X}\nC 6F1 {trig:02X}\nCONT\n")
            self._wait(rf"PC={self.labels['frame_end']:04X}")
            self.frames += 1
        self._refresh()

    def idle(self, n: int = 1) -> None:
        self.step(0, n)

    def run(self, n: int, buttons: int = 0, chunk: int = 50) -> None:
        """Run ``n`` frames with constant input, fast: the CONTs are pipelined and state is read once per chunk."""
        stick = 0x0F & ~(buttons & 0x0F)
        trig = 0x00 if buttons & FIRE else 0x01
        pc = rf"PC={self.labels['frame_end']:04X}"
        left = n
        while left > 0:
            k = min(chunk, left)
            self._send(f"C 6F0 {stick:02X}\nC 6F1 {trig:02X}\n" + "CONT\n" * k)
            for _ in range(k):
                self._wait(pc, 30)
            self.frames += k
            left -= k
        self._refresh()

    def run_until(self, cond, limit: int = 3000, buttons: int = 0, every: int = 5) -> int:
        """Run until ``cond(game)`` is true, checking every ``every`` frames. Returns the frames run."""
        ran = 0
        while ran < limit:
            if cond(self):
                return ran
            self.run(every, buttons, chunk=every)
            ran += every
        raise AssertionError(f"condition not met within {limit} frames")

    def start_game(self) -> None:
        """From the title: press fire, then wait out the 'come to life' animation until play begins."""
        assert self.mode == TITLE, f"not on the title screen (mode {self.mode})"
        self.step(FIRE)
        self.idle()
        self.run_until(lambda g: g.mode == PLAY, limit=SPAWN_FRAMES + 20, every=1)

    @property
    def score16(self) -> int:
        return self.zp[self.labels["score"] - 0x80] | (self.zp[self.labels["score"] + 1 - 0x80] << 8)

    def word(self, name: str) -> int:
        a = self.labels[name] - 0x80
        return self.zp[a] | (self.zp[a + 1] << 8)

    def poke(self, name_or_addr, value: int) -> None:
        addr = self.labels[name_or_addr] if isinstance(name_or_addr, str) else name_or_addr
        self._send(f"C {addr:X} {value:02X}\n")
        self._wait(r"Changed \d+ bytes")
        self._refresh()

    def poke_bytes(self, addr: int, data) -> None:
        """Write several bytes at once (the monitor's C command takes a list)."""
        data = bytes(data)
        for i in range(0, len(data), 64):
            chunk = data[i : i + 64]
            self._send(f"C {addr + i:X} " + " ".join(f"{b:02X}" for b in chunk) + "\n")
            self._wait(r"Changed \d+ bytes")
        self._refresh()

    def put_tiles(self, col: int, row: int, tiles) -> None:
        """Write map bytes into screen RAM starting at (col,row); the game reads its map from there."""
        self.poke_bytes(self.screen_addr + row * COLS + col, tiles)

    def bss(self, name: str, count: int = 1) -> bytes:
        """``count`` bytes of the BSS table ``name`` (they live outside the zero page window)."""
        addr = self.labels[name]
        return self._dump(addr & ~0xFF, 256)[addr & 0xFF : (addr & 0xFF) + count]

    def mem(self, addr: int, count: int = 256) -> bytes:
        return self._dump(addr, count)

    def screen(self) -> list[str]:
        """The 24 screen rows as lists of tile ids, joined as hex strings (two digits per tile)."""
        raw = self.mem(self.screen_addr, 1024)
        return [raw[r * COLS : (r + 1) * COLS].hex() for r in range(ROWS)]

    def tile(self, col: int, row: int) -> int:
        return self.mem(self.screen_addr + row * COLS, 256)[col]

    def sprite(self) -> bytes:
        """The 16 bytes of Player 0 around the player's current line."""
        raw = self.mem(self.pm0, 512)
        return raw[PM_YOFF + self.py : PM_YOFF + self.py + 16]

    def __getattr__(self, name: str):
        labels = self.__dict__.get("labels", {})
        if name in labels and 0x80 <= labels[name] < 0x180:
            return self.__dict__["zp"][labels[name] - 0x80]  # zp holds RAM from $0080
        raise AttributeError(name)

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=5)

    def __enter__(self) -> "Game":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def main() -> int:
    if not XEX.exists():
        print("build the test ROM first:  task build-test", file=sys.stderr)
        return 1
    with Game() as g:
        print(f"title: mode={g.mode} hiscore={g.word('hiscore')}")
        g.start_game()
        print(f"start: px={g.px} py={g.py} state={g.state} left={g.left} lives={g.lives} level={g.level}")
        g.step(RIGHT, 10)
        print(f"after 10 frames right: px={g.px} py={g.py}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
