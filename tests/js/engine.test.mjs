// Quick rule checks on web/engine.js, without the emulator. (tests/test_engine.py is the real proof: it plays the same
// input on the 6502 code and on this engine and compares them.) Run with: node --test tests/js
import test from 'node:test';
import assert from 'node:assert/strict';
import { JOY, MODE, STATE, FRAME, BOUNCE_N, TRAMP_AMP } from '../../web/engine.js';
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

test('a jump rises 26 pixels and lands again', () => {
  const g = play(room());
  g.step(JOY.FIRE);
  let top = g.py;
  for (let i = 0; i < 60; i++) {
    g.step(0);
    top = Math.min(top, g.py);
  }
  assert.equal(FLOOR_Y - top, 26);
  assert.deepEqual([g.py, g.state], [FLOOR_Y, STATE.GROUND]);
});

test('he floats down slower than he rises (a pixel a frame to begin with) and `fall` still counts pixels', () => {
  const g = play(room());
  g.step(JOY.FIRE);
  const ys = [g.py];
  const falls = [g.fall];
  while (g.state === STATE.AIR) {
    g.step(0);
    ys.push(g.py);
    falls.push(g.fall);
  }
  const apex = ys.indexOf(Math.min(...ys));
  const down = ys.slice(apex);
  const steps = down.slice(1).map((y, i) => y - down[i]).filter((d) => d); // (not the frame at the apex, nor the landing one)
  assert.equal(steps.reduce((a, b) => a + b), 26);
  assert.ok(steps.every((d) => d === 1 || d === 2) && steps[0] === 1, `1 pixel a frame to begin with, never more than 2: ${steps}`);
  assert.ok(steps.length >= apex + 4, `${apex} frames up, ${steps.length} down`);
  assert.equal(falls[falls.length - 1], 0, 'and is zero again on the ground');
});

test('a fall of 64 pixels is survived, 65 kills (the lethal distance is in pixels, not frames)', () => {
  for (const [dist, dies] of [[64, false], [65, true]]) {
    const g = play(room({ '8,2': '###' }));
    g.px = 8;
    g.py = FLOOR_Y - dist;
    g.state = STATE.AIR;
    g.jt = 0xff;
    run(g, 80);
    assert.equal(g.deaths, dies ? 1 : 0, `${dist} pixels`);
  }
});

test('a spike hurts from the line its tips are on (line 1 of the tile) down, not above it', () => {
  for (const [line, dies] of [[0, false], [1, true], [7, true]]) {
    const g = play(room({ '10,22': '^' }));
    g.px = 88;
    g.py = 10 * 8 + line - 15;
    g.checkTiles();
    assert.equal(g.mode, dies ? MODE.DYING : MODE.PLAY, `feet on line ${line}`);
  }
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

test('an item is collected at his level only: walking under it or jumping up through it from below does not', () => {
  // row 21 is his head row on the floor (he occupies rows 21 and 22 there); row 22 is his feet row
  const head = play(room({ '21,5': '*', '21,6': '*' }));
  run(head, 40, JOY.RIGHT);
  assert.equal(head.score, 0, 'walked under items at head height');
  assert.equal(head.left, 3);
  const feet = play(room({ '22,5': '*' }));
  run(feet, 40, JOY.RIGHT);
  assert.equal(feet.score, 10, 'walked into one at his level');
  // an item on a ledge above him: the jump rises through it (head, then body) without taking it
  const up = play(room({ '17,8': '*', '18,6': '====' }));
  run(up, 30, JOY.RIGHT);
  up.step(JOY.FIRE);
  const seen = [];
  for (let i = 0; i < 12; i++) {
    up.step(0);
    seen.push(up.left);
  }
  assert.ok(up.py < FLOOR_Y - 20, 'he went up');
  assert.equal(up.state, STATE.AIR);
  assert.equal(up.score, 0, 'rising through it collects nothing');
  assert.ok(seen.every((l) => l === 3));
});

test('landing on the ledge, at the level of its item, collects it', () => {
  const g = play(room({ '19,8': '*', '20,6': '=====' })); // a ledge 3 tiles up: reachable by a jump
  g.px = 32; // right under the item
  g.step(JOY.FIRE);
  run(g, 8, 0);
  assert.equal(g.score, 0, 'he is still rising through it');
  run(g, 40, 0);
  assert.equal(g.py, FLOOR_Y - 24, 'standing on the ledge');
  assert.equal(g.score, 10, 'its item is his now: collected on landing, at its level');
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

test('you walk straight past steps and a down chute that stands on the floor, and can jump up onto a step', () => {
  for (const ch of ['S', '\\']) {
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

test('walking into a down chute that fills a gap in the floor: locked in, carried down, released below it', () => {
  const g = play(room({ '12,5': '#####', ...vertical(12, 16, 10, '\\') }));
  g.px = 6 * 4;
  g.py = 12 * 8 - 16; // on the platform at row 12, which ends at the chute
  run(g, 2);
  assert.equal(g.state, STATE.GROUND);
  let rode = 0;
  for (let i = 0; i < 60 && g.state !== STATE.AIR; i++) {
    g.step(JOY.RIGHT);
    if (g.state === STATE.RIDE) {
      rode++;
      assert.equal(g.px, 10 * 4, 'snapped to the chute column and stays there');
    }
  }
  assert.ok(rode >= 10, `rode ${rode} frames`);
  for (let i = 0; i < 40 && g.state === STATE.RIDE; i++) g.step(JOY.LEFT); // joystick ignored while riding
  run(g, 60);
  assert.deepEqual([g.px, g.py, g.state], [10 * 4, FLOOR_Y, STATE.GROUND], 'fell out of the bottom of the chute onto the floor');
});

test('an up chute carries you to its top and you hop out onto the platform beside it', () => {
  const g = play(room({ '18,11': '#######', ...vertical(18, 22, 10, '/') }));
  g.px = 6 * 4;
  g.py = FLOOR_Y;
  run(g, 2);
  let rode = 0;
  let top = 999;
  for (let i = 0; i < 200 && !(rode && g.state === STATE.GROUND); i++) {
    g.step(g.state === STATE.RIDE ? JOY.LEFT : rode ? 0 : JOY.RIGHT); // walk in; the joystick is ignored while riding: pulling left does not turn him round
    if (g.state === STATE.RIDE) {
      rode++;
      top = Math.min(top, g.py);
      assert.equal(g.px, 10 * 4);
    }
  }
  assert.ok(rode >= 20, `rode ${rode} frames`);
  assert.equal(top, 18 * 8 - 16, 'rode up until his feet were level with the top tile');
  assert.equal(g.py, 18 * 8 - 16);
  assert.ok(g.px > 11 * 4 - 2, `hopped out to the right: ${g.px}`);
  assert.equal(g.state, STATE.GROUND);
});

test('chutes do not carry you sideways, and in the air you pass straight through them', () => {
  const g = play(room({ ...vertical(18, 22, 10, '/'), ...vertical(18, 22, 20, '\\') }));
  g.px = 32;
  g.py = FLOOR_Y;
  run(g, 1);
  g.step(JOY.RIGHT | JOY.FIRE); // jump from just before the up chute and fly through it
  for (let i = 0; i < 18; i++) {
    g.step(JOY.RIGHT);
    assert.notEqual(g.state, STATE.RIDE, 'not caught in the air');
  }
  assert.ok(g.px > 40, 'went through the up chute column');
  const h = play(room({ ...vertical(21, 22, 20, '\\') })); // a down chute standing on the floor: walk through, no sideways push
  h.px = 60;
  h.py = FLOOR_Y;
  run(h, 40, JOY.RIGHT);
  assert.equal(h.px, 100);
  run(h, 40);
  assert.equal(h.px, 100, 'nothing carried him');
  assert.equal(h.py, FLOOR_Y);
});

test('rising in a jump ignores everything above: he overlays a block and lands on top of it, or falls back out of a thick one', () => {
  const g = play(room({ '20,1': '#####' })); // a ledge just over his head: the top is at y 160
  g.step(JOY.FIRE);
  run(g, 60);
  assert.deepEqual([g.py, g.state], [20 * 8 - 16, STATE.GROUND], 'went up through it and landed on top');
  const h = play(room({ '19,1': '#####', '20,1': '#####' })); // two thick: the apex is inside it
  h.step(JOY.FIRE);
  run(h, 80);
  assert.deepEqual([h.py, h.state], [FLOOR_Y, STATE.GROUND], 'fell back out of the bottom, not stuck in it');
  const w = play(room({ '19,1': '########', '20,1': '########' })); // under a low ceiling he keeps moving sideways inside it
  w.step(JOY.FIRE | JOY.RIGHT);
  const x0 = w.px;
  run(w, 14, JOY.RIGHT);
  assert.equal(w.px, x0 + 14, 'not stuck in the block');
  const o = play(room({ '16,1': '=====' })); // a thin platform
  o.step(JOY.FIRE);
  run(o, 80);
  assert.deepEqual([o.py, o.state], [FLOOR_Y, STATE.GROUND]);
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
  assert.equal(g.px, 44, 'carried clear of the peg (it is 4 wide)');
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

// The peg's push carries him all the way along a platform whatever is in it: belts dragging him back, steps, ice, a ladder
// standing on it. Peg row 18, the platform on row 19 (he stands at py 136 and falls 32 pixels when he is carried off its
// end: not fatal).
test('a peg carries him to the end of a platform with belts, steps, ice and a ladder in it, and off it', () => {
  const rows = room({
    '18,5': 'p',
    '19,4': '((((((((S~=oS####', // fast belts against the push, then a step, ice, a one-way platform, a roller, a step, brick
    '18,10': 'H', // a ladder standing on the platform
    '18,14': 'S', // a step standing on the platform
  });
  const g = play(rows);
  const { x, y, min: lo, max: hi } = g.pegs[0];
  assert.deepEqual([x, y, lo, hi], [16, 144, 16, 80], 'the whole run, columns 4-20');
  g.px = 28;
  g.py = 136;
  g.state = STATE.GROUND;
  let far = 0;
  for (let i = 0; i < 900 && g.mode === MODE.PLAY; i++) {
    g.step(0);
    far = Math.max(far, g.px);
  }
  assert.ok(far >= hi + 4, `he was carried to the end of the platform and off it (got to ${far}, the end is ${hi + 4})`);
  assert.equal(g.mode, MODE.PLAY, 'and lived');
});

test('pushed over a spike he still dies of it (the push does not make him immune)', () => {
  const g = play(room({ '18,5': 'p', '19,4': '########', '18,8': '^' }));
  g.px = 28;
  g.py = 136;
  g.state = STATE.GROUND;
  for (let i = 0; i < 400 && g.mode === MODE.PLAY; i++) g.step(0);
  assert.equal(g.mode, MODE.DYING);
});

// ---- trampolines -------------------------------------------------------------------------------------------------
// A trampoline is a solid platform. Landing on it from the air throws him straight up, just high enough to land on the
// next surface above him in his column (up to 14 tiles), see tryBounce in web/engine.js and try_bounce in main.s.

/** Jump on the spot (at pixel column px) and report the highest point (smallest py) and where he ends up. */
function jumpOn(g, frames = 150) {
  g.step(JOY.FIRE);
  let top = g.py;
  for (let i = 0; i < frames; i++) {
    g.step(0);
    top = Math.min(top, g.py);
  }
  return { top, py: g.py, state: g.state };
}

test('walking over a trampoline does nothing', () => {
  const g = play(room({ '23,10': 'TTTT', '18,8': '#######' }));
  g.px = 32;
  for (let i = 0; i < 40; i++) {
    g.step(JOY.RIGHT);
    assert.deepEqual([g.py, g.state], [FLOOR_Y, STATE.GROUND], `frame ${i}`);
  }
  assert.ok(g.px >= 70, 'walked right across it');
  run(g, 30);
  assert.deepEqual([g.py, g.state, g.jt], [FLOOR_Y, STATE.GROUND, 0xff]);
  assert.equal(g.map[23 * 40 + 11], T.TRAMPOLINE, 'no dots on it');
});

test('landing from a jump on a trampoline bounces him up to the platform above', () => {
  const g = play(room({ '23,10': 'TTTT', '18,8': '#######' })); // the platform's top is 5 tiles above the trampoline's
  g.px = 11 * 4;
  const r = jumpOn(g);
  assert.equal(FLOOR_Y - r.top, 17 + 3 * 11, 'rose 50 pixels: 8*5+8=48 rounded up to the 3 pixel steps');
  assert.ok(r.top < 18 * 8 - 16 - 8, 'the apex clears the platform by more than a tile');
  assert.deepEqual([r.py, r.state], [18 * 8 - 16, STATE.GROUND], 'then lands on it');
});

test('a bounce is automatic: a long fall onto a trampoline does not hurt and bounces him up to the ledge above', () => {
  const g = play(room({ '23,10': 'TTTT', '12,8': '#######' }));
  g.px = 11 * 4;
  g.py = 100; // (a fall of 68 pixels, more than MAX_FALL: fatal on any other floor); the ledge's top is above his feet
  g.state = STATE.AIR;
  g.jt = 0xff;
  run(g, 200);
  assert.equal(g.deaths, 0);
  assert.deepEqual([g.py, g.state], [12 * 8 - 16, STATE.GROUND]);
  const hard = play(room({ '23,10': 'WWWW' }));
  hard.px = 11 * 4;
  hard.py = 100;
  hard.state = STATE.AIR;
  hard.jt = 0xff;
  run(hard, 60);
  assert.equal(hard.mode, MODE.DYING, 'the same fall onto a plain floor kills');
});

test('nothing above him means no bounce', () => {
  const g = play(room({ '23,10': 'TTTT' }));
  g.px = 11 * 4;
  const r = jumpOn(g);
  assert.equal(FLOOR_Y - r.top, 26, 'an ordinary jump');
  assert.deepEqual([r.py, r.state, g.jt, g.bn], [FLOOR_Y, STATE.GROUND, 0xff, 0]);
});

test('a surface 14 tiles up is reached, 15 is not', () => {
  const far = play(room({ '23,10': 'TTTT', '9,8': '#######' })); // 14 tiles up: rows 22 .. 9
  far.px = 11 * 4;
  assert.equal(jumpOn(far).py, 9 * 8 - 16);
  const none = play(room({ '23,10': 'TTTT', '8,8': '#######' }));
  none.px = 11 * 4;
  const r = jumpOn(none);
  assert.deepEqual([r.py, FLOOR_Y - r.top], [FLOOR_Y, 26], 'out of range: no bounce');
});

test('every height from 2 to 14 tiles lands on the surface (one-way, too) and clears it by a tile', () => {
  for (let k = 2; k <= 14; k++) {
    const row = 23 - k; // (one tile up would be inside his body)
    const g = play(room({ '23,10': 'TTTT', [`${row},8`]: '=======' }));
    g.px = 11 * 4;
    g.py = FLOOR_Y - 10; // dropped onto the trampoline from just above it
    g.state = STATE.AIR;
    g.jt = 0xff;
    let top = g.py;
    for (let i = 0; i < 200; i++) {
      g.step(0);
      top = Math.min(top, g.py);
    }
    assert.deepEqual([k, g.py, g.state], [k, row * 8 - 16, STATE.GROUND]);
    const clear = row * 8 - 16 - top;
    assert.ok(clear >= 8 && clear <= 10, `k=${k}: the apex is ${clear} pixels above the standing height`);
  }
});

test('a bounce can be repeated: landing on a trampoline on the upper level bounces again', () => {
  const g = play(room({ '23,10': 'TTTT', '18,8': 'TTTTTTT', '12,8': '#######' }));
  g.px = 11 * 4;
  const r = jumpOn(g, 300);
  assert.deepEqual([r.py, r.state], [12 * 8 - 16, STATE.GROUND], 'up to the first trampoline, then to the ledge above it');
});

test('the table of bounce lengths gives the least rise that clears the surface by a tile', () => {
  for (let k = 1; k <= 14; k++) {
    const rise = 17 + 3 * BOUNCE_N[k];
    assert.ok(rise >= 8 * k + 8, `k=${k}`);
    if (BOUNCE_N[k] > 0) assert.ok(rise - 3 < 8 * k + 8, `k=${k} is not higher than it needs to be`);
  }
});

test('a trampoline run sags like a rubber band across its span, caps stay, and the plain tiles come back', () => {
  const g = play(room({ '23,5': 'TTTTTTTT', '23,20': 'TTTT', '18,6': '########' }));
  const row = () => Array.from(g.map.slice(23 * 40 + 5, 23 * 40 + 13));
  const other = () => Array.from(g.map.slice(23 * 40 + 20, 23 * 40 + 24));
  const plain = row();
  const plainOther = other();
  const [L, M, R] = [T.TRAMPOLINE_L, T.TRAMPOLINE, T.TRAMPOLINE_R];
  assert.deepEqual(plain, [L, M, M, M, M, M, M, R]);
  g.px = 32; // column 8
  g.step(JOY.FIRE);
  const frames = [];
  for (let i = 0; i < 110; i++) {
    g.step(0);
    frames.push(row());
    assert.deepEqual(other(), plainOther, 'another trampoline does not move');
  }
  assert.ok(frames.every((f) => f[0] === L && f[7] === R), 'the posts never change');
  const moving = frames.filter((f) => f.join() !== plain.join()).length;
  assert.equal(moving, TRAMP_AMP.filter((a) => a).length * 2, 'two frames a step (the last, plain step shows nothing)');
  for (let c = 1; c < 7; c++) assert.ok(frames.some((f) => f[c] !== M), `tile ${c} moves`);
  const rank = [M, T.TRAMPOLINE_S1, T.TRAMPOLINE_S2, T.TRAMPOLINE_S3];
  const deepest = frames.find((f) => f[3] === T.TRAMPOLINE_S3);
  assert.ok(rank.indexOf(deepest[3]) > rank.indexOf(deepest[1]) && rank.indexOf(deepest[3]) > rank.indexOf(deepest[6]), 'deepest where he landed');
  assert.ok(frames.some((f) => f[2] === T.TRAMPOLINE_TAUT), 'and springs back past plain');
  assert.deepEqual(frames.at(-1), plain);
  assert.equal(g.tr.t, 0);
  assert.deepEqual([g.py, g.state], [18 * 8 - 16, STATE.GROUND]);
  for (const b of [T.TRAMPOLINE_S1, T.TRAMPOLINE_S2, T.TRAMPOLINE_S3, T.TRAMPOLINE_TAUT]) assert.equal(g.canon[b], T.TRAMPOLINE, 'a frame is a trampoline to every rule');
});
