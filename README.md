# atarigame

A single-screen platformer / puzzle game for the **Atari 8-bit (XL/XE, 64 KB)** in 6502 assembly, in the spirit of
*Miner 2049er* and *Mr. Robot and His Robot Factory*. The title, "MINE RUNNER", is a placeholder
(`assets/screens/title.txt`).

## Game flow

```
TITLE --fire--> new game --> come to life --> PLAY --> level clear --> next level (come to life) ...
  |                              ^              |
  | idle 10 s                    |              +--> death animation --> come to life (a life fewer)
  v                              |                                    \--> last life: GAME OVER --> TITLE
ATTRACT: an AI plays for 30 s, then back to TITLE; fire starts a real game
```

- **Title screen** with the hi-score and a blinking PRESS FIRE.
- **Attract mode**: after 10 s idle on the title an AI plays one level for 30 s (each run uses the next map), with a
  blinking DEMO marker where the lives are. Fire starts a real game. The 30 s are counted in frames and adapt to PAL
  (50 Hz) or NTSC (60 Hz).
- **Lives** (3), **score** (10 per item, 100 for clearing a level; kept when you die), **hi-score**, and the **level
  counter** are on the top row: `SCORE 00000 LEVEL 01  LIVES 3  LEFT 08` (LEFT = items still to collect).
- **Death animation**: red flash, the player hops, tumbles off the bottom of the screen, a falling tone.
- **Come to life animation**: at every start and respawn the player is drawn line by line from the top, then blinks, in
  cycling colours with a rising tone. You cannot move until it ends.
- **Game over screen** with the score, the hi-score and NEW HIGH SCORE!; fire (after one second) or 10 s returns to the title.
- Three levels; after the last one the maps repeat while the level counter keeps counting (to 99).

Dying restores the level (all items back) but keeps your score, as in the arcade games.

## Tools

```sh
brew install cc65 atari800 go-task    # ca65/ld65, the emulator, the task runner
```

## Build and run

```sh
task run          # build build/atarigame.xex and start it in atari800
task build        # just build
task test         # asset-tool tests + headless game tests (about 5 minutes)
task --list
```

Controls (set in `~/.atari800.cfg`, `SDL2_JOY_0_*`, for a laptop without a keypad): arrow keys move, Up/Down climb
ladders, Space jumps and starts the game. atari800's stock mapping was keypad 8/5/4/6 and right Ctrl.
In the emulator: F5 warm reset, F9 quit.

## Layout

| Path | What |
| --- | --- |
| `src/main.s` | The whole game (ca65): modes, physics, text, HUD, the attract AI. Zero-page variables are listed at the top. |
| `assets/tiles.txt` | 4x8 tiles, four colours, with the character each one has in level maps. |
| `assets/font.txt` | 3x5 text font (A-Z, 0-9, `- ! ? :`). Ids: digits 16-25, letters 32-57, others from 58. |
| `assets/sprites.txt` | Player frames (4x16, one colour): stand, walk, climb, and the two death frames. |
| `assets/levels/*.txt` | 40x24 maps, played in name order. `#` brick, `H` ladder, `*` item, `^` spike, `@` start. Row 0 is the score row. |
| `assets/screens/*.txt` | Full-screen text maps (`title`, `gameover`). Letters/digits come from the font; a lowercase letter is the same glyph in the second text colour; `#` `*` `^` are tiles. Comments start with `#!`. |
| `tools/build_assets.py` | Validates the assets and generates `src/gen/*.inc` (charset with the font merged in, `.charmap` so `.byte "TEXT"` works, sprites, levels and level tables, screens). |
| `tools/mkxex.py` | Packs the linker output into an Atari `.xex` with a RUNAD. |
| `tools/headless.py` | Runs the game in atari800's monitor with no window, frame by frame, for tests. |
| `cfg/` | ld65 memory layouts (normal and TEST). |
| `tests/` | `test_assets.py` (asset validation), `test_game.py` (plays the real 6502 code). |

Adding a level: drop `assets/levels/levelN.txt` next to the others; it is picked up automatically. A level must have
exactly one `@` and at least one `*`. For the attract AI to be able to play it (the tests run it on every map, so the
test suite will tell you), keep items standing on floors, connect floors with ladders, and keep spikes a few tiles
away from ladders, items and the edges of gaps.

## The attract AI

`ai_input` in `src/main.s` produces the same joystick bits a person would. It picks the cheapest item (columns apart
+ 8 per row apart, so items on its own floor come first), walks to it, and when the item is on another floor walks to
the nearest ladder that leads there, lines up and climbs. It jumps a spike when it sees one 7 pixels ahead and a gap
when the next step would leave nothing under it.

## How the tests work

`task build-test` builds with `-D TEST`, which reads the joystick from RAM instead of the hardware. `headless.py`
starts atari800 with its monitor on a pipe and a breakpoint on the `frame_end` label, so each `Game.step()` is exactly
one frame (and `Game.run(n)` pipelines many). Tests inject joystick state, then read the game's variables and the
screen and sprite memory. They cover the physics, the title, the spawn/death/clear animations, lives, game over,
hi-score, the score row, the 30-second attract run, and the AI clearing every map without dying. They are skipped if
atari800 or the test build is missing.

## What is not verified

The headless tests check game logic and what is written to screen and player memory. They do **not** check what
ANTIC/GTIA actually draws: the colours, how the font and animations look, and the vertical offset of the player sprite
(`PM_YOFF` in `main.s`, assumed 32 for a standard-height playfield) were only reasoned about. Run `task run` and, if
the player is a few pixels off from the floor, adjust `PM_YOFF`.

## Memory map

`$2000-$5FFF` code and data (levels, screens, sprites) · `$6000` character set (1 KB aligned) · `$6400` display list ·
`$6500` screen (40x24) · `$7000` player/missile area (2 KB aligned; player 0 at `$7400`) · zero page `$80-$DF`.
