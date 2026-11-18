// Quick rule checks on web/engine.js, without the emulator. (tests/test_engine.py is the real proof: it plays the same
// input on the 6502 code and on this engine and compares them.) Run with: node --test tests/js
import test from 'node:test';
import assert from 'node:assert/strict';
import { JOY, MODE, STATE, FRAME } from '../../web/engine.js';
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

test('the last thing collected makes the exit door fade in; walking into it ends the level and the door fades out', () => {
  const h = play(room({ '22,3': '*' }));
  const T = tables.T;
  const door = () => [22, 21, 20].flatMap((r) => [37, 38].map((c) => h.map[r * 40 + c]));
  assert.deepEqual(door(), [T.DOOR_BL, T.DOOR_BR, T.DOOR_ML, T.DOOR_MR, T.DOOR_TL, T.DOOR_TR], 'the compiler puts all six tiles in');
  assert.deepEqual([h.doorOpen, h.doorPhase], [0, 0], 'nothing to see yet');
  h.left = 1;
  h.map[1 * 40 + 38] = T.EMPTY;
  run(h, 10, JOY.RIGHT);
  assert.equal(h.left, 0);
  assert.equal(h.mode, MODE.PLAY, 'collecting everything does not end the level by itself');
  assert.equal(h.score, 10);
  assert.equal(h.doorOpen, 1);
  assert.ok(h.events.includes('opened'));
  assert.ok(h.doorPhase > 0 && h.doorPhase < 16, 'it is fading in');
  const before = h.doorPhase;
  run(h, 2);
  assert.equal(h.doorPhase, before + 1, 'one step every other frame');
  run(h, 60);
  assert.equal(h.doorPhase, 16, 'fully there');
  while (h.mode === MODE.PLAY) h.step(JOY.RIGHT);
  assert.equal(h.mode, MODE.CLEAR);
  assert.equal(h.score, 110);
  assert.equal(h.drawn, 0, 'he has gone through the door');
  assert.equal(h.doorDir, -1, 'and it fades out behind him');
  run(h, 40);
  assert.equal(h.doorPhase, 0);
  assert.equal(h.doorDir, 0);
});

test('a door that has not appeared yet is walked through harmlessly', () => {
  const g = play(room());
  run(g, 200, JOY.RIGHT);
  assert.equal(g.mode, MODE.PLAY);
  assert.ok(g.px > 37 * 4 - 4, 'went past the door');
});

test('the door fades in evenly: every step shows twelve more of its 192 pixels', () => {
  const f = tables.fade;
  assert.equal(f.length, 192);
  for (let step = 0; step <= 16; step++) assert.equal(f.filter((t) => t < step).length, 12 * step, `step ${step}`);
});

test('you walk straight past steps and chutes, and can jump up onto a step', () => {
  for (const ch of ['S', '\\', '/']) {
    const g = play(room({ '22,10': ch }));
    run(g, 60, JOY.RIGHT);
    assert.ok(g.px > 10 * 4 + 6, `walked past ${ch}`);
    assert.equal(g.py, FLOOR_Y);
  }
  const g = play(room({ '22,10': 'S' }));
  g.px = 10 * 4;
  g.py = FLOOR_Y;
  run(g, 2);
  g.step(JOY.FIRE);
  run(g, 60);
  assert.equal(g.py, FLOOR_Y - 8, 'jumped up through the step and landed on top of it');
  assert.equal(g.state, 0);
  run(g, 30, JOY.RIGHT);
  assert.equal(g.py, FLOOR_Y, 'walked off its end and dropped to the floor');
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
  g.py = FLOOR_Y;
  run(g, 2);
  const x0 = g.px;
  run(g, 20);
  assert.equal(g.px - x0, 20, 'drifts right with no input');
  run(g, 20, JOY.RIGHT);
  assert.equal(g.px - x0, 60, 'walking with the belt: both add up');
});

test('walking against a belt is slowed by it, not stopped', () => {
  const g = play(room({ '23,1': '>'.repeat(38) }));
  g.px = 100;
  run(g, 2);
  const x0 = g.px;
  run(g, 20, JOY.LEFT);
  // a pixel a frame to the left, less 3/8 of the belt's pixel a frame: 20 - 7.5, give or take a pixel
  assert.ok(x0 - g.px >= 12 && x0 - g.px <= 13, `moved ${x0 - g.px} pixels left`);
});

test('you can walk onto a fast belt that is turning against you, in both directions', () => {
  const right = play(room({ '23,10': ')'.repeat(10) })); // fast belt carrying right: walk onto it from its right
  right.px = 90;
  run(right, 260, JOY.LEFT);
  assert.ok(right.px < 10 * 4, `got to ${right.px}, past the belt's left end`);
  const left = play(room({ '23,10': '('.repeat(10) })); // fast belt carrying left: walk onto it from its left
  left.px = 20;
  run(left, 260, JOY.RIGHT);
  assert.ok(left.px > 20 * 4 + 2, `got to ${left.px}, past the belt's right end`);
});

test('a chute is not a belt: it carries you at full speed whatever you do', () => {
  const g = play(room({ '22,10': '\\\\\\\\' }));
  g.px = 11 * 4;
  g.py = 22 * 8 - 16;
  run(g, 2);
  const x0 = g.px;
  run(g, 10, JOY.LEFT);
  assert.ok(g.px >= x0, 'walking against it does not get you anywhere');
});

test('a roller grips harder the longer it is', () => {
  const lens = {};
  for (const n of [1, 2, 4, 6, 8, 12]) {
    const g = play(room({ '23,10': 'o'.repeat(n) }));
    g.px = 10 * 4 + 2;
    run(g, 1);
    lens[n] = g.rollerLen();
    run(g, 1, JOY.RIGHT);
    assert.equal(g.vx, Math.min(n, 8), `a roller ${n} long speeds you up by ${Math.min(n, 8)}`);
  }
  assert.deepEqual(lens, { 1: 1, 2: 2, 4: 4, 6: 6, 8: 8, 12: 8 });
});

test('the length counts the roller to both sides of the feet', () => {
  const g = play(room({ '23,10': 'oooo' }));
  g.px = 12 * 4 + 1; // under the third tile
  run(g, 1);
  assert.equal(g.rollerLen(), 4);
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

test('a bomb block going off over his head does not hurt him: only his feet count', () => {
  const g = play(room({ '20,5': 'X' })); // its bottom is just above his head when he stands on the floor
  g.px = 5 * 4;
  run(g, 2);
  g.armCell(5, 20, 0, 2, g.map[20 * 40 + 5]);
  run(g, 4);
  assert.equal(g.map[20 * 40 + 5], T.BOOM, 'it went off');
  assert.equal(g.mode, MODE.PLAY);
  assert.equal(g.lives, 3);
});

test('a bomb block going off beside his feet kills; beside his knees, level with the tile above, it does not', () => {
  for (const [row, dies] of [[22, true], [21, false]]) {
    const g = play(room({ [`${row},6`]: 'X' }));
    g.px = 5 * 4;
    run(g, 2);
    g.armCell(6, row, 0, 2, g.map[row * 40 + 6]);
    run(g, 4);
    assert.equal(g.mode, dies ? MODE.DYING : MODE.PLAY, `row ${row}`);
  }
});

test('standing on a bomb block when it goes off kills him, in the blast zone two tiles above it too', () => {
  for (const above of [0, 1, 2]) {
    const g = play(room({ '23,5': 'X', '23,7': 'W' }));
    g.px = 5 * 4;
    g.py = (23 - above) * 8 - 16; // feet on the top of the block (0) or this many tiles above it
    g.state = STATE.AIR; // hanging in the air for the test: the block goes off before he falls far
    g.jt = 0xff;
    g.armCell(5, 23, 0, 1, g.map[23 * 40 + 5]);
    run(g, 2);
    assert.equal(g.mode, MODE.DYING, `${above} tiles above the block`);
  }
});

test('a peg on the block above does not push him from below', () => {
  const g = play(room());
  const peg = { x: 40, y: 170, min: 20, max: 60, dir: 1, wait: 0 }; // overlaps his head and chest, not his feet
  g.px = 40;
  g.pegs = [peg];
  g.pegPush(peg);
  assert.equal(g.px, 40);
  const level = { x: 40, y: 176, min: 20, max: 60, dir: 1, wait: 0 }; // beside his feet
  g.pegs = [level];
  g.pegPush(level);
  assert.equal(g.px, 41);
});

test('he looks at you until he moves, then the way he last went, leaning while he walks', () => {
  const g = play(room());
  run(g, 5);
  assert.equal(g.frame, FRAME.STAND);
  const seen = new Set();
  for (let i = 0; i < 20; i++) {
    g.step(JOY.RIGHT);
    seen.add(g.frame);
  }
  assert.deepEqual([...seen].sort(), [FRAME.STAND + 1, FRAME.LEAN]);
  run(g, 5);
  assert.equal(g.frame, FRAME.STAND + 1);
  seen.clear();
  for (let i = 0; i < 20; i++) {
    g.step(JOY.LEFT);
    seen.add(g.frame);
  }
  assert.deepEqual([...seen].sort(), [FRAME.STAND + 2, FRAME.LEAN + 1]);
});

test('he squashes to take off, stretches in the air and squashes again on landing', () => {
  const g = play(room());
  run(g, 3, JOY.RIGHT);
  g.step(JOY.FIRE | JOY.RIGHT);
  assert.equal(g.frame, FRAME.SQUASH + 1);
  run(g, 3, JOY.RIGHT);
  assert.equal(g.frame, FRAME.STRETCH + 1);
  while (g.state !== STATE.GROUND) g.step(0);
  for (let i = 0; i < 4; i++) {
    assert.equal(g.frame, FRAME.SQUASH + 1, `landing frame ${i}`);
    g.step(0);
  }
  assert.equal(g.frame, FRAME.STAND + 1);
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
