// The level editor: drag parts from the palette onto the board, test-play the level right in the page, and
// save it as assets/levels/<name>.txt for the real game to pick up (task build / task run-map).

import { COLS, ROWS, makeTables, parseLevelText, compileLevel, serializeLevel, titleOf, blankRows } from './model.js';
import { Game, MODE, JOY, STATE } from './engine.js';
import { Atlas, COLORS, cellSize, drawMap, drawTile, drawSprite, drawHud, PEG_SHAPE } from './render.js';
import { GROUPS, STAMPS } from './palette.js';

const $ = (id) => document.getElementById(id);
const DRAFT_KEY = 'factoryEditor.draft';
const NAME_RE = /^[a-z][a-z0-9_]{0,39}$/;

let tables;
let atlas;
let sprites = [];
let ctx;
const canvas = $('board');

const S = {
  grid: [], // grid[r][c] = map character
  name: 'level6',
  title: '',
  loaded: null, // the text on disk when the level was loaded or last saved ('' for a new one)
  levels: [],
  brush: null,
  tool: 'brush', // brush | select
  zoom: 3,
  gridOn: true,
  hover: null,
  stroke: null,
  sel: null, // {c0, r0, c1, r1}
  move: null, // dragging the selection
  undo: [],
  redo: [],
  compiled: null,
  serverIssues: [],
  flash: null,
  mode: 'edit',
  play: null,
  server: true,
  dpr: 1,
  tick: 0,
};

// ------------------------------------------------------------------------------------------------
// server

async function call(path, method = 'GET', body = null) {
  const res = await fetch(`/api/${path}`, {
    method,
    headers: { 'X-Editor': '1', 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

// ------------------------------------------------------------------------------------------------
// the level in memory

const text = () => S.grid.map((r) => r.join(''));
const snapshot = () => text().join('\n');
const inside = (c, r) => c >= 0 && c < COLS && r >= 1 && r < ROWS;
const charOf = (name) => (name === 'PEG' ? 'p' : name === 'START' ? '@' : tables.tiles.find((t) => t.name === name).char);

function setGridFromRows(rows) {
  const warn = [];
  const grid = [];
  for (let r = 0; r < ROWS; r++) {
    const line = (rows[r] || '').padEnd(COLS, '.');
    if ((rows[r] || '').length > COLS) warn.push(`row ${r} was longer than ${COLS} columns and was cut`);
    grid.push(line.slice(0, COLS).split(''));
  }
  if (rows.length !== ROWS) warn.push(`the file had ${rows.length} map rows; it now has ${ROWS}`);
  S.grid = grid;
  return warn;
}

/** Where this level would sit among the game's levels (natural order of the file names): it sets the row hues. */
function levelIndex() {
  const key = (n) => n.split(/(\d+)/).map((x) => (/^\d+$/.test(x) ? Number(x) : x));
  const cmp = (a, b) => {
    const ka = key(a);
    const kb = key(b);
    for (let i = 0; i < Math.min(ka.length, kb.length); i++) {
      if (ka[i] === kb[i]) continue;
      return typeof ka[i] === typeof kb[i] ? (ka[i] < kb[i] ? -1 : 1) : typeof ka[i] === 'number' ? -1 : 1;
    }
    return ka.length - kb.length;
  };
  const names = S.levels.map((l) => l.name).filter((n) => n !== S.name);
  names.push(S.name);
  names.sort(cmp);
  return names.indexOf(S.name);
}

function loadLevel(name, fileText, { onDisk = true } = {}) {
  const parsed = parseLevelText(fileText);
  const warn = setGridFromRows(parsed.rows);
  S.name = name;
  S.title = titleOf(parsed.header);
  S.loaded = onDisk ? fileText : null;
  S.undo = [];
  S.redo = [];
  S.sel = null;
  S.serverIssues = [];
  changed(false);
  localStorage.removeItem(DRAFT_KEY);
  if (warn.length) toast(`Loaded with changes: ${warn.join('; ')}`, 'warn');
  syncForm();
}

function changed(dirtying = true) {
  S.compiled = compileLevel(text(), tables);
  if (dirtying) saveDraft();
  updateStatus();
  scheduleCheck();
  updateButtons();
}

function isDirty() {
  if (S.loaded === null) return snapshot() !== blankRows().join('\n') || S.title !== '';
  const base = parseLevelText(S.loaded);
  return snapshot() !== base.rows.join('\n') || S.title !== titleOf(base.header);
}

function saveDraft() {
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify({ name: S.name, title: S.title, text: serializeLevel(text(), S.name, S.title), loaded: S.loaded }));
  } catch {
    /* private mode or full: no draft */
  }
}

function pushUndo(before) {
  if (before === snapshot()) return false;
  S.undo.push(before);
  if (S.undo.length > 200) S.undo.shift();
  S.redo = [];
  changed();
  return true;
}

function restore(snap) {
  S.grid = snap.split('\n').map((r) => r.split(''));
  changed();
}

function undo() {
  if (!S.undo.length) return;
  S.redo.push(snapshot());
  restore(S.undo.pop());
}

function redo() {
  if (!S.redo.length) return;
  S.undo.push(snapshot());
  restore(S.redo.pop());
}

// ------------------------------------------------------------------------------------------------
// painting

function setCell(c, r, ch) {
  if (!inside(c, r)) return;
  if (ch === '@') for (const row of S.grid) for (let i = 0; i < COLS; i++) if (row[i] === '@') row[i] = '.';
  S.grid[r][c] = ch;
}

function paintBrush(c, r) {
  const b = S.brush;
  if (!b) return;
  if (b.kind === 'tile') setCell(c, r, charOf(b.name));
  else if (b.kind === 'erase') setCell(c, r, '.');
  else if (b.kind === 'peg') setCell(c, r, 'p');
  else if (b.kind === 'start') setCell(c, r, '@');
}

function placeStamp(stamp, c, r) {
  for (const [dc, dr, name] of stamp.cells) setCell(c + dc, r + dr, charOf(name));
}

function line(a, b, fn) {
  let [x0, y0] = a;
  const [x1, y1] = b;
  const dx = Math.abs(x1 - x0);
  const dy = -Math.abs(y1 - y0);
  const sx = x0 < x1 ? 1 : -1;
  const sy = y0 < y1 ? 1 : -1;
  let err = dx + dy;
  for (;;) {
    fn(x0, y0);
    if (x0 === x1 && y0 === y1) break;
    const e2 = 2 * err;
    if (e2 >= dy) {
      err += dy;
      x0 += sx;
    }
    if (e2 <= dx) {
      err += dx;
      y0 += sy;
    }
  }
}

function rectCells(a, b) {
  const out = [];
  for (let r = Math.min(a[1], b[1]); r <= Math.max(a[1], b[1]); r++) for (let c = Math.min(a[0], b[0]); c <= Math.max(a[0], b[0]); c++) out.push([c, r]);
  return out;
}

function cellAt(e) {
  const rect = canvas.getBoundingClientRect();
  const cell = cellSize(S.zoom);
  return [Math.max(0, Math.min(COLS - 1, Math.floor((e.clientX - rect.left) / cell))), Math.max(0, Math.min(ROWS - 1, Math.floor((e.clientY - rect.top) / cell)))];
}

const within = (sel, c, r) => sel && c >= sel.c0 && c <= sel.c1 && r >= sel.r0 && r <= sel.r1;

canvas.addEventListener('contextmenu', (e) => e.preventDefault());

canvas.addEventListener('pointerdown', (e) => {
  if (S.mode !== 'edit') return;
  canvas.focus();
  const [c, r] = cellAt(e);
  try {
    canvas.setPointerCapture(e.pointerId);
  } catch {
    /* a synthetic pointer: nothing to capture */
  }
  const before = snapshot();
  if (S.tool === 'select' && e.button === 0) {
    if (within(S.sel, c, r)) {
      const cells = [];
      for (const [cc, rr] of rectCells([S.sel.c0, S.sel.r0], [S.sel.c1, S.sel.r1])) cells.push([cc - S.sel.c0, rr - S.sel.r0, S.grid[rr][cc]]);
      S.move = { from: [c, r], cells, copy: e.altKey, before, dc: 0, dr: 0 };
    } else {
      S.sel = { c0: c, r0: Math.max(1, r), c1: c, r1: Math.max(1, r) };
      S.stroke = { kind: 'marquee', anchor: [c, Math.max(1, r)], before };
    }
    return;
  }
  const erase = e.button === 2;
  if (!erase && S.brush && S.brush.kind === 'stamp') {
    placeStamp(S.brush, c, r);
    pushUndo(before);
    return;
  }
  S.stroke = { kind: !erase && e.shiftKey ? 'rect' : 'free', erase, anchor: [c, r], last: [c, r], before };
  if (S.stroke.kind === 'free') strokeCell(c, r);
  changedLive();
});

function strokeCell(c, r) {
  if (S.stroke.erase) setCell(c, r, '.');
  else paintBrush(c, r);
}

function changedLive() {
  S.compiled = compileLevel(text(), tables);
}

canvas.addEventListener('pointermove', (e) => {
  const [c, r] = cellAt(e);
  S.hover = [c, r];
  updateStatus();
  if (S.move) {
    S.move.dc = c - S.move.from[0];
    S.move.dr = r - S.move.from[1];
  } else if (S.stroke) {
    const st = S.stroke;
    if (st.kind === 'marquee') {
      S.sel = { c0: Math.min(st.anchor[0], c), r0: Math.max(1, Math.min(st.anchor[1], r)), c1: Math.max(st.anchor[0], c), r1: Math.max(1, Math.max(st.anchor[1], r)) };
    } else if (st.kind === 'free') {
      line(st.last, [c, r], (x, y) => strokeCell(x, y));
      st.last = [c, r];
      changedLive();
    }
  }
});

canvas.addEventListener('pointerleave', () => {
  if (!S.stroke && !S.move) S.hover = null;
  updateStatus();
});

function endStroke(e) {
  const [c, r] = cellAt(e);
  if (S.move) {
    const m = S.move;
    S.move = null;
    if (m.dc || m.dr) {
      if (!m.copy) for (const [dc, dr] of m.cells) setCell(S.sel.c0 + dc, S.sel.r0 + dr, '.');
      for (const [dc, dr, ch] of m.cells) if (ch !== '.') setCell(S.sel.c0 + dc + m.dc, S.sel.r0 + dr + m.dr, ch);
      S.sel = { c0: S.sel.c0 + m.dc, r0: S.sel.r0 + m.dr, c1: S.sel.c1 + m.dc, r1: S.sel.r1 + m.dr };
      pushUndo(m.before);
    }
    return;
  }
  const st = S.stroke;
  if (!st) return;
  S.stroke = null;
  if (st.kind === 'marquee') return;
  if (st.kind === 'rect') for (const [x, y] of rectCells(st.anchor, [c, r])) (st.erase ? setCell(x, y, '.') : paintBrush(x, y));
  if (!pushUndo(st.before)) changedLive();
}

canvas.addEventListener('pointerup', endStroke);
canvas.addEventListener('pointercancel', endStroke);

// drag from the palette
canvas.addEventListener('dragover', (e) => {
  if (S.mode !== 'edit') return;
  e.preventDefault();
  S.hover = cellAt(e);
  updateStatus();
});
canvas.addEventListener('dragleave', () => {
  S.hover = null;
});
canvas.addEventListener('drop', (e) => {
  if (S.mode !== 'edit') return;
  e.preventDefault();
  const item = ITEMS[Number(e.dataTransfer.getData('text/plain'))];
  if (!item) return;
  selectBrush(item);
  const [c, r] = cellAt(e);
  const before = snapshot();
  if (item.kind === 'stamp') placeStamp(item, c, r);
  else paintBrush(c, r);
  pushUndo(before);
});

// ------------------------------------------------------------------------------------------------
// selection, clipboard

function selectionStamp(cut) {
  if (!S.sel) return null;
  const cells = [];
  for (const [c, r] of rectCells([S.sel.c0, S.sel.r0], [S.sel.c1, S.sel.r1])) {
    const ch = S.grid[r][c];
    if (ch === '.' || ch === '@') continue;
    const t = ch === 'p' ? 'PEG' : tables.tiles.find((x) => x.char === ch)?.name;
    if (t) cells.push([c - S.sel.c0, r - S.sel.r0, t]);
  }
  if (cut) {
    const before = snapshot();
    for (const [c, r] of rectCells([S.sel.c0, S.sel.r0], [S.sel.c1, S.sel.r1])) if (S.grid[r][c] !== '@') S.grid[r][c] = '.';
    pushUndo(before);
  }
  return cells.length ? { kind: 'stamp', label: 'Clipboard', cells, tip: 'What you copied: click to paste' } : null;
}

function clearSelection() {
  if (!S.sel) return;
  const before = snapshot();
  for (const [c, r] of rectCells([S.sel.c0, S.sel.r0], [S.sel.c1, S.sel.r1])) S.grid[r][c] = '.';
  pushUndo(before);
}

// ------------------------------------------------------------------------------------------------
// the palette

const ITEMS = [];

function iconFor(item, size) {
  const cv = document.createElement('canvas');
  cv.width = cv.height = size;
  const g = cv.getContext('2d');
  g.imageSmoothingEnabled = false;
  g.fillStyle = COLORS.bg;
  g.fillRect(0, 0, size, size);
  if (item.kind === 'tile') drawTile(g, atlas, tables.T[item.name], 0, 0, size);
  else if (item.kind === 'peg') {
    drawTile(g, atlas, tables.T.BRICK, 0, size * 0.25, size * 0.75);
    drawSprite(g, PEG_SHAPE, 0, 0, size, COLORS.peg, 8);
  } else if (item.kind === 'start') drawSprite(g, sprites[0], 0, 0, size / 2, COLORS.player, 16);
  else if (item.kind === 'erase') {
    g.strokeStyle = '#c55';
    g.lineWidth = 3;
    g.strokeRect(4, 4, size - 8, size - 8);
    g.beginPath();
    g.moveTo(4, 4);
    g.lineTo(size - 4, size - 4);
    g.stroke();
  }
  return cv;
}

function stampPreview(stamp) {
  const w = Math.max(...stamp.cells.map((c) => c[0])) + 1;
  const h = Math.max(...stamp.cells.map((c) => c[1])) + 1;
  const cell = 12;
  const cv = document.createElement('canvas');
  cv.width = w * cell;
  cv.height = h * cell;
  const g = cv.getContext('2d');
  g.imageSmoothingEnabled = false;
  g.fillStyle = COLORS.bg;
  g.fillRect(0, 0, cv.width, cv.height);
  for (const [c, r, name] of stamp.cells) {
    if (name === 'PEG') {
      drawSprite(g, PEG_SHAPE, c * 4, r * 8, cell, COLORS.peg, 8);
    } else drawTile(g, atlas, tables.T[name], c * cell, r * cell, cell);
  }
  return cv;
}

function addItem(item) {
  item.id = ITEMS.length;
  ITEMS.push(item);
  return item;
}

function buildPalette() {
  const root = $('palette');
  root.textContent = '';
  const make = (item, node) => {
    node.className = 'pal-item';
    node.setAttribute('role', 'button');
    node.tabIndex = 0;
    node.draggable = true;
    node.title = item.tip || '';
    node.setAttribute('aria-label', item.label || item.tip || item.name || item.kind);
    node.dataset.item = item.id;
    node.addEventListener('click', () => selectBrush(item));
    node.addEventListener('dragstart', (e) => {
      e.dataTransfer.setData('text/plain', String(item.id));
      e.dataTransfer.effectAllowed = 'copy';
      const img = node.querySelector('canvas');
      if (img) e.dataTransfer.setDragImage(img, 8, 8);
      selectBrush(item);
    });
    return node;
  };
  for (const g of GROUPS) {
    const h = document.createElement('h3');
    h.textContent = g.title;
    root.append(h);
    const box = document.createElement('div');
    box.className = 'pal-grid';
    for (const it of g.items) {
      addItem(it);
      const btn = make(it, document.createElement('div'));
      btn.append(iconFor(it, 32));
      box.append(btn);
    }
    root.append(box);
  }
  const h = document.createElement('h3');
  h.textContent = 'Ready-made (drag or click, then click the board)';
  root.append(h);
  const box = document.createElement('div');
  box.className = 'pal-stamps';
  for (const st of STAMPS) {
    st.kind = 'stamp';
    addItem(st);
    const btn = make(st, document.createElement('div'));
    btn.classList.add('stamp');
    btn.append(stampPreview(st));
    const label = document.createElement('span');
    label.textContent = st.label;
    btn.append(label);
    box.append(btn);
  }
  root.append(box);
  selectBrush(ITEMS[0]);
}

function selectBrush(item) {
  S.brush = item;
  S.tool = 'brush';
  document.querySelectorAll('.pal-item').forEach((n) => n.classList.toggle('selected', Number(n.dataset.item) === item.id));
  updateTools();
  updateStatus();
}

function updateTools() {
  $('tool-brush').classList.toggle('on', S.tool === 'brush');
  $('tool-select').classList.toggle('on', S.tool === 'select');
  canvas.style.cursor = S.tool === 'select' ? 'crosshair' : 'cell';
}

// ------------------------------------------------------------------------------------------------
// checking the level

let checkTimer = null;
function scheduleCheck() {
  clearTimeout(checkTimer);
  if (!S.server) return;
  checkTimer = setTimeout(async () => {
    try {
      const res = await call('check', 'POST', { text: serializeLevel(text(), S.name, S.title) });
      S.serverIssues = [...res.errors.map((m) => ({ msg: m, level: 'error' })), ...res.problems.map((m) => ({ msg: m, level: 'warn' }))];
      renderIssues();
    } catch {
      /* the server went away: keep the local checks */
    }
  }, 500);
}

function locate(msg) {
  let m = /column (\d+), row (\d+)/.exec(msg);
  if (m) return [Number(m[1]), Number(m[2])];
  m = /row (\d+), column (\d+)/.exec(msg);
  if (m) return [Number(m[2]), Number(m[1])];
  return null;
}

function issues() {
  const out = [];
  const comp = S.compiled;
  for (const e of comp.errors) out.push({ msg: e.msg, level: 'error', at: e.c !== undefined ? [e.c, e.r] : null });
  for (const w of comp.warnings) out.push({ msg: w.msg, level: 'warn', at: [w.c, w.r] });
  const seen = new Set(out.map((o) => o.msg));
  for (const s of S.serverIssues) {
    if (seen.has(s.msg)) continue;
    if (s.level === 'error' && comp.errors.length) continue; // the same thing, worded by the asset tool
    out.push({ ...s, at: locate(s.msg) });
  }
  return out;
}

function renderIssues() {
  const list = $('issues');
  list.textContent = '';
  const all = issues();
  const errors = all.filter((i) => i.level === 'error').length;
  const comp = S.compiled;
  $('summary').textContent = `${comp.stars} item${comp.stars === 1 ? '' : 's'}, ${comp.dots} dot${comp.dots === 1 ? '' : 's'}, ${comp.pegs.length} peg${comp.pegs.length === 1 ? '' : 's'}`;
  $('verdict').className = errors ? 'bad' : all.length ? 'meh' : 'good';
  $('verdict').textContent = errors ? `${errors} problem${errors === 1 ? '' : 's'} to fix before saving` : all.length ? 'Can be saved; check the notes below' : 'Looks good';
  for (const i of all) {
    const li = document.createElement('li');
    li.className = i.level;
    li.textContent = i.msg;
    if (i.at) {
      li.classList.add('link');
      li.title = 'Click to find it on the board';
      li.addEventListener('click', () => {
        S.flash = { c: i.at[0], r: i.at[1], until: performance.now() + 1800 };
      });
    }
    list.append(li);
  }
  if (!all.length) {
    const li = document.createElement('li');
    li.className = 'ok';
    li.textContent = 'Every item, dot and the door look reachable (approximately) and the level compiles.';
    list.append(li);
  }
}

// ------------------------------------------------------------------------------------------------
// drawing the editor view

function sizeCanvas() {
  const cell = cellSize(S.zoom);
  const dpr = Math.max(1, Math.round(window.devicePixelRatio || 1));
  S.dpr = dpr;
  canvas.width = COLS * cell * dpr;
  canvas.height = ROWS * cell * dpr;
  canvas.style.width = `${COLS * cell}px`;
  canvas.style.height = `${ROWS * cell}px`;
}

function drawEditor() {
  const cell = cellSize(S.zoom);
  const comp = S.compiled;
  atlas.levelIndex = levelIndex();
  ctx.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
  ctx.imageSmoothingEnabled = false;
  drawMap(ctx, atlas, comp.map, cell);
  // row 0 belongs to the score display
  ctx.fillStyle = '#16161c';
  ctx.fillRect(0, 0, COLS * cell, cell);
  ctx.globalAlpha = 0.55;
  drawHud(ctx, cell, { score: 0, level: Number((/\d+/.exec(S.name) || [0])[0]), lives: 3, left: comp.items });
  ctx.globalAlpha = 1;
  // pegs and their runs
  for (const [x, y, min, max] of comp.pegs) {
    ctx.fillStyle = 'rgba(255,90,74,0.16)';
    ctx.fillRect((min / 4) * cell, (y / 8) * cell, ((max - min) / 4 + 1) * cell, cell);
    drawSprite(ctx, PEG_SHAPE, x, y, cell, COLORS.peg, 8);
  }
  for (const [c, r] of comp.pegMarks) {
    if (comp.errors.some((e) => e.c === c && e.r === r)) {
      ctx.fillStyle = 'rgba(255,60,60,0.5)';
      ctx.fillRect(c * cell, r * cell, cell, cell);
      ctx.fillStyle = '#fff';
      ctx.font = `bold ${cell * 0.8}px monospace`;
      ctx.textBaseline = 'middle';
      ctx.textAlign = 'center';
      ctx.fillText('p', c * cell + cell / 2, r * cell + cell / 2);
      ctx.textAlign = 'left';
    }
  }
  if (comp.spawn) drawSprite(ctx, sprites[0], comp.spawn[0] * 4, comp.spawn[1] * 8, cell, COLORS.player, 16);
  // grid
  if (S.gridOn) {
    ctx.strokeStyle = 'rgba(255,255,255,0.10)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let c = 0; c <= COLS; c++) {
      ctx.moveTo(c * cell + 0.5, 0);
      ctx.lineTo(c * cell + 0.5, ROWS * cell);
    }
    for (let r = 0; r <= ROWS; r++) {
      ctx.moveTo(0, r * cell + 0.5);
      ctx.lineTo(COLS * cell, r * cell + 0.5);
    }
    ctx.stroke();
  }
  // problems
  ctx.strokeStyle = '#ff5050';
  ctx.lineWidth = 2;
  for (const i of issues()) if (i.at && i.level === 'error') ctx.strokeRect(i.at[0] * cell + 1, i.at[1] * cell + 1, cell - 2, cell - 2);
  ctx.strokeStyle = '#ffc040';
  for (const i of issues()) if (i.at && i.level === 'warn') ctx.strokeRect(i.at[0] * cell + 1, i.at[1] * cell + 1, cell - 2, cell - 2);
  if (S.flash && performance.now() < S.flash.until) {
    const on = Math.floor(performance.now() / 150) % 2 === 0;
    ctx.strokeStyle = on ? '#fff' : '#35f';
    ctx.lineWidth = 3;
    ctx.strokeRect(S.flash.c * cell - 3, S.flash.r * cell - 3, cell + 6, cell + 6);
  }
  drawGhost(cell);
  if (S.sel) {
    const { c0, r0, c1, r1 } = S.sel;
    ctx.strokeStyle = '#4af';
    ctx.fillStyle = 'rgba(70,170,255,0.15)';
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.fillRect(c0 * cell, r0 * cell, (c1 - c0 + 1) * cell, (r1 - r0 + 1) * cell);
    ctx.strokeRect(c0 * cell, r0 * cell, (c1 - c0 + 1) * cell, (r1 - r0 + 1) * cell);
    ctx.setLineDash([]);
    if (S.move && (S.move.dc || S.move.dr)) {
      for (const [dc, dr, ch] of S.move.cells) {
        const b = ch === '.' ? 0 : ch === 'p' || ch === '@' ? 0 : tables.chars[ch];
        if (b) drawTile(ctx, atlas, b, (c0 + dc + S.move.dc) * cell, (r0 + dr + S.move.dr) * cell, cell, 0.7);
      }
    }
  }
}

function drawGhost(cell) {
  if (!S.hover || S.mode !== 'edit' || S.tool !== 'brush' || S.move) return;
  const [c, r] = S.hover;
  const b = S.brush;
  if (!b) return;
  const put = (cc, rr, name) => {
    if (!inside(cc, rr)) return;
    if (name === 'PEG') drawSprite(ctx, PEG_SHAPE, cc * 4, rr * 8, cell, 'rgba(255,90,74,0.7)', 8);
    else if (name === 'START') drawSprite(ctx, sprites[0], cc * 4, rr * 8, cell, 'rgba(255,224,64,0.7)', 16);
    else if (name === 'ERASE') {
      ctx.fillStyle = 'rgba(255,255,255,0.2)';
      ctx.fillRect(cc * cell, rr * cell, cell, cell);
    } else drawTile(ctx, atlas, tables.T[name], cc * cell, rr * cell, cell, 0.65);
  };
  if (S.stroke && S.stroke.kind === 'rect') {
    for (const [x, y] of rectCells(S.stroke.anchor, [c, r])) put(x, y, S.stroke.erase ? 'ERASE' : b.kind === 'tile' ? b.name : b.kind === 'peg' ? 'PEG' : b.kind === 'start' ? 'START' : 'ERASE');
    return;
  }
  if (b.kind === 'stamp') for (const [dc, dr, n] of b.cells) put(c + dc, r + dr, n);
  else put(c, r, b.kind === 'tile' ? b.name : b.kind === 'peg' ? 'PEG' : b.kind === 'start' ? 'START' : 'ERASE');
  ctx.strokeStyle = 'rgba(255,255,255,0.6)';
  ctx.lineWidth = 1;
  ctx.strokeRect(c * cell + 0.5, r * cell + 0.5, cell - 1, cell - 1);
}

// ------------------------------------------------------------------------------------------------
// play test

const KEYS = {
  ArrowUp: JOY.UP, w: JOY.UP, W: JOY.UP,
  ArrowDown: JOY.DOWN, s: JOY.DOWN, S: JOY.DOWN,
  ArrowLeft: JOY.LEFT, a: JOY.LEFT, A: JOY.LEFT,
  ArrowRight: JOY.RIGHT, d: JOY.RIGHT, D: JOY.RIGHT,
  ' ': JOY.FIRE, z: JOY.FIRE, Z: JOY.FIRE, x: JOY.FIRE, X: JOY.FIRE,
};
const held = new Set();

function startPlay(fromHover = false) {
  const comp = S.compiled;
  if (comp.errors.length) {
    toast(`Fix first: ${comp.errors[0].msg}`, 'error');
    return;
  }
  const game = new Game({ map: comp.map, spawn: comp.spawn, items: comp.items, pegs: comp.pegs }, tables, { lives: 3 });
  if (fromHover && S.hover && inside(S.hover[0], S.hover[1])) {
    game.px = S.hover[0] * 4;
    game.py = S.hover[1] * 8;
    game.mode = MODE.PLAY;
    game.drawn = 16;
  }
  S.mode = 'play';
  S.play = { game, levelIndex: levelIndex(), acc: 0, last: performance.now(), tick: 0, overlay: null, fromHover, start: fromHover && S.hover ? [...S.hover] : null, level: Number((/\d+/.exec(S.name) || [1])[0]) };
  held.clear();
  document.body.classList.add('playing');
  $('play').textContent = 'Stop (Esc)';
  updateStatus();
  canvas.focus();
}

function stopPlay() {
  S.mode = 'edit';
  S.play = null;
  held.clear();
  document.body.classList.remove('playing');
  $('play').textContent = 'Play test (P)';
  updateStatus();
}

function stepPlay(now) {
  const p = S.play;
  const dt = Math.min(250, now - p.last);
  p.last = now;
  if (p.overlay) return;
  p.acc += dt;
  let n = 0;
  while (p.acc >= 20 && n < 6) {
    p.acc -= 20;
    n++;
    let bits = 0;
    for (const k of held) bits |= KEYS[k] || 0;
    p.game.step(bits);
    p.tick++;
    atlas.animateBelts(p.tick);
    for (const ev of p.game.events.splice(0)) {
      if (ev === 'cleared') p.overlay = { title: 'LEVEL CLEAR!', hint: 'Enter: play again    Esc: back to editing' };
      if (ev === 'gameover') p.overlay = { title: 'GAME OVER', hint: 'Enter: try again    Esc: back to editing' };
    }
    if (p.overlay) break;
  }
}

function drawPlay() {
  const p = S.play;
  const g = p.game;
  const cell = cellSize(S.zoom);
  atlas.levelIndex = p.levelIndex;
  ctx.setTransform(S.dpr, 0, 0, S.dpr, 0, 0);
  ctx.imageSmoothingEnabled = false;
  drawMap(ctx, atlas, g.map, cell);
  for (const peg of g.pegs) drawSprite(ctx, PEG_SHAPE, peg.x, peg.y, cell, COLORS.peg, 8);
  if (g.mode !== MODE.OVER && g.py < 200) {
    let colour = COLORS.player;
    if (g.mode === MODE.SPAWN) colour = `hsl(${(g.mtimer * 22) % 360} 90% 60%)`;
    else if (g.mode === MODE.DYING) colour = g.mtimer & 2 ? '#e84a4a' : COLORS.player;
    const rows = (sprites[g.frame] || sprites[0]);
    drawSprite(ctx, rows, g.px, g.py, cell, colour, g.drawn);
  }
  drawHud(ctx, cell, { score: g.score, level: p.level, lives: g.lives, left: g.left });
  if (g.mode === MODE.CLEAR) {
    ctx.fillStyle = `rgba(80,255,120,${0.25 * (1 - g.mtimer / 60)})`;
    ctx.fillRect(0, cell, COLS * cell, (ROWS - 1) * cell);
  }
  if (g.mode === MODE.DYING && g.mtimer < 12) {
    ctx.fillStyle = `rgba(255,50,40,${0.3 * (1 - g.mtimer / 12)})`;
    ctx.fillRect(0, cell, COLS * cell, (ROWS - 1) * cell);
  }
  if (p.overlay) {
    ctx.fillStyle = 'rgba(0,0,0,0.6)';
    ctx.fillRect(0, (ROWS / 2 - 3) * cell, COLS * cell, 6 * cell);
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.font = `bold ${cell * 1.4}px ui-monospace, Menlo, monospace`;
    ctx.fillText(p.overlay.title, (COLS * cell) / 2, (ROWS / 2 - 0.8) * cell);
    ctx.font = `${cell * 0.6}px ui-monospace, Menlo, monospace`;
    ctx.fillText(p.overlay.hint, (COLS * cell) / 2, (ROWS / 2 + 1.4) * cell);
    ctx.textAlign = 'left';
  }
}

function frame(now) {
  requestAnimationFrame(frame);
  if (!ctx) return;
  if (S.mode === 'play') {
    stepPlay(now);
    drawPlay();
  } else {
    S.tick = Math.floor(now / 20);
    atlas.animateBelts(S.tick);
    drawEditor();
  }
}

// ------------------------------------------------------------------------------------------------
// buttons, keys, forms

function toast(msg, level = 'info') {
  const t = $('toast');
  t.textContent = msg;
  t.className = `show ${level}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.className = ''), level === 'error' ? 8000 : 4500);
}

function updateStatus() {
  const bar = $('status');
  if (S.mode === 'play') {
    bar.textContent = 'PLAYING   arrows / WASD move   Space / Z jump   R restart   Esc back to editing';
    return;
  }
  const brush = S.tool === 'select' ? 'select' : S.brush ? S.brush.label || S.brush.name || S.brush.kind : '';
  let where = '';
  if (S.hover) {
    const [c, r] = S.hover;
    const ch = S.grid[r][c];
    const t = ch === '@' ? 'player start' : ch === 'p' ? 'peg' : (tables.tiles.find((x) => x.char === ch) || {}).name || ch;
    where = `column ${c}, row ${r}: ${t}`;
  }
  bar.textContent = `${where}${where ? '    ' : ''}Tool: ${brush}`;
}

function updateButtons() {
  $('undo').disabled = !S.undo.length;
  $('redo').disabled = !S.redo.length;
  $('dirty').hidden = !isDirty();
  renderIssues();
}

function syncForm() {
  $('name').value = S.name;
  $('title').value = S.title;
  refreshLevelSelect();
  updateButtons();
}

function refreshLevelSelect() {
  const sel = $('level-select');
  sel.textContent = '';
  for (const lv of S.levels) {
    const o = document.createElement('option');
    o.value = lv.name;
    o.textContent = `${lv.index}. ${lv.name}${lv.title ? ` - ${lv.title}` : ''}`;
    sel.append(o);
  }
  if (!S.levels.some((l) => l.name === S.name)) {
    const o = document.createElement('option');
    o.value = S.name;
    o.textContent = `${S.name} (not saved yet)`;
    sel.append(o);
  }
  sel.value = S.name;
}

async function refreshLevels() {
  S.levels = await call('levels');
  refreshLevelSelect();
}

function confirmDiscard() {
  return !isDirty() || confirm('This level has changes that are not saved. Discard them?');
}

async function openLevel(name) {
  if (!confirmDiscard()) {
    $('level-select').value = S.name;
    return;
  }
  try {
    const res = await call(`level/${name}`);
    loadLevel(name, res.text);
  } catch (e) {
    toast(`Could not open ${name}: ${e.message}`, 'error');
  }
}

function nextName() {
  const nums = S.levels.map((l) => Number((/\d+$/.exec(l.name) || [0])[0]));
  return `level${Math.max(0, ...nums) + 1}`;
}

function newLevel() {
  if (!confirmDiscard()) return;
  const name = prompt('Name for the new level (lowercase letters, digits, _):', nextName());
  if (!name) return;
  if (!NAME_RE.test(name)) return toast('A level name is lowercase letters, digits and underscores, starting with a letter.', 'error');
  setGridFromRows(blankRows());
  S.name = name;
  S.title = '';
  S.loaded = null;
  S.undo = [];
  S.redo = [];
  S.sel = null;
  S.serverIssues = [];
  changed();
  syncForm();
}

function duplicateLevel() {
  const name = prompt('Name for the copy:', nextName());
  if (!name) return;
  if (!NAME_RE.test(name)) return toast('A level name is lowercase letters, digits and underscores, starting with a letter.', 'error');
  S.name = name;
  S.loaded = null;
  changed();
  syncForm();
  toast(`Editing a copy called ${name}. Save it to add it to the game.`);
}

async function save() {
  const errors = S.compiled.errors;
  if (errors.length) {
    toast(`Cannot save yet: ${errors[0].msg}`, 'error');
    return false;
  }
  S.name = $('name').value.trim();
  S.title = $('title').value.trim();
  if (!NAME_RE.test(S.name)) {
    toast('A level name is lowercase letters, digits and underscores, starting with a letter.', 'error');
    return false;
  }
  const exists = S.levels.some((l) => l.name === S.name);
  if (exists && S.loaded === null && !confirm(`${S.name} already exists in the game. Replace it?`)) return false;
  const body = serializeLevel(text(), S.name, S.title);
  try {
    const res = await call(`level/${S.name}`, 'PUT', { text: body });
    S.loaded = body;
    S.serverIssues = res.problems.map((m) => ({ msg: m, level: 'warn' }));
    localStorage.removeItem(DRAFT_KEY);
    await refreshLevels();
    syncForm();
    toast(`Saved ${res.path} as map ${res.index}. Run \`task build\` (or press "Run in emulator") to play it.`);
    return true;
  } catch (e) {
    toast(`Not saved: ${e.message}`, 'error');
    return false;
  }
}

async function runInEmulator() {
  if (isDirty() && !(await save())) return;
  try {
    const res = await call('run', 'POST', { name: S.name });
    toast(`Building and starting the game on map ${res.index}...`);
  } catch (e) {
    toast(e.message, 'error');
  }
}

function download() {
  const body = serializeLevel(text(), $('name').value.trim() || S.name, $('title').value.trim());
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([body], { type: 'text/plain' }));
  a.download = `${$('name').value.trim() || S.name}.txt`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function importFile(file) {
  const reader = new FileReader();
  reader.onload = () => {
    if (!confirmDiscard()) return;
    const name = file.name.replace(/\.txt$/, '').toLowerCase().replace(/[^a-z0-9_]/g, '_').replace(/^[^a-z]+/, 'level_');
    loadLevel(name, String(reader.result), { onDisk: false });
    changed();
    toast(`Imported ${file.name}`);
  };
  reader.readAsText(file);
}

function wire() {
  $('level-select').addEventListener('change', (e) => openLevel(e.target.value));
  $('new').addEventListener('click', newLevel);
  $('duplicate').addEventListener('click', duplicateLevel);
  $('save').addEventListener('click', save);
  $('run').addEventListener('click', runInEmulator);
  $('download').addEventListener('click', download);
  $('import').addEventListener('change', (e) => e.target.files[0] && importFile(e.target.files[0]));
  $('undo').addEventListener('click', undo);
  $('redo').addEventListener('click', redo);
  $('play').addEventListener('click', () => (S.mode === 'play' ? stopPlay() : startPlay(false)));
  $('tool-brush').addEventListener('click', () => {
    S.tool = 'brush';
    updateTools();
  });
  $('tool-select').addEventListener('click', () => {
    S.tool = 'select';
    updateTools();
  });
  $('grid').addEventListener('change', (e) => (S.gridOn = e.target.checked));
  $('zoom').addEventListener('change', (e) => {
    S.zoom = Number(e.target.value);
    sizeCanvas();
  });
  $('name').addEventListener('input', () => {
    S.name = $('name').value.trim();
    saveDraft();
  });
  $('title').addEventListener('input', () => {
    S.title = $('title').value.trim();
    saveDraft();
    updateButtons();
  });
  window.addEventListener('beforeunload', (e) => {
    if (isDirty()) e.preventDefault();
  });
  window.addEventListener('keydown', onKey);
  window.addEventListener('keyup', (e) => held.delete(e.key));
  window.addEventListener('blur', () => held.clear());
}

function onKey(e) {
  const tag = (e.target.tagName || '').toLowerCase();
  const typing = tag === 'input' || tag === 'textarea' || tag === 'select';
  const mod = e.metaKey || e.ctrlKey;
  if (mod && e.key.toLowerCase() === 's') {
    e.preventDefault();
    if (S.mode === 'edit') save();
    return;
  }
  if (S.mode === 'play') {
    if (e.key === 'Escape') return stopPlay();
    if (KEYS[e.key] !== undefined) {
      e.preventDefault();
      held.add(e.key);
      return;
    }
    if (e.key === 'r' || e.key === 'R' || (e.key === 'Enter' && S.play.overlay)) {
      const from = S.play.fromHover ? S.play.start : null;
      if (from) S.hover = from;
      startPlay(!!from);
    }
    return;
  }
  if (typing) return;
  if (mod && e.key.toLowerCase() === 'z') {
    e.preventDefault();
    return e.shiftKey ? redo() : undo();
  }
  if (mod && e.key.toLowerCase() === 'y') {
    e.preventDefault();
    return redo();
  }
  if (mod && e.key.toLowerCase() === 'a') {
    e.preventDefault();
    S.tool = 'select';
    S.sel = { c0: 0, r0: 1, c1: COLS - 1, r1: ROWS - 1 };
    return updateTools();
  }
  if (mod && (e.key.toLowerCase() === 'c' || e.key.toLowerCase() === 'x')) {
    const st = selectionStamp(e.key.toLowerCase() === 'x');
    if (st) {
      e.preventDefault();
      addItem(st);
      selectBrush(st);
      S.sel = null;
      toast('Copied. Click the board to paste it.');
    }
    return;
  }
  if (e.key === 'Delete' || e.key === 'Backspace') {
    e.preventDefault();
    return clearSelection();
  }
  if (e.key === 'Escape') {
    S.sel = null;
    return;
  }
  const k = e.key.toLowerCase();
  if (k === 'p') return startPlay(e.shiftKey);
  if (k === 'b') {
    S.tool = 'brush';
    return updateTools();
  }
  if (k === 'v') {
    S.tool = 'select';
    return updateTools();
  }
  if (k === 'e') return selectBrush(ITEMS.find((i) => i.kind === 'erase'));
  if (k === 'g') {
    S.gridOn = !S.gridOn;
    $('grid').checked = S.gridOn;
  }
}

// ------------------------------------------------------------------------------------------------
// start up

async function boot() {
  let api;
  try {
    api = await call('tiles');
  } catch (e) {
    $('fatal').hidden = false;
    $('fatal').textContent = `Cannot reach the editor server (${e.message}). Start it with:  task editor`;
    return;
  }
  tables = makeTables(api);
  atlas = new Atlas(api);
  sprites = api.sprites.map((s) => s.rows);
  ctx = canvas.getContext('2d');
  try {
    S.levels = await call('levels');
  } catch {
    S.levels = [];
    S.server = false;
  }
  const avail = window.innerWidth - 520;
  S.zoom = Math.max(2, Math.min(4, Math.floor(avail / 320)));
  $('zoom').value = String(S.zoom);
  sizeCanvas();
  buildPalette();
  wire();
  S.name = nextName();
  setGridFromRows(blankRows());
  S.compiled = compileLevel(text(), tables);
  let draft = null;
  try {
    draft = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null');
  } catch {
    draft = null;
  }
  if (draft && draft.text) {
    loadLevel(draft.name, draft.text, { onDisk: false });
    S.loaded = draft.loaded;
    changed();
    toast('Restored your unsaved work from last time.');
  } else if (S.levels.length) {
    const last = S.levels[S.levels.length - 1];
    try {
      loadLevel(last.name, (await call(`level/${last.name}`)).text);
    } catch {
      changed(false);
    }
  } else changed(false);
  syncForm();
  window.editor = { S, tables, atlas, text, startPlay, stopPlay, save, loadLevel, undo, redo, selectBrush, ITEMS, held };
  requestAnimationFrame(frame);
}

boot();
