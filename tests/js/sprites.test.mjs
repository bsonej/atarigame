// The sprite editor's model (web/spritemodel.js): parsing and writing sprites.txt, validation, undo, mirroring, the
// preview cycles. The real assets/sprites.txt is only ever read here (and only checked to parse).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {
  THIRD,
  ANIMATIONS, BOB_FLOAT, FLOAT, H, SpriteDoc, W, blankRows, checkFrames, counterpartName, flipRows, linePixels, maxLift, parseSprites,
  serializeSprites, toBytes,
} from '../../web/spritemodel.js';
import { api, ROOT } from './helpers.mjs';

const REAL = fs.readFileSync(path.join(ROOT, 'assets/sprites.txt'), 'utf8');
// the tests that rely on the particular art (mirror images, pairs, pixel positions) use a frozen copy, so that
// redrawing the player in the sprite editor never breaks them
const TEXT = fs.readFileSync(path.join(ROOT, 'tests/js/fixtures/sprites.txt'), 'utf8');
const frames = () => parseSprites(TEXT);

test('the real sprites.txt parses into 13 frames of 16 rows of 8', () => {
  const f = parseSprites(REAL);
  assert.equal(f.length, 13);
  assert.deepEqual(f.map((x) => x.name).slice(0, 5), ['stand', 'stand_right', 'stand_left', 'lean_right', 'lean_left']);
  for (const x of f) {
    assert.equal(x.rows.length, H);
    for (const r of x.rows) assert.match(r, /^[#.eo]{8}$/);
  }
  assert.deepEqual(checkFrames(f, f.map((x) => x.name)), []);
});

test('the bytes agree with what the asset tool made (the editor server sends them)', () => {
  const f = parseSprites(REAL);
  assert.equal(api.sprites.length, f.length);
  f.forEach((x, i) => {
    const b = toBytes(x.rows);
    assert.deepEqual(b.body, api.sprites[i].rows, x.name);
    assert.deepEqual(b.eyes, api.sprites[i].eyes, x.name);
    assert.deepEqual(b.third, api.sprites[i].third, x.name);
  });
});

test('writing the frames back gives the identical file, header and all', () => {
  assert.equal(serializeSprites(TEXT, frames()), TEXT);
});

test('a changed pixel changes one line only', () => {
  const f = frames();
  f[3].rows[4] = '########';
  const out = serializeSprites(TEXT, f);
  const a = TEXT.split('\n');
  const b = out.split('\n');
  assert.equal(a.length, b.length);
  const diff = a.map((l, i) => i).filter((i) => a[i] !== b[i]);
  assert.equal(diff.length, 1);
  assert.equal(b[diff[0]], '########');
  assert.deepEqual(parseSprites(out)[3].rows[4], '########');
  assert.equal(out.split('\n').filter((l) => l.startsWith('# ')).length, a.filter((l) => l.startsWith('# ')).length);
});

test('writing keeps a file that has no final newline the way it was', () => {
  const t = TEXT.replace(/\n$/, '');
  assert.equal(serializeSprites(t, parseSprites(t)), t);
});

test('parsing refuses what build_assets refuses', () => {
  const one = (extra) => `frame a\n${blankRows().join('\n')}\n${extra}`;
  assert.throws(() => parseSprites(''), /no frames/);
  assert.throws(() => parseSprites('frame a\n........\n'), /1 rows, needs 16/);
  assert.throws(() => parseSprites(one('..####.')), /8 characters/);
  assert.throws(() => parseSprites(one('..##?###')), /8 characters/);
  assert.throws(() => parseSprites('........\nframe a\n'), /before any 'frame'/);
  assert.equal(parseSprites(one('# a comment\n#\n')).length, 1);
  assert.equal(parseSprites(one('')).length, 1);
});

test('checkFrames: count, names, order, rows and the first frame', () => {
  const f = frames();
  const names = f.map((x) => x.name);
  const bad = (edit, re, withNames = true) => {
    const g = f.map((x) => ({ name: x.name, rows: x.rows.slice() }));
    const r = edit(g);
    const out = Array.isArray(r) ? r : g;
    const errors = checkFrames(out, withNames ? names : null);
    assert.ok(errors.length, `expected an error matching ${re}`);
    assert.match(errors[0], re);
  };
  bad((g) => g.slice(1), /12 frames but the game has 13/);
  bad((g) => [...g, g[0]], /14 frames but the game has 13/);
  bad((g) => (g[2].name = 'x_left'), /renamed or reordered/);
  bad((g) => [g[1], g[0], ...g.slice(2)], /renamed or reordered/);
  bad((g) => g[1].rows.pop(), /15 rows, needs 16/);
  bad((g) => (g[1].rows[3] = '..##'), /frame stand_right row 3/);
  bad((g) => (g[1].rows[3] = '..##x###'), /frame stand_right row 3/);
  bad((g) => (g[0].name = '9bad'), /usable name/, false);
  assert.deepEqual(checkFrames(f, null), []);
  assert.deepEqual(checkFrames('no'), ['frames must be a list']);
  assert.throws(() => serializeSprites(TEXT, f.slice(1)), /12 frames/);
});

test('flipping and the counterpart frames', () => {
  assert.deepEqual(flipRows(['#.e.....', '.......#']), ['.....e.#', '#.......']);
  assert.equal(counterpartName('stand_right'), 'stand_left');
  assert.equal(counterpartName('lean_left'), 'lean_right');
  assert.equal(counterpartName('stretch'), null);
  const f = frames();
  // the shipped frames already are mirror images of each other, which is what the helper is for
  const byName = Object.fromEntries(f.map((x) => [x.name, x]));
  assert.deepEqual(flipRows(byName.stand_right.rows), byName.stand_left.rows);
  assert.deepEqual(flipRows(byName.squash_right.rows), byName.squash_left.rows);
  assert.deepEqual(flipRows(byName.stretch_right.rows), byName.stretch_left.rows);
});

test('linePixels covers every cell of a fast drag', () => {
  assert.deepEqual(linePixels(1, 1, 1, 1), [[1, 1]]);
  assert.deepEqual(linePixels(0, 0, 3, 0), [[0, 0], [1, 0], [2, 0], [3, 0]]);
  const diag = linePixels(0, 0, 3, 7);
  assert.deepEqual(diag[0], [0, 0]);
  assert.deepEqual(diag[diag.length - 1], [3, 7]);
  assert.equal(diag.length, 8);
  for (let i = 1; i < diag.length; i++) assert.ok(Math.abs(diag[i][0] - diag[i - 1][0]) <= 1 && Math.abs(diag[i][1] - diag[i - 1][1]) === 1);
  assert.deepEqual(linePixels(3, 0, 0, 0).map((p) => p[0]), [3, 2, 1, 0]);
});

test('painting: a stroke is one undo step, redo brings it back', () => {
  let changes = 0;
  const doc = new SpriteDoc(frames(), () => changes++);
  const before = doc.rows(1).slice();
  doc.beginStroke();
  assert.ok(doc.setPixel(1, 0, 0, '#'));
  assert.ok(doc.line(1, 0, 0, 0, 5, 'e'));
  assert.ok(!doc.setPixel(1, 0, 0, 'e'), 'no change when the pixel already has it');
  doc.endStroke();
  assert.equal(doc.get(1, 0, 3), 'e');
  assert.ok(doc.dirty(1) && doc.dirty() && !doc.dirty(2));
  assert.ok(doc.canUndo && !doc.canRedo);
  assert.ok(doc.undo());
  assert.deepEqual(doc.rows(1), before);
  assert.ok(!doc.dirty());
  assert.ok(!doc.canUndo && doc.canRedo);
  assert.ok(doc.redo());
  assert.equal(doc.get(1, 0, 3), 'e');
  assert.ok(!doc.redo());
  assert.ok(changes > 0);
});

test('a stroke that changes nothing leaves no undo step; a new edit clears redo', () => {
  const doc = new SpriteDoc(frames());
  doc.beginStroke();
  doc.setPixel(0, 3, 3, doc.get(0, 3, 3));
  doc.endStroke();
  assert.ok(!doc.canUndo);
  doc.setPixel(0, 0, 0, '#');
  doc.undo();
  assert.ok(doc.canRedo);
  doc.setPixel(0, 1, 0, '#');
  assert.ok(!doc.canRedo);
});

test('pixels outside the frame or with a bad character are ignored', () => {
  const doc = new SpriteDoc(frames());
  for (const [x, y, c] of [[-1, 0, '#'], [W, 0, '#'], [0, -1, '#'], [0, H, '#'], [0, 0, 'x'], [0, 0, '']]) assert.ok(!doc.setPixel(0, x, y, c));
  assert.ok(!doc.dirty());
});

test('copy, paste, clear, flip, shift, revert', () => {
  const doc = new SpriteDoc(frames());
  const f5 = doc.rows(5).slice();
  assert.ok(!doc.paste(0), 'nothing copied yet');
  doc.copy(5);
  assert.ok(doc.paste(0));
  assert.deepEqual(doc.rows(0), f5);
  doc.copy(5);
  doc.setPixel(5, 0, 15, '#'); // the clipboard is a copy, not a view
  assert.deepEqual(doc.rows(0), f5);
  assert.ok(doc.revert(0));
  assert.deepEqual(doc.rows(0), frames()[0].rows);
  assert.ok(doc.clear(2));
  assert.deepEqual(doc.rows(2), blankRows());
  assert.ok(!doc.clear(2), 'already empty');
  doc.undo();
  assert.deepEqual(doc.rows(2), frames()[2].rows);
  assert.ok(doc.flip(3));
  assert.deepEqual(doc.rows(3), flipRows(frames()[3].rows));
  doc.undo();
  doc.reset(frames());
  assert.ok(doc.shift(0, 1, 0));
  assert.equal(doc.rows(0)[7], `.${frames()[0].rows[7].slice(0, 7)}`);
  doc.undo();
  assert.ok(doc.shift(0, 0, 1));
  assert.equal(doc.rows(0)[0], '........');
  assert.equal(doc.rows(0)[1], frames()[0].rows[0]);
  assert.equal(doc.rows(0).length, H);
});

test('mirroring a frame overwrites its other side and can be undone', () => {
  const doc = new SpriteDoc(frames());
  const i = doc.frames.findIndex((f) => f.name === 'lean_right');
  const j = doc.frames.findIndex((f) => f.name === 'lean_left');
  doc.setPixel(i, 7, 0, '#');
  assert.equal(doc.counterpart(i), j);
  assert.equal(doc.mirrorToCounterpart(i), j);
  assert.deepEqual(doc.rows(j), flipRows(doc.rows(i)));
  assert.ok(doc.dirty(j));
  doc.undo();
  assert.deepEqual(doc.rows(j), frames()[j].rows);
  const stretch = doc.frames.findIndex((f) => f.name === 'stretch');
  assert.equal(doc.counterpart(stretch), -1);
  assert.equal(doc.mirrorToCounterpart(stretch), -1);
});

test('saved, restored and reset', () => {
  const doc = new SpriteDoc(frames());
  doc.setPixel(0, 0, 0, '#');
  doc.markSaved();
  assert.ok(!doc.dirty());
  assert.ok(doc.canUndo, 'undo still reaches back past a save');
  doc.undo();
  assert.ok(doc.dirty(0), 'undoing past a save makes it unsaved again');
  doc.restore(frames().map((f, k) => (k === 4 ? { name: f.name, rows: blankRows() } : f)));
  assert.ok(doc.dirty(4));
  assert.ok(!doc.canUndo);
  doc.reset(frames());
  assert.ok(!doc.dirty());
  assert.deepEqual(doc.problems(frames().map((f) => f.name)), []);
  doc.clear(0);
  assert.deepEqual(doc.problems(), [], 'a blank frame is allowed');
});

test('the preview cycles only use frames the file has, and the jump comes back to the ground', () => {
  const names = new Set(frames().map((f) => f.name));
  for (const a of ANIMATIONS) {
    assert.ok(a.ticks.length > 0, a.id);
    for (const t of a.ticks) {
      assert.ok(names.has(t.name), `${a.id} uses ${t.name}`);
      assert.ok(t.lift >= 0);
    }
  }
  const jump = ANIMATIONS.find((a) => a.id === 'jump');
  assert.equal(maxLift(jump), 26, 'the jump table rises 3*5+2*4+1*3 pixels');
  assert.equal(jump.ticks[0].name, 'squash');
  assert.equal(jump.ticks[3].name, 'stretch');
  assert.equal(jump.ticks.at(-1).lift, 0);
  const walk = ANIMATIONS.find((a) => a.id === 'walk_left');
  assert.deepEqual([...new Set(walk.ticks.map((t) => t.name))], ['stand_left', 'lean_left']);
  const right = ANIMATIONS.find((a) => a.id === 'jump_right');
  assert.ok(right.ticks.every((t) => t.name.endsWith('_right')));
});

test('he floats one or two pixels above the surface', () => {
  assert.ok(FLOAT >= 1 && FLOAT <= 2);
});

test('the bob stays within 1 to 3 lines above the surface and agrees with the table in main.s', () => {
  assert.equal(BOB_FLOAT.length, 64);
  assert.equal(Math.min(...BOB_FLOAT), 1);
  assert.equal(Math.max(...BOB_FLOAT), 3);
  assert.ok(BOB_FLOAT.every((v, i) => Math.abs(v - BOB_FLOAT[(i + 1) % 64]) <= 1), 'one line at a time');
  const asm = fs.readFileSync(path.join(ROOT, 'src/main.s'), 'utf8');
  const body = /^bob_float:\n((?:\s+\.byte [\d,]+\n)+)/m.exec(asm)[1];
  assert.deepEqual([...body.matchAll(/\d+/g)].map((m) => Number(m[0])), [...BOB_FLOAT]);
});

test('the third colour is free: any single pixel can be o, painted and erased one at a time', () => {
  const f = frames();
  f[1].rows[3] = '.o.o.o.o';
  assert.deepEqual(checkFrames(f, f.map((x) => x.name)), []);
  // bytes: column c is bit 2*(c>>1) + 1 - (c&1): M0 bits 1-0 ... M3 bits 7-6, high bit on the left
  const rows = ['o.......', '.o......', '..o.....', '......o.', '.......o', 'oooooooo', 'oo......'].concat(Array(9).fill('........'));
  assert.deepEqual(toBytes(rows).third.slice(0, 7), [0x02, 0x01, 0x08, 0x80, 0x40, 0xff, 0x03]);
  const doc = new SpriteDoc(frames());
  doc.setPixel(0, 3, 0, THIRD); // painting one pixel paints just that pixel
  assert.equal(doc.get(0, 3, 0), THIRD);
  assert.equal(doc.get(0, 2, 0), '#', 'the neighbour is untouched');
  doc.setPixel(0, 2, 0, '#'); // body next to it: nothing else changes
  assert.equal(doc.get(0, 3, 0), THIRD);
  doc.setPixel(0, 3, 0, '.'); // erasing one pixel erases just that one
  assert.equal(doc.get(0, 3, 0), '.');
  assert.deepEqual(checkFrames(doc.frames, doc.frames.map((x) => x.name)), []);
});

test('nudging sideways moves all three layers a pixel', () => {
  const doc = new SpriteDoc(frames());
  assert.equal(doc.rows(0)[4], 'eeooooee');
  assert.ok(doc.shift(0, 1, 0));
  assert.equal(doc.rows(0)[4], '.eeooooe', 'the eyes and the pupils all moved one pixel');
  assert.deepEqual(checkFrames(doc.frames, doc.frames.map((x) => x.name)), []);
});
