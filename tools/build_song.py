#!/usr/bin/env python3
"""Turn assets/music/Happy_Pokey_Stomper.sap into the two binaries the title plays.

The SAP is a Raster Music Tracker 4 module (Roland Voss / Triace, 2014) plus the
RMT player. Both were linked for addresses this game already uses, so this script
moves them:

  player  $0390 -> $9C00     (the title picture ends at $9B8F)
  module  $4000 -> $A400     (page aligned, so only the high bytes of its pointers move)
  its variables $0280 -> $B350  (the player clears them itself; they are not in the file)

Only instructions the player actually reaches are patched. The pitch and volume
tables that fill the rest of the player are left byte for byte.
"""

import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
SAP = ROOT / "assets/music/Happy_Pokey_Stomper.sap"
OUT = ROOT / "src/gen"

# Where the two blocks land, and how far each kind of address moves.
PLAYER_AT, MODULE_AT, VARS_AT = 0x9C00, 0xA400, 0xB350
PLAYER_LO, PLAYER_HI = 0x0390, 0x0B60          # inclusive
MODULE_LO, MODULE_HI = 0x4000, 0x4F42
VARS_LO, VARS_HI = 0x0280, 0x0327
D_PLAYER = PLAYER_AT - PLAYER_LO
D_MODULE = MODULE_AT - MODULE_LO
D_VARS = VARS_AT - VARS_LO

# Instruction length by opcode. $A2 (LDX immediate) is 2 bytes; treating it as 1
# shifts every later instruction and the addresses get patched in the wrong place.
LENGTH = bytes([
    2,2,1,2, 2,2,2,2, 1,2,1,2, 3,3,3,3,  2,2,1,2, 2,2,2,2, 1,3,1,3, 3,3,3,3,
    3,2,1,2, 2,2,2,2, 1,2,1,2, 3,3,3,3,  2,2,1,2, 2,2,2,2, 1,3,1,3, 3,3,3,3,
    1,2,1,2, 2,2,2,2, 1,2,1,2, 3,3,3,3,  2,2,1,2, 2,2,2,2, 1,3,1,3, 3,3,3,3,
    1,2,1,2, 2,2,2,2, 1,2,1,2, 3,3,3,3,  2,2,1,2, 2,2,2,2, 1,3,1,3, 3,3,3,3,
    2,2,1,2, 2,2,2,2, 1,2,1,2, 3,3,3,3,  2,2,1,2, 2,2,2,2, 1,3,1,3, 3,3,3,3,
    2,2,2,2, 2,2,2,2, 1,2,1,2, 3,3,3,3,  2,2,1,2, 2,2,2,2, 1,3,1,3, 3,3,3,3,
    2,2,1,2, 2,2,2,2, 1,2,1,2, 3,3,3,3,  2,2,1,2, 2,2,2,2, 1,3,1,3, 3,3,3,3,
    2,2,1,2, 2,2,2,2, 1,2,1,2, 3,3,3,3,  2,2,1,2, 2,2,2,2, 1,3,1,3, 3,3,3,3,
])
# Opcodes whose operand is a 16-bit address. Immediates ($A9 and friends) are not here:
# patching those would corrupt the player.
ABSOLUTE = {
    0x0D, 0x0E, 0x19, 0x1D, 0x1E, 0x20, 0x2C, 0x2D, 0x2E, 0x39, 0x3D, 0x3E,
    0x4C, 0x4D, 0x4E, 0x59, 0x5D, 0x5E, 0x6C, 0x6D, 0x6E, 0x79, 0x7D, 0x7E,
    0x8C, 0x8D, 0x8E, 0x99, 0x9D, 0xAC, 0xAD, 0xAE, 0xB9, 0xBC, 0xBD, 0xBE,
    0xCC, 0xCD, 0xCE, 0xD9, 0xDD, 0xDE, 0xEC, 0xED, 0xEE, 0xF9, 0xFD, 0xFE,
}
for op in ABSOLUTE:
    if LENGTH[op] != 3:
        raise SystemExit(f"opcode ${op:02X} is not a 3-byte instruction")
if LENGTH[0xA2] != 2:
    raise SystemExit("LDX immediate must be 2 bytes or the player is relocated out of step")


def blocks(data: bytes) -> dict[int, bytes]:
    """SAP blocks after the header: {load address: bytes}."""
    i = data.index(b"\xff\xff") + 2
    out = {}
    while i < len(data):
        start = data[i] | (data[i + 1] << 8)
        end = data[i + 2] | (data[i + 3] << 8)
        n = end - start + 1
        out[start] = data[i + 4:i + 4 + n]
        i += 4 + n
    return out


def relocate_player(player: bytearray) -> int:
    """Patch absolute addresses in the code the player actually runs. Returns how many."""
    seen = bytearray(len(player))
    starts: list[int] = []
    # The five entries the SAP header's stubs jump to: init, play, sfx, silence, sfx-off.
    queue = [0x0600, 0x0603, 0x0606, 0x0609, 0x060C]
    while queue:
        pc = queue.pop()
        while PLAYER_LO <= pc <= PLAYER_HI and not seen[pc - PLAYER_LO]:
            op = player[pc - PLAYER_LO]
            n = LENGTH[op]
            if n == 0:
                raise SystemExit(f"illegal opcode ${op:02X} at ${pc:04X}")
            starts.append(pc)
            for k in range(n):
                seen[pc - PLAYER_LO + k] = 1
            if op == 0x4C:                                  # jmp
                queue.append(player[pc - PLAYER_LO + 1] | (player[pc - PLAYER_LO + 2] << 8))
                break
            if op == 0x6C:
                raise SystemExit(f"indirect jump at ${pc:04X}, which this relocator does not follow")
            if op == 0x20:                                  # jsr, then fall through
                queue.append(player[pc - PLAYER_LO + 1] | (player[pc - PLAYER_LO + 2] << 8))
            if op in (0x10, 0x30, 0x50, 0x70, 0x90, 0xB0, 0xD0, 0xF0):
                rel = player[pc - PLAYER_LO + 1]
                queue.append((pc + 2 + rel - (256 if rel & 128 else 0)) & 0xFFFF)
            if op in (0x40, 0x60):                          # rti, rts
                break
            pc += n
        # The command dispatch patches a branch at run time, so the JMPs it lands on are
        # never reached by a fixed address. Pick up any jmp or jsr that nothing has walked.
        if not queue:
            for off in range(0x0600 - PLAYER_LO, len(player) - 2):
                if seen[off] or player[off] not in (0x20, 0x4C):
                    continue
                w = player[off + 1] | (player[off + 2] << 8)
                if PLAYER_LO <= w <= PLAYER_HI:
                    queue.append(PLAYER_LO + off)
                    break
    patched = 0
    for pc in starts:
        op = player[pc - PLAYER_LO]
        if op not in ABSOLUTE:
            continue
        at = pc - PLAYER_LO + 1
        w = player[at] | (player[at + 1] << 8)
        if PLAYER_LO <= w <= PLAYER_HI:
            w += D_PLAYER
        elif 0x027F <= w <= VARS_HI:                        # $027F is the base of the clearing loop
            w += D_VARS
        else:
            continue
        player[at] = w & 0xFF
        player[at + 1] = w >> 8
        patched += 1
    # Pitch tables live in the player and are not reached by a full address. The high
    # byte is the immediate of `lda #$04 / sta $D6`, and the low bytes are the even
    # entries of the 16-byte table at the start of the player (the odd entries are
    # distortion values, and must stay). The player did not move by a whole number of
    # pages, so both halves change.
    page_load = 0x0821 - PLAYER_LO
    if player[page_load:page_load + 3] != bytes([0xA9, 0x04, 0x85]):
        raise SystemExit("the pitch-table page load is not where this song's player keeps it")
    player[page_load + 1] = 0x04 + (D_PLAYER >> 8)
    shift = D_PLAYER & 0xFF
    for i in range(0, 16, 2):
        if player[i] + shift > 0xFF:
            raise SystemExit("a pitch table crossed into the next page")
        player[i] += shift
    return patched


def relocate_module(module: bytearray) -> None:
    def move(off: int) -> None:
        w = module[off] | (module[off + 1] << 8)
        if MODULE_LO <= w <= MODULE_HI:
            w += D_MODULE
            module[off] = w & 0xFF
            module[off + 1] = w >> 8

    for off in range(0x08, 0x32, 2):        # the four header pointers, then the instrument pointers
        move(off)
    for i in range(0x37):                   # track high bytes, and only where the pair is a real track
        lo = module[(0x4032 - MODULE_LO) + i]
        hi = module[(0x4069 - MODULE_LO) + i]
        if MODULE_LO <= (lo | (hi << 8)) <= MODULE_HI:
            module[(0x4069 - MODULE_LO) + i] = hi + (D_MODULE >> 8)
    # A $FE inside a track is a command, not an address. The one jump in the song
    # itself sits two bytes after the $FE (FE, padding, then the word).
    move(0x4F41 - MODULE_LO)


def main() -> None:
    parts = blocks(SAP.read_bytes())
    player = bytearray(parts[PLAYER_LO])
    module = bytearray(parts[MODULE_LO])
    if module[:4] != b"RMT4":
        raise SystemExit("not an RMT4 module")
    n = relocate_player(player)
    relocate_module(module)
    if player[0x0270] != 0x4C or (player[0x0271] | (player[0x0272] << 8)) != PLAYER_AT + 0x027F:
        raise SystemExit("the init entry did not land where the game calls it")
    OUT.mkdir(exist_ok=True)
    (OUT / "stomper_player.bin").write_bytes(player)
    (OUT / "stomper_module.bin").write_bytes(module)
    print(f"player {len(player)} bytes at ${PLAYER_AT:04X}, {n} addresses moved")
    print(f"module {len(module)} bytes at ${MODULE_AT:04X}")


if __name__ == "__main__":
    main()
