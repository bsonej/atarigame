// The sprite editor's model: Mr. Bubble's frames as text rows, with the same rules as tools/build_assets.py
// (parse_sprite_frames), a file writer that keeps assets/sprites.txt's comments, an undo history and the walk and
// jump cycles used by the animated preview. No DOM in here, so node can test it (tests/js/sprites.test.mjs).
//
// A frame is 16 strings of 8 characters:  '#' body (hardware Player 0, pink)   'e' eye (Player 3, white; it sits
// behind the body)   'o' the third colour (the four missiles as a fifth sprite behind the other two: the pupils and the
// grin; every single pixel can be 'o')   '.' nothing (the
// playfield shows through). A pixel is one character, so it is never two of these.

export const W = 8;
export const H = 16;
/** Mr. Bubble floats: he is drawn this many scan lines above the surface he stands on (src/main.s PLAYER_FLOAT). Purely visual. */
export const FLOAT = 2;
/** On top of the hover he bobs like a bubble: the lines he floats above the surface on each of 64 frames (1 to 3, a slow
 *  sine; the game indexes bob_float in src/main.s with the OS frame counter and 63). Purely visual. */
export const BOB_FLOAT = Object.freeze([2,2,2,2,2,2,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,3,2,2,2,2,2,2,2,2,2,2,2,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2]);
export const bobFloat = (tick) => BOB_FLOAT[tick & 63];
export const BODY = '#';
export const EYE = 'e';
export const THIRD = 'o';
export const NONE = '.';
const ROW_RE = new RegExp(`^[#.eo]{${W}}$`);
const NAME_RE = /^[A-Za-z][A-Za-z0-9_]*$/;

/** The text of a comment line, as build_assets._is_comment sees it: '# ...', a lone '#', or '#!'. Pixel rows never have a space. */
export const isComment = (line) => {
  const t = line.trim();
  return t === '#' || t.startsWith('# ') || t.startsWith('#!');
};

/** Split sprites.txt into lines and frames: [{name, rows: [line indices of the pixel rows], text: [the rows]}]. Throws on a bad file. */
function layout(text) {
  const lines = text.split('\n');
  if (lines.length && lines[lines.length - 1] === '') lines.pop();
  const frames = [];
  let cur = null;
  lines.forEach((raw, i) => {
    const t = raw.trim();
    if (!t || isComment(raw)) return;
    if (t.startsWith('frame ')) {
      const name = t.slice(6).trim();
      cur = { name, at: [], rows: [] };
      frames.push(cur);
      return;
    }
    if (!ROW_RE.test(t)) throw new Error(`sprites.txt line ${i + 1}: sprite rows are ${W} characters of '#', 'e', 'o' and '.', got '${t}'`);
    if (!cur) throw new Error(`sprites.txt line ${i + 1}: sprite row before any 'frame' line`);
    cur.at.push(i);
    cur.rows.push(t);
  });
  return { lines, frames, trailingNewline: text.endsWith('\n') };
}

/** [{name, rows}] from the text of sprites.txt. */
export function parseSprites(text) {
  const { frames } = layout(text);
  if (!frames.length) throw new Error('sprites.txt has no frames');
  for (const f of frames) if (f.rows.length !== H) throw new Error(`frame ${f.name} has ${f.rows.length} rows, needs ${H}`);
  return frames.map((f) => ({ name: f.name, rows: f.rows }));
}

/**
 * What is wrong with `frames` ([{name, rows}]) as a sprite set: a list of messages, empty when it is fine. With
 * `names` (the frame names of the file on disk) the count, names and order must match, because main.s picks a frame
 * by its place in the list.
 */
export function checkFrames(frames, names = null) {
  const errors = [];
  if (!Array.isArray(frames)) return ['frames must be a list'];
  if (names && frames.length !== names.length) errors.push(`there are ${frames.length} frames but the game has ${names.length}: frames cannot be added or removed here`);
  frames.forEach((f, i) => {
    const label = f && typeof f.name === 'string' ? f.name : `#${i}`;
    if (!f || typeof f.name !== 'string' || !NAME_RE.test(f.name)) return errors.push(`frame #${i} has no usable name`);
    if (names && names.length === frames.length && names[i] !== f.name) errors.push(`frame #${i} is called ${f.name}, the game has ${names[i]} there: frames cannot be renamed or reordered here`);
    if (!Array.isArray(f.rows) || f.rows.length !== H) return errors.push(`frame ${label} has ${Array.isArray(f.rows) ? f.rows.length : 0} rows, needs ${H}`);
    f.rows.forEach((row, y) => {
      if (typeof row !== 'string' || !ROW_RE.test(row)) errors.push(`frame ${label} row ${y}: needs ${W} characters of '#', 'e', 'o' and '.', got ${JSON.stringify(row)}`);
    });
  });
  return errors;
}

/**
 * `template` (the text of sprites.txt) with the pixel rows replaced by those of `frames`; the header, the comments, the
 * blank lines and the `frame` lines stay exactly as they are. Throws if the frames do not fit the template.
 */
export function serializeSprites(template, frames) {
  const lay = layout(template);
  const errors = checkFrames(frames, lay.frames.map((f) => f.name));
  if (errors.length) throw new Error(errors[0]);
  const lines = lay.lines.slice();
  lay.frames.forEach((f, i) => f.at.forEach((line, y) => (lines[line] = frames[i].rows[y])));
  return lines.join('\n') + (lay.trailingNewline ? '\n' : '');
}

/** The bytes the asset tool makes of a frame: body rows and eye rows (one byte per row, leftmost pixel in bit 7) and the
 * third layer as missile bytes (column c is bit 2*(c>>1) + 1 - (c&1): M0 bits 1-0 ... M3 bits 7-6, high bit on the left). */
export function toBytes(rows) {
  const bits = (ch) => rows.map((r) => [...r].reduce((b, c, i) => (c === ch ? b | (0x80 >> i) : b), 0));
  const third = rows.map((r) => [...r].reduce((b, c, i) => (c === THIRD ? b | (1 << (2 * (i >> 1) + 1 - (i & 1))) : b), 0));
  return { body: bits(BODY), eyes: bits(EYE), third };
}

export const blankRows = () => Array.from({ length: H }, () => NONE.repeat(W));
export const cloneRows = (rows) => rows.slice();
export const flipRows = (rows) => rows.map((r) => [...r].reverse().join(''));
export const cloneFrames = (frames) => frames.map((f) => ({ name: f.name, rows: f.rows.slice() }));
export const sameRows = (a, b) => a.length === b.length && a.every((r, i) => r === b[i]);

/** The frame a right/left frame mirrors into: stand_right <-> stand_left, lean_right <-> lean_left, ... or null. */
export function counterpartName(name) {
  if (/_right$/.test(name)) return name.replace(/_right$/, '_left');
  if (/_left$/.test(name)) return name.replace(/_left$/, '_right');
  return null;
}

/** Where a pixel changes when a line is drawn from (x0, y0) to (x1, y1): Bresenham, both ends included. */
export function linePixels(x0, y0, x1, y1) {
  const out = [];
  const dx = Math.abs(x1 - x0);
  const dy = -Math.abs(y1 - y0);
  const sx = x0 < x1 ? 1 : -1;
  const sy = y0 < y1 ? 1 : -1;
  let err = dx + dy;
  let x = x0;
  let y = y0;
  for (;;) {
    out.push([x, y]);
    if (x === x1 && y === y1) return out;
    const e2 = 2 * err;
    if (e2 >= dy) {
      err += dy;
      x += sx;
    }
    if (e2 <= dx) {
      err += dx;
      y += sy;
    }
  }
}

/**
 * The frames being edited, what is on disk, and the undo history. Every change goes through a method here;
 * `onchange` fires after each one.
 */
export class SpriteDoc {
  constructor(frames, onchange = () => {}) {
    this.frames = cloneFrames(frames);
    this.saved = cloneFrames(frames);
    this.undoStack = [];
    this.redoStack = [];
    this.pending = null; // the frames before the stroke in progress
    this.strokeChanged = false;
    this.clipboard = null;
    this.onchange = onchange;
  }

  rows(i) {
    return this.frames[i].rows;
  }

  get(i, x, y) {
    return this.frames[i].rows[y][x];
  }

  /** Is frame `i` (or, with no argument, anything) different from what is on disk? */
  dirty(i = null) {
    if (i !== null) return !sameRows(this.frames[i].rows, this.saved[i].rows);
    return this.frames.some((_, k) => this.dirty(k));
  }

  /** Mark the present state as what is on disk (after a save). */
  markSaved() {
    this.saved = cloneFrames(this.frames);
    this.onchange();
  }

  /** Replace everything with `frames` (a reload from disk), forgetting the history. */
  reset(frames) {
    this.frames = cloneFrames(frames);
    this.saved = cloneFrames(frames);
    this.undoStack = [];
    this.redoStack = [];
    this.pending = null;
    this.onchange();
  }

  /** Make the frames `frames` the working copy but leave the disk copy alone (a restored draft). */
  restore(frames) {
    this.frames = cloneFrames(frames);
    this.undoStack = [];
    this.redoStack = [];
    this.pending = null;
    this.onchange();
  }

  // -- strokes: a drag of the mouse is one undo step -------------------------------------------
  beginStroke() {
    this.pending = cloneFrames(this.frames);
    this.strokeChanged = false;
  }

  /** Paint pixel (x, y) of frame `i` with `ch`. Returns whether anything changed. */
  setPixel(i, x, y, ch) {
    if (x < 0 || x >= W || y < 0 || y >= H || ch.length !== 1 || !'#.eo'.includes(ch)) return false;
    const row = this.frames[i].rows[y];
    const chars = [...row];
    chars[x] = ch;
    const next = chars.join('');
    if (next === row) return false;
    const autoStroke = !this.pending;
    if (autoStroke) this.beginStroke();
    this.frames[i].rows[y] = next;
    this.strokeChanged = true;
    if (autoStroke) this.endStroke();
    else this.onchange();
    return true;
  }

  /** Paint a line of pixels (a quick drag skips cells otherwise). */
  line(i, x0, y0, x1, y1, ch) {
    let any = false;
    for (const [x, y] of linePixels(x0, y0, x1, y1)) any = this.setPixel(i, x, y, ch) || any;
    return any;
  }

  endStroke() {
    if (this.pending && this.strokeChanged) {
      this.undoStack.push(this.pending);
      this.redoStack = [];
    }
    this.pending = null;
    this.strokeChanged = false;
    this.onchange();
  }

  // -- whole-frame operations: one undo step each -----------------------------------------------
  edit(fn) {
    const before = cloneFrames(this.frames);
    fn(this.frames);
    if (this.frames.every((f, k) => sameRows(f.rows, before[k].rows))) return false;
    this.undoStack.push(before);
    this.redoStack = [];
    this.onchange();
    return true;
  }

  clear(i) {
    return this.edit((fr) => (fr[i].rows = blankRows()));
  }

  flip(i) {
    return this.edit((fr) => (fr[i].rows = flipRows(fr[i].rows)));
  }

  /** Move the picture of frame `i` by (dx, dy) pixels (all three layers, single pixels); what falls off the edge is lost. */
  shift(i, dx, dy) {
    return this.edit((fr) => {
      const old = fr[i].rows;
      fr[i].rows = old.map((_, y) => {
        const sy = y - dy;
        if (sy < 0 || sy >= H) return NONE.repeat(W);
        return [...old[sy]].map((_c, x) => (x - dx >= 0 && x - dx < W ? old[sy][x - dx] : NONE)).join('');
      });
    });
  }

  revert(i) {
    return this.edit((fr) => (fr[i].rows = this.saved[i].rows.slice()));
  }

  copy(i) {
    this.clipboard = cloneRows(this.frames[i].rows);
  }

  paste(i) {
    if (!this.clipboard) return false;
    return this.edit((fr) => (fr[i].rows = cloneRows(this.clipboard)));
  }

  /** The index of the frame that frame `i` mirrors into, or -1. */
  counterpart(i) {
    const other = counterpartName(this.frames[i].name);
    return other ? this.frames.findIndex((f) => f.name === other) : -1;
  }

  /** Overwrite the right/left counterpart of frame `i` with its mirror image. Returns the counterpart's index, or -1. */
  mirrorToCounterpart(i) {
    const j = this.counterpart(i);
    if (j < 0) return -1;
    this.edit((fr) => (fr[j].rows = flipRows(fr[i].rows)));
    return j;
  }

  undo() {
    if (this.pending) this.endStroke();
    const prev = this.undoStack.pop();
    if (!prev) return false;
    this.redoStack.push(cloneFrames(this.frames));
    this.frames = prev;
    this.onchange();
    return true;
  }

  redo() {
    const next = this.redoStack.pop();
    if (!next) return false;
    this.undoStack.push(cloneFrames(this.frames));
    this.frames = next;
    this.onchange();
    return true;
  }

  get canUndo() {
    return this.undoStack.length > 0;
  }

  get canRedo() {
    return this.redoStack.length > 0;
  }

  /** Problems that would stop a save. */
  problems(names = null) {
    return checkFrames(this.frames, names);
  }
}

// ---- the animated preview ------------------------------------------------------------------------
// A timeline is a list of ticks, one per video frame, {name, lift}: the frame to show and how many pixels he is above
// the ground. The walk and the jump follow choose_frame in src/main.s and engine.js (updatePlayer).

const JUMP_DY = [3, 3, 3, 3, 3, 2, 2, 2, 2, 1, 1, 1, 0]; // rise per frame, the same as the game's jump table
const FALL_SLOW = 4; // falling is slower: 1 pixel a frame for the first FALL_SLOW pixels, then 1, 1, 2 up to FALL_FAST, then 2
const FALL_FAST = 16;

const rep = (name, n, lift = 0) => Array.from({ length: n }, () => ({ name, lift }));

function walk(face) {
  const stand = face === 'right' ? 'stand_right' : 'stand_left';
  const lean = face === 'right' ? 'lean_right' : 'lean_left';
  return [...rep(stand, 4), ...rep(lean, 4)];
}

function jump(face) {
  const sfx = face === 'front' ? '' : `_${face}`;
  const out = [];
  let y = 0;
  JUMP_DY.forEach((dy, i) => {
    y += dy;
    out.push({ name: (i < 3 ? 'squash' : 'stretch') + sfx, lift: y }); // squashed at take-off, then stretched
  });
  // the way down is slower: the pixels a frame depend on how far he has fallen (air_fall in main.s)
  for (let fallen = 0; y > 0; ) {
    out.push({ name: `stretch${sfx}`, lift: y });
    const speed = fallen >= FALL_FAST ? 2 : fallen < FALL_SLOW ? 1 : fallen & 2 ? 1 : 2;
    for (let i = 0; i < speed && y > 0; i++, y--, fallen++);
  }
  out.push(...rep(`squash${sfx}`, 4), ...rep(`stand${sfx}`, 14));
  return out;
}

export const ANIMATIONS = [
  { id: 'walk_right', label: 'Walk right (stand, lean)', ticks: walk('right') },
  { id: 'walk_left', label: 'Walk left (stand, lean)', ticks: walk('left') },
  { id: 'jump', label: 'Jump (squash, stretch, land)', ticks: jump('front') },
  { id: 'jump_right', label: 'Jump right', ticks: jump('right') },
  { id: 'jump_left', label: 'Jump left', ticks: jump('left') },
  { id: 'look', label: 'Look around (stand)', ticks: [...rep('stand', 40), ...rep('stand_right', 40), ...rep('stand', 40), ...rep('stand_left', 40)] },
  { id: 'pop', label: 'Pop (death)', ticks: [...rep('stand', 20), ...rep('squash', 4), ...rep('pop_a', 4), ...rep('pop_b', 4), ...rep('pop_a', 4), ...rep('pop_b', 4)] },
];

/** The highest `lift` of an animation: the preview needs this much room above him. */
export const maxLift = (anim) => anim.ticks.reduce((m, t) => Math.max(m, t.lift), 0);
