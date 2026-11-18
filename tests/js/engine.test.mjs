// Quick rule checks on web/engine.js, without the emulator. (tests/test_engine.py is the real proof: it plays the same
// input on the 6502 code and on this engine and compares them.) Run with: node --test tests/js
import test from 'node:test';
import assert from 'node:assert/strict';
import { JOY, MODE, STATE } from '../../web/engine.js';
import { room, play, run, tables, vertical } from './helpers.mjs';

const T = tables.T;
const FLOOR_Y = 168;

test('a level begins with the come-to-life animation, then play', () => {
  const g = play(room());
  g.mode = MODE.SPAWN;
  g.beginLevel();
  run(g, 47);
  assert.equal(g.mode, MODE.SPAWN);
  run(g, 1);
  assert.equal(g.mode, MODE.PLAY);
});

test('standing on the floor stays put; walking moves one pixel a frame', () => {
  const g = play(room());
  run(g, 10);
  assert.deepEqual([g.px, g.py, g.state], [8, FLOOR_Y, STATE.GROUND]);
  run(g, 20, JOY.RIGHT);
  assert.equal(g.px, 28);
  run(g, 5, JOY.LEFT);
  assert.equal(g.px, 23);
});

test('walls stop you', () => {
  const g = play(room({ '21,12': '#', '22,12': '#' }));
  run(g, 100, JOY.RIGHT);
  assert.equal(g.px, 12 * 4 - 4);
});

test('a jump rises 18 pixels and lands again', () => {
  const g = play(room());
  g.step(JOY.FIRE);
  let top = g.py;
  for (let i = 0; i < 60; i++) {
    g.step(0);
    top = Math.min(top, g.py);
  }
  assert.equal(FLOOR_Y - top, 18);
  assert.deepEqual([g.py, g.state], [FLOOR_Y, STATE.GROUND]);
});

test('holding fire does not jump again until it is pressed afresh', () => {
  const g = play(room());
  run(g, 80, JOY.FIRE);
  assert.equal(g.py, FLOOR_Y);
  g.step(0);
  g.step(JOY.FIRE);
  assert.equal(g.state, STATE.AIR);
});

test('falling too far is fatal, a short drop is not', () => {
  const g = play(room({ '8,2': '###' }));
  g.px = 8;
  g.py = 8 * 8 - 16; // standing on the little ledge, 120 pixels up
  run(g, 5);
  run(g, 20, JOY.RIGHT); // walk off
  run(g, 120);
  assert.equal(g.mode, MODE.DYING, 'fell about 100 pixels');
  const h = play(room({ '19,2': '###' }));
  h.px = 8;
  h.py = 19 * 8 - 16; // 3 tiles up
  run(h, 5);
  run(h, 20, JOY.RIGHT);
  run(h, 60);
  assert.equal(h.mode, MODE.PLAY);
  assert.equal(h.py, FLOOR_Y);
});

test('items score ten points', () => {
  const g = play(room({ '22,3': '**' }));
  assert.equal(g.left, 3);
  run(g, 30, JOY.RIGHT);
  assert.equal(g.score, 20);
  assert.equal(g.left, 1);
});

test('the last thing collected opens the door; walking into the open door clears the level with a bonus', () => {
  const h = play(room({ '22,3': '*' }));
  const T = tables.T;
  const doorCells = () => [h.map[22 * 40 + 37], h.map[21 * 40 + 37]];
  assert.deepEqual(doorCells(), [T.DOOR, T.DOOR_TOP], 'the top half comes from the compiler');
  h.left = 1;
  h.map[1 * 40 + 38] = T.EMPTY;
  run(h, 10, JOY.RIGHT);
  assert.equal(h.left, 0);
  assert.equal(h.mode, MODE.PLAY, 'collecting everything does not end the level by itself');
  assert.equal(h.score, 10);
  assert.deepEqual(doorCells(), [T.DOOR_OPEN, T.DOOR_OPEN_TOP]);
  assert.ok(h.events.includes('opened'));
  run(h, 200, JOY.RIGHT);
  assert.equal(h.mode, MODE.CLEAR);
  assert.equal(h.score, 110);
});

test('a closed door is walked through harmlessly', () => {
  const g = play(room());
  run(g, 200, JOY.RIGHT);
  assert.equal(g.mode, MODE.PLAY);
  assert.ok(g.px > 37 * 4 - 4, 'went past the door');
});

test('walking over a dot eats it: a point, one less to collect, and the plain tile stays', () => {
  const T = tables.T;
  const g = play(room({ '23,5': '#######' })); // seven platform tiles: end cap, then dots at columns 6, 8 and 10
  const dotted = [6, 8, 10];
  for (const c of dotted) assert.equal(g.map[23 * 40 + c], T.BRICK_DOT, `a dot at column ${c}`);
  g.px = 6 * 4;
  g.py = 23 * 8 - 16; // feet on the platform row
  const left = g.left;
  run(g, 1);
  assert.equal(g.state, 0);
  assert.equal(g.map[23 * 40 + 6], T.BRICK, 'the dot is gone');
  assert.equal(g.score, 1);
  assert.equal(g.left, left - 1);
  run(g, 30, JOY.RIGHT);
  assert.equal(g.score, 3, 'two more dots on the way along');
  assert.deepEqual(dotted.map((c) => g.map[23 * 40 + c]), [T.BRICK, T.BRICK, T.BRICK]);
  assert.ok(g.events.filter((e) => e === 'dot').length === 3);
});

test('jumping over a dot leaves it: only the feet on the tile eat', () => {
  const T = tables.T;
  const g = play(room({ '23,5': '#######' }));
  g.px = 5 * 4;
  g.py = 23 * 8 - 16;
  run(g, 2);
  g.joy = 0;
  run(g, 1, JOY.RIGHT | JOY.FIRE); // jump
  assert.equal(g.state, 1);
  const score = g.score;
  run(g, 4, JOY.RIGHT); // still rising over the dot at column 6
  assert.equal(g.score, score);
  assert.equal(g.map[23 * 40 + 6], T.BRICK_DOT);
});

test('spikes kill, and the death animation ends in a new life', () => {
  const g = play(room({ '22,10': '^' }));
  run(g, 60, JOY.RIGHT);
  assert.equal(g.mode, MODE.DYING);
  run(g, 80);
  assert.equal(g.mode, MODE.SPAWN);
  assert.equal(g.lives, 2);
  assert.deepEqual([g.px, g.py], [8, FLOOR_Y]);
});

test('the last life lost is game over', () => {
  const g = play(room({ '22,10': '^' }), { lives: 1 });
  run(g, 60, JOY.RIGHT);
  run(g, 80);
  assert.equal(g.mode, MODE.OVER);
  assert.ok(g.events.includes('gameover'));
});

test('a belt carries you: normal speed is one pixel a frame', () => {
  const g = play(room({ '23,1': '>'.repeat(38) }));
  g.py = 168 - 8; // on top of the belt row (row 23 is the belt now)
  g.py = FLOOR_Y;
  run(g, 2);
  const x0 = g.px;
  run(g, 20);
  assert.equal(g.px - x0, 20, 'drifts right with no input');
  run(g, 20, JOY.LEFT);
  assert.equal(g.px - x0, 20, 'walking left at the same speed stands still');
});

test('ice: you speed up slowly and slide after letting go', () => {
  const g = play(room({ '23,1': '~'.repeat(38) }));
  run(g, 30, JOY.RIGHT);
  const x = g.px;
  assert.ok(g.vx > 0 && g.vx <= 20);
  run(g, 30);
  assert.ok(g.px > x + 10, 'kept sliding');
  run(g, 200);
  assert.equal(g.vx, 0);
});

test('a vanishing block goes after half a second and comes back later', () => {
  const g = play(room({ '23,5': 'vvvv' }));
  g.px = 6 * 4;
  run(g, 1);
  const cell = 23 * 40 + 6;
  assert.equal(g.map[cell] !== T.EMPTY, true);
  run(g, 29);
  assert.equal(g.map[cell], T.EMPTY, 'gone after 30 frames');
  run(g, 30, JOY.LEFT); // it will not come back while you are in it
  run(g, 200);
  assert.notEqual(g.map[cell], T.EMPTY, 'back again');
});

test('a bomb block blows after 45 frames and sets off its neighbours', () => {
  const g = play(room({ '23,5': 'XXX' }));
  g.px = 30 * 4; // well out of the way
  g.py = FLOOR_Y;
  g.armCell(6, 23, 0, 45, g.map[23 * 40 + 6]);
  run(g, 44);
  assert.notEqual(g.map[23 * 40 + 6], T.EMPTY);
  run(g, 1);
  assert.equal(g.map[23 * 40 + 6], T.BOOM, 'blast');
  run(g, 12);
  assert.equal(g.map[23 * 40 + 5], T.BOOM, 'the neighbours went off a little after');
  assert.equal(g.map[23 * 40 + 7], T.BOOM);
  run(g, 20);
  assert.deepEqual([5, 6, 7].map((c) => g.map[23 * 40 + c]), [0, 0, 0]);
  assert.equal(g.mode, MODE.PLAY);
});

test('standing on a bomb block when it goes off is fatal', () => {
  const g = play(room({ '23,5': 'XX' }));
  g.px = 5 * 4;
  run(g, 44);
  assert.equal(g.mode, MODE.PLAY);
  run(g, 2);
  assert.equal(g.mode, MODE.DYING);
});

test('a ladder is climbed with up and down', () => {
  const g = play(room(vertical(17, 22, 6, 'H')));
  g.px = 6 * 4;
  run(g, 3, JOY.UP);
  assert.equal(g.state, STATE.CLIMB);
  const y = g.py;
  run(g, 10, JOY.UP);
  assert.equal(y - g.py, 10);
  run(g, 10, JOY.DOWN);
  assert.equal(g.py, y);
});

test('a peg pushes you along ahead of it', () => {
  const g = play(room({ '22,3': 'p', '23,3': '######' }));
  assert.equal(g.pegs.length, 1);
  g.px = 5 * 4;
  g.py = FLOOR_Y - 8 - 8;
  g.pegs[0].wait = 0;
  g.pegs[0].dir = 1;
  const peg = g.pegs[0];
  peg.x = 3 * 4;
  const before = g.px;
  run(g, 100);
  assert.ok(g.px > before, 'was carried to the right');
});
