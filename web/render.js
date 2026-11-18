// Drawing: the game's 4x8 tiles and sprites on canvases, at the shape they have on the Atari screen.
//
// A game pixel is one colour clock: twice as wide as it is tall. So one tile (4x8 pixels) is a square cell
// of 8*zoom CSS pixels, and the 160x192 playfield is 40x24 square cells.

import { COLS, ROWS } from './model.js';

export const COLORS = {
  bg: '#000000',
  c0: '#f0a030', // COLOR0 (pixel value 1): bright orange
  c1: '#a05a20', // COLOR1 (2): brown
  c2: '#f4f4f4', // COLOR2 (3): white
  c3: '#34c8f0', // COLOR3 (3 in an "alt" tile): cyan
  player: '#ffe040',
  peg: '#ff5a4a',
  hud: '#f4f4f4',
};

// The belts' animation (animate_belts in main.s): one bright pixel marches along rows 0-1 of the glyph.
const BELT_PAT = [0xea, 0xba, 0xae, 0xab];
const CONV_MASK = [7, 3, 1, 3, 7, 3, 1, 3];
const CONV_DIR = [0, 0, 0, 0, 1, 1, 1, 1];
const CONV_FIRST = 64;

export class Atlas {
  /** @param api the /api/tiles reply */
  constructor(api) {
    this.api = api;
    this.canvas = document.createElement('canvas');
    this.canvas.width = 256 * 4;
    this.canvas.height = 8;
    this.ctx = this.canvas.getContext('2d');
    this.cph = new Array(8).fill(0);
    this.alt = new Set(api.tiles.filter((t) => t.alt).map((t) => t.byte));
    this.rows = {};
    for (const t of api.tiles) this.rows[t.byte] = t.rows;
    for (const t of api.tiles) this.paint(t.byte);
    this.beltPhase = -1;
  }

  colour(v, alt) {
    return v === 0 ? COLORS.bg : v === 1 ? COLORS.c0 : v === 2 ? COLORS.c1 : alt ? COLORS.c3 : COLORS.c2;
  }

  paint(byte, onlyRows = null) {
    const rows = this.rows[byte];
    if (!rows) return;
    const alt = this.alt.has(byte);
    for (let y = 0; y < 8; y++) {
      if (onlyRows && !onlyRows.includes(y)) continue;
      for (let x = 0; x < 4; x++) {
        this.ctx.fillStyle = this.colour(Number(rows[y][x]), alt);
        this.ctx.fillRect(byte * 4 + x, y, 1, 1);
      }
    }
  }

  /** March the belts. `tick` counts 50 Hz frames. */
  animateBelts(tick) {
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

export function drawTile(ctx, atlas, byte, x, y, cell, alpha = 1) {
  if (alpha !== 1) ctx.globalAlpha = alpha;
  ctx.drawImage(atlas.canvas, byte * 4, 0, 4, 8, x, y, cell, cell);
  if (alpha !== 1) ctx.globalAlpha = 1;
}

/** The map: 40x24 bytes, row 0 left to the HUD. */
export function drawMap(ctx, atlas, map, cell, fromRow = 1) {
  ctx.imageSmoothingEnabled = false;
  ctx.fillStyle = COLORS.bg;
  ctx.fillRect(0, 0, COLS * cell, ROWS * cell);
  for (let r = fromRow; r < ROWS; r++)
    for (let c = 0; c < COLS; c++) {
      const b = map[r * COLS + c];
      if (b) drawTile(ctx, atlas, b, c * cell, r * cell, cell);
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

export const PEG_SHAPE = [0x60, 0xf0, 0xf0, 0xf0, 0xf0, 0xf0, 0xf0, 0x90];

/** HUD text as the game shows it, in row 0. */
export function drawHud(ctx, cell, { score, level, lives, left }) {
  ctx.fillStyle = COLORS.bg;
  ctx.fillRect(0, 0, COLS * cell, cell);
  ctx.fillStyle = COLORS.hud;
  ctx.font = `bold ${Math.round(cell * 0.62)}px ui-monospace, Menlo, monospace`;
  ctx.textBaseline = 'middle';
  const pad = (n, w) => String(n).padStart(w, '0');
  ctx.fillText(`SCORE ${pad(score, 5)}  LEVEL ${pad(level, 2)}  LIVES ${lives}  LEFT ${pad(left, 2)}`, cell * 0.5, cell * 0.5);
}
