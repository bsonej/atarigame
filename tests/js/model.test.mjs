// web/model.js and web/palette.js. Run with: node --test tests/js
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { applyCaps, applyTwins, parseLevelText, compileLevel, serializeLevel, titleOf, blankRows, COLS, ROWS } from '../../web/model.js';
import { GROUPS, STAMPS, offeredTiles } from '../../web/palette.js';
import { Atlas, chuteFrame } from '../../web/render.js';
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

test('a peg sweeps the whole platform: tiles of every kind count, only a solid in its own row ends it', () => {
  // brick, belts, a spike, a step, ice, a one-way platform, a ladder, a chute, then brick again: one platform
  const run = room({ '10,5': 'p', '11,4': '#>(^S~=H\\#' });
  const ok = compileLevel(run, tables);
  assert.deepEqual(ok.errors, []);
  assert.deepEqual(ok.pegs, [[16, 80, 16, 52, 1]], 'columns 4-13');
  // the same, with the marker nearer the right end: it starts there going left
  assert.deepEqual(compileLevel(room({ '10,12': 'p', '11,4': '#>(^S~=H\\#' }), tables).pegs, [[52, 80, 16, 52, 255]]);
  // a solid in the peg's own row (a wall) ends the run; items, doors and gaps end it too
  assert.deepEqual(compileLevel(room({ '10,5': 'p', '10,9': 'W', '11,4': '#>(^S~=H\\#' }), tables).pegs, [[16, 80, 16, 32, 1]]);
  assert.deepEqual(compileLevel(room({ '10,5': 'p', '11,4': '##*#####' }), tables).pegs, [[20, 80, 16, 20, 255]]);
  // things standing on the platform that are not solid (a step, a spike, a ladder) do not end it
  assert.deepEqual(compileLevel(room({ '10,5': 'p', '10,7': 'S^H', '11,4': '########' }), tables).pegs, [[16, 80, 16, 44, 1]]);
});

test('a peg needs a block under it that is at least two wide', () => {
  assert.ok(compileLevel(room({ '10,5': 'p' }), tables).errors.some((e) => /needs a platform tile/.test(e.msg)));
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


test('dots go in every second middle tile of a run, never on an end cap, and are counted with the items', () => {
  const T = tables.T;
  const c = compileLevel(room({ '10,3': '###########' }), tables); // a run of 11 in columns 3-13
  assert.deepEqual([4, 5, 6, 7, 8, 9, 10, 11, 12].map((col) => c.map[10 * 40 + col] === T.BRICK_DOT), [true, false, true, false, true, false, true, false, true]);
  assert.equal(c.map[10 * 40 + 3], tables.caps[T.BRICK].L);
  assert.equal(c.map[10 * 40 + 13], tables.caps[T.BRICK].R);
  assert.equal(c.dots, 5);
  assert.equal(c.items, c.stars + c.dots, 'everything to collect is one number');
});

test('a platform with only ends has no dot, and a tile without headroom gets none', () => {
  const T = tables.T;
  const c = compileLevel(room({ '10,3': '##', '14,3': '#######', '13,6': 'W' }), tables);
  assert.ok(![3, 4].some((col) => c.map[10 * 40 + col] === T.BRICK_DOT));
  // the platform in columns 3-9 of row 14 would have dots at 4, 6, 8; the wall tile above column 6 blocks that one
  assert.deepEqual([4, 6, 8].map((col) => c.map[14 * 40 + col] === T.BRICK_DOT), [true, false, true]);
});

test('no dot goes where the player would have to stand in spikes to eat it', () => {
  const T = tables.T;
  const c = compileLevel(room({ '14,3': '#######', '13,6': '^' }), tables);
  assert.deepEqual([4, 6, 8].map((col) => c.map[14 * 40 + col] === T.BRICK_DOT), [true, false, true]);
});

test('every level needs an exit door with room above it and beside it', () => {
  const noDoor = room().map((r) => r.replace('D', '.'));
  assert.ok(compileLevel(noDoor, tables).errors.some((e) => e.msg.includes('no exit door')));
  for (const [key, ch] of [['21,37', 'W'], ['20,38', '*'], ['22,38', 'W']]) {
    const blocked = room({ [key]: ch });
    assert.ok(compileLevel(blocked, tables).errors.some((e) => e.msg.includes('needs an empty space')), key);
  }
  const ok = compileLevel(room(), tables);
  assert.deepEqual(ok.errors, []);
  assert.deepEqual(ok.doors, [[37, 22]]);
});

test('the palette from the server drives the row colours (assets/palette.txt)', () => {
  assert.equal(tables.palette.hues.length, 8);
  for (const k of ['grey', 'white', 'ice', 'hud', 'background']) assert.equal(typeof tables.palette[k], 'number', k);
});

// ---- the chutes' screw thread -----------------------------------------------------------------------------------

const thread = (name) => [...tables.byByte[T[name]].rows, ...tables.byByte[T[`${name}_B`]].rows];
const asRows = (frame) => [...frame[0], ...frame[1]];

test('a chute and its twin: the twin goes on odd rows only and the game sees a plain chute', () => {
  assert.equal(tables.twins[T.SLIDE_R], T.SLIDE_R_B);
  assert.equal(tables.twins[T.SLIDE_L], T.SLIDE_L_B);
  for (const [plain, twin] of Object.entries(tables.twins)) assert.equal(tables.canon[twin], Number(plain));
  const data = Array(COLS * ROWS).fill(0);
  for (let r = 4; r < 12; r++) data[r * COLS + 7] = T.SLIDE_R;
  data[5 * COLS + 8] = T.BRICK;
  const out = applyTwins(data, tables.twins);
  assert.deepEqual([4, 5, 6, 7, 8, 9, 10, 11].map((r) => out[r * COLS + 7]), [T.SLIDE_R, T.SLIDE_R_B, T.SLIDE_R, T.SLIDE_R_B, T.SLIDE_R, T.SLIDE_R_B, T.SLIDE_R, T.SLIDE_R_B]);
  assert.equal(out[5 * COLS + 8], T.BRICK);
  assert.equal(data[5 * COLS + 7], T.SLIDE_R, 'the input is left alone');
});

test('a level compiles with the twins in: stacks alternate', () => {
  const rows = room({ '10,10': '\\', '11,11': '\\', '12,12': '\\', '13,13': '\\', '14,25': '/', '15,25': '/', '16,25': '/' });
  const c = compileLevel(rows, tables);
  const at = (r, col) => c.map[r * COLS + col];
  assert.deepEqual([at(10, 10), at(11, 11), at(12, 12), at(13, 13)], [T.SLIDE_R, T.SLIDE_R_B, T.SLIDE_R, T.SLIDE_R_B]);
  assert.deepEqual([at(14, 25), at(15, 25), at(16, 25)], [T.SLIDE_L, T.SLIDE_L_B, T.SLIDE_L]);
});

test('the thread of each chute lines up from tile to tile, and the left one is the right one mirrored', () => {
  const R = thread('SLIDE_R').map((r) => [...r].map(Number));
  const L = thread('SLIDE_L').map((r) => [...r].map(Number));
  for (let y = 0; y < 16; y++) {
    assert.deepEqual(L[y], [...R[y]].reverse());
    for (let x = 0; x < 3; x++) {
      assert.equal(R[(y + 4) % 16][x], R[y][x + 1], `right, row ${y}`);
      assert.equal(L[(y + 4) % 16][x + 1], L[y][x], `left, row ${y}`);
    }
  }
});

test('chuteFrame: the down thread moves a row down every second frame and comes round in 32 frames; the up one goes up', () => {
  const h = thread('SLIDE_R');
  for (let t = 0; t < 64; t += 2) {
    const now = asRows(chuteFrame(h, t));
    assert.deepEqual(asRows(chuteFrame(h, t + 1)), now, 'odd frames change nothing');
    assert.deepEqual(asRows(chuteFrame(h, t + 2)).slice(1), now.slice(0, -1), 'everything moves down by one row');
    assert.deepEqual(asRows(chuteFrame(h, t + 32)), now);
    assert.deepEqual(asRows(chuteFrame(h, t + 2, true)).slice(0, -1), asRows(chuteFrame(h, t, true)).slice(1), 'the up chute: everything moves up by one row');
    assert.deepEqual(asRows(chuteFrame(h, t + 32, true)), asRows(chuteFrame(h, t, true)));
  }
});

test('the editor draws the thread the way the game does (same rows at the same frame), and nothing else moves', () => {
  const saved = globalThis.document;
  globalThis.document = { createElement: () => ({ getContext: () => ({ set fillStyle(v) {}, fillRect() {} }), width: 0, height: 0 }) };
  try {
    const atlas = new Atlas(api);
    const brick = atlas.rows[T.BRICK];
    for (const tick of [0, 1, 2, 7, 30, 31, 46, 63, 64]) {
      atlas.animateBelts(tick);
      for (const name of ['SLIDE_R', 'SLIDE_L']) {
        const want = chuteFrame(thread(name), tick, name === 'SLIDE_L');
        assert.deepEqual(atlas.rows[T[name]], want[0], `${name} at ${tick}`);
        assert.deepEqual(atlas.rows[T[`${name}_B`]], want[1], `${name}_B at ${tick}`);
      }
      assert.equal(atlas.rows[T.BRICK], brick);
    }
  } finally {
    globalThis.document = saved;
  }
});

test('the palette offers the chutes and the ready-made runs, and not the twins', () => {
  const offered = offeredTiles();
  assert.ok(offered.has('SLIDE_R') && offered.has('SLIDE_L'));
  assert.ok(!offered.has('SLIDE_R_B') && !offered.has('SLIDE_L_B'));
  for (const label of ['Chute down', 'Chute up']) assert.ok(STAMPS.some((s) => s.label === label), label);
});
