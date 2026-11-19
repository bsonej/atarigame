// Drawing: the game's 4x8 tiles and sprites on canvases, at the shape they have on the Atari screen.
//
// A game pixel is one colour clock: twice as wide as it is tall. So one tile (4x8 pixels) is a square cell
// of 8*zoom CSS pixels, and the 160x192 playfield is 40x24 square cells.

import { COLS, ROWS } from './model.js';
import { FLOAT } from './spritemodel.js';

export { FLOAT };

export const COLORS = {
  bg: '#000000',
  player: 'hsl(350 70% 86.1%)', // Atari $4E: the pink bubble
  eye: '#ffffff',
  third: 'hsl(215 70% 55%)', // Atari $8A: the ice blue, which the missiles (his pupils and grin) share with the ice tiles
  peg: '#ff5a4a',
  hud: '#f4f4f4',
};

// Atari colour bytes (hue in the high nibble, luminance in the low one) as CSS colours. An approximation: a
// real TV or emulator differs a little. tools/render_level.py uses the same table, so the PNGs match.
const HUE_DEG = [0, 45, 28, 12, 350, 325, 295, 265, 235, 215, 192, 170, 135, 95, 70, 45];
export function atariColour(byte) {
  const hue = byte >> 4;
  const light = 0.04 + (0.88 * (byte & 15)) / 15;
  return hue === 0 ? `hsl(0 0% ${(light * 100).toFixed(1)}%)` : `hsl(${HUE_DEG[hue]} 70% ${(light * 100).toFixed(1)}%)`;
}

/** Which of the 9 colour sets a screen row uses: the score row (0) has its own, the rest step round the 8 hues. */
export const rowVariant = (levelIndex, row) => (row <= 0 ? 8 : (row + levelIndex) % 8);

/** The Atari colour byte of pixel value 1 in screen row `row` of level number `levelIndex` (0-based). */
export const rowHueByte = (palette, levelIndex, row) => {
  const v = rowVariant(levelIndex, row);
  return v === 8 ? palette.hud : palette.hues[v];
};

/** Mr. Bubble's three colours from assets/palette.txt: `player` (body, Player 0), `eyes` (Player 3) and `ice`, which is
 * also his third colour (the missiles take the playfield's colour 3). Sets COLORS.player, .eye and .third. */
export function applyPlayerColours(pal) {
  if (!pal) return;
  if (pal.player !== undefined) COLORS.player = atariColour(pal.player);
  if (pal.eyes !== undefined) COLORS.eye = atariColour(pal.eyes);
  if (pal.ice !== undefined) COLORS.third = atariColour(pal.ice);
}

const DEFAULT_PALETTE = { hues: [0x1e, 0x2c, 0x4c, 0x5c, 0x7c, 0x9c, 0xac, 0xcc], grey: 0x0a, white: 0x0e, ice: 0x8a, hud: 0x2a, background: 0 };

// The belts' animation (animate_belts in main.s): one bright pixel marches along rows 0-1 of the glyph.
const BELT_PAT = [0xea, 0xba, 0xae, 0xab];
const CONV_MASK = [7, 3, 1, 3, 7, 3, 1, 3];
const CONV_DIR = [0, 0, 0, 0, 1, 1, 1, 1];
const CONV_FIRST = 64;

/**
 * The chutes' screw thread (animate_chutes in main.s). `helix` is the 16 rows of a chute's thread (its tile's 8 rows,
 * then its twin's 8). Every second frame the thread moves one row along the stack - down for a down chute, up for an
 * up chute (`up`): the plain tile (even screen rows) shows 8 rows from the phase on, its twin (odd rows) the next 8.
 * Returns [rows of the plain tile, rows of the twin].
 */
export function chuteFrame(helix, tick, up = false) {
  const ph = up ? (tick >> 1) & 15 : ((tick >> 1) & 15) ^ 15;
  const at = (y) => helix[(y + ph) & 15];
  return [[0, 1, 2, 3, 4, 5, 6, 7].map(at), [8, 9, 10, 11, 12, 13, 14, 15].map(at)];
}

export class Atlas {
  /**
   * Tiles are stored as pixel values 0-3 and coloured per row of the screen, as the game does with its
   * display-list interrupt (assets/palette.txt): pixel 1 takes the hue of the row, 2 is grey, 3 is white (ice
   * blue in an alt tile). There is one canvas per hue step, plus one for the score row; `levelIndex` shifts
   * which hue a row gets, as the level number does in the game.
   * @param api the /api/tiles reply
   */
  constructor(api) {
    this.api = api;
    this.pal = api.palette || DEFAULT_PALETTE;
    applyPlayerColours(this.pal);
    this.levelIndex = 0;
    this.variants = [];
    for (let i = 0; i < 9; i++) {
      const canvas = document.createElement('canvas');
      canvas.width = 256 * 4;
      canvas.height = 8;
      this.variants.push({ canvas, ctx: canvas.getContext('2d') });
    }
    this.canvas = this.variants[8].canvas; // the score row's colours (handy for a quick look)
    this.cph = new Array(8).fill(0);
    this.alt = new Set(api.tiles.filter((t) => t.alt).map((t) => t.byte));
    this.rows = {};
    for (const t of api.tiles) this.rows[t.byte] = t.rows;
    for (const t of api.tiles) this.paint(t.byte);
    this.beltPhase = -1;
    this.chuteTick = -1;
    // each chute and its twin: the thread they draw between them (16 rows)
    const byName = {};
    for (const t of api.tiles) byName[t.name] = t;
    this.chutes = ['SLIDE_R', 'SLIDE_L']
      .filter((n) => byName[n] && byName[`${n}_B`])
      .map((n) => ({ a: byName[n].byte, b: byName[`${n}_B`].byte, helix: [...byName[n].rows, ...byName[`${n}_B`].rows], up: n === 'SLIDE_L' }));
  }

  /** The canvas holding the tiles as they look in screen row `row`. */
  canvasFor(row) {
    return this.variants[rowVariant(this.levelIndex, row)].canvas;
  }

  colour(v, alt, variant) {
    const p = this.pal;
    if (v === 0) return atariColour(p.background);
    if (v === 1) return atariColour(variant === 8 ? p.hud : p.hues[variant]);
    if (v === 2) return atariColour(p.grey);
    return atariColour(alt ? p.ice : p.white);
  }

  paint(byte, onlyRows = null) {
    const rows = this.rows[byte];
    if (!rows) return;
    const alt = this.alt.has(byte);
    this.variants.forEach(({ ctx }, variant) => {
      for (let y = 0; y < 8; y++) {
        if (onlyRows && !onlyRows.includes(y)) continue;
        for (let x = 0; x < 4; x++) {
          ctx.fillStyle = this.colour(Number(rows[y][x]), alt, variant);
          ctx.fillRect(byte * 4 + x, y, 1, 1);
        }
      }
    });
  }

  /** Turn the chutes' thread. `tick` counts 50 Hz frames. */
  animateChutes(tick) {
    const ph = (tick >> 1) & 15;
    if (ph === this.chuteTick) return;
    this.chuteTick = ph;
    for (const c of this.chutes) {
      const [a, b] = chuteFrame(c.helix, tick, c.up);
      this.rows[c.a] = a;
      this.rows[c.b] = b;
      this.paint(c.a);
      this.paint(c.b);
    }
  }

  /** March the belts (and turn the chutes). `tick` counts 50 Hz frames. */
  animateBelts(tick) {
    this.animateChutes(tick);
    if (tick === this.beltPhase) return;
    this.beltPhase = tick;
    for (let k = 0; k < 8; k++) {
      if ((tick & CONV_MASK[k]) !== 0) continue;
      this.cph[k] = (this.cph[k] + (CONV_DIR[k] ? -1 : 1)) & 3;
      const pat = BELT_PAT[this.cph[k]];
      const px = [(pat >> 6) & 3, (pat >> 4) & 3, (pat >> 2) & 3, pat & 3];
      for (const base of [0, 8, 16, 24]) {
        const byte = CONV_FIRST + base + k;
        if (!this.rows[byte]) continue;
        for (const y of [0, 1]) {
          const row = this.rows[byte][y].split('');
          px.forEach((v, x) => (row[x] = String(v)));
          this.rows[byte] = this.rows[byte].slice();
          this.rows[byte][y] = row.join('');
        }
        this.paint(byte, [0, 1]);
      }
    }
  }
}

/** The size of one cell for a zoom level. */
export const cellSize = (zoom) => 8 * zoom;

/** Draw a tile at (x, y); `row` (default: the screen row that y falls in) picks its colours. */
export function drawTile(ctx, atlas, byte, x, y, cell, alpha = 1, row = Math.round(y / cell)) {
  if (alpha !== 1) ctx.globalAlpha = alpha;
  ctx.drawImage(atlas.canvasFor(row), byte * 4, 0, 4, 8, x, y, cell, cell);
  if (alpha !== 1) ctx.globalAlpha = 1;
}

/**
 * One tile of the exit door as it looks part way through its fade: only the pixels whose fade step is below the
 * door's current phase are there (the same table the game uses to redraw the door's glyphs).
 * @param door {bytes: the six tile bytes, fade: step of each pixel, phase, steps}
 */
export function drawDoorTile(ctx, atlas, byte, x, y, cell, row, door) {
  const k = door.bytes.indexOf(byte);
  if (door.phase <= 0) return;
  if (door.phase >= door.steps) return drawTile(ctx, atlas, byte, x, y, cell, 1, row);
  const src = atlas.canvasFor(row);
  const pw = cell / 4;
  const ph = cell / 8;
  for (let py = 0; py < 8; py++)
    for (let px = 0; px < 4; px++)
      if (door.fade[(k * 8 + py) * 4 + px] < door.phase) ctx.drawImage(src, byte * 4 + px, py, 1, 1, x + px * pw, y + py * ph, pw, ph);
}

/** The map: 40x24 bytes, row 0 left to the HUD. During play `door` says how much of the exit door shows. */
export function drawMap(ctx, atlas, map, cell, fromRow = 1, door = null) {
  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = COLORS.bg;
  ctx.fillRect(0, 0, COLS * cell, ROWS * cell);
  for (let r = fromRow; r < ROWS; r++)
    for (let c = 0; c < COLS; c++) {
      const b = map[r * COLS + c];
      if (!b) continue;
      if (door && door.bytes.includes(b)) drawDoorTile(ctx, atlas, b, c * cell, r * cell, cell, r, door);
      else drawTile(ctx, atlas, b, c * cell, r * cell, cell, 1, r);
    }
}

/** A sprite frame (16 rows, the top 4 bits of each) with its top-left game pixel at (px, py). */
export function drawSprite(ctx, rows, px, py, cell, colour, lines = 16, bit = 4) {
  const w = cell / 4; // one game pixel is as wide as 1/4 of a cell
  const h = cell / 8;
  ctx.fillStyle = colour;
  for (let y = 0; y < Math.min(lines, rows.length); y++)
    for (let x = 0; x < bit; x++) if (rows[y] & (0x80 >> x)) ctx.fillRect((px + x) * w, (py + y) * h, w, h);
}

/** Mr. Bubble: his third colour (the missiles, a fifth sprite behind the other two: `frame.thirdPx`, pairs of pixels),
 * his eyes (hardware Player 3, which sits behind the body) and then the pink body (Player 0). The frames
 * are 8 pixels wide on a 4 pixel wide physics box, so he is drawn 2 pixels to the left of (px, py). He is a bubble: he
 * floats FLOAT lines above his box (py is the top of the physics box, so its bottom, where he stands, is py + 16). */
export function drawPlayer(ctx, frame, px, py, cell, colour = COLORS.player, lines = 16, eyeColour = COLORS.eye, float = FLOAT, thirdColour = COLORS.third) {
  if (frame.thirdPx) drawSprite(ctx, frame.thirdPx, px - 2, py - float, cell, thirdColour, lines, 8);
  drawSprite(ctx, frame.eyes, px - 2, py - float, cell, eyeColour, lines, 8);
  drawSprite(ctx, frame.rows, px - 2, py - float, cell, colour, lines, 8);
}

export const PEG_SHAPE = [0x60, 0xf0, 0xf0, 0xf0, 0xf0, 0xf0, 0xf0, 0x90];

/** HUD text as the game shows it, in row 0. */
export function drawHud(ctx, cell, { score, level, lives, left }) {
  ctx.fillStyle = COLORS.bg;
  ctx.fillRect(0, 0, COLS * cell, cell);
  ctx.fillStyle = COLORS.hud;
  ctx.font = `bold ${Math.round(cell * 0.62)}px ui-monospace, Menlo, monospace`;
  ctx.textBaseline = 'middle';
  const pad = (n, w) => String(n).padStart(w, '0');
  ctx.fillText(`SCORE ${pad(score, 5)}  LEVEL ${pad(level, 2)}  LIVES ${lives}  LEFT ${pad(left, 3)}`, cell * 0.5, cell * 0.5);
}
