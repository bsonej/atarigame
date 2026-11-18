// Level files as the editor sees them: text <-> a grid of map characters, and the compiled map the
// game would get (tile bytes with platform end caps, the start, the item count and the pegs).
//
// This is a port of the level parts of tools/build_assets.py (parse_level, peg_for, apply_caps); the
// tests compare the two on every shipped level, so keep them in step.

export const COLS = 40;
export const ROWS = 24;
export const TILE_W = 4;
export const TILE_H = 8;
export const MAX_PEGS = 2;

/** What the server's /api/tiles describes, made handy: char -> byte, solid bytes, cap families. */
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
  return { chars, solid, caps, byByte, T, flags: api.flags, canon: api.canon, tiles: api.tiles };
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
    else rows.push('#' + '.'.repeat(COLS - 2) + '#');
  }
  rows[ROWS - 3] = '#.@' + '.'.repeat(COLS - 4) + '#';
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
  const items = data.filter((b) => b === itemByte).length;
  if (items === 0) errors.push({ msg: "no items ('*') to collect" });
  if (items > 99) errors.push({ msg: 'too many items (the display shows two digits)' });
  const pegs = [];
  for (const [c, r] of pegMarks) {
    const res = pegFor(data, c, r, tables.solid);
    if (res.error) errors.push({ msg: res.error, c, r });
    else pegs.push(res.peg);
  }
  if (pegMarks.length > MAX_PEGS) errors.push({ msg: `${pegMarks.length} pegs, at most ${MAX_PEGS} per level` });
  const map = applyCaps(data, tables.caps);
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
  return { map, spawn, items, pegs, errors, warnings, pegMarks, starts };
}
