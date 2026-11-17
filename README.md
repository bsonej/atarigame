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
task check-levels # are all items on every map reachable? (a quick static check, see below)
task test         # asset-tool tests + headless game tests (about 12 minutes)
task --list
```

Controls (set in `~/.atari800.cfg`, `SDL2_JOY_0_*`, for a laptop without a keypad): arrow keys move, Up/Down climb
ladders, Space jumps and starts the game. atari800's stock mapping was keypad 8/5/4/6 and right Ctrl.
In the emulator: F5 warm reset, F9 quit.

## Layout

| Path | What |
| --- | --- |
| `src/main.s` | The whole game (ca65): modes, physics, text, HUD, the attract AI. Zero-page variables are listed at the top. |
| `assets/tiles.txt` | 4x8 tiles, four colours, with the character each one has in level maps and what it does (`solid`, `oneway`, `alt`). The header documents the format. |
| `assets/font.txt` | 3x5 text font (A-Z, 0-9, `- ! ? :`). Ids: digits 16-25, letters 32-57, others from 58. |
| `assets/sprites.txt` | Player frames (4x16, one colour): stand, walk, climb, and the two death frames. |
| `assets/levels/*.txt` | 40x24 maps, played in name order. `#` brick, `H` ladder, `*` item, `^` spike, `@` start, `p` peg, plus the factory parts below. Row 0 is the score row. |
| `assets/screens/*.txt` | Full-screen text maps (`title`, `gameover`). Letters/digits come from the font; a lowercase letter is the same glyph in the second text colour; `#` `*` `^` are tiles. Comments start with `#!`. |
| `tools/build_assets.py` | Validates the assets and generates `src/gen/*.inc` (charset with the font merged in, `.charmap` so `.byte "TEXT"` works, the tile flags table, sprites, levels with their pegs and level tables, screens). |
| `tools/mkxex.py` | Packs the linker output into an Atari `.xex` with a RUNAD. |
| `tools/headless.py` | Runs the game in atari800's monitor with no window, frame by frame, for tests. |
| `cfg/` | ld65 memory layouts (normal and TEST). |
| `tools/levelcheck.py` | Static reachability check for maps (`task check-levels`). |
| `tests/` | `test_assets.py` (asset validation, tile flags, pegs), `test_game.py` (plays the real 6502 code), `test_factory.py` (each factory part), `test_levelcheck.py`. |

## Factory parts

All of these are ordinary tiles in the map; put the character in a level and it works. Solid means you cannot walk or
jump through it and can stand on it.

| Char | Part | What it does |
| --- | --- | --- |
| `#` | brick | solid |
| `=` | platform | one-way: jump up through it, land on top, walk through it at body height |
| `S` | stair | solid, but you walk up a one-tile step onto it from the side, and down it again. Needs a free tile above your head. |
| `\` `/` | chute | solid; carries you right (`\`) or left (`/`) at 2 pixels a frame. A diagonal row of them takes you down a slope: the walk-down step works on chutes too, but you cannot walk up one |
| `{` `<` `(` | belt, left | slow (half a pixel a frame), normal (1), fast (2). Drifts you whether or not you walk |
| `}` `>` `)` | belt, right | the same, to the right |
| `[` `]` | accelerating belt, left / right | starts slow, gains speed every few frames up to fast, resets when you step off |
| `~` | ice | solid; you speed up slowly, turn round slowly and slide a long way after letting go |
| `o` | roller | solid; the same idea with quicker grip, so you stop sooner |
| `X` | bomb block | step on it and it flashes for about 0.9 seconds, then explodes. The blast kills you if you are within one tile either side or two above, and sets off bomb blocks next to it. The block is gone afterwards |
| `v` | vanishing block | step on it and it flickers for about 0.6 seconds, then goes (you fall); it comes back after about 3.6 seconds, waiting until you are out of the way |
| `p` | peg | not a tile: marks where a peg starts. It sits on the platform under it and sweeps along the solid blocks there, pausing at each end, at half a pixel a frame. It pushes you along ahead of it (off the edge if you let it); jump over it. At most 2 per map, each needs a platform at least 2 tiles wide |

Notes for map builders:

- Bomb blocks and vanishing blocks in the bottom row leave a one-tile hole you can walk out of, not a pit: put them on
  upper floors.
- A peg sweeps the whole run of solid blocks under its starting tile, so give it a block of its own (a floating block,
  or a short ledge) rather than a full-width floor.
- A spike needs three clear tiles above it to be jumpable. `task check-levels` flags spikes that have not.
- Fuses and rests are counted in frames, so the times above are for 50 Hz PAL (what atari800 runs here) and are a sixth
  shorter on NTSC.
- Durations and speeds are constants at the top of `src/main.s` (`FUSE_EXPL`, `FUSE_VANISH`, `VANISH_BACK`, `PEG_WAIT`,
  `SLICK_MAX`, and the belt tables `conv_spd`, `slick_acc`...).
- To add a tile, add it to `assets/tiles.txt` (ids 0-15 and 64-71 are in use; an alt-colour tile is stored with bit 7
  set, so its map byte is its id plus 128) and give it behaviour in `main.s` if it needs any; flags alone make it solid
  or one-way.

`tools/levelcheck.py` models a competent player (walk, stairs, ladders, jumps up to two tiles and across five, drops up
to eight tiles) and reports items it cannot reach. It is an approximation: it ignores pegs, treats bomb and vanishing
blocks as solid, and cannot tell you a map is fair.

Adding a level: drop `assets/levels/levelN.txt` next to the others; it is picked up automatically. A level must have
exactly one `@` and at least one `*`. For the attract AI to be able to play it (the tests run it on every map listed in
`DEMO_LEVELS`, so the test suite will tell you), keep items standing on floors, connect floors with ladders, and keep
spikes a few tiles away from ladders, items and the edges of gaps. Maps from 4 on use the factory parts, which the AI does not understand,
so the attract mode only plays the first `DEMO_LEVELS` (3) maps; the others are checked by `task check-levels` and the
component tests.

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
hi-score, the score row, the 30-second attract run, and the AI clearing maps 1-3 without dying. `test_factory.py` builds small arenas
by poking tiles into screen RAM and checks each part (platform jump-through, stair climb and ceiling, belt speeds and
direction, acceleration and reset, ice and roller glide, chutes, vanishing and bomb timing and chain reaction, peg
start/sweep/push/jump-over) and that maps 4 and 5 load. They are skipped if
atari800 or the test build is missing.

## What is not verified

The headless tests check game logic and what is written to screen and player memory. They do **not** check what
ANTIC/GTIA actually draws: the colours, how the font and animations look, and the vertical offset of the player sprite
(`PM_YOFF` in `main.s`, assumed 32 for a standard-height playfield) were only reasoned about. The same goes for the
new tiles: their art, the cyan used for ice (`COLOR3`), the moving-pixel belt animation and the red pegs have never been
looked at on a real display, and the numbers for speeds, fuses and friction are a first guess to be tuned by playing.
Maps 4 and 5 have not been completed by anything: the AI gets round most of both (it climbs the stairs and ladders,
crosses roller, bomb and vanishing blocks) but does not know to jump pegs or ride belts to the end, and nobody has played them. Run `task run` and, if
the player is a few pixels off from the floor, adjust `PM_YOFF`.

## Memory map

`$2000-$5FFF` code and data (levels, screens, sprites) · `$6000` character set (1 KB aligned) · `$6400` display list ·
`$6500` screen (40x24) · `$7000` player/missile area (2 KB aligned; player 0 at `$7400`) · zero page `$80-$F7` · tables for timed tiles, pegs and belt animation at `$0600-$06DF` (the TEST build's joystick bytes are at `$06F0`).
