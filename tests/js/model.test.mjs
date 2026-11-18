// web/model.js and web/palette.js. Run with: node --test tests/js
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { applyCaps, parseLevelText, compileLevel, serializeLevel, titleOf, blankRows, COLS, ROWS } from '../../web/model.js';
import { GROUPS, STAMPS, offeredTiles } from '../../web/palette.js';
import { api, tables, ROOT, room } from './helpers.mjs';

const T = tables.T;

test('every tile with a map character can be placed from the palette (except the empty tile)', () => {
  const offered = offeredTiles();
  const missing = api.tiles.filter((t) => t.char && !t.family && t.name !== 'EMPTY' && !offered.has(t.name)).map((t) => t.name);
  assert.deepEqual(missing, []);
});

test('the palette only names tiles that exist, and every stamp fits on the board', () => {
  const names = new Set(api.tiles.map((t) => t.name));
  for (const n of offeredTiles()) assert.ok(n === 'PEG' || names.has(n), n);
  for (const s of STAMPS) {
    const w = Math.max(...s.cells.map((c) => c[0])) + 1;
    const h = Math.max(...s.cells.map((c) => c[1])) + 1;
    assert.ok(w <= COLS && h <= ROWS - 1, s.label);
  }
  assert.ok(GROUPS.length >= 5);
});

test('end caps appear where a platform meets something else', () => {
  const map = applyCaps([...Array(40).fill(0)].map((_, i) => (i >= 3 && i <= 6 ? T.BRICK : i === 9 ? T.BRICK : 0)), tables.caps);
  const caps = tables.caps[T.BRICK];
  assert.equal(map[3], caps.L);
  assert.equal(map[4], T.BRICK);
  assert.equal(map[6], caps.R);
  assert.equal(map[9], caps.LR);
});

test('a block touching the screen edge keeps a plain edge', () => {
  const row = Array(40).fill(0);
  row[0] = row[1] = T.BRICK;
  const out = applyCaps(row, tables.caps);
  assert.equal(out[0], T.BRICK);
  assert.equal(out[1], tables.caps[T.BRICK].R);
});

test('caps never change what the game thinks a tile is', () => {
  for (const [fam, v] of Object.entries(tables.caps)) for (const b of Object.values(v)) assert.equal(tables.canon[b], Number(fam));
});

test('compiling reports problems without throwing', () => {
  const rows = room();
  rows[5] = rows[5].replace('.', '?');
  const c = compileLevel(rows, tables);
  assert.ok(c.errors.some((e) => /unknown character '\?' at row 5/.test(e.msg)));
  const none = compileLevel(room().map((r) => r.replace('@', '.')), tables);
  assert.ok(none.errors.some((e) => /no '@'/.test(e.msg)));
  const two = room();
  two[3] = '#' + '@' + two[3].slice(2);
  assert.ok(compileLevel(two, tables).errors.some((e) => /more than one/.test(e.msg)));
  const noItems = compileLevel(room().map((r) => r.replace('*', '.')), tables);
  assert.ok(noItems.errors.some((e) => /no items/.test(e.msg)));
});

test('a peg needs a block under it that is at least two wide', () => {
  assert.ok(compileLevel(room({ '10,5': 'p' }), tables).errors.some((e) => /needs a solid block/.test(e.msg)));
  assert.ok(compileLevel(room({ '10,5': 'p', '11,5': '#' }), tables).errors.some((e) => /only one tile wide/.test(e.msg)));
  const ok = compileLevel(room({ '10,5': 'p', '11,4': '######' }), tables);
  assert.deepEqual(ok.errors, []);
  assert.deepEqual(ok.pegs, [[16, 80, 16, 36, 1]]);
});

test('a level file survives parse and serialise', () => {
  const rows = room({ '10,5': '=====' });
  const text = serializeLevel(rows, 'level7', 'Test Title');
  const parsed = parseLevelText(text);
  assert.deepEqual(parsed.errors, []);
  assert.deepEqual(parsed.rows, rows);
  assert.equal(titleOf(parsed.header), 'Test Title');
  assert.equal(titleOf(parseLevelText(serializeLevel(rows, 'level7', '')).header), '');
});

test('every shipped level parses and compiles cleanly', () => {
  const dir = path.join(ROOT, 'assets/levels');
  for (const f of readdirSync(dir).filter((n) => n.endsWith('.txt'))) {
    const parsed = parseLevelText(readFileSync(path.join(dir, f), 'utf8'));
    assert.deepEqual(parsed.errors, [], f);
    const c = compileLevel(parsed.rows, tables);
    assert.deepEqual(c.errors, [], f);
  }
});

test('the new-level template is a valid level', () => {
  const c = compileLevel(blankRows().map((r) => r), tables);
  // it has a start but no items yet: that is the one thing a new level still needs
  assert.deepEqual(c.errors.map((e) => e.msg), ["no items ('*') to collect"]);
  assert.ok(c.spawn);
});
