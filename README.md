# atarigame

A single-screen platformer / puzzle game for the **Atari 8-bit (XL/XE, 64 KB)** in 6502 assembly, in the spirit of
*Miner 2049er* and *Mr. Robot and His Robot Factory*. The title, "MINE RUNNER", is a placeholder
(`assets/screens/title.txt`).

## Game flow

```
TITLE --fire--> new game --> come to life --> PLAY --> eat every dot, take every item, door opens, walk in
                                                      --> level clear --> next level (come to life) ...
  |                              ^              |
  | idle 10 s                    |              +--> death animation --> come to life (a life fewer)
  v                              |                                    \--> last life: GAME OVER --> TITLE
ATTRACT: an AI plays for 30 s, then back to TITLE; fire starts a real game
```

- **Title screen** with the hi-score and a blinking PRESS FIRE.
- **Attract mode**: after 10 s idle on the title an AI plays one level for 30 s (each run uses the next map), with a
  blinking DEMO marker where the lives are. Fire starts a real game. The 30 s are counted in frames and adapt to PAL
  (50 Hz) or NTSC (60 Hz).
- **The goal**: walk along every platform and eat its **dots** (1 point each), take every **item** (10 points) and,
  when nothing is left, the **exit door** appears (a flash and a rising tone): a blue police box, 2 tiles wide and 3
  tall, that fades in pixel by pixel. Walk into it to clear the level (100 points); it fades out the same way as you
  go through. Until it has appeared it is not there, so a level is not won by running to the end.
- **Lives** (3), **score** (kept when you die), **hi-score**, and the **level counter** are on the top row:
  `SCORE 00000 LEVEL 01  LIVES 3  LEFT 074` (LEFT = dots and items still to collect, up to 250 a level).
- **Colour**: every screen row has its own hue (a display-list interrupt rewrites the four colour registers at the
  start of each row), so a level is banded in the way of the arcade games it imitates. The hues step round eight
  colours, and move one step per level, so each level looks different. The grey, white, ice blue and the score row's
  colour are the same on every row. All of it comes from `assets/palette.txt`, which the editor reads too.
- **Death animation**: red flash, the player hops, tumbles off the bottom of the screen, a falling tone.
- **Come to life animation**: at every start and respawn the player is drawn line by line from the top, then blinks, in
  cycling colours with a rising tone. You cannot move until it ends.
- **Game over screen** with the score, the hi-score and NEW HIGH SCORE!; fire (after one second) or 10 s returns to the title.
- Three levels; after the last one the maps repeat while the level counter keeps counting (to 99).

Dying restores the level (all items and dots back, the door shut) but keeps your score, as in the arcade games.

### Level design notes

- **Capsule platforms.** Every platform has a rounded end cap on each free end, so a platform reads as a free-standing
  object (see "End caps"). Platforms that run into a wall have no cap there. The side walls are the `W` tile: plain
  solid blocks with no caps and no dots, so a platform can run into them cleanly.
- **Dots** are not placed by hand. The asset tool puts one in every second middle tile of each run of a brick or thin
  platform (never on an end cap), but only where the player can stand to eat it: no solid tile in the two cells above and
  no spikes (a dot under a spike would be a trap). A dot is eaten by walking over it on the ground; jumping over one
  leaves it.
- **The door** is the `D` character: the bottom left tile of a 2x3 box. The compiler adds the other five tiles, so the
  two columns to its right and the two rows above must be empty. Every level needs exactly one. It is never solid. Its
  art is six `alt` tiles (ids 117-122 in `assets/tiles.txt`); the fade rewrites their six glyphs in the character set
  each frame from a 16-step table (`src/gen/fade.inc`, built by `tools/build_assets.py`, also sent to the editor).

## Tools

```sh
brew install cc65 atari800 go-task    # ca65/ld65, the emulator, the task runner
```

## Build and run

```sh
task run          # build build/atarigame.xex and start it in atari800
task build        # just build
task run-map -- 4   # run with games starting on map 4 (to try the factory parts without clearing 1-3)
task check-levels # are all items on every map reachable? (a quick static check, see below)
task editor       # the drag-and-drop level editor in your browser (see "Level editor" below)
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
| `assets/palette.txt` | The row hues, grey, white, ice blue, score row and background colours as Atari colour bytes. Generates `src/gen/palette.inc`; the editor gets them through `/api/tiles`. |
| `assets/font.txt` | 3x5 text font (A-Z, 0-9, `- ! ? :`). Ids: digits 16-25, letters 32-57, others from 58. |
| `assets/sprites.txt` | Player frames (4x16, one colour): stand, walk, climb, and the two death frames. |
| `assets/levels/*.txt` | 40x24 maps, played in name order. `#` platform, `W` wall, `H` ladder, `*` item, `^` spike, `D` exit door, `@` start, `p` peg, plus the factory parts below. Row 0 is the score row. |
| `assets/screens/*.txt` | Full-screen text maps (`title`, `gameover`). Letters/digits come from the font; a lowercase letter is the same glyph in the second text colour; `#` `*` `^` are tiles. Comments start with `#!`. |
| `tools/build_assets.py` | Validates the assets and generates `src/gen/*.inc` (charset with the font merged in, `.charmap` so `.byte "TEXT"` works, the tile flags table, sprites, levels with their pegs and level tables, screens). |
| `tools/mkxex.py` | Packs the linker output into an Atari `.xex` with a RUNAD. |
| `tools/headless.py` | Runs the game in atari800's monitor with no window, frame by frame, for tests. |
| `cfg/` | ld65 memory layouts (normal and TEST). |
| `tools/levelcheck.py` | Static reachability check for maps (`task check-levels`). |
| `tools/render_level.py` | Draws a compiled level (end caps and all) to a PNG: `python3 tools/render_level.py assets/levels/level4.txt out.png --scale 7`. |
| `tools/editor_server.py` | The small local web server behind the level editor: serves `web/`, reads and writes `assets/levels/`. |
| `web/` | The level editor (plain ES modules, no build step): `editor.js` (the page), `model.js` (level text and compiling), `engine.js` (the game's rules in JavaScript, for test play), `render.js`, `palette.js`. |
| `tests/` | `test_assets.py` (asset validation, tile flags, end caps, pegs), `test_game.py` (plays the real 6502 code), `test_factory.py` (each factory part and its end caps), `test_levelcheck.py`, `test_editor_server.py`, `test_engine.py` (the editor's engine against the game in the emulator), `test_js.py` + `tests/js/` (node tests of the editor code). |

## Factory parts

All of these are ordinary tiles in the map; put the character in a level and it works. Solid means you cannot walk or
jump through it and can stand on it.

| Char | Part | What it does |
| --- | --- | --- |
| `#` | brick | solid |
| `=` | platform | one-way: jump up through it, land on top, walk through it at body height |
| `S` | stair | a thin ledge (the top 3 pixel rows of the tile). Not solid: walk past it, or jump up through it and land on top; a flight of them is climbed by jumping |
| `\` `/` | chute | a ledge like stairs that also carries you right (`\`) or left (`/`) at 2 pixels a frame. Not solid; a diagonal row of them takes you down a slope (the walk-down step works on chutes), but you jump to go up one |
| `{` `<` `(` | belt, left | slow (half a pixel a frame), normal (1), fast (2). Drifts you whether or not you walk |
| `}` `>` `)` | belt, right | the same, to the right |
| `[` `]` | accelerating belt, left / right | starts slow, gains speed every few frames up to fast, resets when you step off |
| `~` | ice | solid; you speed up slowly, turn round slowly and slide a long way after letting go |
| `o` | roller | solid; the same idea with quicker grip, so you stop sooner |
| `X` | bomb block | step on it and it flashes for about 0.9 seconds, then explodes. The blast kills you if you are within one tile either side or two above, and sets off bomb blocks next to it. The block is gone afterwards |
| `v` | vanishing block | step on it and it flickers for about 0.6 seconds, then goes (you fall); it comes back after about 3.6 seconds, waiting until you are out of the way |
| `p` | peg | not a tile: marks where a peg starts. It sits on the platform under it and sweeps along the solid blocks there, pausing at each end, at half a pixel a frame. It pushes you along ahead of it (off the edge if you let it); jump over it. At most 2 per map, each needs a platform at least 2 tiles wide |

### End caps

Every platform type has a left end, a right end and a both-ends look (`cap` lines in `assets/tiles.txt`). You never
write them in a map: where a tile's left or right neighbour is a different tile (the screen edge counts as the same)
`tools/build_assets.py` swaps in the cap, so `##########` gives a brick run with rounded ends and `>>>>>` a belt with
bevelled ones. The game treats a cap as the plain tile (`tile_canon` in `src/gen/tileflags.inc`), so rules, the AI and
`levelcheck` never see the difference; belt caps animate with their belt, and a bomb or vanishing block puts back the
exact byte it had. Caps are art only. To change one, edit its rows in `tiles.txt` (or delete the rows to have the tool
round off the plain tile again). One limitation: while a vanishing or bomb block is gone, its neighbours keep the end cap
they were built with, so the gap's edges look unchanged until it returns.

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

## Level editor

```sh
task editor        # starts tools/editor_server.py and opens http://localhost:8765/
```

Build a level by dragging parts from the palette onto the board (or click a part, then click or drag on the board):

- **Palette** (each swatch is a little scene compiled and drawn like the playfield: capsule ends, dots, the row's colours, the whole 2x3 door): platforms, belts (left and right, four speeds), ice, rollers, ladders, stairs, chutes, spikes, bomb and
  vanishing blocks, pegs, items and the player start, plus ready-made **stamps** (a belt run, a flight of stairs, a block
  with a peg already on it). `Shift`+drag fills a rectangle, the right mouse button erases, `V` is a select tool (drag a
  selection to move it, `Alt`+drag or `Cmd/Ctrl+C` to copy, `Delete` to clear). `Cmd/Ctrl+Z` undoes. Row 0 belongs to the
  score display.
- **Test play**: `P` plays the level in the page with the game's own rules (arrows or WASD move, `Space` or `Z` jumps,
  `R` restarts, `Esc` returns to editing). `Shift+P` starts you at the cell under the mouse, to try the far end of a big
  map. Pegs, belts, ice, bombs, vanishing blocks, spikes, lives, death, spawn and clearing all work.
- **Checks** on the right update as you edit: the problems that would stop the game accepting the level (no start, no
  items, a peg with nothing under it) and the `levelcheck` reachability warnings. Click one to find it on the board.
- **Save to game** writes `assets/levels/<name>.txt` (only if the game's own asset tool accepts it). The level number is its
  place in name order, so a new `levelN` joins the end. Then `task build` or `task run`, or press **Run in emulator**,
  which saves, builds and opens the game on that map. Your unsaved work is also kept in the browser, so a closed tab does
  not lose it. **Download** and **Import** move level files by hand.

Security: the server listens on 127.0.0.1 only, answers only requests for `localhost`, refuses to save unless the request
carries the editor's own header (so another web page cannot save through your browser), accepts level names that are
lowercase letters, digits and underscores, and writes only inside `assets/levels/`.

The test play is a **port** of the game's rules to JavaScript (`web/engine.js`), not the 6502 code. To keep the two
honest, `tests/test_engine.py` plays the same scripted joystick input on the real game in the emulator and on the port,
and compares the player, the screen map and the pegs after every stretch of input: on all five shipped maps from the start,
from random standing places and from places on the pegs' blocks, and on randomly generated maps that mix every part. If you
change a rule in `main.s`, change `engine.js` and let that test tell you if they have drifted. The editor compiles levels
(end caps, dots, the door, pegs, item counts) the same way as `build_assets.py`, which `CompileParity` in the same file checks on every level.

## The attract AI

`ai_input` in `src/main.s` produces the same joystick bits a person would. It picks the cheapest item (columns apart
+ 8 per row apart, so items on its own floor come first), walks to it, and when the item is on another floor walks to
the nearest ladder that leads there, lines up and climbs. It jumps a spike when it sees one 7 pixels ahead and a gap
when the next step would leave nothing under it. Dots are targets as well (it stands in the cell above the dotted tile),
and once everything is collected the open door is the target.

## How the tests work

`task build-test` builds with `-D TEST`, which reads the joystick from RAM instead of the hardware. `headless.py`
starts atari800 with its monitor on a pipe and a breakpoint on the `frame_end` label, so each `Game.step()` is exactly
one frame (and `Game.run(n)` pipelines many). Tests inject joystick state, then read the game's variables and the
screen and sprite memory. They cover the physics, the title, the spawn/death/clear animations, lives, game over,
hi-score, the score row, dots and the door, the 30-second attract run, and the AI clearing maps 1-3 (dots, items, door) without dying. `test_engine.py` also checks that the colour tables the game's display-list interrupt loads are the editor's colours for every level, and that the interrupt fires once per row, every frame. `test_factory.py` builds small arenas
by poking tiles into screen RAM and checks each part (platform jump-through, stairs and chutes as ledges you walk past and jump onto, belt speeds and
direction, acceleration and reset, ice and roller glide, chutes, vanishing and bomb timing and chain reaction, peg
start/sweep/push/jump-over) and that maps 4 and 5 load. They are skipped if
atari800 or the test build is missing. `test_engine.py` (see "Level editor") replays scripted input on both the game and the
editor's JavaScript engine; `task test-js` runs just the node tests, which need no emulator.

## What is not verified

The level editor's page was exercised in Cursor's built-in browser (Chromium): loading, painting, dropping parts, undo,
select and move, saving, and a test play with key presses. Other browsers, touch screens, and the feel of real-time
play with a physical keyboard have not been tried, and test play has no sound.

The headless tests check game logic and what is written to screen and player memory, including the per-row colour
tables and that the display-list interrupt runs 23 times a frame. They do **not** check what ANTIC/GTIA actually draws:
whether the colour changes land cleanly at the start of each row (the interrupt waits for the end of the line with `WSYNC`
before writing, so there should be no visible tearing, but nobody has looked), the colours themselves (the editor and
`render_level.py` use an approximation of the Atari palette, so the real hues will differ a little), how the font and animations look, and the vertical offset of the player sprite
(`PM_YOFF` in `main.s`, assumed 32 for a standard-height playfield) were only reasoned about. The same goes for the
new tiles: their art, the deep blue used for ice and the police box (`COLOR3`, `ice` in `assets/palette.txt`), the door's pixel fade, the moving-pixel belt animation and the red pegs have never been
looked at on a real display, and the numbers for speeds, fuses and friction are a first guess to be tuned by playing.
Maps 4 and 5 have not been completed by anything (the AI clears 1-3 in about 1,000 frames each; on 4 and 5 it ran out of its 3,000-frame test budget with 32 and 16 things left, and it never dies): the AI gets round most of both (it climbs the stairs and ladders,
crosses roller, bomb and vanishing blocks) but does not know to jump pegs or ride belts to the end, and nobody has played them. Run `task run` and, if
the player is a few pixels off from the floor, adjust `PM_YOFF`.

## Memory map

`$2000-$5FFF` code and data (levels, screens, sprites) · `$6000` character set (1 KB aligned) · `$6400` display list ·
`$6500` screen (40x24) · `$7000` player/missile area (2 KB aligned; player 0 at `$7400`) · zero page `$80-$F7` · tables for timed tiles, pegs and belt animation at `$0600-$06DF` (the TEST build's joystick bytes are at `$06F0`).
