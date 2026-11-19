# atarigame

A single-screen platformer / puzzle game for the **Atari 8-bit (XL/XE, 64 KB)** in 6502 assembly, in the spirit of
*Miner 2049er* and *Mr. Robot and His Robot Factory*. The title screen is a picture of Mr. Bubble (see
"The title screen" below); the game's own name is still undecided.

## Game flow

```
TITLE --fire--> new game --> come to life --> PLAY --> eat every dot, take every item, door opens, walk in
                                                      --> level clear --> next level (come to life) ...
  |                              ^              |
  | idle 10 s                    |              +--> death animation --> come to life (a life fewer)
  v                              |                                    \--> last life: GAME OVER --> TITLE
ATTRACT: an AI plays for 30 s, then back to TITLE; fire starts a real game
```

- **Title screen**: the Mr. Bubble splash picture, the hi-score and a blinking PRESS FIRE TO START (see "The title screen").
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
- **The player is Mr. Bubble**: a round pink bubble with eyes and a grin, 8x16 and drawn centred on the 4-wide physics
  box (so he overhangs a tile by about 2 pixels each side; only the 4 pixels in the middle collide). His eyes look the
  way he last moved (at you until he first moves), he leans while he walks, squashes to take off and on landing (4 frames),
  stretches while he rises, and pops on death. 13 frames in all. He is a bubble, so he **floats**: the picture is drawn
  `PLAYER_FLOAT` (2) scan lines above the surface he stands on. That is purely visual: the physics box, the collisions and
  the feet-only hazard rules are unchanged (`py` is still the top of a 16 line box whose bottom touches the floor). The
  value lives in `src/main.s`, `web/spritemodel.js`, `tools/render_level.py` and `tools/headless.py`, and a test checks they agree.
  On top of the hover he **bobs** like a bubble: `draw_player` looks the float up in `bob_float` (64 bytes: 2 + round(sin),
  so 1, 2 or 3 lines above the surface, never below it and never more than 3 above, a period of 64 frames) indexed by the
  OS frame counter `RTCLOK+2` (no new state in the game; the lookup is stored in the zero-page `pfloat` for the tests). All
  layers (body, eyes, the four missiles) use the same value and the same hide/wrap rule (`py - pfloat` of 200 or more hides
  him). It is purely visual: no physics, collision or hazard change, and it is not part of the state `test_engine.py`
  compares. `web/spritemodel.js` has the same table (`BOB_FLOAT`; a test checks it equals `main.s`), used by the editor's
  test play and the sprite editor's animation preview; `tools/render_level.py` keeps the mean hover (`PLAYER_FLOAT`).
  If `py` is so far above the screen that the image would start above PM byte 0 (the death hop), he is hidden rather than wrapped.
- **He has three colours**, all set in `assets/palette.txt`: `player` (body, Player 0, pink `$4E`), `eyes` (Player 3, white
  `$0E`) and a third (pupils and grin, `o` in `sprites.txt`) that is **the `ice` entry**. The third layer is drawn with the
  four **missiles** used as a fifth 8-clock-wide sprite (`GPRIOR` = `$11`: PRIOR bit 4, `SDMCTL` = `$3E` for missile DMA,
  `HPOSM0..3` = HPOS, +2, +4, +6, `SIZEM` = 0, so each missile is 2 clocks wide; the data is in the missile page `PMAREA+$300`,
  2 bits per missile per line: M0 bits 1-0 ... M3 bits 7-6, copied and erased with the other layers, with the same
  `PLAYER_FLOAT` and the same hide/wrap rule). Hardware makes a fifth player take the colour of playfield colour 3
  (`COLPF3`), which is the ice colour (the ice tiles and the exit door's blue), hence the coupling: changing `ice` changes
  his pupils too. Its priority is that of playfield colour 3, so it sits **behind the body and the eyes** (it shows through
  their holes, which is what the pupils and the grin are) and in front of the background, but behind playfield colours 0-2
  (so over a platform or a ladder pixel his pupils are hidden). Each `o` pixel is free (a missile is a 2-bit-wide player, one pixel per bit); a pixel is one character, so there is no pixel that is body and third at once.
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

## The title screen

The title is a picture of Mr. Bubble with two text rows under it. It has its own display list, `dlist_title` (next to the
game's `dlist` at `$6400`):

```
24 blank lines                       the same top as the game's display list
176 lines of ANTIC mode E            the picture: 160 x 176, 4 colours, 40 bytes a line (22 text rows' worth)
  LMS $8000  lines 0-101             one load-memory-scan per 4 KB block: ANTIC's address counter cannot cross a 4 KB
  LMS $9000  lines 102-175           boundary inside a line (102 lines are 4080 bytes; the packer pads up to $9000)
  DLI on line 175                    sets the text rows' colours
2 lines of mode 4 text               rows 22 (PRESS FIRE TO START, blinking) and 23 (HI-SCORE) of the screen RAM at $6500
```

- **Pixels and colours.** Mode E pixel values 0-3 are the background `COLBK` and `COLPF0-2`; they come from the shadow
  registers `COLOR4` and `COLOR0-2`, set from four entries of `assets/palette.txt`: `splash_bg` (pink, also the border
  and the text rows' background), `splash_light` (face, nose, "EST. 1961"), `splash_navy` (lettering, pupils, grin) and
  `splash_white` (eyes, bubble outlines). The text rows use navy letters: the interrupt on the picture's last line
  (`dli_title`) copies row 22 of the `pal0-3` tables into `COLPF0-3` for them (the title is not banded: every row of the
  tables holds the same colours). Edit the entries to retint the picture; the lowest bit of a luminance is not used.
- **Rows 0-21 of the screen RAM are not shown on the title** (the picture replaces them), so `assets/screens/title.txt` only
  has the HI-SCORE label in row 23; the game writes PRESS FIRE TO START in row 22 and the digits in row 23, column 22.
  The game over screen is unchanged (the normal display list with its colour bands).
- **Switching display lists** is done at the vertical blank, so it cannot tear: a mode change writes `SDLSTL` (the OS
  copies it at the next blank, together with the colour shadows), and a deferred vertical-blank routine (`vbi_hook`,
  installed with `SETVBV`) picks the display-list interrupt routine (`dli_title` or `dli`) that matches the display list the
  OS has just made current and resets the game's row counter, all inside the blank where no interrupt can happen.
  Going to the title first sets the picture's colours and the display list, waits one frame (`vwait`) and only then fills in
  the screen RAM and the pal tables, so the picture never shows the game's colours. Going from the title into a game
  fills everything first and switches at the next blank (the text rows may show a frame of the game's last two rows).
  Players and missiles are hidden on the title.
- **Colours of the background** are held by `update_fx` each frame (`COLOR4`): the picture's pink on the title, black elsewhere.

### The picture and how it was made

`assets/splash-source.webp` (700 x 538, the Mr. Bubble ad) was converted by `tools/make_splash.py` into
`assets/splash.txt`. The picture really has four flat colours (background pink, light pink face/nose/lettering,
navy, and white for the eyes and bubble outlines), so there is no dithering: everything is a solid fill or a one or two pixel line.

1. A window of the source is cut out so that it keeps its proportions on the TV: a mode E pixel is about 1.5 times as wide as a
   line is tall (`PIXEL_ASPECT`), so 160 x 176 pixels correspond to a 700 x 513 window of the source (6 rows cut from
   the top, 19 from the bottom; `--top`, `--pixel-aspect`).
2. Every source pixel gets the nearest of four reference colours (CIE Lab distance): background, light, white, navy.
3. The print's grain is removed as small connected patches (fewer than 40 pixels) of the wrong class; the pale shapes
   (light pink and white together) are cleaned first so that the broken outlines of the bubbles stay in one piece.
4. Small pale shapes (the lettering "EST. 1961" and the little bubbles) are made one source pixel wider on each side so that their
   thin strokes survive; then the shapes are shrunk onto 160 x 176 by counting what share of each target pixel is covered by each class,
   with a bonus for the pale lines; a pale pixel is white if most of the pale pixels in it are white, else light pink.
5. A last pass on the bitmap removes isolated pixels (patches of fewer than 3).

Regenerate with `python3 tools/make_splash.py assets/splash-source.webp --preview /tmp/splash.png --compare /tmp/side.png`
(`pip install pillow` first; it overwrites `assets/splash.txt`, so keep hand edits elsewhere). Draw a preview of any
`splash.txt` with `python3 tools/make_splash.py --show assets/splash.txt /tmp/splash.png` (palette colours from `assets/palette.txt` through the approximate
`atari_rgb`, 3 x 2 upscale = the pixel shape on a TV). Dropped in the conversion: the (R) mark, the period after EST, and the finest grain.
`tools/build_assets.py` checks `splash.txt` (176 rows of 160 characters `0`-`3`) and packs it, four pixels to a byte (leftmost in the top bits).

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
task editor       # the drag-and-drop level editor in your browser (see "Level editor" below); its Sprite editor page edits Mr. Bubble
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
| `assets/palette.txt` | The row hues, grey, white, ice blue, score row and background colours as Atari colour bytes, and Mr. Bubble's `player` and `eyes` colours (his third colour is `ice`). Generates `src/gen/palette.inc` (`PAL_PLAYER`, `PAL_EYES`, `PAL_ICE`); the editor gets them through `/api/tiles`. |
| `assets/font.txt` | 3x5 text font (A-Z, 0-9, `- ! ? :`). Ids: digits 16-25, letters 32-57, others from 58. |
| `assets/sprites.txt` | Mr. Bubble's 13 frames (8x16): stand (front, looking right, looking left), lean right and left, squash (front, right, left), stretch (front, right, left) and two pop frames. `#` is body (Player 0, pink), `e` is an eye (Player 3, white, shown only where the body has no pixel), `o` is the third colour (the four missiles as a fifth sprite, behind both, so it shows through their holes; any single pixel: the pupils and the grin). `.` is nothing. |
| `assets/levels/*.txt` | 40x24 maps, played in name order. `#` platform, `W` wall, `H` ladder, `*` item, `^` spike, `D` exit door, `@` start, `p` peg, plus the factory parts below. Row 0 is the score row. |
| `assets/splash.txt` | The title picture: 160x176 pixels, one character `0`-`3` per pixel (ANTIC mode E, four colours), editable by hand. Generates `src/gen/splash.inc`. `assets/splash-source.webp` is the picture it was made from. |
| `tools/make_splash.py` | One-off converter (needs Pillow, not part of the build) from a picture to `assets/splash.txt`, plus `--show` to draw a preview PNG of a `splash.txt` (no Pillow). |
| `assets/screens/*.txt` | Full-screen text maps (`title`, `gameover`). Letters/digits come from the font; a lowercase letter is the same glyph in the second text colour; `#` `*` `^` are tiles. Comments start with `#!`. |
| `tools/build_assets.py` | Validates the assets and generates `src/gen/*.inc` (charset with the font merged in, `.charmap` so `.byte "TEXT"` works, the tile flags table, the chutes' thread, sprites, levels with their pegs and level tables, screens). |
| `tools/mkxex.py` | Packs the linker output into an Atari `.xex` with a RUNAD. |
| `tools/headless.py` | Runs the game in atari800's monitor with no window, frame by frame, for tests. |
| `cfg/` | ld65 memory layouts (normal and TEST). |
| `tools/levelcheck.py` | Static reachability check for maps (`task check-levels`). |
| `tools/render_level.py` | Draws a compiled level (end caps and all) to a PNG: `python3 tools/render_level.py assets/levels/level4.txt out.png --scale 7`. |
| `tools/editor_server.py` | The small local web server behind the level and sprite editors: serves `web/`, reads and writes `assets/levels/`, `assets/sprites.txt` and Mr. Bubble's colours in `assets/palette.txt`. |
| `web/` | The level editor (plain ES modules, no build step): `editor.js` (the page), `model.js` (level text and compiling), `engine.js` (the game's rules in JavaScript, for test play), `render.js`, `palette.js`. The sprite editor is `sprites.html` + `sprites.js` (the page) and `spritemodel.js` (parsing, writing, undo, the preview cycles). |
| `tests/` | `test_assets.py` (asset validation, tile flags, end caps, pegs), `test_game.py` (plays the real 6502 code), `test_factory.py` (each factory part and its end caps), `test_levelcheck.py`, `test_editor_server.py` (levels and sprites), `test_engine.py` (the editor's engine against the game in the emulator), `test_js.py` + `tests/js/` (node tests of the editor code). |

## Factory parts

All of these are ordinary tiles in the map; put the character in a level and it works. Solid means you cannot walk
through it and can stand on it (a jump still rises through it: see "Jumping").

| Char | Part | What it does |
| --- | --- | --- |
| `#` | brick | solid |
| `=` | platform | one-way: jump up through it, land on top, walk through it at body height |
| `S` | stair | a thin ledge (the top 3 pixel rows of the tile). Not solid: walk past it, or jump up through it and land on top; a flight of them is climbed by jumping |
| `\` | chute down | a vertical lift: walk into it (it replaces a gap in the floor) and it carries you down to the end of its column, joystick ignored. Not solid, nothing stands on it, you pass through it in the air (see "Chutes") |
| `/` | chute up | the same, upwards: it carries you to its top and you hop out onto the platform beside it. Its screw thread turns upwards |
| `{` `<` `(` | belt, left | slow (half a pixel a frame), normal (1), fast (2). Drifts you whether or not you walk. Walking with it adds its speed to yours; walking against it, it pulls at you only 3/8 as hard, so you can always walk onto it and along it, slowly (a normal belt costs you 3/8 of a pixel a frame, a fast one 3/4) |
| `}` `>` `)` | belt, right | the same, to the right |
| `[` `]` | accelerating belt, left / right | starts slow, gains speed every few frames up to fast, resets when you step off |
| `~` | ice | solid; you speed up slowly, turn round slowly and slide a long way after letting go |
| `o` | roller | solid; the same idea as ice with quicker grip, so you stop sooner. The longer the run of rollers under your feet, the harder it grips: it speeds you up by as many 1/16 pixels a frame as it is tiles long, up to 8 (a 1-tile roller is slower to get going than ice, an 8-tile one is almost instant) |
| `T` | trampoline | solid, like a platform, with no dots: walking over it or standing on it does nothing. Land on it from a JUMP (not from walking or falling off an edge) and it bounces you straight back up, no button needed, just high enough to land on the next surface above you (see "Trampolines"). Nothing above you in range, or no jump: no bounce, an ordinary landing |
| `Z` | teleport | solid, no dots. Tiles of it that touch (sides or above and below) are **one** teleporter. Stand on it (feet on the top of any of its tiles, walking along it counts) for 1 second and you are pixelated away and rebuilt at the next teleporter (see "Teleports") |
| `z` | one-use teleport | the same, but once you have gone from it, all of it turns into a plain platform for good. Still a destination while unused |
| `X` | bomb block | step on it and it flashes for about 0.9 seconds, then explodes. The blast kills you if your feet are within one tile either side and between two tiles above the block and its bottom edge (so a bomb going off over your head, or beside your knees, does nothing), and sets off bomb blocks next to it. The block is gone afterwards |
| `v` | vanishing block | step on it and it flickers for about 0.6 seconds, then goes (you fall); it comes back after about 3.6 seconds, waiting until you are out of the way |
| `p` | peg | not a tile: marks where a peg starts. It sits on the platform under it and sweeps the whole platform there (see below), pausing at each end, at half a pixel a frame. It pushes you along ahead of it, all the way to the end of the platform and off it, if it is beside your feet; jump over it. A peg on a block above you does not touch you. At most 2 per map, each needs a platform at least 2 tiles wide |

### End caps

Every platform type has a left end, a right end and a both-ends look (`cap` lines in `assets/tiles.txt`). You never
write them in a map: where a tile's left or right neighbour is a different tile (the screen edge counts as the same)
`tools/build_assets.py` swaps in the cap, so `##########` gives a brick run with rounded ends and `>>>>>` a belt with
bevelled ones. The game treats a cap as the plain tile (`tile_canon` in `src/gen/tileflags.inc`), so rules, the AI and
`levelcheck` never see the difference; belt caps animate with their belt, and a bomb or vanishing block puts back the
exact byte it had. Caps are art only. To change one, edit its rows in `tiles.txt` (or delete the rows to have the tool
round off the plain tile again). One limitation: while a vanishing or bomb block is gone, its neighbours keep the end cap
they were built with, so the gap's edges look unchanged until it returns.

### Chutes

Chutes are vertical lifts, one tile wide, in two kinds: `\` is the **down chute** (`SLIDE_R`, "Chute down" in the editor) and
`/` is the **up chute** (`SLIDE_L`, "Chute up"). They are not solid, not one-way and not a surface: nothing stands on them,
and in the air (a jump, a fall) you pass straight through them. They only catch you when you are *walking* (the ground
state) into one: a chute tile at the middle of your body column (`px+2`) at your body rows (`py+8` or `py+15`), or directly
under your feet (`py+16`, a chute that fills a gap in the floor). Once caught you are locked in (`S_RIDE`, joystick
ignored, he stands facing the way he last went and does not turn) and snapped to the tile column (`(px+2) & $FC`), and
carried 2 pixels a frame to the end of the column:

- **Down**: `py += 2` while a chute is under your feet. Below the last tile you are released into normal physics (`S_AIR`,
  `fall` = 0) and land on whatever is there, or keep falling. The ride starts in the floor (a platform whose gap the chute
  fills, with room to land below the last tile): a down chute caught from its body rows alone (it stands on the floor you
  walk on) has nowhere to take you, so it is simply walked through rather than snapping you back every frame.
- **Up**: `py -= 2` while a chute is at your feet row. When your feet are level with the top of the top tile you hop out
  in the direction you faced (a short jump from the jump table, `HOP_JT`, with 4 pixels of forced sideways drift,
  `HOP_FRAMES`) and land on the platform beside the top, so put a platform level with the top tile.

Chutes must be isolated, single-wide vertical runs of one kind: `task check-levels` (and the editor's check list) rejects
a chute with another chute in the neighbouring columns at the rows above, level with and below it (diagonals and
side-by-side layouts), and an up chute stacked on a down chute.

A chute is drawn as a screw thread: a diagonal stroke two pixels wide that crosses the tile and carries on in the tile
below, so a stack of chutes is one unbroken thread with no seams. One turn of the thread is
16 rows, two tiles, so each chute is a pair in `assets/tiles.txt`: the plain tile (`SLIDE_R` id 14, `SLIDE_L` id 15) and
its `twin` (`SLIDE_R_B` id 123, `SLIDE_L_B` id 124), which holds the next 8 rows. You write one character in a map; the asset
tool (and the editor) puts the twin on every odd screen row, so tiles alternate plain, twin, plain, twin down a stack. Like
caps and dots, a twin is the plain tile to the game (`tile_canon`).

To make it turn, the game rewrites the four glyphs every second frame (`animate_chutes` in `src/main.s`, reusing the
belts' trick of changing the character set): the 16 rows move one row further along the stack each time and come round
every 32 frames, with no state in RAM (the phase is read from the frame counter). The down chute's thread travels down the
stack, the up chute's travels up. `build_assets.py` writes the thread to `src/gen/helix.inc` (from the art of the four tiles, so
changing the art in `tiles.txt` is all it takes); `web/render.js` (`chuteFrame(helix, tick, up)`), `tools/render_level.py --tick N` and
`build_assets.chute_frame(helix, tick, up)` do the same sum, and the tests check they agree.

### Trampolines

A trampoline (`T`, `TRAMPOLINE`) is a solid platform whose middle tiles are just the mat (a two line thick rubber band at the top of the tile, nothing below) and whose end caps are the posts it is anchored to, with the spring legs (ids 26-29: the tile and its three end caps; no dot version, so no dots). Walking, standing and jumping off it are as on any platform. The
bounce happens on the air-to-ground transition (`try_bounce` in `src/main.s`, `tryBounce` in `web/engine.js`), but only after a *jump*: the zero-page flag `jumped` is set when fire starts a jump on the ground (and a bounce keeps it, so bounces chain) and cleared by every landing, by walking or being pushed (peg, belt) off an edge, by grabbing a ladder or entering a chute, and on level start, so the hop out of an up chute does not count. A landing without it is an ordinary landing on a platform: no bounce, no animation, the usual fall-death rule. When
`air_fall` lands him after a jump and the tile under the middle of his feet, else under either foot (the belt probe order), is a
trampoline, it looks up from that tile row by row, at most `BOUNCE_ROWS` (14) rows and never above pixel line 24 (tile
row 3: a surface higher could not be landed on, because the score row is the ceiling). In each row it tries `px+2`,
`px` and `px+3` with `tile_standable`, so the target is the first thing he could land on: a solid tile of any kind
(brick, wall, ice, roller, belt, bomb or vanishing block, another trampoline), the top of a one-way platform or step or
of a ladder. If there is one, `k` rows up, he is thrown up with a rise of at least `8k + 8` pixels, so the apex clears
the target's top by a tile (8 to 10 pixels): that is the end of an ordinary jump (`jump_dy` from index 3: 17 pixels)
preceded by `bounce_n[k]` extra frames of 3 pixels (`bn`, a new zero-page byte; `jt` stays at 3 meanwhile), and the
table is `ceil((8k - 9) / 3)`. As in every jump, rising ignores everything above him and the joystick steers freely;
on the way down he lands on the first surface, which is the target (a surface directly stacked above the target
within the 8-10 pixel margin may be landed on instead). He is caught however far he fell: the fall that would kill him
(more than 64 pixels) does not when a bounce follows, but with nothing above him it is an ordinary landing, so the
usual rule applies. If he is steered back onto a trampoline, or lands on one on the upper level, it bounces him again.
Range and rows are constants: `BOUNCE_ROWS`, `BOUNCE_TOP` (`web/engine.js` has the same, and `bounce_n` / `BOUNCE_N`). The bounce only decides how far he rises; the way down is the usual slow fall (see "Jumping").

**The rubber band.** When a bounce starts, the mat of the whole connected run he landed on (the trampoline tiles on that row
either side of the one under him, caps counted) animates like a stretched rubber band: `tramp_start` finds the run's ends and
the column he landed in, and `tramp_anim` (every frame of play, after `update_timed`; `trampAnim` in `web/engine.js`) steps
through `tramp_amp` (`TRAMP_AMP`), two frames per step, 26 frames in all: it sags 1, 2, 3 lines, holds, comes back up, springs
past plain (the band stretched taut and thin), sags a little again, goes taut once more and settles (the last step is plain).
The pictures are extra tiles, so only that run's *screen* tiles change (like a vanishing block): `TRAMPOLINE_S1`, `_S2`, `_S3` (the
mat 1, 2, 3 lines lower; ids 30, 31, 62) and `TRAMPOLINE_TAUT` (id 63), `frame` lines in `assets/tiles.txt`. The sag of a middle
tile is the smallest of the amplitude, one more than its distance from the end of the run (so it tapers to the posts) and
3 minus half its distance from where he landed (deepest there, at least 1): `tramp_draw`. The end caps never change; a run of
caps only (one or two tiles) has no mat to stretch and stays still. Other trampolines on the screen do not move; the game
treats every picture as the trampoline (`tile_canon` maps a `frame` tile to its tile, like caps and dots), so `get_tile`,
the bounce, `levelcheck` and the AI see `TRAMPOLINE` throughout, and gameplay is unchanged. A bounce on another run (or the
same again) puts the old one back first; `timed_reset` (every level start and respawn) clears it, and the map is copied
afresh anyway. The state is zero-page `tr_t` (0 = idle), `tr_row`, `tr_l`, `tr_r`, `tr_c`. The editor's test play shows it
(it draws the engine's map); `tools/render_level.py` draws the plain art.
`tools/levelcheck.py` treats a landing cell on a trampoline (standing on it he can always jump up and land again, which bounces) as reaching the first surface above it (cells on that row
within the bounce's air time), and does not claim anything more. The attract AI knows nothing of trampolines (it
ignores them); no shipped map has one yet.

### Teleports

`Z` (`TELEPORT`, id 125) and `z` (`TELEPORT_ONCE`, id 126) are solid, single-tile parts with no end caps and no dots, drawn
as a pad with two rows of dots on top that glow (ice blue in place of white, `glow` flag in `assets/tiles.txt`).

- **A teleporter** is a set of tiles of the same kind joined by an edge (4-connected, at most 64 tiles). Each has a
  *first tile*: the top-most, then left-most one. A group with both kinds in it is an error.
- **Charging**: with his feet on top of any tile of a teleporter, grounded, `fps` frames (1 second: 60 NTSC, 50 PAL) in a
  row, he teleports. Walking along it keeps counting; jumping, falling or stepping off starts over. While he charges the
  pad flickers between its two colours every 4 frames, and is plain again if he leaves. After arriving he must leave the
  ground (jump or walk off) before the pad he landed on charges again, or he would go straight back.
- **Where to**: teleporters are ordered by their first tile in reading order (row, then column); he goes to the next one,
  the last to the first, skipping one-use ones that have been used. With no other teleporter left nothing happens. He is
  rebuilt standing on the first tile of the destination. The count of teleporters is taken from the screen map, so it
  tracks what has been used.
- **One-use**: when he leaves it, the whole group turns into plain `BRICK` (map-only: `begin_level` copies the whole
  map afresh on every level start and respawn, which restores it). It is skipped as a destination from then on.
- **The dissolve** (mode `M_TELE`, 32 frames): 16 frames taking the picture out in a 4x4 ordered dither, over the body
  (Player 0), eyes (Player 3) and the third colour (missiles), the move on the 17th, 16 frames building it up again.
  Input is ignored, hazards do not act, pegs and fuses wait. The masks are `src/gen/dissolve.inc` (17 steps).
- **Checks**: the asset tool, `levelcheck` and the editor refuse a level with exactly one teleporter, a group of both
  kinds, a first tile without two clear tiles above it (no room to stand and be rebuilt), or a group over 64 tiles.
  `levelcheck` adds an edge from every tile of a teleporter to the next one's first tile (first trips only: it does not
  model one-use ones being gone, so it never claims more is reachable than is). The attract AI ignores teleporters.
- **Slots**: ids 125 and 126 are the two tiles; 127 is kept as the marker the flood fill (a runtime walk of the screen
  map, so levels poked into RAM work) writes while it scans, and is cleaned afterwards; no existing tile was removed. The
  glow is the alt-colour bit (map byte + 128) of the same id, so it takes no further slot.
- State: zero page `tp_t` (frames charged), `tp_lock`, `tp_s4` (dissolve mask row offset, 0 = whole) and temporaries
  `tp_*`; BSS `tp_a`, `tp_b`, `tp_n`, `tp_hr`, `tp_hc` (group scan).

### Jumping

A jump rises 26 pixels (`jump_dy` in `src/main.s`, `JUMP_DY` in `web/engine.js` and `web/spritemodel.js`; three tiles up
reach, `JUMP_REACH` in `tools/levelcheck.py`), and the way down is slower than the way up, so he floats back down
(`air_fall`, `airFall`): the pixels a frame depend on `fall`, the pixels fallen since the apex: 1 a frame for the first
`FALL_SLOW` (4) pixels, then the pattern 1, 1, 2 (`fall` bit 1 clear = 2 pixels) up to `FALL_FAST` (16), then 2 a frame as before.
A 26 pixel jump takes 13 frames up and about 18 down (it was 13), and he drifts that much further sideways. `fall` still
counts pixels, so the lethal distance (more than 64 pixels) is unchanged, and `tools/levelcheck.py` computes its
jump reach (`JUMP_REACH`) and the bounce's from the same fall (`fall_frames`: one tile wider than before for a flat
jump). The sprite editor's jump preview uses the same descent. While rising nothing above him matters: no head bump on bricks, walls, bombs,
one-way platforms or chutes, he simply overlays them (only the score row is a ceiling). Sideways collisions stay as they were (a brick
beside him blocks him), with one exception so he is never stuck: at a body row where he is already inside a solid on the
edge he is on, he can slide on (he rose into a block and slides about in it and out of it). Falling, he lands on the first solid or one-way surface under his feet
as before, but never inside a solid: if a solid tile is at the lowest row of his body (`py+15`) he keeps falling until he is clear,
so a block he rose into lets him fall out of its bottom (or land on its top if his feet got above it).

**Items are taken at his level only.** Rising through a tile does not collect what is in it. An item is picked up only
when it is in the row of his feet (the point 13 pixels below `py`; the head and the middle of his body never take one)
and he is not rising (the up phase of a jump or of the hop out of an up chute, or a ride up a chute). Walking, standing,
climbing, riding down and falling all take it. So you walk into an item on your own floor, you take an item on a ledge by
landing or standing on that ledge, and an item hanging at head height over the floor cannot be taken by walking or jumping
under it (put something under it to stand on). Dots are unchanged (eaten when standing on their tile). `check_tiles` in
`src/main.s` and `checkTiles` in `web/engine.js`; the door is still entered by any overlap.

Notes for map builders:

- Bomb blocks and vanishing blocks in the bottom row leave a one-tile hole you can walk out of, not a pit: put them on
  upper floors.
- A peg sweeps the whole platform under its starting tile, so give it a block of its own (a floating block, or a short
  ledge) rather than a full-width floor. The platform is the run of tiles of **any** kind on the line under the peg (bricks,
  one-way platforms, steps, belts, ice, rollers, bomb and vanishing blocks, spikes, ladders, chutes, walls), from the gap
  before to the gap after: empty space, an item or the exit door ends it, and so does a solid tile in the peg's own row
  (a wall it would bump into); a step, spike or ladder standing on the platform does not. Its push is not stopped by what is
  in the run: it carries him clear of the peg in one go (up to 4 pixels, so a fast belt dragging him back never wins), and
  at the end of its run it gives one more push the way it was going before it turns round, so he ends up off the end and
  not on its last pixel. A solid beside him (a wall) still stops him as it stops any walk, and what is under his feet still
  applies (a spike at his feet still kills: pushed over, not made immune; a gap in the floor still drops him).
- A spike tile is two white-tipped needles on a solid base, drawn from the second line of the tile (7 lines; it used
  to start at the third). It hurts from the line its tips are on down: only his feet count, as before, and the check
  (`SPIKE_TOP` in `main.s` and `engine.js`, `check_tiles`) is that line, one pixel more height than the old rule.
- A spike needs three clear tiles above it to be jumpable. `task check-levels` flags spikes that have not.
- Fuses and rests are counted in frames, so the times above are for 50 Hz PAL (what atari800 runs here) and are a sixth
  shorter on NTSC.
- Durations and speeds are constants at the top of `src/main.s` (`FUSE_EXPL`, `FUSE_VANISH`, `VANISH_BACK`, `PEG_WAIT`,
  `SLICK_MAX`, and the belt tables `conv_spd`, `slick_acc`...).
- To add a tile, add it to `assets/tiles.txt` (ids 0-15, 26-31, 62-126 are in use; only 127 is left, and the teleports' flood fill uses it as its marker, see the header of that file; a `glow` flag makes bit 7 of the byte a flickering twin of a solid tile; a `frame` line adds a picture only the game puts on the screen, as the trampoline's rubber band does; an alt-colour tile is stored with bit 7
  set, so its map byte is its id plus 128) and give it behaviour in `main.s` if it needs any; flags alone make it solid
  or one-way.

`tools/levelcheck.py` models a competent player (walk, stairs, ladders, chutes, jumps up to three tiles and across six or seven, drops up
to eight tiles) and reports items it cannot reach (an item counts only if he can *stand* in its row, with his feet on the
row under it, in its column or a neighbour, or climb past it on a ladder: a jump up into it from below does not take it; the door keeps the old overlap reach) and chutes that are not single-wide vertical runs. It is an approximation: it ignores pegs, treats bomb and vanishing
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

- **Palette** (each swatch is a little scene compiled and drawn like the playfield: capsule ends, dots, the row's colours, the whole 2x3 door): platforms, belts (left and right, four speeds), ice, rollers, trampolines, teleports (two tiles, a short stamp each), ladders, stairs, chutes, spikes, bomb and
  vanishing blocks, pegs, items and the player start, plus ready-made **stamps** (a belt run, a flight of stairs, a block
  with a peg already on it). `Shift`+drag fills a rectangle, the right mouse button erases, `V` is a select tool (drag a
  selection to move it, `Alt`+drag or `Cmd/Ctrl+C` to copy, `Delete` to clear). `Cmd/Ctrl+Z` undoes. Row 0 belongs to the
  score display.
- **Test play**: `P` plays the level in the page with the game's own rules (arrows or WASD move, `Space` or `Z` jumps,
  `R` restarts, `Esc` returns to editing). `Shift+P` starts you at the cell under the mouse, to try the far end of a big
  map. Pegs, belts, ice, bombs, vanishing blocks, spikes, lives, death, spawn and clearing all work.
- **Checks** on the right update as you edit: the problems that would stop the game accepting the level (no start, no
  items, a peg with nothing under it, a lone teleporter, a teleporter of both kinds, no room over a teleporter's first tile) and the `levelcheck` reachability warnings. Click one to find it on the board.
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

## Sprite editor

`task editor`, then click **Sprite editor** in the level editor's top bar (or open `http://localhost:8765/sprites.html`).
It edits `assets/sprites.txt`, Mr. Bubble's 13 frames of 8x16 pixels:

- **Frames** on the left, each with a thumbnail and the name it has in `sprites.txt`; a dot marks frames that differ from
  what is saved. The big grid edits the selected frame: left button paints with the selected tool (**Body** `B`/`1`: pink,
  Player 0; **Eye** `E`/`2`: white, Player 3, which sits behind the body and shows only where the body has no pixel;
  **Third** `O`/`3`: the third colour (missiles, behind both), painted one pixel at a time like the others; **Erase** `X`/`4`), the right button erases, and a fast drag fills every cell in between. Zoom, a grid, a 2:1 "TV shape"
  for the pixels, and guides (the 4 pixel wide physics box he collides with, and the line `PLAYER_FLOAT` lines above his
  feet) are options under the grid.
- **Colours**: the three colours as swatches (body = `player`, eyes, third = `ice`, which the ice tiles and the exit door
  share) and the Atari palette (16 hues x 8 luminances) to pick from; the previews follow at once. **Save colours** (and
  **Save to game**, if they changed) sends them to `PUT /api/palette`, which validates them (a colour byte 0-255 with an even
  luminance) and rewrites just those lines of `assets/palette.txt`, comments and all.
- **In the game** shows the frame at 1x and 4x the way the screen does: pink body, white eyes, pupils and the grin in the third colour
  over black, standing `PLAYER_FLOAT` pixels above a floor. **Animation** loops the real frame choices of `choose_frame`:
  walk right and left (stand, lean), jump (squash, stretch, land, with the rise of the game's jump table), jump right and
  left, look around and the death pop. Play/pause (`Space`), speed and size are options.
- **Frame tools**: copy and paste a frame (`Cmd/Ctrl+C`/`V`), clear, revert to what is saved, flip (`H`), nudge the picture a
  pixel (`Shift`+arrows; all three colours move together), and **Mirror to the other side** (`M`), which overwrites the right/left counterpart of the
  selected frame (`stand_right` <-> `stand_left`, `lean_*`, `squash_*`, `stretch_*`) with its mirror image. Undo/redo
  (`Cmd/Ctrl+Z`, `Shift+Cmd/Ctrl+Z`) cover every stroke and every frame operation.
- **Save to game** (`Cmd/Ctrl+S`) sends the frames to `PUT /api/sprites`, which writes the pixel rows into
  `assets/sprites.txt` and leaves everything else in the file (the header comment, blank lines, the `frame` lines)
  exactly as it was. The server refuses, with a message that says which frame and row, anything `tools/build_assets.py`
  would refuse (rows of 8 characters of `#`, `.`, `e` and `o`, with `o` free to be any pixel; exactly 16 rows) and what the game relies on: the same number of
  frames with the same names in the same order (`main.s` picks a frame by its place in the list), (rows may be empty). Then `task build` / `task run`. The level editor
  re-reads the frames whenever its page comes back to the front, so its test play and start marker show the saved ones.
  Unsaved sprite work is kept in the browser like unsaved levels; **Download .txt** and **Reload from game** are there too.

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
by poking tiles into screen RAM and checks each part (platform jump-through, stairs as ledges you walk past and jump onto, chutes that carry you down and up (and are walked and jumped through otherwise), jumps that rise through blocks, trampoline bounces (walking over, landing, nothing above, long falls, repeat), belt speeds and
direction, acceleration and reset, ice and roller glide, the thread of the chutes in the character set turning one row at a time, down for one chute and up for the other, vanishing and bomb timing and chain reaction, peg
start/sweep/push/jump-over, teleporter timing, order, one-use and the dissolve) and that maps 4 and 5 load. They are skipped if
atari800 or the test build is missing. `test_engine.py` (see "Level editor") replays scripted input on both the game and the
editor's JavaScript engine; `task test-js` runs just the node tests, which need no emulator.

## What is not verified

The level editor's page was exercised in Cursor's built-in browser (Chromium): loading, painting, dropping parts, undo,
select and move, saving, and a test play with key presses. The sprite editor's page was loaded there against a throwaway copy of
the assets: painting, undo, mirroring, saving (the written file compared with the original), the frame list and the animated
preview. Its model and the server endpoint have automated tests; dragging with a real mouse, the keyboard shortcuts and other
browsers were not tried. Other browsers, touch screens, and the feel of real-time
play with a physical keyboard have not been tried, and test play has no sound.

The headless tests check game logic and what is written to screen and player memory, including the per-row colour
tables and that the display-list interrupt runs 23 times a frame. They do **not** check what ANTIC/GTIA actually draws:
what the title picture looks like on a real Atari or in the emulator (the display list, the load-memory-scans, the colours, the preview's pixel shape and the text-row colour change under the picture were checked in memory and in a PNG made with the approximate palette, never on a display), whether the colour changes land cleanly at the start of each row (the interrupt waits for the end of the line with `WSYNC`
before writing, so there should be no visible tearing, but nobody has looked), the colours themselves (the editor and
`render_level.py` use an approximation of the Atari palette, so the real hues will differ a little), how the font and animations look, and the vertical offset of the player sprite
(`PM_YOFF` in `main.s`, assumed 32 for a standard-height playfield, and the 2 line float above the surface, with its 1-3 line bob: how smooth and how light it looks) were only reasoned about. The same goes for the
new tiles: their art, the deep blue used for ice and the police box (`COLOR3`, `ice` in `assets/palette.txt`), the door's pixel fade, the moving-pixel belt animation, the chutes' turning thread and the ride (the art, its speed and how it reads on a real display, the two directions, and how the ride and the hop out of an up chute feel), the red pegs and Mr. Bubble, a round pink bubble with white eyes (Player 3 drawn behind Player 0, so the eyes only show where the body has a hole) and the third colour (the four missiles as a fifth sprite with `GPRIOR` bit 4: that the missiles line up with the player, the colour of `COLPF3` and the priority behind the body were checked only in memory, not on a real display or screenshot) have never been
looked at on a real display, and the numbers for speeds, fuses and friction are a first guess to be tuned by playing.
Maps 4 and 5 have not been completed by anything (the AI clears 1-3 in about 1,000 frames each; on 4 and 5 it ran out of its 3,000-frame test budget with 32 and 16 things left, and it never dies): the AI gets round most of both (it climbs the stairs and ladders,
crosses roller, bomb and vanishing blocks) but does not know to jump pegs or ride belts to the end, and nobody has played them. Run `task run` and, if
the player is a few pixels off from the floor (he should hover 2 lines above it), adjust `PM_YOFF` and `PLAYER_FLOAT` (and `FLOAT` in `web/spritemodel.js`).

## Memory map

`$2000-$5FFF` code and data (levels, screens, sprites) · `$6000` character set (1 KB aligned) · `$6400` display list ·
`$6500` screen (40x24) · `$8000-$9B8F` the title picture (mode E bitmap, in its own load segment; `$8000-$BFFF` is free otherwise) · `$7000` player/missile area (2 KB aligned; the missiles, Mr. Bubble's third colour, at `$7300`; player 0 at `$7400`, the pegs are players 1 and 2 and Mr. Bubble's eyes player 3) · zero page `$80-$F7` · tables for timed tiles, pegs and belt animation at `$0600-$06DF` (the TEST build's joystick bytes are at `$06F0`).
