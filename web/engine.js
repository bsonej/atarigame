// The game's rules, ported from src/main.s so a level can be played in the browser while it is built.
//
// It follows the 6502 code routine by routine (same probe points, same order, same 8-bit wrap-around)
// and the test suite replays scripted inputs on both this and the real game in the emulator and compares
// them frame by frame (tests/test_engine.py). If you change the rules in main.s, change them here too.
//
// One call to step() is one video frame (50 or 60 per second); `hjoy` is the joystick bits.

export const COLS = 40;
export const ROWS = 24;

export const JOY = { UP: 1, DOWN: 2, LEFT: 4, RIGHT: 8, FIRE: 16 };
export const MODE = { TITLE: 0, PLAY: 1, DYING: 2, SPAWN: 3, CLEAR: 4, OVER: 5, TELE: 6 }; // TELE: dissolving, moved, rebuilt (teleporter)
export const STATE = { GROUND: 0, AIR: 1, CLIMB: 2, RIDE: 3 }; // RIDE: carried along a chute, joystick ignored
// Sprite frames (assets/sprites.txt): families to which `face` (0 at you, 1 right, 2 left) is added.
export const FRAME = { STAND: 0, LEAN: 3, SQUASH: 5, STRETCH: 8, DIE_A: 11, DIE_B: 12 };
const LAND_FRAMES = 4; // how long he stays squashed after landing
const HOP_JT = 8; // the hop out of the top of an up chute starts this far into the jump table (5 pixels up) ...
const HOP_FRAMES = 4; // ... and drifts sideways this many pixels (enough to leave the chute's column)
const BOUNCE_ROWS = 14; // a trampoline looks this many tile rows up his column for something to bounce him to ...
const BOUNCE_TOP = 24; // ... but not above this pixel line (tile row 3: a surface higher could not be landed on)
const BOUNCE_JT = 3; // a bounce is the jump's last 17 pixels (JUMP_DY from index 3) after bn frames of 3 pixels each
export const FALL_SLOW = 4; // falling is slower than rising: the first FALL_SLOW pixels of a fall take a pixel a frame, then up to
export const FALL_FAST = 16; // FALL_FAST it is 1, 1, 2 pixels on successive frames (a pixel and a third a frame), after that 2
const SPIKE_TOP = 1; // a spike tile's tips are on this line of the tile (assets/tiles.txt): feet below it are hurt

const KIND_EXPL = 0;
const KIND_VANISH = 1;
const PH_FUSE = 0;
const PH_GONE = 1;
const PH_BOOM = 2;
const FREE = 0xff;
const FUSE_EXPL = 45;
const FUSE_VANISH = 30;
const VANISH_BACK = 180;
const CHAIN_FUSE = 8;
const BOOM_FRAMES = 8;
const PEG_WAIT = 40;
const SLICK_MAX = 20;
const ROLLER_LONG = 8; // a roller this long (or longer) has the most grip
const MAX_FALL = 64;
const SPR_H = 16;
export const START_LIVES = 3;
const ITEM_POINTS = 10;
const DOT_POINTS = 1;
const F_DOT = 4;
const CLEAR_BONUS = 100;
export const SPAWN_FRAMES = 48;
export const DIE_FRAMES = 80;
export const CLEAR_FRAMES = 60;
export const TP_FRAMES = 32; // teleporting: 16 frames dissolving, 16 rebuilding him at the other teleporter
const MAX_TP_STACK = 64; // (the game's flood fill; groups are at most 64 tiles, see MAX_TELEPORT_GROUP in build_assets.py)

const JUMP_DY = [3, 3, 3, 3, 3, 2, 2, 2, 2, 1, 1, 1, 0];
// Extra full-speed frames of a bounce to clear a surface k tiles up (index k): the smallest n with 17 + 3n >= 8k + 8.
export const BOUNCE_N = [0, 0, 3, 5, 8, 11, 13, 16, 19, 21, 24, 27, 29, 32, 35];
// The trampoline's rubber band: the amplitude on each step (2 frames) of the animation, 0 plain, 1..3 sag, 4 taut (see trampDraw).
export const TRAMP_AMP = [1, 2, 3, 3, 2, 1, 4, 4, 1, 2, 1, 4, 0];
const DIE_DY = [0xfc, 0xfc, 0xfd, 0xfd, 0xfe, 0xfe, 0xff, 0xff, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5];
const CONV_DIR = [0, 0, 0, 0, 1, 1, 1, 1];
const CONV_SPD = [8, 16, 32, 0, 8, 16, 32, 0];
const SLICK_ACC = [2, 4];
const SLICK_FRIC = [1, 2];
const SLICK_FMASK = [1, 0];
const PROBE_DX = [2, 0, 3];
const NB_DC = [0xff, 1, 0, 0];
const NB_DR = [0, 0, 0xff, 1];
const PT_DX = [0, 3, 0, 3, 0, 3];
const PT_DY = [3, 3, 8, 8, 13, 13];

const u8 = (v) => v & 0xff;

export class Game {
  /**
   * @param level  {map: 1024 map bytes (end caps and dots included), spawn: [col,row], items (things to collect: items +
   *               dots), pegs: [[x,y,min,max,dir]...]}
   * @param tables {T: name -> tile byte, flags: [256], canon: [256]}
   * @param opts   {lives}
   */
  constructor(level, tables, opts = {}) {
    this.level = level;
    this.T = tables.T;
    this.flags = tables.flags;
    this.canon = tables.canon;
    this.convFirst = this.T.CONV_R_SLOW;
    this.door = tables.door; // the bytes of the exit door's six tiles, bottom left first
    this.fadeSteps = tables.fadeSteps || 16;
    this.fps = opts.fps || 50; // frames a second: the game counts a second on a teleporter in these (60 NTSC, 50 PAL)
    this.lives = opts.lives === undefined ? START_LIVES : opts.lives;
    this.score = 0;
    this.deaths = 0;
    this.joy = 0;
    this.joyprev = 0;
    this.fcount = 0;
    this.under = 0;
    this.events = [];
    this.beginLevel();
  }

  // ---- level start ---------------------------------------------------------------------------
  beginLevel() {
    const lv = this.level;
    this.map = Uint8Array.from(lv.map);
    this.ptr = -1;
    this.tt = [];
    for (let i = 0; i < 8; i++) this.tt.push({ ph: FREE, col: 0, row: 0, kind: 0, t: 0, orig: 0 });
    this.pegs = lv.pegs.map(([x, y, min, max, dir]) => ({ x, y, min, max, dir, wait: PEG_WAIT }));
    this.vx = 0;
    this.vfrac = 0;
    this.cfrac = 0;
    this.fcount = 0;
    this.gtick = 0;
    this.cacc_t = 0;
    this.cacc = 4;
    this.cdir = 0;
    this.px = lv.spawn[0] * 4;
    this.py = lv.spawn[1] * 8;
    this.left = lv.items;
    this.state = STATE.GROUND;
    this.jt = 0xff;
    this.bn = 0; // trampoline bounce: frames of full-speed rise still to go
    this.jumped = 0; // 1 = this airborne phase began with a jump (a bounce keeps it): a trampoline only bounces then
    this.tr = { t: 0, row: 0, l: 0, r: 0, c: 0 }; // the trampoline's rubber-band animation (t 0 = none), see trampStart
    this.hop = 0; // frames of forced sideways drift left (the hop out of an up chute)
    this.hdir = 0; // which way that drift goes (the way he faced when the ride ended): 2 = left, else right
    this.rkind = 0; // which chute he rides: 0 down, 1 up
    this.fall = 0;
    this.anim = 0;
    this.moved = 0;
    this.mtimer = 0;
    this.doorOpen = 0; // no door yet: it fades in when everything is collected
    this.doorDir = 0; // 1 fading in, -1 fading out
    this.doorPhase = 0; // how much of it shows, 0..fadeSteps
    this.doorTick = 0;
    this.face = 0; // which way he looks: 0 at you (until he first moves), 1 right, 2 left
    this.landT = 0; // frames of landing squash left
    this.lastSt = 0; // his state on the previous frame
    this.frame = FRAME.STAND;
    this.drawn = 0;
    this.dyi = 0;
    this.tpT = 0; // teleporter: frames he has stood on one (0 = not charging)
    this.tpLock = 0; // 1 = he arrived on this one: step off it before it charges again
    this.tpK = 0; // the kind of the teleporter he stands on (TELEPORT or TELEPORT_ONCE) and the column and row of its tile
    this.tpC = 0;
    this.tpR = 0;
    this.tpDc = 0; // where it sends him: column and row of the first tile of the next teleporter
    this.tpDr = 0;
    this.tpS4 = 0; // the dissolve: 4 * the step (0 whole, 16 gone), the row of the mask table
    this.mode = MODE.SPAWN;
  }

  /** Everything a test or the UI wants to look at. */
  snapshot() {
    return {
      mode: this.mode, px: this.px, py: this.py, state: this.state, left: this.left, lives: this.lives,
      score: this.score, jt: this.jt, bn: this.bn, jumped: this.jumped, fall: this.fall, vx: this.vx, vfrac: this.vfrac, under: this.under,
      cacc: this.cacc, mtimer: this.mtimer, frame: this.frame, face: this.face, hop: this.hop,
      doorOpen: this.doorOpen, doorDir: u8(this.doorDir), doorPhase: this.doorPhase,
      tpT: this.tpT, tpLock: this.tpLock, tpS4: this.tpS4,
    };
  }

  // ---- tiles ---------------------------------------------------------------------------------
  /** The tile (plain, never an end cap) at pixel (tx,ty); outside the playfield it is brick. Sets this.ptr. */
  getTile(tx, ty) {
    tx = u8(tx);
    ty = u8(ty);
    if (ty >= 192 || tx >= 160 || ty < 8) {
      // the game's version leaves ptr alone for the outside; nothing reads it after a brick
      return this.T.BRICK;
    }
    this.ptr = (ty >> 3) * COLS + (tx >> 2);
    return this.canon[this.map[this.ptr]];
  }

  /** [solid, tile] at pixel (tx,ty). */
  getSolid(tx, ty) {
    const t = this.getTile(tx, ty);
    return [(this.flags[t] & 1) !== 0, t];
  }

  tileStandable(tx, ty) {
    let t = this.getTile(tx, ty);
    const f = this.flags[t];
    if (f & 1) return true;
    if (f & 2) return (u8(ty) & 7) === 0;
    if (t !== this.T.LADDER) return false;
    if ((u8(ty) & 7) !== 0) return false;
    return this.getTile(tx, u8(ty) - 1) !== this.T.LADDER;
  }

  groundBelow() {
    const ty = u8(this.py + SPR_H);
    return this.tileStandable(this.px, ty) || this.tileStandable(u8(this.px + 3), ty);
  }

  ladderOverlap() {
    const tx = u8(this.px + 2);
    return this.getTile(tx, u8(this.py + 8)) === this.T.LADDER || this.getTile(tx, u8(this.py + 15)) === this.T.LADDER;
  }

  ladderUnder() {
    return this.getTile(u8(this.px + 2), u8(this.py + SPR_H)) === this.T.LADDER;
  }

  isChute(t) {
    return t === this.T.SLIDE_R || t === this.T.SLIDE_L;
  }

  /**
   * Chutes are vertical, one tile wide, neither solid nor a surface: he passes straight through them in the air. Only
   * WALKING into one catches him: a chute at the middle of his body column (px+2) at his body rows (py+8, py+15), or
   * directly under his feet (py+16: a chute that fills a gap in the floor). He is then locked in (STATE.RIDE).
   * A DOWN chute only catches him from under his feet: at the body rows alone (it stands on the floor he walks on) it
   * has nowhere to take him, and would only snap him back every frame (see chute_catch in main.s).
   */
  chuteCatch() {
    const tx = u8(this.px + 2);
    let t = this.getTile(tx, u8(this.py + 8));
    if (t !== this.T.SLIDE_L) {
      t = this.getTile(tx, u8(this.py + 15));
      if (t !== this.T.SLIDE_L) {
        t = this.getTile(tx, u8(this.py + SPR_H));
        if (!this.isChute(t)) return false;
      }
    }
    this.rkind = t === this.T.SLIDE_R ? 0 : 1;
    this.px = u8(this.px + 2) & 0xfc; // snap to the tile column
    this.py &= 0xfe; // (even, so 2 pixel steps meet a tile edge exactly)
    this.state = STATE.RIDE;
    this.jt = 0xff;
    this.fall = 0;
    this.vx = 0;
    this.vfrac = 0;
    this.hop = 0;
    this.jumped = 0;
    return true;
  }

  /** One frame of the ride: down while a chute is under the feet, up while one is at the feet row; then released. */
  upRide() {
    this.px = u8(this.px + 2) & 0xfc;
    const tx = this.px;
    let hop = false;
    if (this.rkind === 0) {
      if (this.getTile(tx, u8(this.py + SPR_H)) === this.T.SLIDE_R) {
        this.py = u8(this.py + 2);
        return;
      }
    } else {
      if (this.py >= 10 && this.getTile(tx, u8(this.py + 15)) === this.T.SLIDE_L) {
        this.py = u8(this.py - 2);
        return;
      }
      hop = true; // his feet are above the top tile: hop out the way he faces
    }
    if (hop) {
      this.hdir = this.face; // (he does not turn while riding: the joystick is ignored)
      this.jt = HOP_JT;
      this.hop = HOP_FRAMES;
    } else {
      this.jt = 0xff;
      this.hop = 0;
    }
    this.state = STATE.AIR;
    this.fall = 0;
    this.vx = 0;
    this.vfrac = 0;
  }

  isSurface(t) {
    const T = this.T;
    return t === T.ICE || t === T.ROLLER || u8(t - this.convFirst) < 8;
  }

  // ---- teleporters ---------------------------------------------------------------------------
  // Teleport tiles that touch (same kind) are ONE teleporter. A second (this.fps frames) standing on the ground on any tile
  // of one sends him to the next teleporter: they are ordered by their first tile in reading order, the one after the last
  // is the first, and he arrives on the next one's first tile. A one-use teleporter he leaves becomes brick. A teleporter
  // he arrives on does not charge until he has stepped off it. While he charges the group flips between its byte and its
  // byte + 128 (the `glow` tile) every 4 frames. main.s finds the groups on the screen with a flood fill (tp_fill ...);
  // this does the same through fill(), which also gives the first tile in reading order.

  /** Flood fill from (c, r): every tile of 4-neighbours holding `match` becomes `next`. Returns the first of them in
   *  reading order as [row, col] (null if the start does not hold `match`). */
  fill(c, r, match, next) {
    if (this.map[r * COLS + c] !== match) return null;
    this.map[r * COLS + c] = next;
    const todo = [[c, r]];
    let first = [0xff, 0];
    while (todo.length) {
      const [x, y] = todo.pop();
      if (y < first[0] || (y === first[0] && x < first[1])) first = [y, x];
      for (let k = 3; k >= 0; k--) {
        const nx = u8(x + NB_DC[k]);
        const ny = u8(y + NB_DR[k]);
        if (nx >= COLS || ny >= ROWS || this.map[ny * COLS + nx] !== match || todo.length >= MAX_TP_STACK) continue;
        this.map[ny * COLS + nx] = next;
        todo.push([nx, ny]);
      }
    }
    return first;
  }

  /** True (and tpK, tpC, tpR set) if his feet are on a teleport tile (the tile under px or px+3). */
  tpUnder() {
    const ty = u8(this.py + SPR_H);
    for (const tx of [this.px, u8(this.px + 3)]) {
      const t = this.getTile(tx, ty);
      if (t === this.T.TELEPORT || t === this.T.TELEPORT_ONCE) {
        this.tpK = t;
        this.tpC = tx >> 2;
        this.tpR = ty >> 3;
        return true;
      }
    }
    return false;
  }

  /** One frame of play: count the time on a teleporter. */
  tpUpdate() {
    if (this.state === STATE.GROUND && this.tpUnder()) {
      if (this.tpLock) return;
      this.tpT = u8(this.tpT + 1);
      if ((this.tpT & 3) === 0) this.tpFlip();
      if (this.tpT >= this.fps) this.tpGo();
      return;
    }
    this.tpLock = 0;
    if (this.tpT === 0) return;
    if (this.tpT & 4) this.tpFlip(); // the pad's colour back to the plain one
    this.tpT = 0;
  }

  /** Flip the glow of the teleporter at (tpC, tpR): its byte <-> its byte + 128, the whole group. */
  tpFlip() {
    const b = this.map[this.tpR * COLS + this.tpC];
    this.fill(this.tpC, this.tpR, b, b ^ 0x80);
  }

  tpGo() {
    if (this.tpT & 4) this.tpFlip();
    this.tpT = 0;
    const dest = this.tpDest();
    if (!dest) {
      this.tpLock = 1; // nowhere to go: nothing to do until he steps off
      return;
    }
    [this.tpDc, this.tpDr] = dest;
    this.mode = MODE.TELE;
    this.mtimer = 0;
    this.vx = 0;
    this.vfrac = 0;
    this.landT = 0;
    this.lastSt = 0;
    this.moved = 0;
    this.frame = FRAME.STAND + this.face;
  }

  /** The first tile [col, row] of the teleporter after the one at (tpC, tpR) in reading order of first tiles (cyclic), or null.
   *  Teleporters are the connected tiles of one byte. */
  tpDest() {
    const T = this.T;
    const seen = new Set();
    const heads = []; // the first tile of every teleporter, in reading order
    let mine = null;
    for (let i = COLS; i < ROWS * COLS; i++) {
      const b = this.map[i];
      if ((b !== T.TELEPORT && b !== T.TELEPORT_ONCE) || seen.has(i)) continue;
      const todo = [i];
      seen.add(i);
      const members = [];
      while (todo.length) {
        const j = todo.pop();
        members.push(j);
        const x = j % COLS;
        for (const n of [x > 0 ? j - 1 : -1, x < COLS - 1 ? j + 1 : -1, j - COLS, j + COLS]) {
          if (n >= COLS && n < ROWS * COLS && this.map[n] === b && !seen.has(n)) {
            seen.add(n);
            todo.push(n);
          }
        }
      }
      heads.push(i); // the scan is in reading order, so this is the group's first tile
      if (members.includes(this.tpR * COLS + this.tpC)) mine = heads.length - 1;
    }
    if (mine === null || heads.length < 2) return null;
    const h = heads[(mine + 1) % heads.length];
    return [h % COLS, Math.floor(h / COLS)];
  }

  /** Halfway through the teleport: he reappears on the first tile of the destination; a one-use pad he left is spent. */
  tpMove() {
    this.px = u8(this.tpDc << 2);
    this.py = u8((this.tpDr << 3) - SPR_H);
    if (this.tpK === this.T.TELEPORT_ONCE) this.fill(this.tpC, this.tpR, this.T.TELEPORT_ONCE, this.T.BRICK);
  }

  modeTele(hjoy) {
    this.joy = hjoy; // a held button must not count as a fresh press later
    this.incMtimer();
    if (this.mtimer === TP_FRAMES / 2 + 1) this.tpMove();
    this.tpS4 = (this.mtimer < TP_FRAMES / 2 + 1 ? this.mtimer : TP_FRAMES + 1 - this.mtimer) << 2; // 1..16, then 16 down to 1
    if (this.mtimer >= TP_FRAMES) {
      this.mode = MODE.PLAY;
      this.tpS4 = 0;
      this.tpLock = 1; // he stands on a teleporter: step off before it charges again
    }
  }

  // ---- one frame -----------------------------------------------------------------------------
  /** Advance one frame with the joystick `hjoy` (JOY bits). Returns this.mode. */
  step(hjoy) {
    switch (this.mode) {
      case MODE.PLAY: this.modePlay(hjoy); break;
      case MODE.DYING: this.modeDying(); break;
      case MODE.SPAWN: this.modeSpawn(hjoy); break;
      case MODE.CLEAR: this.modeClear(); break;
      case MODE.TELE: this.modeTele(hjoy); break;
      default: break;
    }
    return this.mode;
  }

  incMtimer() {
    if (this.mtimer !== 255) this.mtimer++;
  }

  modePlay(hjoy) {
    this.doorFade();
    this.joyprev = this.joy;
    this.joy = hjoy;
    this.updatePlayer();
    if (this.mode !== MODE.PLAY) return;
    this.checkTiles();
    if (this.mode !== MODE.PLAY) return;
    this.armUnder();
    this.eatDots();
    this.updateTimed();
    this.trampAnim();
    this.updatePegs();
    if (this.mode !== MODE.PLAY) return;
    this.tpUpdate();
    if (this.mode !== MODE.PLAY) return;
    this.chooseFrame();
  }

  modeSpawn(hjoy) {
    this.joy = hjoy; // a held button must not count as a fresh press later
    this.incMtimer();
    if (this.mtimer < (SPAWN_FRAMES / 3) * 2) this.drawn = (this.mtimer >> 1) + 1;
    else {
      this.drawn = 16;
      if (this.mtimer & 2) this.drawn = 0;
    }
    this.frame = FRAME.STAND;
    if (this.mtimer >= SPAWN_FRAMES) {
      this.mode = MODE.PLAY;
      this.drawn = 16;
    }
  }

  modeDying() {
    this.incMtimer();
    if (this.py < 200) {
      let v = 6; // after the hop: a steady fall
      if (this.dyi < DIE_DY.length) v = DIE_DY[this.dyi++];
      if (v & 0x80) {
        const sum = this.py + v; // negative step: do not wrap above the top of the screen
        this.py = sum > 255 ? sum & 255 : 0;
      } else this.py = u8(this.py + v);
    }
    this.frame = FRAME.DIE_A + ((this.mtimer >> 2) & 1);
    if (this.mtimer >= DIE_FRAMES) this.deathDone();
  }

  deathDone() {
    this.lives = u8(this.lives - 1);
    if (this.lives === 0) {
      this.mode = MODE.OVER;
      this.mtimer = 0;
      this.drawn = 0;
      this.events.push('gameover');
    } else this.beginLevel();
  }

  modeClear() {
    this.incMtimer();
    this.doorFade();
    if (this.mtimer >= CLEAR_FRAMES) this.events.push('cleared');
  }

  die() {
    if (this.mode !== MODE.PLAY) return;
    this.mode = MODE.DYING;
    this.mtimer = 0;
    this.dyi = 0;
    this.moved = 0;
    this.drawn = 16;
    this.frame = FRAME.DIE_A;
    this.deaths++;
  }

  addScore(n) {
    this.score = Math.min(this.score + n, 0xffff);
  }

  chooseFrame() {
    if (this.state === STATE.RIDE) {
      // locked in a chute he does not turn, whatever the joystick says
    } else if (this.joy & JOY.RIGHT) this.face = 1;
    else if (this.joy & JOY.LEFT) this.face = 2;
    if (this.lastSt === STATE.AIR && this.state === STATE.GROUND) this.landT = LAND_FRAMES; // landing: squash
    this.lastSt = this.state;
    if (this.state === STATE.CLIMB) {
      this.landT = 0;
      this.frame = this.moved ? FRAME.LEAN + ((this.anim >> 2) & 1) : FRAME.STAND; // wobbling up the ladder
    } else if (this.state === STATE.RIDE) {
      this.landT = 0;
      this.frame = FRAME.STAND + this.face; // riding a chute: standing, looking the way he last went
    } else if (this.state === STATE.AIR) {
      this.landT = 0;
      this.frame = (this.jt < 3 ? FRAME.SQUASH : FRAME.STRETCH) + this.face; // squashed at take-off, then stretched
    } else if (this.landT > 0) {
      this.landT--;
      this.frame = FRAME.SQUASH + this.face;
    } else if (this.moved && this.anim & 4) this.frame = FRAME.LEAN + (this.face === 2 ? 1 : 0);
    else this.frame = FRAME.STAND + this.face;
  }

  // ---- the player ----------------------------------------------------------------------------
  updatePlayer() {
    const joy = this.joy;
    this.moved = 0;
    if (this.state === STATE.CLIMB) return this.upClimb();
    if (this.state === STATE.AIR) return this.upAir();
    if (this.state === STATE.RIDE) return this.upRide();
    if (this.chuteCatch()) return; // walked into a chute: it carries him
    if (!this.groundBelow()) {
      this.state = STATE.AIR; // walked off an edge
      this.jumped = 0; // (walking or being pushed off: a trampoline is only a floor)
      this.fall = 0;
      this.vx = 0;
      this.vfrac = 0;
      this.hop = 0;
      this.jt = 0xff;
      return;
    }
    if (joy & JOY.UP && this.ladderOverlap()) return this.startClimb();
    if (joy & JOY.DOWN && this.ladderUnder()) return this.startClimb();
    if (joy & JOY.FIRE && !(this.joyprev & JOY.FIRE)) {
      this.jt = 0;
      this.fall = 0;
      this.vx = 0;
      this.vfrac = 0;
      this.hop = 0;
      this.jumped = 1;
      this.state = STATE.AIR;
      return this.doHoriz();
    }
    this.surfaceDrift();
    if (this.under === this.T.ICE) return this.slickMove(0);
    if (this.under === this.T.ROLLER) return this.slickMove(1);
    this.vx = 0;
    this.vfrac = 0;
    this.doHoriz();
  }

  startClimb() {
    this.px = u8(this.px + 2) & 0xfc;
    this.state = STATE.CLIMB;
    this.jt = 0xff;
    this.fall = 0;
    this.hop = 0;
    this.bn = 0;
    this.jumped = 0;
  }

  upAir() {
    if (this.joy & JOY.UP && this.ladderOverlap()) return this.startClimb();
    if (this.hop) {
      this.hop--; // the hop out of an up chute: drift the way he faces, joystick ignored
      if (this.hdir === 2) this.moveLeft();
      else this.moveRight();
    } else this.doHoriz();
    if (this.jt === 0xff) return this.airFall();
    // Rising: nothing above him matters (no head bumps: he overlays blocks, bombs, platforms, chutes); only the score row is a ceiling.
    let n;
    if (this.bn) {
      this.bn--; // a trampoline bounce: bn frames at full speed first (jt stays where it is), then the usual slowing tail
      this.jt--;
      n = 3;
    } else n = JUMP_DY[this.jt];
    if (n === 0) {
      this.jt = 0xff;
      this.bn = 0;
      return;
    }
    while (n > 0) {
      if (this.py < 9) {
        this.jt = 0xff;
        this.bn = 0;
        return;
      }
      this.py = u8(this.py - 1);
      n--;
    }
    this.jt++;
  }

  /**
   * Landing on a trampoline (the tile under the middle of his feet, else under either foot, like belts): if there is
   * anything he could land on in his column above it, he is thrown straight up and falls onto it. Looking up from the
   * trampoline tile by tile (BOUNCE_ROWS at most, never above BOUNCE_TOP), the first row where the middle (px+2) or either
   * foot column (px, px+3) has a surface (tileStandable) is the target, k tiles up. The bounce is the end of an ordinary
   * jump (BOUNCE_JT) after BOUNCE_N[k] frames of 3 pixels: it rises 17 + 3*BOUNCE_N[k] >= 8k + 8 pixels, so his feet clear the
   * target's top by a tile (8 to 10 pixels) and he lands on it on the way down. Nothing in range: an ordinary landing.
   * True if he bounced.
   */
  tryBounce() {
    const feet = u8(this.py + SPR_H);
    const hit = PROBE_DX.find((dx) => this.getTile(u8(this.px + dx), feet) === this.T.TRAMPOLINE);
    if (hit === undefined) return false;
    const landCol = u8(this.px + hit) >> 2;
    const landRow = feet >> 3;
    let y = feet & 0xf8;
    for (let k = 1; k <= BOUNCE_ROWS; k++) {
      y = u8(y - 8);
      if (y < BOUNCE_TOP) return false;
      if (PROBE_DX.some((dx) => this.tileStandable(u8(this.px + dx), y))) {
        this.bn = BOUNCE_N[k];
        this.jt = BOUNCE_JT;
        this.fall = 0;
        this.trampStart(landCol, landRow);
        this.events.push('bounce');
        return true;
      }
    }
    return false;
  }

  /**
   * The trampoline's rubber band. When he bounces, the mat of the whole connected run he landed on (tiles of the trampoline
   * family on that row, caps included in the count) sags like a stretched rubber band and wobbles back: every second frame
   * the run's middle tiles are swapped for another picture (TRAMPOLINE_S1..S3, the mat 1 to 3 lines lower, or _TAUT, the band
   * stretched thin), 26 frames in all, then the plain tiles go back. Only that run's screen tiles change, the game treats
   * every picture as the trampoline (canon), the end caps (the posts it is anchored to) never change. A new bounce finishes
   * the old animation first; a new level clears it.
   */
  trampStart(col, row) {
    if (this.tr.t) this.trampRestore();
    const tr = this.tr;
    tr.row = row;
    tr.c = col;
    const same = (c) => this.canon[this.map[row * COLS + c]] === this.T.TRAMPOLINE;
    let l = col;
    while (l > 0 && same(l - 1)) l--;
    let r = col;
    while (r < COLS - 1 && same(r + 1)) r++;
    tr.l = l;
    tr.r = r;
    tr.t = 1;
  }

  /** One frame of the animation (every frame of play). */
  trampAnim() {
    const tr = this.tr;
    if (!tr.t) return;
    const step = (tr.t - 1) >> 1;
    if (step >= TRAMP_AMP.length) return this.trampRestore();
    if (tr.t & 1) this.trampDraw(TRAMP_AMP[step]);
    tr.t++;
  }

  trampRestore() {
    this.trampDraw(0);
    this.tr.t = 0;
  }

  /**
   * Draw the run at amplitude a: 0 plain, 1..3 sagging, 4 taut. The sag of a tile is the smallest of: the amplitude, one more
   * than its distance from the end of the run (tapering to the posts), and 3 - half its distance from the column he
   * landed in (deepest there, at least 1). End caps are left alone.
   */
  trampDraw(a) {
    const { row, l, r, c } = this.tr;
    const T = this.T;
    const caps = [T.TRAMPOLINE_L, T.TRAMPOLINE_R, T.TRAMPOLINE_LR];
    const tile = [T.TRAMPOLINE, T.TRAMPOLINE_S1, T.TRAMPOLINE_S2, T.TRAMPOLINE_S3, T.TRAMPOLINE_TAUT];
    for (let i = l; i <= r; i++) {
      const at = row * COLS + i;
      if (caps.includes(this.map[at])) continue;
      let s = 4;
      if (a < 4) {
        s = Math.min(a, Math.min(i - l, r - i) + 1, Math.max(1, 3 - (Math.abs(i - c) >> 1)));
      }
      this.map[at] = tile[s];
    }
  }

  /** No solid in either foot column at the lowest row of the body (py+15); at the bottom of the screen the floor is the edge. */
  feetClear() {
    if (this.py >= 176) return true;
    const ty = u8(this.py + 15);
    return !this.getSolid(this.px, ty)[0] && !this.getSolid(u8(this.px + 3), ty)[0];
  }

  /** Falling: lands on the first surface under the feet, but never inside a solid (he keeps falling until clear). */
  airFall() {
    // Slower than rising, so he floats down: 1 pixel a frame for the first FALL_SLOW pixels fallen, then the pattern 1, 1, 2
    // (fall bit 1 clear = 2) up to FALL_FAST, then 2. (`fall` counts pixels, so the lethal distance is unchanged.)
    const f = this.fall;
    const speed = f >= FALL_FAST ? 2 : f < FALL_SLOW ? 1 : f & 2 ? 1 : 2;
    for (let i = 0; i < speed; i++) {
      if (this.groundBelow() && this.feetClear()) {
        if (this.jumped && this.tryBounce()) return; // a trampoline catches him (if he jumped), however far he fell
        if (this.fall > MAX_FALL) return this.die();
        this.state = STATE.GROUND;
        this.fall = 0;
        this.jumped = 0;
        return;
      }
      this.py = u8(this.py + 1);
      this.fall = u8(this.fall + 1);
    }
  }

  upClimb() {
    const joy = this.joy;
    if (joy & (JOY.LEFT | JOY.RIGHT) && this.groundBelow()) {
      this.state = STATE.GROUND;
      return this.doHoriz();
    }
    if (joy & JOY.UP) {
      if (this.getSolid(this.px, u8(this.py - 1))[0]) return; // ceiling
      if (this.getTile(this.px, u8(this.py + 15)) === this.T.LADDER) {
        this.py = u8(this.py - 1);
        this.anim = u8(this.anim + 1);
        this.moved = u8(this.moved + 1);
        if (this.getTile(this.px, u8(this.py + 15)) === this.T.LADDER) return;
      }
      this.state = STATE.GROUND; // stepped off the top of the ladder
      return;
    }
    if (joy & JOY.DOWN) {
      if (!this.getSolid(this.px, u8(this.py + SPR_H))[0]) {
        this.py = u8(this.py + 1);
        this.anim = u8(this.anim + 1);
        this.moved = u8(this.moved + 1);
        if (this.getTile(this.px, u8(this.py + 15)) === this.T.LADDER) return;
      }
      this.state = STATE.GROUND; // reached a floor, or the ladder ended
    }
  }

  doHoriz() {
    if (this.joy & JOY.RIGHT) this.moveRight();
    else if (this.joy & JOY.LEFT) this.moveLeft();
  }

  /** The shared body of move_right / move_left: `tx` is the pixel column being stepped into. Stairs and chutes are not
   *  solid: you walk through them. */
  moveInto(tx, dir) {
    // a solid at the head, middle or feet row of that column blocks him, unless he is already inside a solid at that
    // row on the edge he is on now (he rose into a block: he slides about in it and out of it, rather than being stuck)
    const cx = u8(tx - dir);
    for (const dy of [0, 8, 15]) {
      const y = u8(this.py + dy);
      if (this.getSolid(tx, y)[0] && !this.getSolid(cx, y)[0]) return;
    }
    this.px = u8(this.px + dir);
    this.anim = u8(this.anim + 1);
    this.moved = u8(this.moved + 1);
  }

  moveRight() {
    if (this.px >= 156) return;
    this.moveInto(u8(this.px + 4), 1);
  }

  moveLeft() {
    if (this.px === 0) return;
    this.moveInto(u8(this.px - 1), -1);
  }

  pushRight() {
    const [m, a] = [this.moved, this.anim];
    this.moveRight();
    this.moved = m;
    this.anim = a;
  }

  pushLeft() {
    const [m, a] = [this.moved, this.anim];
    this.moveLeft();
    this.moved = m;
    this.anim = a;
  }

  /** Belts carry the player. Sets `under`. */
  surfaceDrift() {
    let mid = 0;
    let found = false;
    for (let i = 0; i < 3; i++) {
      const t = this.getTile(u8(this.px + PROBE_DX[i]), u8(this.py + SPR_H));
      if (i === 0) mid = t;
      this.under = t;
      if (this.isSurface(t)) {
        found = true;
        break;
      }
    }
    if (!found) this.under = mid;
    const u = this.under;
    let speed;
    const k = u8(u - this.convFirst);
    if (k >= 8) {
      this.cacc = 4;
      this.cacc_t = 0;
      this.cfrac = 0;
      return;
    }
    this.cdir = CONV_DIR[k];
    if (CONV_SPD[k]) {
      this.cacc = 4;
      this.cacc_t = 0;
      speed = CONV_SPD[k];
    } else {
      this.cacc_t = u8(this.cacc_t + 1);
      if ((this.cacc_t & 3) === 0 && this.cacc < 32) this.cacc++;
      speed = this.cacc;
    }
    // a belt turning against the way he is walking pulls at him only 3/8 as hard (he can always walk onto it)
    const against = this.cdir ? this.joy & JOY.RIGHT : this.joy & JOY.LEFT;
    if (against) speed = (speed >> 2) + (speed >> 3);
    this.cfrac = u8(this.cfrac + speed);
    while (this.cfrac >= 16) {
      this.cfrac -= 16;
      if (this.cdir) this.pushLeft();
      else this.pushRight();
    }
  }

  /** Roller tiles in the run under the feet, 1..ROLLER_LONG: a longer roller grips harder. */
  rollerLen() {
    const y = u8(this.py + SPR_H);
    let mid = 0;
    for (let i = 0; i < 3; i++) {
      mid = u8(u8(this.px + PROBE_DX[i]) & 0xfc);
      if (this.getTile(mid, y) === this.T.ROLLER) break;
    }
    let n = 1;
    for (let x = mid - 4; x >= 0; x -= 4) {
      if (this.getTile(x, y) !== this.T.ROLLER) break;
      if (++n >= ROLLER_LONG) return n;
    }
    for (let x = mid + 4; ; x += 4) {
      if (this.getTile(x, y) !== this.T.ROLLER) break;
      if (++n >= ROLLER_LONG) return n;
    }
    return n;
  }

  /** Ice (x=0) and rollers (x=1): speed up gradually, glide when you let go. */
  slickMove(x) {
    const acc = x === 1 ? this.rollerLen() : SLICK_ACC[x];
    const fric = SLICK_FRIC[x];
    const fmask = SLICK_FMASK[x];
    this.fcount = u8(this.fcount + 1);
    let a;
    if (this.joy & JOY.RIGHT) {
      a = u8(this.vx + acc);
      if (!(a & 0x80) && a >= SLICK_MAX + 1) a = SLICK_MAX;
      this.vx = a;
    } else if (this.joy & JOY.LEFT) {
      a = u8(this.vx - acc);
      if (a & 0x80 && a < 256 - SLICK_MAX) a = 256 - SLICK_MAX;
      this.vx = a;
    } else if ((this.fcount & fmask) === 0 && this.vx !== 0) {
      if (this.vx & 0x80) {
        a = u8(this.vx + fric);
        if (!(a & 0x80)) a = 0;
      } else {
        a = u8(this.vx - fric);
        if (a & 0x80) a = 0;
      }
      this.vx = a;
    }
    if (this.vx === 0) return;
    if (!(this.vx & 0x80)) {
      this.vfrac = u8(this.vfrac + this.vx);
      while (this.vfrac >= 16) {
        this.vfrac -= 16;
        const before = this.px;
        this.moveRight();
        if (this.px === before) return this.stopSlick();
      }
    } else {
      this.vfrac = u8(this.vfrac + u8(-this.vx));
      while (this.vfrac >= 16) {
        this.vfrac -= 16;
        const before = this.px;
        this.moveLeft();
        if (this.px === before) return this.stopSlick();
      }
    }
  }

  stopSlick() {
    this.vx = 0;
    this.vfrac = 0;
  }

  // ---- items, spikes -------------------------------------------------------------------------
  // An item is only collected AT HIS LEVEL: only the feet points (the last two, py+13: the row his feet are in) collect
  // it, never the head or mid-body ones, and neither does rising (the up phase of a jump or hop, or a ride up a chute):
  // he is passing through it from below. Standing, walking, climbing, riding down and falling collect it.
  checkTiles() {
    const rising = (this.state === STATE.AIR && this.jt !== 0xff) || (this.state === STATE.RIDE && this.rkind !== 0);
    for (let i = 0; i < 6; i++) {
      const t = this.getTile(u8(this.px + PT_DX[i]), u8(this.py + PT_DY[i]));
      if (t === this.T.ITEM) {
        if (i < 4 || rising) continue;
        this.map[this.ptr] = this.T.EMPTY;
        this.pickup();
      } else if (this.doorOpen && this.door && t >= this.door[0] && t <= this.door[5]) {
        return this.levelClear(); // any of the door's six tiles, once it is there
      }
    }
    const ty = u8(this.py + 15);
    if ((ty & 7) < SPIKE_TOP) return; // only the part of a spike tile from its tips down hurts
    if (this.getTile(this.px, ty) === this.T.SPIKE) return this.die();
    if (this.getTile(u8(this.px + 3), ty) === this.T.SPIKE) return this.die();
  }

  pickup() {
    this.events.push('item');
    this.collected(ITEM_POINTS);
  }

  pickupDot() {
    this.events.push('dot');
    this.collected(DOT_POINTS);
  }

  collected(points) {
    this.addScore(points);
    this.left = u8(this.left - 1);
    if (this.left !== 0) return;
    this.openDoors(); // that was the last one: the exit opens
    this.events.push('opened');
  }

  /** Everything is collected: the exit door fades in. */
  openDoors() {
    this.doorOpen = 1;
    this.doorDir = 1;
  }

  /** Every other frame the door takes one step towards fully there (doorDir 1) or gone (-1). */
  doorFade() {
    if (this.doorDir === 0) return;
    this.doorTick = u8(this.doorTick + 1);
    if (this.doorTick & 1) return;
    this.doorPhase += this.doorDir;
    if (this.doorPhase === this.fadeSteps || this.doorPhase === 0) this.doorDir = 0;
  }

  /** Walking into the open door finishes the level: he is gone, and the door fades away behind him. */
  levelClear() {
    this.addScore(CLEAR_BONUS);
    this.mode = MODE.CLEAR;
    this.mtimer = 0;
    this.drawn = 0;
    this.doorDir = -1;
    this.frame = FRAME.STAND;
  }

  /** Standing on a platform tile with a dot in it eats the dot (either foot counts). */
  eatDots() {
    if (this.state !== STATE.GROUND) return;
    const ty = u8(this.py + SPR_H);
    for (const tx of [this.px, u8(this.px + 3)]) {
      if (ty >= 192 || tx >= 160) continue; // off the screen
      const i = (ty >> 3) * COLS + (tx >> 2);
      const raw = this.map[i];
      if (!(this.flags[raw] & F_DOT)) continue;
      this.map[i] = this.canon[raw]; // the plain tile stays behind
      this.pickupDot();
    }
  }

  // ---- bomb blocks and vanishing blocks ------------------------------------------------------
  armUnder() {
    if (this.state !== STATE.GROUND) return;
    const ty = u8(this.py + SPR_H);
    this.armAt(this.px, ty);
    this.armAt(u8(this.px + 3), ty);
  }

  armAt(tx, ty) {
    const t = this.getTile(tx, ty);
    const T = this.T;
    const raw = this.ptr >= 0 ? this.map[this.ptr] : 0; // the byte as drawn, end caps and all
    let kind;
    let fuse;
    if (t === T.EXPLOSIVE || t === T.EXPLOSIVE_B) {
      kind = KIND_EXPL;
      fuse = FUSE_EXPL;
    } else if (t === T.VANISH || t === T.VANISH_B) {
      kind = KIND_VANISH;
      fuse = FUSE_VANISH;
    } else return;
    this.armCell(tx >> 2, ty >> 3, kind, fuse, raw);
  }

  /** Put the tile at (col,row) in the table with a fuse, unless it is already there. */
  armCell(col, row, kind, fuse, raw) {
    for (let x = 7; x >= 0; x--) {
      const s = this.tt[x];
      if (s.ph !== FREE && s.col === col && s.row === row) return;
    }
    for (let x = 7; x >= 0; x--) {
      const s = this.tt[x];
      if (s.ph === FREE) {
        Object.assign(s, { orig: raw, col, row, kind, t: fuse, ph: PH_FUSE });
        return;
      }
    }
  }

  setCell(s, byte) {
    this.map[s.row * COLS + s.col] = byte;
  }

  playerInCell(s) {
    const ox = u8(s.col << 2);
    const oy = u8(s.row << 3);
    return u8(this.px + 3) >= ox && u8(ox + 3) >= this.px && u8(this.py + 15) >= oy && u8(oy + 7) >= this.py;
  }

  updateTimed() {
    const T = this.T;
    for (let x = 7; x >= 0; x--) {
      const s = this.tt[x];
      if (s.ph === FREE) continue;
      if (s.ph === PH_GONE) {
        s.t = u8(s.t - 1);
        if (s.t !== 0) continue;
        if (this.playerInCell(s)) s.t = 1; // do not come back inside the player
        else {
          this.setCell(s, s.orig);
          s.ph = FREE;
        }
      } else if (s.ph === PH_BOOM) {
        s.t = u8(s.t - 1);
        if (s.t !== 0) continue;
        this.setCell(s, T.EMPTY);
        s.ph = FREE;
      } else {
        s.t = u8(s.t - 1);
        if (s.t === 0) {
          if (s.kind === KIND_EXPL) this.explode(x);
          else {
            this.setCell(s, T.EMPTY);
            s.ph = PH_GONE;
            s.t = VANISH_BACK;
          }
        } else if (s.kind === KIND_EXPL) this.setCell(s, s.t & 4 ? T.EXPLOSIVE_B : s.orig);
        else this.setCell(s, s.t & 2 ? T.VANISH_B : s.orig);
      }
    }
  }

  explode(x) {
    const s = this.tt[x];
    s.ph = PH_BOOM;
    s.t = BOOM_FRAMES;
    this.setCell(s, this.T.BOOM);
    this.events.push('boom');
    // blast zone: from one tile left of the block to one tile right, from two tiles above to its bottom
    const ox = u8((s.col << 2) - 4);
    const oyRaw = u8(s.row << 3) - 16;
    const oy = oyRaw < 0 ? 0 : oyRaw;
    if (
      u8(this.px + 3) >= ox &&
      u8(ox + 11) >= this.px &&
      u8(this.py + 15) >= oy &&
      u8(u8(s.row << 3) + 7) >= u8(this.py + 15) // only his feet count
    )
      this.die();
    // chain reaction: bomb blocks next to this one (down, up, right, left)
    for (let y = 3; y >= 0; y--) {
      const c = u8(s.col + NB_DC[y]);
      const r = u8(s.row + NB_DR[y]);
      const t = this.getTile(u8(c << 2), u8(r << 3));
      if (t === this.T.EXPLOSIVE || t === this.T.EXPLOSIVE_B) this.armCell(c, r, KIND_EXPL, CHAIN_FUSE, this.map[this.ptr]);
    }
  }

  // ---- pegs ----------------------------------------------------------------------------------
  updatePegs() {
    if (this.pegs.length === 0) return;
    this.gtick = u8(this.gtick + 1);
    for (const p of this.pegs) {
      if (p.wait !== 0) p.wait--;
      else if ((this.gtick & 1) === 0) {
        p.x = u8(p.x + p.dir);
        if (p.x === p.max || p.x === p.min) {
          p.wait = PEG_WAIT; // at the end of the block: rest, then turn round
          this.pegPush(p); // (first one last push the way it was going: whoever is ahead of it is carried off the end)
          p.dir ^= 0xfe;
        }
      }
      this.pegPush(p);
    }
  }

  /**
   * Push the player along if the peg overlaps it and the player is ahead of the peg. The push carries him clear of the
   * peg in one go (up to 4 pixels, the peg is 4 wide), so a belt or ice dragging him back never wins, and nothing in the
   * platform (a step, a spike, a ladder, a chute, any tile) slows it: only a solid beside him (walking into it, as ever)
   * stops him, and the peg's run ends at such a solid. So he is carried, a peg's width ahead of it, to the end of the
   * platform and off it. What is under his feet still applies as usual.
   */
  pegPush(p) {
    if (
      u8(this.px + 3) < p.x ||
      u8(p.x + 3) < this.px ||
      u8(this.py + 15) < p.y ||
      u8(p.y + 7) < u8(this.py + 15) // only his feet touch it
    )
      return;
    for (let k = 0; k < 4; k++) {
      if (p.dir & 0x80) {
        if (this.px > p.x || u8(this.px + 3) < p.x) break; // behind it, or clear of it
        this.pushLeft();
      } else {
        if (this.px < p.x || u8(p.x + 3) < this.px) break;
        this.pushRight();
      }
    }
  }
}
