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
export const MODE = { TITLE: 0, PLAY: 1, DYING: 2, SPAWN: 3, CLEAR: 4, OVER: 5 };
export const STATE = { GROUND: 0, AIR: 1, CLIMB: 2 };
export const FRAME = { STAND: 0, WALK_A: 1, AIR: 2, CLIMB: 3, DIE_A: 5, DIE_B: 6 };

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

const JUMP_DY = [3, 3, 3, 2, 2, 2, 1, 1, 1, 0];
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
    this.fall = 0;
    this.anim = 0;
    this.moved = 0;
    this.mtimer = 0;
    this.doorOpen = 0; // no door yet: it fades in when everything is collected
    this.doorDir = 0; // 1 fading in, -1 fading out
    this.doorPhase = 0; // how much of it shows, 0..fadeSteps
    this.doorTick = 0;
    this.frame = FRAME.STAND;
    this.drawn = 0;
    this.dyi = 0;
    this.mode = MODE.SPAWN;
  }

  /** Everything a test or the UI wants to look at. */
  snapshot() {
    return {
      mode: this.mode, px: this.px, py: this.py, state: this.state, left: this.left, lives: this.lives,
      score: this.score, jt: this.jt, fall: this.fall, vx: this.vx, vfrac: this.vfrac, under: this.under,
      cacc: this.cacc, mtimer: this.mtimer, frame: this.frame,
      doorOpen: this.doorOpen, doorDir: u8(this.doorDir), doorPhase: this.doorPhase,
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

  isStep(t) {
    return t === this.T.SLIDE_R || t === this.T.SLIDE_L;
  }

  /** A chute exactly one tile below the feet: slide down onto it. */
  stepDown() {
    const ty = u8(this.py + 24);
    if (this.isStep(this.getTile(this.px, ty)) || this.isStep(this.getTile(u8(this.px + 3), ty))) {
      this.py = u8(this.py + 8);
      return true;
    }
    return false;
  }

  isSurface(t) {
    const T = this.T;
    return t === T.SLIDE_R || t === T.SLIDE_L || t === T.ICE || t === T.ROLLER || u8(t - this.convFirst) < 8;
  }

  // ---- one frame -----------------------------------------------------------------------------
  /** Advance one frame with the joystick `hjoy` (JOY bits). Returns this.mode. */
  step(hjoy) {
    switch (this.mode) {
      case MODE.PLAY: this.modePlay(hjoy); break;
      case MODE.DYING: this.modeDying(); break;
      case MODE.SPAWN: this.modeSpawn(hjoy); break;
      case MODE.CLEAR: this.modeClear(); break;
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
    this.updatePegs();
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
    if (this.state === STATE.CLIMB) {
      this.frame = this.moved ? FRAME.CLIMB + ((this.anim >> 2) & 1) : FRAME.CLIMB;
    } else if (this.state === STATE.AIR) this.frame = FRAME.AIR;
    else this.frame = this.moved ? FRAME.WALK_A + ((this.anim >> 2) & 1) : FRAME.STAND;
  }

  // ---- the player ----------------------------------------------------------------------------
  updatePlayer() {
    const joy = this.joy;
    this.moved = 0;
    if (this.state === STATE.CLIMB) return this.upClimb();
    if (this.state === STATE.AIR) return this.upAir();
    if (!this.groundBelow() && !this.stepDown()) {
      this.state = STATE.AIR; // walked off an edge
      this.fall = 0;
      this.vx = 0;
      this.vfrac = 0;
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
  }

  upAir() {
    if (this.joy & JOY.UP && this.ladderOverlap()) return this.startClimb();
    this.doHoriz();
    if (this.jt === 0xff) return this.airFall();
    let n = JUMP_DY[this.jt];
    if (n === 0) {
      this.jt = 0xff;
      return;
    }
    while (n > 0) {
      const ty = u8(this.py - 1);
      if (this.getSolid(this.px, ty)[0] || this.getSolid(u8(this.px + 3), ty)[0]) {
        this.jt = 0xff; // bumped our head
        return;
      }
      this.py = u8(this.py - 1);
      n--;
    }
    this.jt++;
  }

  airFall() {
    for (let i = 0; i < 2; i++) {
      if (this.groundBelow()) {
        if (this.fall > MAX_FALL) return this.die();
        this.state = STATE.GROUND;
        this.fall = 0;
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
   *  solid: you walk through them (and jump up onto them). */
  moveInto(tx, dir) {
    if (this.getSolid(tx, this.py)[0]) return;
    if (this.getSolid(tx, u8(this.py + 8))[0]) return;
    if (this.getSolid(tx, u8(this.py + 15))[0]) return;
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

  /** Belts and chutes carry the player. Sets `under`. */
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
    let k0 = false; // true for a belt (not a chute)
    if (u === this.T.SLIDE_R || u === this.T.SLIDE_L) {
      this.cdir = u === this.T.SLIDE_R ? 0 : 1;
      this.cacc = 4;
      this.cacc_t = 0;
      speed = 32;
    } else {
      const k = u8(u - this.convFirst);
      if (k >= 8) {
        this.cacc = 4;
        this.cacc_t = 0;
        this.cfrac = 0;
        return;
      }
      this.cdir = CONV_DIR[k];
      k0 = true;
      if (CONV_SPD[k]) {
        this.cacc = 4;
        this.cacc_t = 0;
        speed = CONV_SPD[k];
      } else {
        this.cacc_t = u8(this.cacc_t + 1);
        if ((this.cacc_t & 3) === 0 && this.cacc < 32) this.cacc++;
        speed = this.cacc;
      }
    }
    if (k0) {
      // a belt turning against the way he is walking pulls at him only 3/8 as hard (he can always walk onto it)
      const against = this.cdir ? this.joy & JOY.RIGHT : this.joy & JOY.LEFT;
      if (against) speed = (speed >> 2) + (speed >> 3);
    }
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
  checkTiles() {
    for (let i = 0; i < 6; i++) {
      const t = this.getTile(u8(this.px + PT_DX[i]), u8(this.py + PT_DY[i]));
      if (t === this.T.ITEM) {
        this.map[this.ptr] = this.T.EMPTY;
        this.pickup();
      } else if (this.doorOpen && this.door && t >= this.door[0] && t <= this.door[5]) {
        return this.levelClear(); // any of the door's six tiles, once it is there
      }
    }
    const ty = u8(this.py + 15);
    if ((ty & 7) < 2) return; // only the lower part of a spike tile hurts
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
          p.dir ^= 0xfe;
        }
      }
      this.pegPush(p);
    }
  }

  /** Push the player along if the peg overlaps it and the player is ahead of the peg. */
  pegPush(p) {
    if (
      u8(this.px + 3) < p.x ||
      u8(p.x + 3) < this.px ||
      u8(this.py + 15) < p.y ||
      u8(p.y + 7) < u8(this.py + 15) // only his feet touch it
    )
      return;
    if (p.dir & 0x80) {
      if (this.px <= p.x) this.pushLeft();
    } else if (this.px >= p.x) this.pushRight();
  }
}
