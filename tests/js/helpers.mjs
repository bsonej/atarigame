// Shared by the node tests: the tile tables as the editor server would send them, and little levels to play.
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { makeTables, compileLevel, blankRows, COLS, ROWS } from '../../web/model.js';
import { Game, MODE } from '../../web/engine.js';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
export const api = JSON.parse(execFileSync('python3', [path.join(ROOT, 'tools/editor_server.py'), '--dump-tiles'], { cwd: ROOT, encoding: 'utf8' }));
export const tables = makeTables(api);

/** A room: brick walls and floor (the floor is row 23), then `edit` can change rows. Player stands at column 2. */
export function room(edit = {}) {
  const rows = blankRows().map((r) => r.split(''));
  for (let r = 1; r < ROWS - 1; r++) for (let c = 1; c < COLS - 1; c++) rows[r][c] = '.';
  rows[21][2] = '@';
  for (const [key, line] of Object.entries(edit)) {
    const [r, c0] = key.split(',').map(Number);
    [...line].forEach((ch, i) => (rows[r][c0 + i] = ch));
  }
  // an item far away so that the level is never cleared by accident
  rows[1][38] = '*';
  return rows.map((r) => r.join(''));
}

/** A game in PLAY mode on a level given as rows. */
export function play(rows, opts = {}) {
  const compiled = compileLevel(rows, tables);
  if (compiled.errors.length) throw new Error(compiled.errors.map((e) => e.msg).join('; '));
  const g = new Game(compiled, tables, opts);
  g.mode = MODE.PLAY;
  return g;
}

export const run = (g, frames, joy = 0) => {
  for (let i = 0; i < frames; i++) g.step(joy);
};

/** Edit entries for a vertical run of `ch` in column `c`, rows r0..r1. */
export const vertical = (r0, r1, c, ch) => Object.fromEntries(Array.from({ length: r1 - r0 + 1 }, (_, i) => [`${r0 + i},${c}`, ch]));
