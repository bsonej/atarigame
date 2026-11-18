// Level files as the editor sees them: text <-> a grid of map characters, and the compiled map the
// game would get (tile bytes with platform end caps and dots, the door, the start, the number of things to
// collect and the pegs).
//
// This is a port of the level parts of tools/build_assets.py (parse_level, peg_for, apply_caps, apply_dots, apply_twins); the
// tests compare the two on every shipped level, so keep them in step.

export const COLS = 40;
export const ROWS = 24;
export const TILE_W = 4;
export const TILE_H = 8;
export const MAX_PEGS = 2;
export const F_SOLID = 1;
export const F_ONEWAY = 2;
export const F_DOT = 4;

/** What the server's /api/tiles describes, made handy: char -> byte, solid bytes, cap and dot families, the door. */
export function makeTables(api) {
  const chars = {};
  const solid = new Set();
  for (const t of api.tiles) {
    if (t.char) chars[t.char] = t.byte;
    if (t.solid) solid.add(t.byte);
  }
  const caps = {};
  for (const [fam, v] of Object.entries(api.caps)) caps[Number(fam)] = v;
  const byByte = {};
  for (const t of api.tiles) byByte[t.byte] = t;
  const T = {};
  for (const t of api.tiles) T[t.name] = t.byte;
  const dots = {};
  for (const [fam, v] of Object.entries(api.dots || {})) dots[Number(fam)] = v;
  const dotted = new Set(Object.values(dots));
  const twins = {};
  for (const [fam, v] of Object.entries(api.twins || {})) twins[Number(fam)] = v;
  return {
    chars, solid, caps, dots, dotted, twins, byByte, T, flags: api.flags, canon: api.canon, tiles: api.tiles,
    door: api.door || null, doorCells: api.doorCells || [], fade: api.fade || [], fadeSteps: api.fadeSteps || 16,
    palette: api.palette || null, maxCollect: api.maxCollect || 250,
  };
}

/** A comment line: '# ' or a lone '#' or '#!' (map rows never contain spaces). */
export function isComment(line) {
  const t = line.trim();
  return t === '#' || t.startsWith('# ') || t.startsWith('#!');
}

/** Split level text into the 24 map rows and the comment lines above them. */
export function parseLevelText(text) {
  const header = [];
  const rows = [];
  const errors = [];
  for (const line of text.split(/\r?\n/)) {
    if (line.trim() === '') continue;
    if (isComment(line)) {
      if (rows.length === 0) header.push(line);
      continue;
    }
    rows.push(line);
  }
  if (rows.length !== ROWS) errors.push(`has ${rows.length} map rows, needs ${ROWS}`);
  rows.forEach((r, i) => {
    if (r.length !== COLS) errors.push(`row ${i} is ${r.length} wide, needs ${COLS}`);
  });
  return { rows, header, errors };
}

export function blankRows() {
  const rows = [];
  for (let r = 0; r < ROWS; r++) {
    if (r === 0) rows.push('.'.repeat(COLS));
    else if (r === ROWS - 1) rows.push('#'.repeat(COLS));
    else rows.push('W' + '.'.repeat(COLS - 2) + 'W');
  }
  rows[ROWS - 3] = 'W.@' + '.'.repeat(COLS - 4) + 'W';
  rows[ROWS - 2] = 'W' + '.'.repeat(COLS - 4) + 'D.W'; // the exit door, near the right wall
  return rows;
}

/** Level title from a header such as "# Level 4: Assembly Line. 40 columns ...". */
export function titleOf(header) {
  for (const h of header) {
    const m = /^#\s*Level\s+\S+:\s*(.+?)\.(\s|$)/.exec(h);
    if (m) return m[1];
  }
  return '';
}

export function serializeLevel(rows, name, title) {
  const num = (/\d+/.exec(name) || [name])[0];
  return (
    `# Level ${num}${title ? `: ${title}` : ''}. 40 columns x 24 rows. Row 0 is reserved for the score display.\n` +
    '# Characters are defined in assets/tiles.txt (see the table in README.md). p = a peg (one per block)\n' +
    rows.join('\n') +
    '\n'
  );
}

/** Put the left/right/both-ends variant on tiles whose neighbour is a different tile (screen edge = same). */
export function applyCaps(data, caps) {
  const out = data.slice();
  for (let i = 0; i < data.length; i++) {
    const variants = caps[data[i]];
    if (!variants) continue;
    const col = i % COLS;
    const left = col > 0 && data[i - 1] !== data[i];
    const right = col < COLS - 1 && i + 1 < data.length && data[i + 1] !== data[i];
    const kind = left && right ? 'LR' : left ? 'L' : right ? 'R' : null;
    if (kind && variants[kind] !== undefined) out[i] = variants[kind];
  }
  return out;
}

/** Swap each tile's twin in on every odd screen row, so art that is two tiles tall lines up in a stack (the chutes' thread). */
export function applyTwins(data, twins) {
  const out = data.slice();
  for (let i = 0; i < data.length; i++) {
    if (Math.floor(i / COLS) % 2 === 1 && data[i] in twins) out[i] = twins[data[i]];
  }
  return out;
}

/**
 * Put a dot in every second middle tile of each run of a dotted tile (the 2nd, 4th, ... tile of the run).
 * `plain` is the map before end caps, `capped` after. A tile only gets a dot when the player can stand on it:
 * the two cells above must not be solid. Mirrors apply_dots in build_assets.py.
 */
export function applyDots(plain, capped, dots, solid) {
  const out = capped.slice();
  for (let r = 3; r < ROWS; r++) {
    let c = 0;
    while (c < COLS) {
      const b = plain[r * COLS + c];
      if (!(b in dots)) {
        c++;
        continue;
      }
      const start = c;
      while (c < COLS && plain[r * COLS + c] === b) c++;
      for (let k = start + 1; k < c; k += 2) {
        const i = r * COLS + k;
        if (capped[i] !== b) continue; // an end cap, never a dot
        if (solid.has(plain[i - COLS]) || solid.has(plain[i - 2 * COLS])) continue;
        out[i] = dots[b];
      }
    }
  }
  return out;
}

/** A peg's start (x, y, min x, max x, direction) or an error string. Mirrors peg_for in build_assets.py. */
export function pegFor(data, c, r, solid) {
  if (r + 1 >= ROWS || !solid.has(data[(r + 1) * COLS + c])) return { error: `peg at row ${r}, column ${c} needs a solid block under it` };
  const free = (col) => col >= 0 && col < COLS && solid.has(data[(r + 1) * COLS + col]) && !solid.has(data[r * COLS + col]);
  let lo = c;
  let hi = c;
  while (free(lo - 1)) lo--;
  while (free(hi + 1)) hi++;
  if (lo === hi) return { error: `peg at row ${r}, column ${c} has a platform only one tile wide` };
  if (c - lo <= hi - c) return { peg: [lo * 4, r * 8, lo * 4, hi * 4, 1] };
  return { peg: [hi * 4, r * 8, lo * 4, hi * 4, 255] };
}

/**
 * Compile the character grid. Never throws: problems are returned in `errors` (the game would refuse
 * the level) and `warnings`, and whatever could be compiled still is, so the editor can keep drawing.
 */
export function compileLevel(rows, tables) {
  const errors = [];
  const warnings = [];
  const data = new Array(COLS * ROWS).fill(0);
  let spawn = null;
  const starts = [];
  const pegMarks = [];
  const unknown = [];
  for (let r = 0; r < ROWS; r++) {
    const line = rows[r] || '';
    for (let c = 0; c < COLS; c++) {
      const ch = line[c] === undefined ? '.' : line[c];
      if (ch === '@') {
        starts.push([c, r]);
        continue;
      }
      if (ch === 'p') {
        pegMarks.push([c, r]);
        continue;
      }
      if (!(ch in tables.chars)) {
        unknown.push([c, r, ch]);
        continue;
      }
      data[r * COLS + c] = tables.chars[ch];
    }
  }
  for (const [c, r, ch] of unknown) errors.push({ msg: `unknown character '${ch}' at row ${r}, column ${c}`, c, r });
  if (starts.length === 0) errors.push({ msg: "no '@' player start" });
  else spawn = starts[0];
  if (starts.length > 1) errors.push({ msg: `more than one '@' start (second at row ${starts[1][1]}, column ${starts[1][0]})`, c: starts[1][0], r: starts[1][1] });
  const itemByte = tables.chars['*'];
  const stars = data.filter((b) => b === itemByte).length;
  if (stars === 0) errors.push({ msg: "no items ('*') to collect" });
  const doors = [];
  if (tables.door) {
    const cells = tables.doorCells; // [column, rows up] of each of the door's six tiles from its bottom left one
    for (let i = 0; i < COLS * ROWS; i++) {
      if (data[i] !== tables.door[0]) continue;
      const c = i % COLS;
      const r = Math.floor(i / COLS);
      const blocked = c + 1 >= COLS || r < 3 || cells.slice(1).some(([dc, dr]) => data[i + dc - dr * COLS] !== 0);
      if (blocked) errors.push({ msg: `the door at row ${r}, column ${c} needs an empty space above and to the right of it (2 columns by 3 rows, not touching the score row or the screen edge)`, c, r });
      else doors.push([c, r]);
    }
    if (doors.length === 0 && !errors.some((e) => e.msg.startsWith('the door'))) errors.push({ msg: "no exit door ('D')" });
    for (const [c, r] of doors) cells.forEach(([dc, dr], k) => { data[(r - dr) * COLS + c + dc] = tables.door[k]; });
  }
  const pegs = [];
  for (const [c, r] of pegMarks) {
    const res = pegFor(data, c, r, tables.solid);
    if (res.error) errors.push({ msg: res.error, c, r });
    else pegs.push(res.peg);
  }
  if (pegMarks.length > MAX_PEGS) errors.push({ msg: `${pegMarks.length} pegs, at most ${MAX_PEGS} per level` });
  let map = applyCaps(data, tables.caps);
  // no dot where standing to eat it would put the player in spikes
  const blocking = new Set(tables.solid);
  if ('^' in tables.chars) blocking.add(tables.chars['^']);
  map = applyDots(data, map, tables.dots, blocking);
  const dots = map.filter((b) => tables.dotted.has(b)).length;
  map = applyTwins(map, tables.twins);
  const items = stars + dots; // everything to collect before the door opens
  if (items > tables.maxCollect) errors.push({ msg: `${stars} items and ${dots} dots is too much to collect (at most ${tables.maxCollect} in all)` });
  // the game's loader copies whole pages
  while (map.length < 1024) map.push(0);
  // advice, not errors
  if (spawn) {
    const [sc, sr] = spawn;
    if (sr + 2 >= ROWS) warnings.push({ msg: 'the player starts below the floor', c: sc, r: sr });
    else {
      const t = tables.byByte[tables.canon[data[(sr + 2) * COLS + sc]]];
      if (!t || !(t.solid || t.oneway)) warnings.push({ msg: 'the player starts in mid-air (nothing to stand on two tiles below the @)', c: sc, r: sr });
    }
  }
  return { map, spawn, items, stars, dots, doors, pegs, errors, warnings, pegMarks, starts };
}
