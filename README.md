# atarigame

A single-screen platformer / puzzle game for the **Atari 8-bit (XL/XE, 64 KB)** in 6502 assembly, in the spirit of
*Miner 2049er* and *Mr. Robot and His Robot Factory*. The game is a generic skeleton for now: walk, jump, climb
ladders, collect every item, avoid spikes and long falls.

## Tools

```sh
brew install cc65 atari800 go-task    # ca65/ld65, the emulator, the task runner
```

## Build and run

```sh
task run          # build build/atarigame.xex and start it in atari800
task build        # just build
task test         # asset-tool tests + headless game-logic tests
task --list
```

Controls: joystick 1 (arrow keys + left Ctrl in atari800). Up/down on a ladder to climb, fire to jump.

## Layout

| Path | What |
| --- | --- |
| `src/main.s` | The whole game (ca65). Zero-page variables are listed at the top. |
| `assets/tiles.txt` | 4x8 tiles, four colours, with the character each one has in level maps. |
| `assets/sprites.txt` | Player frames (4x16, one colour). |
| `assets/levels/*.txt` | 40x24 maps. `#` brick, `H` ladder, `*` item, `^` spike, `@` start. |
| `tools/build_assets.py` | Validates the assets and generates `src/gen/*.inc` (charset, sprites, levels). |
| `tools/mkxex.py` | Packs the linker output into an Atari `.xex` with a RUNAD. |
| `tools/headless.py` | Runs the game in atari800's monitor with no window, one frame at a time, for tests. |
| `cfg/` | ld65 memory layouts (normal and TEST). |
| `tests/` | `test_assets.py` (asset validation), `test_game.py` (plays the real 6502 code). |

Adding a level: drop `assets/levels/levelN.txt` next to `level1.txt`; the tools pick it up (level switching in
`main.s` is not wired yet, so only `level1` is played).

## How the tests work

`task build-test` builds with `-D TEST`, which reads the joystick from RAM instead of the hardware. `headless.py`
starts atari800 with its monitor on a pipe and a breakpoint on the `frame_end` label, so each `Game.step()` is exactly
one frame. Tests inject joystick state, then read the player's variables and the screen memory. They are skipped if
atari800 or the test build is missing.

## What is not verified

The headless tests check game logic and what is written to screen and player memory. They do **not** check what
ANTIC/GTIA actually draws: the colours, and the vertical offset of the player sprite (`PM_YOFF` in `main.s`, assumed 32
for a standard-height playfield) were only reasoned about. Run `task run` and, if the player is a few pixels off from
the floor, adjust `PM_YOFF`.

## Memory map

`$2000` code · `$4000` character set (1 KB aligned) · `$4400` display list · `$4500` screen (40x24) ·
`$5000` player/missile area (2 KB aligned; player 0 at `$5400`) · zero page `$80-$DF`.
