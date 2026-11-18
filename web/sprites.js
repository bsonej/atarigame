// The sprite editor: Mr. Bubble's 13 frames as 8x16 pixel grids. Save writes assets/sprites.txt through the editor
// server (PUT /api/sprites); the game picks the change up on its next build, the level editor on its next focus.

import { COLORS, atariColour } from './render.js';
import { ANIMATIONS, BODY, EYE, FLOAT, H, NONE, SpriteDoc, W, checkFrames, maxLift, parseSprites, serializeSprites } from './spritemodel.js';

const $ = (id) => document.getElementById(id);
const DRAFT_KEY = 'spriteEditor.draft';
const FLOOR = atariColour(0x9c); // something to stand on in the previews
const TOOLS = { body: BODY, eye: EYE, erase: NONE };

const S = {
  sel: 0,
  tool: 'body',
  zoom: 40,
  gridOn: true,
  wide: false,
  guides: true,
  hover: null, // [x, y] under the mouse
  anim: ANIMATIONS[0],
  playing: true,
  speed: 2,
  scale: 3,
  tick: 0,
  template: '', // the text of sprites.txt as loaded: the header and comments the file keeps
  path: 'assets/sprites.txt',
};

let doc = null;
let names = [];
const canvas = $('grid');
const g = canvas.getContext('2d');

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

function toast(msg, level = 'info') {
  const t = $('toast');
  t.textContent = msg;
  t.className = `show ${level}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.className = ''), level === 'error' ? 8000 : 3500);
}

// ------------------------------------------------------------------------------------------------
// drawing

/** Draw a frame as the game does: black, eyes (Player 3) first, body (Player 0) over them. (x, y) is the top left, in game pixels. */
function drawFrame(ctx, rows, x, y, pw, ph) {
  for (const [ch, colour] of [[EYE, COLORS.eye], [BODY, COLORS.player]]) {
    ctx.fillStyle = colour;
    rows.forEach((row, ry) => {
      for (let rx = 0; rx < W; rx++) if (row[rx] === ch) ctx.fillRect((x + rx) * pw, (y + ry) * ph, pw, ph);
    });
  }
}

function sizeGrid() {
  const ch = S.zoom;
  const cw = S.wide ? ch * 2 : ch;
  canvas.width = W * cw;
  canvas.height = H * ch;
  canvas.style.width = `${W * cw}px`;
  canvas.style.height = `${H * ch}px`;
  return [cw, ch];
}

function drawGrid() {
  const [cw, ch] = sizeGrid();
  g.fillStyle = '#0b0c10';
  g.fillRect(0, 0, canvas.width, canvas.height);
  // empty pixels get a faint checker so a hole can be told from the page
  g.fillStyle = '#14161c';
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) if ((x + y) & 1) g.fillRect(x * cw, y * ch, cw, ch);
  drawFrame(g, doc.rows(S.sel), 0, 0, cw, ch);
  if (S.gridOn) {
    g.strokeStyle = 'rgba(255,255,255,0.16)';
    g.lineWidth = 1;
    g.beginPath();
    for (let x = 0; x <= W; x++) {
      g.moveTo(x * cw + 0.5, 0);
      g.lineTo(x * cw + 0.5, H * ch);
    }
    for (let y = 0; y <= H; y++) {
      g.moveTo(0, y * ch + 0.5);
      g.lineTo(W * cw, y * ch + 0.5);
    }
    g.stroke();
  }
  if (S.guides) {
    // the physics box is 4 pixels wide, centred (columns 2-5); the bottom FLOAT lines float above the surface
    g.save();
    g.strokeStyle = 'rgba(240,160,48,0.85)';
    g.lineWidth = 2;
    g.setLineDash([6, 4]);
    g.strokeRect(2 * cw + 1, 1, 4 * cw - 2, H * ch - 2);
    g.strokeStyle = 'rgba(100,170,255,0.9)';
    g.beginPath();
    g.moveTo(0, (H - FLOAT) * ch);
    g.lineTo(W * cw, (H - FLOAT) * ch);
    g.stroke();
    g.restore();
  }
  if (S.hover) {
    g.strokeStyle = '#fff';
    g.lineWidth = 2;
    g.strokeRect(S.hover[0] * cw + 1, S.hover[1] * ch + 1, cw - 2, ch - 2);
  }
}

/** One game pixel is 2*s wide and s tall (CSS pixels), s = 1 being the actual size on a 1x screen. */
function drawScene(cv, rows, scale, { lift = 0, room = 0 } = {}) {
  const pad = 2;
  const wGame = W + 2 * pad;
  const hGame = room + H + FLOAT + 8; // room above him, his sprite, the gap he floats in, 8 lines of floor
  cv.width = wGame * 2 * scale;
  cv.height = hGame * scale;
  cv.style.width = `${cv.width}px`;
  cv.style.height = `${cv.height}px`;
  const c = cv.getContext('2d');
  c.fillStyle = COLORS.bg;
  c.fillRect(0, 0, cv.width, cv.height);
  c.fillStyle = FLOOR;
  c.fillRect(0, (room + H + FLOAT) * scale, cv.width, 8 * scale);
  // the bottom of his physics box is the floor; the picture is drawn FLOAT lines above that
  drawFrame(c, rows, pad, room - lift, 2 * scale, scale);
}

function thumb(cv, rows) {
  cv.width = W * 2;
  cv.height = H;
  const c = cv.getContext('2d');
  c.fillStyle = COLORS.bg;
  c.fillRect(0, 0, cv.width, cv.height);
  drawFrame(c, rows, 0, 0, 2, 1);
}

function drawPreviews() {
  drawScene($('pv1'), doc.rows(S.sel), 1);
  drawScene($('pv4'), doc.rows(S.sel), 4);
}

function frameIndex(name) {
  return names.indexOf(name);
}

function drawAnim() {
  const anim = S.anim;
  const ticks = anim.ticks;
  const i = Math.floor(S.tick / S.speed) % ticks.length;
  const t = ticks[i];
  const idx = frameIndex(t.name);
  const cv = $('anim-canvas');
  drawScene(cv, idx >= 0 ? doc.rows(idx) : doc.rows(0), S.scale, { lift: t.lift, room: maxLift(anim) });
  $('anim-frame').textContent = idx >= 0 ? `${t.name}  (frame ${idx})` : `${t.name}: this file has no such frame`;
}

// ------------------------------------------------------------------------------------------------
// the frame list

function buildFrameList() {
  const ul = $('frames');
  ul.textContent = '';
  doc.frames.forEach((f, i) => {
    const li = document.createElement('li');
    li.dataset.i = String(i);
    li.tabIndex = 0;
    const cv = document.createElement('canvas');
    cv.className = 'thumb';
    const label = document.createElement('span');
    label.className = 'fname';
    label.textContent = f.name;
    const idx = document.createElement('span');
    idx.className = 'findex';
    idx.textContent = String(i);
    const dot = document.createElement('span');
    dot.className = 'fdirty';
    dot.title = 'changed, not saved yet';
    dot.textContent = '\u25cf';
    li.append(cv, idx, label, dot);
    li.addEventListener('click', () => select(i));
    li.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        select(i);
      }
    });
    ul.append(li);
  });
}

function refreshFrameList() {
  [...$('frames').children].forEach((li, i) => {
    li.classList.toggle('selected', i === S.sel);
    li.classList.toggle('changed', doc.dirty(i));
    thumb(li.querySelector('canvas'), doc.rows(i));
  });
}

function select(i) {
  S.sel = Math.max(0, Math.min(doc.frames.length - 1, i));
  refresh();
  const li = $('frames').children[S.sel];
  if (li && li.scrollIntoView) li.scrollIntoView({ block: 'nearest' });
}

// ------------------------------------------------------------------------------------------------
// state to screen

function refresh() {
  drawGrid();
  drawPreviews();
  refreshFrameList();
  $('frame-name').textContent = `${S.sel}: ${doc.frames[S.sel].name}`;
  $('undo').disabled = !doc.canUndo;
  $('redo').disabled = !doc.canRedo;
  $('paste').disabled = !doc.clipboard;
  $('mirror').disabled = doc.counterpart(S.sel) < 0;
  const other = doc.counterpart(S.sel);
  $('mirror').textContent = other >= 0 ? `Mirror to ${doc.frames[other].name}` : 'Mirror to other side';
  $('revert').disabled = !doc.dirty(S.sel);
  const dirty = doc.dirty();
  $('dirty').hidden = !dirty;
  $('save').disabled = false;
  const problems = checkFrames(doc.frames, names);
  const p = $('problems');
  p.textContent = problems.length ? problems[0] : dirty ? 'Ready to save.' : 'Nothing to save.';
  p.className = problems.length ? 'bad' : dirty ? 'meh' : 'good';
  for (const name of Object.keys(TOOLS)) $(`tool-${name}`).classList.toggle('on', S.tool === name);
  saveDraft();
  drawAnim();
}

function saveDraft() {
  try {
    if (doc.dirty()) localStorage.setItem(DRAFT_KEY, JSON.stringify({ names, frames: doc.frames }));
    else localStorage.removeItem(DRAFT_KEY);
  } catch {
    // no storage: unsaved work simply is not kept across a reload
  }
}

function loadDraft() {
  try {
    const d = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null');
    if (!d || !Array.isArray(d.frames) || d.frames.length !== names.length) return null;
    if (checkFrames(d.frames, names).length && d.frames.some((f) => !f || !Array.isArray(f.rows))) return null;
    return d.frames.map((f) => ({ name: f.name, rows: f.rows }));
  } catch {
    return null;
  }
}

// ------------------------------------------------------------------------------------------------
// the mouse

let stroke = null; // {ch, last: [x, y]} while a button is down on the grid

function pixelAt(e) {
  const r = canvas.getBoundingClientRect();
  const x = Math.floor(((e.clientX - r.left) / r.width) * W);
  const y = Math.floor(((e.clientY - r.top) / r.height) * H);
  return [Math.max(0, Math.min(W - 1, x)), Math.max(0, Math.min(H - 1, y))];
}

canvas.addEventListener('contextmenu', (e) => e.preventDefault());
canvas.addEventListener('pointerdown', (e) => {
  if (e.button !== 0 && e.button !== 2) return;
  e.preventDefault();
  canvas.focus();
  canvas.setPointerCapture(e.pointerId);
  const ch = e.button === 2 ? NONE : TOOLS[S.tool];
  const at = pixelAt(e);
  stroke = { ch, last: at };
  doc.beginStroke();
  doc.setPixel(S.sel, at[0], at[1], ch);
  S.hover = at;
  refresh();
});
canvas.addEventListener('pointermove', (e) => {
  const at = pixelAt(e);
  const moved = !S.hover || S.hover[0] !== at[0] || S.hover[1] !== at[1];
  S.hover = at;
  if (stroke) {
    doc.line(S.sel, stroke.last[0], stroke.last[1], at[0], at[1], stroke.ch);
    stroke.last = at;
    refresh();
  } else if (moved) drawGrid();
  $('status').textContent = `x ${at[0]}  y ${at[1]}   ${describe(doc.get(S.sel, at[0], at[1]))}`;
});
const endStroke = () => {
  if (!stroke) return;
  stroke = null;
  doc.endStroke();
  refresh();
};
canvas.addEventListener('pointerup', endStroke);
canvas.addEventListener('pointercancel', endStroke);
canvas.addEventListener('pointerleave', () => {
  if (stroke) return;
  S.hover = null;
  drawGrid();
});

const describe = (ch) => (ch === BODY ? 'body' : ch === EYE ? 'eye' : 'empty');

// ------------------------------------------------------------------------------------------------
// actions

function setTool(name) {
  S.tool = name;
  refresh();
}

function mirror() {
  const j = doc.mirrorToCounterpart(S.sel);
  if (j < 0) return toast('This frame has no right/left counterpart.', 'warn');
  select(j);
  toast(`Mirrored into ${doc.frames[j].name}. Undo (Cmd/Ctrl+Z) takes it back.`);
}

async function save() {
  const problems = checkFrames(doc.frames, names);
  if (problems.length) return toast(problems[0], 'error');
  try {
    const res = await call('sprites', 'PUT', { frames: doc.frames });
    doc.markSaved();
    toast(`Saved ${res.frames} frames to ${res.path}. Rebuild the game (task build) to play with them.`);
  } catch (e) {
    toast(`Not saved: ${e.message}`, 'error');
  }
}

async function reload(force = false) {
  if (!force && doc.dirty() && !confirm('Throw away your unsaved changes and read the file again?')) return;
  try {
    const api = await call('sprites');
    S.template = api.text;
    doc.reset(parseSprites(api.text));
    toast('Reloaded from the game.');
  } catch (e) {
    toast(`Could not reload: ${e.message}`, 'error');
  }
}

function download() {
  try {
    const text = serializeSprites(S.template, doc.frames);
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain' }));
    a.download = 'sprites.txt';
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  } catch (e) {
    toast(e.message, 'error');
  }
}

function setPlaying(on) {
  S.playing = on;
  $('play').textContent = on ? 'Pause' : 'Play';
}

function wire() {
  $('undo').onclick = () => doc.undo();
  $('redo').onclick = () => doc.redo();
  for (const name of Object.keys(TOOLS)) $(`tool-${name}`).onclick = () => setTool(name);
  $('copy').onclick = () => {
    doc.copy(S.sel);
    refresh();
    toast(`Copied ${doc.frames[S.sel].name}.`);
  };
  $('paste').onclick = () => doc.paste(S.sel);
  $('clear').onclick = () => doc.clear(S.sel);
  $('revert').onclick = () => doc.revert(S.sel);
  $('mirror').onclick = mirror;
  $('flip').onclick = () => doc.flip(S.sel);
  $('shift-left').onclick = () => doc.shift(S.sel, -1, 0);
  $('shift-right').onclick = () => doc.shift(S.sel, 1, 0);
  $('shift-up').onclick = () => doc.shift(S.sel, 0, -1);
  $('shift-down').onclick = () => doc.shift(S.sel, 0, 1);
  $('save').onclick = save;
  $('download').onclick = download;
  $('reload').onclick = () => reload();
  $('zoom').onchange = (e) => {
    S.zoom = Number(e.target.value);
    refresh();
  };
  $('grid-on').onchange = (e) => {
    S.gridOn = e.target.checked;
    refresh();
  };
  $('wide').onchange = (e) => {
    S.wide = e.target.checked;
    refresh();
  };
  $('guides').onchange = (e) => {
    S.guides = e.target.checked;
    refresh();
  };
  $('anim').onchange = (e) => {
    S.anim = ANIMATIONS.find((a) => a.id === e.target.value);
    S.tick = 0;
    drawAnim();
  };
  $('speed').onchange = (e) => (S.speed = Number(e.target.value));
  $('pv-scale').onchange = (e) => {
    S.scale = Number(e.target.value);
    drawAnim();
  };
  $('play').onclick = () => setPlaying(!S.playing);
  window.addEventListener('keydown', onKey);
  window.addEventListener('beforeunload', (e) => {
    if (doc.dirty()) {
      e.preventDefault();
      e.returnValue = '';
    }
  });
}

function onKey(e) {
  const tag = (e.target && e.target.tagName) || '';
  if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
  const mod = e.metaKey || e.ctrlKey;
  const k = e.key.toLowerCase();
  if (mod) {
    if (k === 's') {
      e.preventDefault();
      return save();
    }
    if (k === 'z') {
      e.preventDefault();
      return e.shiftKey ? doc.redo() : doc.undo();
    }
    if (k === 'y') {
      e.preventDefault();
      return doc.redo();
    }
    if (k === 'c') {
      e.preventDefault();
      doc.copy(S.sel);
      refresh();
      return toast(`Copied ${doc.frames[S.sel].name}.`);
    }
    if (k === 'v') {
      e.preventDefault();
      return doc.paste(S.sel);
    }
    return;
  }
  if (e.altKey) return;
  if (e.shiftKey && k.startsWith('arrow')) {
    e.preventDefault();
    const d = { arrowleft: [-1, 0], arrowright: [1, 0], arrowup: [0, -1], arrowdown: [0, 1] }[k];
    return doc.shift(S.sel, d[0], d[1]);
  }
  if (k === 'b' || k === '1') return setTool('body');
  if (k === 'e' || k === '2') return setTool('eye');
  if (k === 'x' || k === '3') return setTool('erase');
  if (k === 'g') {
    S.gridOn = !S.gridOn;
    $('grid-on').checked = S.gridOn;
    return refresh();
  }
  if (k === 'm') return mirror();
  if (k === 'h') return doc.flip(S.sel);
  if (k === '[' || k === 'arrowup') {
    e.preventDefault();
    return select(S.sel - 1);
  }
  if (k === ']' || k === 'arrowdown') {
    e.preventDefault();
    return select(S.sel + 1);
  }
  if (k === ' ') {
    e.preventDefault();
    setPlaying(!S.playing);
  }
}

// ------------------------------------------------------------------------------------------------
// start up

async function boot() {
  let api;
  try {
    api = await call('sprites');
  } catch (e) {
    $('fatal').hidden = false;
    $('fatal').textContent = `Cannot reach the editor server (${e.message}). Start it with:  task editor`;
    return;
  }
  S.template = api.text;
  S.path = api.path;
  const frames = parseSprites(api.text);
  names = frames.map((f) => f.name);
  doc = new SpriteDoc(frames, () => refresh());
  $('float-px').textContent = String(FLOAT);
  for (const a of ANIMATIONS) $('anim').append(new Option(a.label, a.id));
  buildFrameList();
  wire();
  const draft = loadDraft();
  if (draft && checkFrames(draft, names).length === 0 && JSON.stringify(draft) !== JSON.stringify(frames)) {
    doc.restore(draft);
    toast('Restored your unsaved sprite work from last time.');
  }
  refresh();
  let last = performance.now();
  const loop = (now) => {
    // the game runs at 50 or 60 frames a second: tick at 60
    if (S.playing && now - last >= 1000 / 60) {
      S.tick += Math.floor((now - last) / (1000 / 60));
      last = now;
      drawAnim();
    } else if (!S.playing) last = now;
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
  window.spriteEditor = { S, doc, select, save, reload, mirror };
}

boot();
