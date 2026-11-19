// Replay scripted joystick input on the JS engine and print the state after each segment as JSON.
// Used by tests/test_engine.py to compare the engine with the real game running in the emulator.
//
//   stdin:  {"tiles": <GET /api/tiles>, "text": "<level file>", "lives": 3, "fps": 50,
//            "start": {"px": 8, "py": 168} | null, "segments": [[buttons, frames], ...]}
//   stdout: {"compiled": {...}, "records": [{"snap": {...}, "map": [...], "pegs": [[x, dir, wait], ...]}, ...]}
//
// The game is put in PLAY mode at once (the emulator side does the same). Replay stops after the first
// segment that ends in the CLEAR or OVER mode, because the real game then moves on to another level.
import { readFileSync } from 'node:fs';
import { Game, MODE } from '../../web/engine.js';
import { makeTables, compileLevel, parseLevelText } from '../../web/model.js';

const spec = JSON.parse(readFileSync(0, 'utf8'));
const tables = makeTables(spec.tiles);
const parsed = parseLevelText(spec.text);
const compiled = compileLevel(parsed.rows, tables);
if (compiled.errors.length) {
  console.log(JSON.stringify({ error: compiled.errors.map((e) => e.msg) }));
  process.exit(0);
}
const game = new Game(compiled, tables, { lives: spec.lives, fps: spec.fps });
game.mode = MODE.PLAY;
game.drawn = 16;
if (spec.start) {
  game.px = spec.start.px;
  game.py = spec.start.py;
}
const records = [];
for (const [buttons, frames] of spec.segments) {
  for (let i = 0; i < frames; i++) game.step(buttons);
  records.push({
    snap: game.snapshot(),
    map: Array.from(game.map.slice(0, 960)),
    pegs: game.pegs.map((p) => [p.x, p.dir, p.wait]),
  });
  if (game.mode === MODE.CLEAR || game.mode === MODE.OVER) break;
}
console.log(
  JSON.stringify({
    compiled: {
      map: Array.from(compiled.map.slice(0, 960)), spawn: compiled.spawn, items: compiled.items, stars: compiled.stars,
      dots: compiled.dots, doors: compiled.doors, pegs: compiled.pegs,
    },
    records,
  }),
);
