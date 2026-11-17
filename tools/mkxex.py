#!/usr/bin/env python3
"""Pack linker output into an Atari DOS binary load file (.xex).

    mkxex.py -o build/game.xex --labels build/game.lbl --run start 0x2000=build/code.bin 0x4000=build/charset.bin ...

Each ADDRESS=FILE pair becomes one load segment; a final segment sets RUNAD ($02E0) so the
program starts at the label given by --run.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path

RUNAD = 0x02E0


def segment(addr: int, data: bytes) -> bytes:
    if not data:
        return b""
    end = addr + len(data) - 1
    if addr < 0 or end > 0xFFFF:
        raise ValueError(f"segment ${addr:04X}-${end:04X} is outside 64 KB")
    return struct.pack("<HH", addr, end) + data


def read_label(path: Path, name: str) -> int:
    """Address of ``name`` from a VICE-style label file written by ld65 -Ln ('al 002000 .start')."""
    pat = re.compile(r"^al\s+([0-9A-Fa-f]+)\s+\.?" + re.escape(name) + r"\s*$")
    for line in path.read_text().splitlines():
        m = pat.match(line)
        if m:
            return int(m.group(1), 16)
    raise ValueError(f"label {name!r} not found in {path}")


def pack(segments: list[tuple[int, bytes]], run: int) -> bytes:
    out = b"\xff\xff"
    for addr, data in segments:
        out += segment(addr, data)
    out += segment(RUNAD, struct.pack("<H", run))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--labels", required=True, help="label file from ld65 -Ln")
    ap.add_argument("--run", default="start", help="label to start at (default: start)")
    ap.add_argument("segments", nargs="+", metavar="ADDRESS=FILE")
    args = ap.parse_args(argv)
    try:
        segs = []
        for spec in args.segments:
            addr, _, file = spec.partition("=")
            if not file:
                raise ValueError(f"expected ADDRESS=FILE, got {spec!r}")
            segs.append((int(addr, 0), Path(file).read_bytes()))
        data = pack(segs, read_label(Path(args.labels), args.run))
    except (OSError, ValueError) as exc:
        print(f"mkxex: {exc}", file=sys.stderr)
        return 1
    Path(args.output).write_bytes(data)
    print(f"{args.output}: {len(data)} bytes, {len(segs)} load segments")
    return 0


if __name__ == "__main__":
    sys.exit(main())
