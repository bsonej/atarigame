// What the palette offers: single tiles, the two markers that are not tiles (player start, peg), the eraser,
// and "stamps" - ready-made arrangements (a stair, a belt, a block for a peg to patrol) dropped in one go.
//
// Tiles are named as in assets/tiles.txt. A test checks that every tile with a map character is offered
// here, so a new tile added to the game cannot be forgotten by the editor.

export const GROUPS = [
  {
    title: 'Platforms',
    items: [
      { kind: 'tile', name: 'BRICK', tip: 'Platform: solid. A dot is put in every second middle tile for the player to eat' },
      { kind: 'tile', name: 'WALL', tip: 'Wall: solid, no end caps, no dots' },
      { kind: 'tile', name: 'PLATFORM', tip: 'Thin platform: one-way. Jump up through it, land on top. Has dots too' },
      { kind: 'tile', name: 'ICE', tip: 'Ice: slow to start, slow to stop, slides far' },
      { kind: 'tile', name: 'ROLLER', tip: 'Roller: like ice, but grips sooner' },
      { kind: 'tile', name: 'TRAMPOLINE', tip: 'Trampoline: walk over it as over any platform (no dots), but JUMP onto it (walking or falling onto it does nothing) and it bounces you straight up, just high enough to land on the next surface above you in your column (up to 14 tiles; nothing there, no bounce)' },
    ],
  },
  {
    title: 'Teleports',
    items: [
      { kind: 'tile', name: 'TELEPORT', tip: 'Teleport: a solid pad (no dots). Teleport tiles that touch are ONE teleporter. Stand on it for 1 second and you dissolve and are rebuilt on the next teleporter (in reading order: top to bottom, then left to right, by each one\'s first tile; the last goes back to the first), standing on its first tile, which needs two free tiles above it. A level with teleports needs at least 2 teleporters; do not join the two kinds. Step off an arrival pad before it can be used again' },
      { kind: 'tile', name: 'TELEPORT_ONCE', tip: 'One-use teleport (dashed glow): works like a teleport, but one way only. After you teleport away from it the whole pad turns into plain brick and is out of the order. You can still arrive on it while it is unused' },
    ],
  },
  {
    title: 'Conveyor belts, right',
    items: [
      { kind: 'tile', name: 'CONV_R_SLOW', tip: 'Belt right, slow' },
      { kind: 'tile', name: 'CONV_R', tip: 'Belt right, normal' },
      { kind: 'tile', name: 'CONV_R_FAST', tip: 'Belt right, fast' },
      { kind: 'tile', name: 'CONV_R_ACC', tip: 'Belt right, accelerating: starts slow, gains speed' },
    ],
  },
  {
    title: 'Conveyor belts, left',
    items: [
      { kind: 'tile', name: 'CONV_L_SLOW', tip: 'Belt left, slow' },
      { kind: 'tile', name: 'CONV_L', tip: 'Belt left, normal' },
      { kind: 'tile', name: 'CONV_L_FAST', tip: 'Belt left, fast' },
      { kind: 'tile', name: 'CONV_L_ACC', tip: 'Belt left, accelerating' },
    ],
  },
  {
    title: 'Climb and slide',
    items: [
      { kind: 'tile', name: 'LADDER', tip: 'Ladder: climb with up and down' },
      { kind: 'tile', name: 'STAIR', tip: 'Step: a thin ledge to jump up onto (you can walk straight past it and jump up through it)' },
      { kind: 'tile', name: 'SLIDE_R', tip: 'Chute down: a vertical screw. Walk into it (from a floor it replaces, at the top) and it carries you down to its end, joystick ignored. Not solid and nothing stands on it: in the air you pass straight through. Stack it into a single-wide column; no diagonals, nothing beside it' },
      { kind: 'tile', name: 'SLIDE_L', tip: 'Chute up: a vertical screw whose thread climbs. Walk into it and it carries you up to its top, where you hop out the way you were facing onto the platform beside it (put one level with the top). Single-wide column, no diagonals' },
    ],
  },
  {
    title: 'Hazards',
    items: [
      { kind: 'tile', name: 'SPIKE', tip: 'Spikes: deadly' },
      { kind: 'tile', name: 'EXPLOSIVE', tip: 'Bomb block: explodes about a second after you step on it' },
      { kind: 'tile', name: 'VANISH', tip: 'Vanishing block: goes after you step on it, comes back later' },
      { kind: 'peg', tip: 'Peg: stand it on a block; it patrols the block and pushes you off the end' },
    ],
  },
  {
    title: 'Level',
    items: [
      { kind: 'tile', name: 'ITEM', tip: 'Item: collect these and all the dots to open the door' },
      { kind: 'tile', name: 'DOOR_BL', tip: 'Exit door, a police box 2 tiles wide and 3 tall (one per level; this is its bottom left tile, stand it on a platform with room above and to the right). It appears when everything is collected' },
      { kind: 'start', tip: 'Player start (one per level)' },
      { kind: 'erase', tip: 'Eraser (also: right mouse button)' },
    ],
  },
];

/** The exit door's six tiles, bottom left first, and where each goes (column, rows up) from the bottom left one. */
export const DOOR_NAMES = ['DOOR_BL', 'DOOR_BR', 'DOOR_ML', 'DOOR_MR', 'DOOR_TL', 'DOOR_TR'];
export const DOOR_CELLS = [[0, 0], [1, 0], [0, 1], [1, 1], [0, 2], [1, 2]];

const row = (name, n) => Array.from({ length: n }, (_, i) => [i, 0, name]);
const diag = (name, n, rising) => Array.from({ length: n }, (_, i) => [i, rising ? n - 1 - i : i, name]);

export const STAMPS = [
  { label: 'Platform', cells: row('BRICK', 8), tip: '8 platform tiles in a row (end caps and dots come by themselves)' },
  { label: 'Thin platform', cells: row('PLATFORM', 8), tip: '8 one-way platform tiles' },
  { label: 'Wall', cells: Array.from({ length: 6 }, (_, i) => [0, i, 'WALL']), tip: 'A wall 6 tiles tall' },
  { label: 'Belt right', cells: row('CONV_R', 8), tip: '8 belt tiles moving right' },
  { label: 'Belt left', cells: row('CONV_L', 8), tip: '8 belt tiles moving left' },
  { label: 'Ice', cells: row('ICE', 8), tip: '8 ice tiles' },
  { label: 'Roller', cells: row('ROLLER', 8), tip: '8 roller tiles' },
  { label: 'Trampoline', cells: row('TRAMPOLINE', 3), tip: '3 trampoline tiles: jump onto them and they bounce you up to the platform above' },
  { label: 'Teleport', cells: row('TELEPORT', 3), tip: '3 teleport tiles = one teleporter. You need at least two teleporters in a level (a second stamp elsewhere); tiles that touch are one teleporter' },
  { label: 'One-use teleport', cells: row('TELEPORT_ONCE', 3), tip: '3 one-use teleport tiles = one teleporter that turns into brick after you leave by it' },
  { label: 'Bombs', cells: row('EXPLOSIVE', 4), tip: '4 bomb blocks: setting one off chains to its neighbours' },
  { label: 'Vanishing', cells: row('VANISH', 4), tip: '4 vanishing blocks' },
  { label: 'Ladder', cells: Array.from({ length: 5 }, (_, i) => [0, i, 'LADDER']), tip: 'A ladder 5 tiles tall' },
  { label: 'Stairs up right', cells: diag('STAIR', 4, true), tip: 'Steps rising to the right: jump up each one' },
  { label: 'Stairs up left', cells: diag('STAIR', 4, false), tip: 'Steps rising to the left' },
  { label: 'Chute down', cells: Array.from({ length: 3 }, (_, i) => [0, i, 'SLIDE_R']), tip: 'A down chute 3 tiles tall (a single-wide column: put it through a gap in the floor, with room to land below)' },
  { label: 'Chute up', cells: Array.from({ length: 3 }, (_, i) => [0, i, 'SLIDE_L']), tip: 'An up chute 3 tiles tall: its top should be level with the platform you hop out onto' },
  { label: 'Peg block', cells: [...row('BRICK', 8).map(([c, , n]) => [c, 1, n]), [1, 0, 'PEG']], tip: 'A block with a peg on it that patrols to the far end' },
  { label: 'Items', cells: Array.from({ length: 5 }, (_, i) => [i * 2, 0, 'ITEM']), tip: '5 items, a tile apart' },
];

/** Every tile name the palette and stamps can place (the test uses this). */
export function offeredTiles() {
  const names = new Set();
  for (const g of GROUPS) for (const it of g.items) if (it.kind === 'tile') names.add(it.name);
  for (const s of STAMPS) for (const [, , n] of s.cells) names.add(n);
  return names;
}

/**
 * A little scene of the playfield for a palette swatch: the part in place, as it looks in the game (end caps,
 * dots, and the part on something to stand on). 4 columns by 3 rows of [column, row, tile name].
 */
export const SCENE_W = 4;
export const SCENE_H = 3;
export function sceneFor(item) {
  const floor = (r) => row('BRICK', SCENE_W).map(([c, , n]) => [c, r, n]);
  const name = item.name;
  switch (name) {
    case 'WALL': return [[1, 0, name], [1, 1, name], [1, 2, name]];
    case 'LADDER': return [[1, 0, name], [1, 1, name], [1, 2, name]];
    case 'STAIR': return [[0, 2, name], [1, 1, name], [2, 0, name]];
    case 'SLIDE_R':
    case 'SLIDE_L': return [[1, 0, name], [1, 1, name], [1, 2, name]];
    case 'SPIKE': return [...floor(2), [1, 1, name], [2, 1, name]];
    case 'ITEM': return [...floor(2), [1, 1, name]];
    case 'DOOR_BL': return DOOR_CELLS.map(([dc, dr], k) => [1 + dc, 2 - dr, DOOR_NAMES[k]]);
    default: return row(name, SCENE_W).map(([c, , n]) => [c, 1, n]);
  }
}
