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
      { kind: 'tile', name: 'SLIDE_R', tip: 'Chute: a turning screw that carries you right (and down a diagonal run of them); stacked chutes join into one thread. You can walk past it and jump up through it' },
      { kind: 'tile', name: 'SLIDE_L', tip: 'Chute: a screw turning the other way, carries you left' },
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
  { label: 'Bombs', cells: row('EXPLOSIVE', 4), tip: '4 bomb blocks: setting one off chains to its neighbours' },
  { label: 'Vanishing', cells: row('VANISH', 4), tip: '4 vanishing blocks' },
  { label: 'Ladder', cells: Array.from({ length: 5 }, (_, i) => [0, i, 'LADDER']), tip: 'A ladder 5 tiles tall' },
  { label: 'Stairs up right', cells: diag('STAIR', 4, true), tip: 'Steps rising to the right: jump up each one' },
  { label: 'Stairs up left', cells: diag('STAIR', 4, false), tip: 'Steps rising to the left' },
  { label: 'Chute right', cells: diag('SLIDE_R', 4, false), tip: 'A chute sloping down to the right' },
  { label: 'Chute left', cells: diag('SLIDE_L', 4, true), tip: 'A chute sloping down to the left' },
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
    case 'SLIDE_R': return [[0, 0, name], [1, 1, name], [2, 2, name]];
    case 'SLIDE_L': return [[2, 0, name], [1, 1, name], [0, 2, name]];
    case 'SPIKE': return [...floor(2), [1, 1, name], [2, 1, name]];
    case 'ITEM': return [...floor(2), [1, 1, name]];
    case 'DOOR_BL': return DOOR_CELLS.map(([dc, dr], k) => [1 + dc, 2 - dr, DOOR_NAMES[k]]);
    default: return row(name, SCENE_W).map(([c, , n]) => [c, 1, n]);
  }
}
