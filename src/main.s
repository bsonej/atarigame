; ---------------------------------------------------------------------------
; atarigame - single-screen puzzle/platformer for the Atari XL/XE (ca65)
;
; Screen : ANTIC mode 4, 40x24 tiles of 4x8 pixels (160x192, 4 colours).
; Player : hardware Player 0, 4 pixels wide x 16 lines tall (two tiles high).
; Coordinates: px = 0..156 (colour clocks from the left edge of the playfield),
;              py = 0..191 (scan lines from the top of the playfield).
;
; The game is a small state machine, one handler per frame (see mode_tab):
;   TITLE -> (fire) new_game -> SPAWN -> PLAY -> DYING -> SPAWN ... -> OVER -> TITLE
;                                          \-> CLEAR -> SPAWN (next level)
;   TITLE --(idle 10 s)--> attract mode: the same PLAY/DYING/SPAWN/CLEAR modes driven by an AI
;   (demo = 1) for 30 s, then back to TITLE; fire starts a real game.
; ---------------------------------------------------------------------------

        .setcpu "6502"
        .export start
        .export frame_end                       ; breakpoint target for tools/headless.py
        .exportzp tr_t, tr_l, tr_r, tr_row, tr_c
        .exportzp fps, tp_t, tp_lock, tp_k, tp_c, tp_r, tp_dc, tp_dr, tp_s4
        .exportzp px, py, state, jt, bn, hop, hdir, rkind, fall, score, hiscore, left, lives, level, lvlidx
        .exportzp mode, demo, demo_n, timer, mtimer, frame, drawn, deaths, joy, anim, moved, flash
        .exportzp ai_have, ai_ic, ai_ir, ai_goal
        .exportzp under, vx, vfrac, cfrac, cacc, gtick, pg_n, joyprev, cacc_t, fcount, cdir, pfloat
        .export tp_a, tp_b, tp_n, tp_hr, tp_hc
        .export tt_col, tt_row, tt_t, tt_ph, tt_kind, tt_orig, pg_x, pg_y, pg_min, pg_max, pg_dir, pg_wait, cph
        .export pal0, pal1, pal2, pal3, dli_row, dli_n, ai_kind, door_open, door_dir, door_phase, door_art, face

        .include "gen/tiles.inc"
        .include "gen/font.inc"                 ; .charmap: .byte "TEXT" gives glyph ids
        .include "gen/palette.inc"              ; PAL_* colours and pal_hues

; ---- OS and hardware registers --------------------------------------------
RTCLOK  = $12           ; frame counter, low byte at RTCLOK+2
ATRACT  = $4D           ; OS attract-mode timer (reset every frame so the OS never dims the colours)
SDMCTL  = $022F
SDLSTL  = $0230
GPRIOR  = $026F
.ifdef TEST
; Test build: tools/headless.py writes the joystick here instead of the hardware.
STICK0  = $06F0         ; active low: bit0 up, bit1 down, bit2 left, bit3 right
STRIG0  = $06F1         ; 0 = fire pressed
.else
STICK0  = $0278
STRIG0  = $0284
.endif
PCOLR0  = $02C0
PCOLR1  = $02C1
PCOLR2  = $02C2
PCOLR3  = $02C3
COLOR0  = $02C4         ; playfield colour for pixel value 1
COLOR1  = $02C5         ; ... value 2
COLOR2  = $02C6         ; ... value 3
COLOR3  = $02C7         ; ... value 3 in a glyph with bit 7 set (lowercase text)
COLOR4  = $02C8         ; background
CHBAS   = $02F4
VDSLST  = $0200         ; display-list interrupt vector
COLPF0  = $D016         ; hardware colour registers (the DLI changes these per row)
COLPF1  = $D017
COLPF2  = $D018
COLPF3  = $D019
WSYNC   = $D40A
NMIEN   = $D40E
HPOSP0  = $D000
HPOSP1  = $D001         ; HPOSP2 follows: pegs are Player 1 and 2
HPOSP3  = $D003         ; his eyes
HPOSM0  = $D004         ; HPOSM1-3 follow: the four missiles are his third colour (a fifth 8 clock wide sprite)
SIZEP0  = $D008
SIZEM   = $D00C
GRACTL  = $D01D
PAL     = $D014         ; bits 1-3 are zero on a PAL machine
AUDF1   = $D200
AUDC1   = $D201
PMBASE  = $D407

; ---- memory layout (must match cfg/atari-xex.cfg) --------------------------
CHARSET_ADDR = $6000
SCREEN  = $6500         ; 24 rows x 40 columns (1 KB reserved)
PMAREA  = $7000         ; 2 KB aligned, single-line resolution
PM0     = PMAREA + $0400
PM_YOFF = 32            ; PM byte index of the first playfield scan line
PM0Y    = PM0 + PM_YOFF
PLAYER_FLOAT = 2        ; he is a bubble: drawn this many scan lines above the surface he stands on (purely visual;
                        ; the physics box is unchanged). Keep equal to FLOAT in web/spritemodel.js and tools/headless.py.
                        ; On top of that he bobs: bob_float holds the actual float for each of 64 frames (1 to 3 lines,
                        ; PLAYER_FLOAT +/- 1, a slow sine), indexed by the OS frame counter (RTCLOK+2) and kept in pfloat.
PM3Y    = PM0Y + $300     ; Player 3: the eyes
MISSY   = PMAREA + $0300 + PM_YOFF      ; the missiles: 2 bits a line each, M0 in bits 1-0 ... M3 in bits 7-6
; His colours come from assets/palette.txt (gen/palette.inc): PAL_PLAYER (the body, Player 0), PAL_EYES (Player 3) and
; PAL_THIRD (= PAL_ICE: the missiles take the colour of playfield colour 3, which is COLPF3, the ice colour).

; ---- game constants --------------------------------------------------------
S_GROUND = 0
S_AIR    = 1
S_CLIMB  = 2
S_RIDE   = 3            ; carried up or down a chute (joystick ignored until its end)

M_TITLE  = 0
M_PLAY   = 1
M_DYING  = 2
M_SPAWN  = 3
M_CLEAR  = 4
M_OVER   = 5
M_TELE   = 6            ; teleporting: dissolving, moving, rebuilding (see mode_tele)

FR_STAND   = 0          ; sprite frames, in the order of assets/sprites.txt: families of frames, to which
FR_LEAN    = 3          ; `face` (0 front, 1 right, 2 left) is added: stand (3), lean (2: right, left),
FR_SQUASH  = 5          ; squash (3), stretch (3) and the two pop frames
FR_STRETCH = 8
FR_DIE_A   = 11
FR_DIE_B   = 12
HOP_JT      = 8         ; the hop out of the top of an up chute starts this far into the jump table (5 pixels up) ...
HOP_FRAMES  = 4         ; ... and drifts sideways this many pixels (enough to leave the chute's column)
LAND_FRAMES = 4         ; how long he stays squashed after landing
BOUNCE_ROWS = 14        ; a trampoline looks this many tile rows up his column for something to bounce him to ...
BOUNCE_TOP  = 24        ; ... but not above this line (pixel row 24 = tile row 3: a surface higher could not be landed on)
BOUNCE_JT   = 3         ; a bounce is the jump's last 17 pixels (jump_dy from index 3) after bn frames of 3 pixels each
FALL_SLOW   = 4         ; falling is slower than rising: the first FALL_SLOW pixels of a fall take a pixel a frame, then up to
FALL_FAST   = 16        ; FALL_FAST it is 1, 1, 2 pixels on successive frames (a pixel and a third a frame), after that 2
SPIKE_TOP   = 1         ; a spike tile's tips are on this line of the tile (assets/tiles.txt): feet below it are hurt
TR_STEPS    = 13        ; the trampoline's mat takes 2 frames on each of these amplitudes (tramp_amp), 26 frames in all
.assert T_TRAMPOLINE_LR - T_TRAMPOLINE_L = 2, error, "the trampoline's three end caps need consecutive ids"
.assert T_TELEPORT = 125 .and T_TELEPORT_ONCE = 126, error, "the flood fill (tp_search) relies on the teleport tiles being 125 and 126 (glow bytes 253, 254) and 127 being free"

JOY_UP    = $01
JOY_DOWN  = $02
JOY_LEFT  = $04
JOY_RIGHT = $08
JOY_FIRE  = $10

F_DOT     = 4           ; tile_flags bit: a platform tile with a dot in it (assets/tiles.txt)

T_CONV_FIRST = T_CONV_R_SLOW    ; the eight belt tiles are consecutive, see assets/tiles.txt
; the exit door: six glyphs with consecutive ids (alt tiles: the map byte is the id + 128), drawn a step at a time
DOOR_GLYPHS  = CHARSET_ADDR + (T_DOOR_BL & $7F) * 8
        .assert (T_DOOR_TR & $7F) - (T_DOOR_BL & $7F) = 5, error, "the six door tiles need consecutive ids"
FADE_STEPS   = 16
CONV_GLYPHS  = CHARSET_ADDR + T_CONV_FIRST * 8
; the chutes' glyphs: each is one of a pair (the plain tile on even screen rows, its twin on odd ones)
CHUTE_R_A    = CHARSET_ADDR + T_SLIDE_R * 8
CHUTE_R_B    = CHARSET_ADDR + T_SLIDE_R_B * 8
CHUTE_L_A    = CHARSET_ADDR + T_SLIDE_L * 8
CHUTE_L_B    = CHARSET_ADDR + T_SLIDE_L_B * 8

KIND_EXPL   = 0         ; timed tiles
KIND_VANISH = 1
PH_FUSE     = 0
PH_GONE     = 1
PH_BOOM     = 2
FUSE_EXPL   = 45        ; frames from stepping on a bomb block to the blast
FUSE_VANISH = 30        ; ... from stepping on a vanishing block until it goes
VANISH_BACK = 180       ; ... until it comes back
CHAIN_FUSE  = 8         ; a bomb block next to a blast goes off this soon
BOOM_FRAMES = 8
PEG_WAIT    = 40        ; frames a peg rests at each end of its block
ROLLER_LONG = 8         ; a roller this long (or longer) has the most grip
SLICK_MAX   = 20        ; top speed on ice and rollers, in 1/16 pixel per frame
DEMO_LEVELS = 3         ; the attract AI plays the first this many maps (it knows nothing of the factory parts)

MAX_FALL   = 64         ; falling further than this (pixels) kills
SPR_H      = 16
START_LIVES = 3
ITEM_POINTS = 10
DOT_POINTS  = 1
CLEAR_BONUS = 100
SPAWN_FRAMES = 48       ; length of the "come to life" animation
COLS         = 40       ; the playfield, in tiles
ROWS         = 24
TP_FRAMES    = 32       ; teleporting: 16 frames of dissolving, then 16 of rebuilding him at the other teleporter
T_MARK       = 127      ; the one unused glyph: the teleport flood fill writes it over the tiles of the group he leaves
MAX_TP_STACK = 64       ; the flood fill's pending tiles (a group is at most 64 tiles: MAX_TELEPORT_GROUP in build_assets.py)
DIE_FRAMES   = 80       ; length of the death animation
CLEAR_FRAMES = 60
TITLE_IDLE_SECS = 10
DEMO_SECS    = 30
OVER_SECS    = 10

        .export SCREEN, PM0, M_TITLE, M_PLAY, M_DYING, M_SPAWN, M_CLEAR, M_OVER, M_TELE

; ---------------------------------------------------------------------------
        .segment "ZEROPAGE"
px:       .res 1
py:       .res 1
oldpy:    .res 1
pfloat:   .res 1        ; lines he floated above his box the last time he was drawn (PLAYER_FLOAT +/- the bob)
state:    .res 1
jt:       .res 1        ; index into jump_dy, $FF = not rising
bn:       .res 1        ; a trampoline bounce: frames of full-speed rise (3 pixels) still to go before the usual slowing tail
cx:       .res 1        ; the pixel column of the edge he is on while stepping (see step_to)
hop:      .res 1        ; frames of forced sideways drift left (the hop out of the top of an up chute)
hdir:     .res 1        ; which way that drift goes (the way he faced when the ride ended): 2 = left, else right
rkind:    .res 1        ; which chute he rides: 0 = down (T_SLIDE_R), 1 = up (T_SLIDE_L)
fall:     .res 1        ; pixels fallen since the top of the arc
anim:     .res 1
moved:    .res 1
joy:      .res 1        ; the joystick the game logic sees (hardware, or the AI in attract mode)
joyprev:  .res 1
hjoy:     .res 1        ; the real joystick, always
hprev:    .res 1
tx:       .res 1        ; pixel being queried by get_tile
ty:       .res 1
tmp:      .res 1
tmp2:     .res 1
score:    .res 2
hiscore:  .res 2
left:     .res 1        ; items still to collect
lives:    .res 1
level:    .res 1        ; level number shown on screen, 1..99
lvlidx:   .res 1        ; which map, 0..LEVEL_COUNT-1
mode:     .res 1
demo:     .res 1        ; 1 = attract mode (the AI plays)
demo_n:   .res 1        ; which level the next attract run uses
timer:    .res 2        ; frames left (title idle, attract run, game over)
mtimer:   .res 1        ; frames since the current mode started (saturates at 255)
fps:      .res 1        ; 60 (NTSC) or 50 (PAL)
tr_t:     .res 1        ; the trampoline animation: 0 = none, else 1 + frames since the bounce (2 per step of tramp_amp)
tr_row:   .res 1        ; ... the tile row of the run that is bouncing
tr_l:     .res 1        ; ... its leftmost and rightmost tile columns
tr_r:     .res 1
tr_c:     .res 1        ; ... and the column he landed in (the mat sags deepest there)
tr_a:     .res 1        ; ... the amplitude being drawn
tr_i:     .res 1
frame:    .res 1        ; player sprite frame to draw
drawn:    .res 1        ; how many lines of it to draw (the spawn animation reveals it)
dyi:      .res 1        ; index into die_dy
newhi:    .res 1
deaths:   .res 1        ; counts deaths, for the tests
snd:      .res 1        ; sound timer / volume
sndf:     .res 1        ; sound pitch
flash:    .res 1        ; background flash timer
flashc:   .res 1        ; background flash colour
ptr:      .res 2
ptr2:     .res 2
sptr:     .res 2        ; string source
dptr:     .res 2        ; screen destination
dn:       .res 2        ; number being printed
vec:      .res 2        ; mode handler
ai_have:  .res 1        ; AI has a target item
ai_ic:    .res 1        ; ... its tile column
ai_ir:    .res 1        ; ... its tile row
ai_goal:  .res 1        ; pixel x the AI is walking to (the item, or the ladder that leads towards it)
ai_vert:  .res 1        ; JOY_UP / JOY_DOWN to press once aligned with the ladder
a_fp:     .res 1
a_ft:     .res 1
a_pc:     .res 1
a_lc:     .res 1
a_best:   .res 1
a_cost:   .res 1
under:    .res 1        ; map byte under the middle of the feet
vx:       .res 1        ; sliding speed, signed, in 1/16 pixel per frame
vfrac:    .res 1
cfrac:    .res 1        ; belt drift remainder
cacc:     .res 1        ; speed of an accelerating belt
cacc_t:   .res 1
cdir:     .res 1        ; 0 = drifting right, 1 = left
s_acc:    .res 1
s_fric:   .res 1
s_fmask:  .res 1
fcount:   .res 1
gtick:    .res 1        ; frames of play (pegs move every other one)
pg_n:     .res 1        ; pegs in this level
pg_i:     .res 1
pg_k:     .res 1        ; pixels a peg may still shove him this frame
tt_i:     .res 1        ; timed tile scratch
tt_j:     .res 1
tt_c:     .res 1
tt_r:     .res 1
tt_k:     .res 1
tt_f:     .res 1
ov_x:     .res 1
ov_y:     .res 1
tt_o:     .res 1        ; the screen byte (with its end cap) of the tile being armed
tp_t:     .res 1        ; teleporter: frames he has stood on one, 0 = not charging
tp_lock:  .res 1        ; 1 = he has arrived on this one (or it leads nowhere): step off it before it charges again
tp_k:     .res 1        ; the kind (T_TELEPORT or T_TELEPORT_ONCE) of the teleporter he stands on, and the column and row
tp_c:     .res 1        ; ... of the tile of it under his feet
tp_r:     .res 1
tp_dc:    .res 1        ; where it sends him: column and row of the first tile (reading order) of the next teleporter
tp_dr:    .res 1
tp_s4:    .res 1        ; the dissolve: 4 * the step (0 = whole, 16 = gone), index into tp_mask
tp_mr:    .res 1        ; flood fill: the first tile (reading order) found, row and column
tp_mc:    .res 1
tcx:      .res 1        ; flood fill: the tile being looked at
tcy:      .res 1

        .segment "BSS"
tt_col:   .res 8        ; timed tiles (bomb blocks and vanishing blocks that have been stepped on)
tt_row:   .res 8
tt_t:     .res 8        ; frames left in the current phase
tt_ph:    .res 8        ; PH_FUSE, PH_GONE, PH_BOOM, or $FF = free slot
tt_kind:  .res 8
tt_orig:  .res 8        ; the screen byte to put back (it may be an end cap)
pg_x:     .res 2        ; pegs: left edge in pixels
pg_y:     .res 2        ;       top line
pg_min:   .res 2
pg_max:   .res 2
pg_dir:   .res 2        ;       1 = right, $FF = left
pg_wait:  .res 2
cph:      .res 8        ; animation phase of each belt tile
pal0:     .res 24       ; colour of pixel value 1, 2, 3, alt 3 for each row of the screen; the display-list
pal1:     .res 24       ; interrupt copies row n+1's colours into the hardware at the end of row n
pal2:     .res 24
pal3:     .res 24
dli_row:  .res 1        ; the row the next interrupt sets up (1..23)
dli_n:    .res 1        ; interrupts so far (test build only)
ai_kind:  .res 1        ; the AI's target: 0 = item or door, 1 = a dot
a_row:    .res 1
a_k:      .res 1
a_tr:     .res 1
door_open: .res 1       ; 1 once everything is collected: the exit is there to walk into
door_dir: .res 1        ; 1 = fading in, $FF = fading out, 0 = still
door_phase: .res 1      ; how much of the door shows: 0 (none) .. FADE_STEPS (all)
door_tick: .res 1
face:     .res 1        ; which way he looks: 0 at you (until he first moves), 1 right, 2 left
land_t:   .res 1        ; frames of landing squash left
last_st:  .res 1        ; his state on the previous frame (to see a landing)
door_art: .res 48       ; the door as the asset tool drew it (6 tiles of 8 bytes), copied at start
d_i:      .res 1
d_b:      .res 1
d_o:      .res 1
d_p:      .res 1
d_t:      .res 1
tp_a:     .res 1        ; flood fill: the byte that is filled over, and the byte written in its place
tp_b:     .res 1
tp_n:     .res 1        ; flood fill: tiles waiting on the stack (2 bytes each: column, row)
tp_hr:    .res 1        ; the first tile of the group he leaves: row and column
tp_hc:    .res 1

; ---------------------------------------------------------------------------
        .macro SETDST addr
        lda #<(addr)
        sta dptr
        lda #>(addr)
        sta dptr+1
        .endmacro

        .macro PUTSTR str, row, col
        lda #<str
        sta sptr
        lda #>str
        sta sptr+1
        SETDST SCREEN + (row) * 40 + (col)
        jsr put_str
        .endmacro

        .macro STR text
        .byte text, $FF
        .endmacro

        .macro BLANK n
        .repeat n
        .byte 0
        .endrepeat
        .byte $FF
        .endmacro

; ---------------------------------------------------------------------------
        .segment "CODE"

start:
        cld
        lda #0
        sta hiscore
        sta hiscore+1
        sta demo_n
        sta deaths
        sta joy
        sta hjoy
        sta hprev
        sta snd
        sta flash
        sta oldpy
        sta frame
        sta demo
        sta tp_s4
        lda #16
        sta drawn
        lda PAL
        and #$0E
        beq @pal
        lda #60
        bne @fps
@pal:   lda #50
@fps:   sta fps

        ldx #47                 ; keep the door's art: its glyphs are rewritten for the fade
@art:   lda DOOR_GLYPHS,x
        sta door_art,x
        dex
        bpl @art
        ldx #7
        lda #0
@cph:   sta cph,x
        dex
        bpl @cph
        sta pg_n
        sta cacc_t
        sta cfrac
        sta vx
        sta vfrac
        sta fcount
        sta gtick
        lda #4
        sta cacc
        jsr clear_pm
        lda #<dlist
        sta SDLSTL
        lda #>dlist
        sta SDLSTL+1
        lda #<dli
        sta VDSLST
        lda #>dli
        sta VDSLST+1
        lda #1
        sta dli_row
        lda #>CHARSET_ADDR
        sta CHBAS
        lda #$11
        sta GPRIOR              ; players in front of the playfield (priority 1); bit 4: the four missiles form a fifth
                                ; player, coloured COLPF3, behind the players and the playfield colours 0-2
        lda #0
        sta SIZEP0
        sta SIZEM               ; the missiles are normal width: 2 clocks each
        lda #>PMAREA
        sta PMBASE
        lda #3
        sta GRACTL              ; enable players and missiles
        jsr enter_title
        lda #$3E                ; DL DMA + single-line PM + missiles + players + normal width
        sta SDMCTL
        lda #$C0                ; vertical blank + display-list interrupts
        sta NMIEN

mainloop:
        jsr vwait
        lda #0
        sta ATRACT
        jsr read_input
        lda demo
        beq @mode
        jsr demo_tick
@mode:  lda mode
        asl a
        tax
        lda mode_tab,x
        sta vec
        lda mode_tab+1,x
        sta vec+1
        jsr run_mode
        jsr animate_belts
        jsr animate_chutes
        jsr update_fx
frame_end:
        jmp mainloop

run_mode:
        jmp (vec)

; Wait for the next frame.
vwait:
        lda RTCLOK+2
@w:     cmp RTCLOK+2
        beq @w
        rts

; ---------------------------------------------------------------------------
; Input: joy bit set = pressed (see JOY_*).
read_input:
        lda hjoy
        sta hprev
        lda STICK0
        eor #$0F
        and #$0F
        sta hjoy
        lda STRIG0
        bne @nofire
        lda hjoy
        ora #JOY_FIRE
        sta hjoy
@nofire:
        rts

; The joystick for the game logic: the real one, or the AI's in attract mode.
get_joy:
        lda joy
        sta joyprev
        lda demo
        bne @ai
        lda hjoy
        sta joy
        rts
@ai:    jmp ai_input

; C set if the real fire button went down this frame.
fire_edge:
        lda hjoy
        and #JOY_FIRE
        beq @no
        lda hprev
        and #JOY_FIRE
        bne @no
        sec
        rts
@no:    clc
        rts

; ---- timers -----------------------------------------------------------------
; timer = A seconds, in frames.
set_timer_secs:
        tax
        lda #0
        sta timer
        sta timer+1
@l:     txa
        beq @d
        lda timer
        clc
        adc fps
        sta timer
        bcc @n
        inc timer+1
@n:     dex
        jmp @l
@d:     rts

; Count the timer down. Z set when it has run out.
tick_timer:
        lda timer
        ora timer+1
        beq @out
        lda timer
        bne @lo
        dec timer+1
@lo:    dec timer
        lda timer
        ora timer+1
@out:   rts

inc_mtimer:
        lda mtimer
        cmp #255
        beq @r
        inc mtimer
@r:     rts

; ---------------------------------------------------------------------------
; Tile lookup. In: tx, ty (pixels). Out: A = tile id, ptr -> its screen byte. A platform end cap comes back
; as the plain tile it is a cap of (tile_canon), so none of the rules below care how a block's ends look.
; Anything outside the playfield (and the score row) counts as brick so the player cannot leave it.
get_tile:
        lda ty
        cmp #192
        bcs @solid
        cmp #8
        bcc @solid
        lda tx
        cmp #160
        bcs @solid
        lsr a
        lsr a
        sta tmp                 ; column
        lda ty
        lsr a
        lsr a
        lsr a
        tax                     ; row
        lda row_lo,x
        clc
        adc tmp
        sta ptr
        lda row_hi,x
        adc #0
        sta ptr+1
        ldy #0
        lda (ptr),y
        tax
        lda tile_canon,x
        rts
@solid: lda #T_BRICK
        rts

; C set if the tile at (tx,ty) is solid (blocks movement). A = the tile.
get_solid:
        jsr get_tile
        tax
        lda tile_flags,x
        and #1
        beq @no
        txa
        sec
        rts
@no:    txa
        clc
        rts

; C set if the tile at (tx,ty) can be stood on: a solid tile, the top edge of a one-way
; platform, or the very top of a ladder.
tile_standable:
        jsr get_tile
        tax
        lda tile_flags,x
        lsr a                   ; bit 0 (solid) -> carry
        bcs @yes
        lsr a                   ; bit 1 (one-way) -> carry
        bcs @top
        cpx #T_LADDER
        bne @no
        lda ty
        and #7
        bne @no                 ; only the top edge of the tile
        lda ty
        sec
        sbc #1
        sta ty
        jsr get_tile            ; tile above must not be ladder
        cmp #T_LADDER
        beq @no
@yes:   sec
        rts
@top:   lda ty
        and #7
        bne @no
        sec
        rts
@no:    clc
        rts

; C set if the player's feet rest on something.
ground_below:
        lda py
        clc
        adc #SPR_H
        sta ty
        lda px
        sta tx
        jsr tile_standable
        bcs @done
        lda py
        clc
        adc #SPR_H
        sta ty
        lda px
        clc
        adc #3
        sta tx
        jsr tile_standable
@done:  rts

; C set if a ladder is at the player's body (used to start climbing).
ladder_overlap:
        lda px
        clc
        adc #2
        sta tx
        lda py
        clc
        adc #8
        sta ty
        jsr get_tile
        cmp #T_LADDER
        beq @yes
        lda py
        clc
        adc #15
        sta ty
        jsr get_tile
        cmp #T_LADDER
        beq @yes
        clc
        rts
@yes:   sec
        rts

; C set if a ladder is directly under the feet (climb down from the top).
ladder_under:
        lda px
        clc
        adc #2
        sta tx
        lda py
        clc
        adc #SPR_H
        sta ty
        jsr get_tile
        cmp #T_LADDER
        beq @yes
        clc
        rts
@yes:   sec
        rts

; ---------------------------------------------------------------------------
update_player:
        lda #0
        sta moved
        lda state
        cmp #S_CLIMB
        bne @notclimb
        jmp up_climb
@notclimb:
        cmp #S_AIR
        bne @notair
        jmp up_air
@notair:
        cmp #S_RIDE
        bne @ground
        jmp up_ride

@ground:
        jsr chute_catch         ; walked into a chute: it carries him
        bcc @nochute
        rts
@nochute:
        jsr ground_below
        bcs @standing
        lda #S_AIR              ; walked off an edge
        sta state
        lda #0
        sta fall
        sta vx
        sta vfrac
        sta hop
        lda #$FF
        sta jt
        rts
@standing:
        lda joy
        and #JOY_UP
        beq @noup
        jsr ladder_overlap
        bcc @noup
        jmp start_climb
@noup:  lda joy
        and #JOY_DOWN
        beq @nodown
        jsr ladder_under
        bcc @nodown
        jmp start_climb
@nodown:
        lda joy
        and #JOY_FIRE
        beq @surface
        lda joyprev
        and #JOY_FIRE
        bne @surface            ; need a fresh press
        lda #0
        sta jt
        sta fall
        sta vx
        sta vfrac
        sta hop
        lda #S_AIR
        sta state
        jmp do_horiz
@surface:
        jsr surface_drift       ; belts carry you; sets `under`
        lda under
        ldx #0
        cmp #T_ICE
        beq @slick
        inx
        cmp #T_ROLLER
        beq @slick
        lda #0
        sta vx
        sta vfrac
        jmp do_horiz
@slick: jmp slick_move

; ---- chutes ------------------------------------------------------------------------------
; Chutes are vertical, one tile wide, and neither solid nor a surface: nothing stands on them and in the air he passes
; straight through. Only WALKING (the ground state) into one catches him: a chute tile at the middle of his body column
; (px+2) at his body rows (py+8, py+15), or directly under his feet (py+16: a chute that fills a gap in the floor).
; He is then locked in (S_RIDE, joystick ignored) and carried to the end of the column, 2 pixels a frame.
; One exception: a DOWN chute only catches him from under his feet. At the body rows alone (the chute stands on the
; floor he walks on) it has nowhere to take him, and catching him would only snap him back every frame (he could never
; walk through it, and would be caught again where a ride ends on a floor); the ride down always starts in the floor.
; C set (and the ride begun) if he walked into one.
chute_catch:
        lda px
        clc
        adc #2
        sta tx
        lda py
        clc
        adc #8
        sta ty
        jsr get_tile
        cmp #T_SLIDE_L
        beq @got
        lda py
        clc
        adc #15
        sta ty
        jsr get_tile
        cmp #T_SLIDE_L
        beq @got
        lda py
        clc
        adc #SPR_H
        sta ty
        jsr get_tile
        jsr is_chute
        bcs @got
        clc
        rts
@got:   ldx #0                  ; A = the tile: down (T_SLIDE_R) or up
        cmp #T_SLIDE_R
        beq @kind
        inx
@kind:  stx rkind
        lda px
        clc
        adc #2
        and #$FC                ; snap to the tile column
        sta px
        lda py
        and #$FE                ; (even, so 2 pixel steps meet a tile edge exactly)
        sta py
        lda #S_RIDE
        sta state
        lda #$FF
        sta jt
        lda #0
        sta fall
        sta vx
        sta vfrac
        sta hop
        sec
        rts

; C set if tile A is a chute (A is kept).
is_chute:
        cmp #T_SLIDE_R
        beq @y
        cmp #T_SLIDE_L
        beq @y
        clc
        rts
@y:     sec
        rts

; One frame of the ride. Down: while a chute is directly under the feet, py += 2; when there is none (he is below
; the last tile, standing on whatever is next, or falling past it) he is released into normal physics. Up: while a
; chute is at the feet row, py -= 2; when his feet are above the top tile he hops out in the direction he faces
; (a short jump with a few pixels of forced drift) to land on the platform beside the top.
up_ride:
        lda px
        clc
        adc #2
        and #$FC
        sta px                  ; (a peg might have nudged him)
        sta tx
        lda rkind
        bne @up
        lda py
        clc
        adc #SPR_H
        sta ty
        jsr get_tile
        cmp #T_SLIDE_R
        bne @free
        inc py
        inc py
        rts
@up:    lda py
        cmp #10
        bcc @hop                ; (do not go up into the score row)
        clc
        adc #15
        sta ty
        jsr get_tile
        cmp #T_SLIDE_L
        bne @hop
        dec py
        dec py
        rts
@hop:   lda face                ; (he does not turn while riding: the joystick is ignored)
        sta hdir
        lda #HOP_JT
        sta jt
        lda #HOP_FRAMES
        sta hop
        bne @air                ; (always)
@free:  lda #$FF
        sta jt
        lda #0
        sta hop
@air:   lda #S_AIR
        sta state
        lda #0
        sta fall
        sta vx
        sta vfrac
        rts

; ---- what the surface under the feet does ---------------------------------------------------
; Belts drift the player (in 1/16 pixel per frame: slow 8, normal 16, fast 32; an
; accelerating belt starts at 4 and gains 1 every 4 frames up to 32). Sets `under`.
surface_drift:
        ldx #0                  ; probe under the middle of the feet, then under each foot: a belt
@probe: stx tt_j                ; may be under only one of them
        lda px
        clc
        adc probe_dx,x
        sta tx
        lda py
        clc
        adc #SPR_H
        sta ty
        jsr get_tile
        ldx tt_j
        bne @n0
        sta tt_k                ; remember the middle tile
@n0:    sta under
        jsr is_surface
        bcs @found
        ldx tt_j
        inx
        cpx #3
        bcc @probe
        lda tt_k
        sta under
@found: lda under
        sec
        sbc #T_CONV_FIRST
        cmp #8
        bcs @none               ; (anything below the belt ids wraps round to a big number)
        tax
        lda conv_dir,x
        sta cdir
        lda conv_spd,x
        bne @fixed
        inc cacc_t              ; accelerating belt
        lda cacc_t
        and #3
        bne @gotacc
        lda cacc
        cmp #32
        bcs @gotacc
        inc cacc
@gotacc:
        lda cacc
        jmp @belt
@fixed: pha
        lda #4
        sta cacc
        lda #0
        sta cacc_t
        pla
@belt:  sta tmp                 ; walking with the belt: carried at its full speed on top of his own. Walking
        lda joy                 ; against it: it pulls at him only 3/8 as hard, so he can always walk onto
        ldx cdir                ; it and along it, just slowly
        bne @bl
        and #JOY_LEFT           ; the belt carries right: left is against it
        jmp @bt
@bl:    and #JOY_RIGHT
@bt:    beq @full               ; not walking against it
        lda tmp
        lsr a
        lsr a
        pha                     ; speed/4 + speed/8
        lsr a
        sta tmp
        pla
        clc
        adc tmp
        jmp @drift
@full:  lda tmp
        jmp @drift
@none:  lda #4
        sta cacc
        lda #0
        sta cacc_t
        sta cfrac
        rts
@drift: clc
        adc cfrac
        sta cfrac
@loop:  lda cfrac
        cmp #16
        bcc @done
        sec
        sbc #16
        sta cfrac
        lda cdir
        bne @left
        jsr push_right
        jmp @loop
@left:  jsr push_left
        jmp @loop
@done:  rts

; C set if tile A does something to a player standing on it: a belt, ice or roller.
is_surface:
        cmp #T_ICE
        beq @y
        cmp #T_ROLLER
        beq @y
        sec
        sbc #T_CONV_FIRST
        cmp #8
        bcc @y
        clc
        rts
@y:     sec
        rts

; Move one pixel with all the usual collision, without the walking animation.
push_right:
        lda moved
        pha
        lda anim
        pha
        jsr move_right
        pla
        sta anim
        pla
        sta moved
        rts

push_left:
        lda moved
        pha
        lda anim
        pha
        jsr move_left
        pla
        sta anim
        pla
        sta moved
        rts

; Ice and rollers (X = 0 ice, 1 roller): speed up gradually, glide when you let go.
slick_move:
        lda slick_fric,x
        sta s_fric
        lda slick_fmask,x
        sta s_fmask
        lda slick_acc,x
        cpx #1
        bne @gotacc
        jsr roller_len          ; a roller grips harder the longer it is
@gotacc:
        sta s_acc
        inc fcount
        lda joy
        and #JOY_RIGHT
        beq @noright
        lda vx
        clc
        adc s_acc
        bmi @setr               ; still moving left
        cmp #SLICK_MAX+1
        bcc @setr
        lda #SLICK_MAX
@setr:  sta vx
        jmp @move
@noright:
        lda joy
        and #JOY_LEFT
        beq @coast
        lda vx
        sec
        sbc s_acc
        bpl @setl               ; still moving right
        cmp #256-SLICK_MAX
        bcs @setl
        lda #256-SLICK_MAX
@setl:  sta vx
        jmp @move
@coast: lda fcount              ; no input: friction, on some frames
        and s_fmask
        bne @move
        lda vx
        beq @move
        bmi @cneg
        sec
        sbc s_fric
        bpl @setc
        lda #0
        beq @setc
@cneg:  clc
        adc s_fric
        bmi @setc
        lda #0
@setc:  sta vx
@move:  lda vx
        bne @go
        rts
@go:    bmi @mneg
        clc
        adc vfrac
        sta vfrac
@r:     lda vfrac
        cmp #16
        bcc @rts
        sbc #16
        sta vfrac
        lda px
        pha
        jsr move_right
        pla
        cmp px
        bne @r
        beq @stop
@mneg:  eor #$FF
        clc
        adc #1                  ; |vx|
        clc
        adc vfrac
        sta vfrac
@l:     lda vfrac
        cmp #16
        bcc @rts
        sbc #16
        sta vfrac
        lda px
        pha
        jsr move_left
        pla
        cmp px
        bne @l
@stop:  lda #0
        sta vx
        sta vfrac
@rts:   rts

; How many roller tiles are in this run under the feet (1..ROLLER_LONG): the longer the roller, the faster it
; picks the player up (acceleration = its length in 1/16 pixel per frame per frame).
roller_len:
        lda #0
        sta tt_i                ; (get_tile clobbers X, so the probe index lives here)
@base:  ldx tt_i                ; the roller tile under the feet (middle, then each foot), as a pixel column
        lda px
        clc
        adc probe_dx,x
        and #$FC
        sta tt_c
        jsr @probe
        beq @found
        inc tt_i
        lda tt_i
        cmp #3
        bcc @base
@found: lda #1
        sta tt_k
        lda tt_c
        sta tt_j
@l:     lda tt_j
        sec
        sbc #4
        bcc @r0
        jsr @probe
        bne @r0
        inc tt_k
        lda tt_k
        cmp #ROLLER_LONG
        bcc @l
        rts
@r0:    lda tt_c
        sta tt_j
@r:     lda tt_j
        clc
        adc #4
        jsr @probe
        bne @done
        inc tt_k
        lda tt_k
        cmp #ROLLER_LONG
        bcc @r
@done:  lda tt_k
        rts
@probe: sta tt_j                ; A = pixel column: Z set if there is a roller under it
        sta tx
        lda py
        clc
        adc #SPR_H
        sta ty
        jsr get_tile
        cmp #T_ROLLER
        rts

; Snap onto the ladder column and start climbing.
start_climb:
        lda px
        clc
        adc #2
        and #$FC
        sta px
        lda #S_CLIMB
        sta state
        lda #$FF
        sta jt
        lda #0
        sta fall
        sta hop
        sta bn
        rts

; ---- airborne ---------------------------------------------------------------
up_air:
        lda joy
        and #JOY_UP
        beq @noladder
        jsr ladder_overlap
        bcc @noladder
        jmp start_climb         ; grab a ladder mid-air
@noladder:
        lda hop
        beq @free
        dec hop                 ; the hop out of an up chute: drift the way he faces, joystick ignored
        lda hdir
        cmp #2
        bne @hr
        jsr move_left
        jmp @drift
@hr:    jsr move_right
        jmp @drift
@free:  jsr do_horiz
@drift: lda jt
        cmp #$FF
        beq air_fall

        lda bn
        beq @table
        dec bn                  ; a trampoline bounce: bn frames at full speed first (jt stays where it is: the
        dec jt                  ; inc below undoes this), then the usual slowing tail of the jump
        lda #3
        bne @have               ; (always)
@table: ldx jt                  ; rising: jump_dy[jt] pixels this frame. Nothing above him matters while he rises:
        lda jump_dy,x           ; no head bumps, he just overlays blocks, bombs, platforms and chutes (only the
        beq @apex               ; score row is a ceiling)
@have:  sta tmp2
@rise:  lda py
        cmp #9
        bcc @apex
        dec py
        dec tmp2
        bne @rise
        inc jt
        rts
@apex:  lda #$FF
        sta jt
        lda #0
        sta bn
        rts

; Falling: slower than rising, so he floats down. The pixels a frame depend on how far he has fallen (fall counts pixels,
; so the lethal distance is unchanged): 1 for the first FALL_SLOW, then the pattern 1, 1, 2 (fall bit 1 clear = 2) up to
; FALL_FAST, then 2. Pixels are moved one at a time. He lands on the first surface under his feet, but never inside a
; solid: if a solid is at the row just above the feet (he rose into a block and is coming back down through it) he keeps
; falling until he is clear.
air_fall:
        lda fall
        cmp #FALL_FAST
        bcs @two
        cmp #FALL_SLOW
        bcc @one
        and #2
        bne @one
@two:   lda #2
        bne @speed
@one:   lda #1
@speed: sta tmp2
@step:  jsr ground_below
        bcc @fall
        jsr feet_clear
        bcs @land
@fall:  inc py
        inc fall
        dec tmp2
        bne @step
        rts
@land:  jsr try_bounce          ; a trampoline under his feet catches him, however far he fell
        bcs @bounced
        lda fall
        cmp #MAX_FALL+1
        bcc @safe
        jmp die
@safe:  lda #S_GROUND
        sta state
        lda #0
        sta fall
@bounced:
        rts

; Landing on a trampoline (the tile under the middle of his feet, else under either foot, like belts): if there is
; anything he could land on in his column above it, he is thrown straight up, joystick free, and falls onto it.
; Looking up from the trampoline tile by tile (BOUNCE_ROWS of them at most, never above BOUNCE_TOP), the first row
; where the middle (px+2) or either foot column (px, px+3) has a surface (tile_standable: a solid tile of any kind,
; the top of a one-way platform or step, or of a ladder) is the target, k tiles up. The bounce is the end of an
; ordinary jump (BOUNCE_JT: the last 17 pixels of jump_dy) after bounce_n[k] extra frames of 3 pixels, so it rises
; 17 + 3*bounce_n[k] pixels >= 8*k + 8: his feet clear the target's top by a tile (8 to 10 pixels), and he lands on it
; on the way down (rising ignores everything above). Nothing in range: no bounce, an ordinary landing.
; C set (the bounce begun, state still S_AIR) if he bounced.
try_bounce:
        ldx #0
@find:  stx tt_j
        lda px
        clc
        adc probe_dx,x
        sta tx
        lda py
        clc
        adc #SPR_H
        sta ty
        jsr get_tile
        cmp #T_TRAMPOLINE
        beq @tramp
        ldx tt_j
        inx
        cpx #3
        bcc @find
        clc
        rts
@tramp: lda tx                  ; the tile he landed on: column and row, for the animation if he bounces
        lsr a
        lsr a
        sta tt_f
        lda ty
        lsr a
        lsr a
        lsr a
        sta tt_r
        lda py
        clc
        adc #SPR_H
        and #$F8
        sta tt_c                ; the top of the trampoline tile
        lda #1
        sta tt_k                ; k: how many tiles up
@up:    lda tt_c
        sec
        sbc #8
        sta tt_c
        cmp #BOUNCE_TOP
        bcc @none
        ldx #0
@col:   stx tt_j
        lda px
        clc
        adc probe_dx,x
        sta tx
        lda tt_c
        sta ty
        jsr tile_standable
        bcs @found
        ldx tt_j
        inx
        cpx #3
        bcc @col
        inc tt_k
        lda tt_k
        cmp #BOUNCE_ROWS+1
        bcc @up
@none:  clc
        rts
@found: ldx tt_k
        lda bounce_n,x
        sta bn
        lda #BOUNCE_JT
        sta jt
        lda #0
        sta fall
        jsr tramp_start
        lda #6                  ; a short "boing"
        sta snd
        lda #$50
        sta sndf
        sec
        rts

; C set if neither foot column has a solid tile at the lowest row of the body (py+15). (At the bottom of the screen
; the floor is the edge itself.)
feet_clear:
        lda py
        cmp #176
        bcs @clear
        clc
        adc #15
        sta ty
        lda px
        sta tx
        jsr get_solid
        bcs @no
        lda px
        clc
        adc #3
        sta tx
        jsr get_solid
        bcs @no
@clear: sec
        rts
@no:    clc
        rts

; ---- climbing ---------------------------------------------------------------
up_climb:
        lda joy
        and #(JOY_LEFT | JOY_RIGHT)
        beq @vert
        jsr ground_below
        bcc @vert               ; nothing to step onto: keep holding the ladder
        lda #S_GROUND
        sta state
        jmp do_horiz
@vert:  lda joy
        and #JOY_UP
        beq @down
        lda px
        sta tx
        lda py
        sec
        sbc #1
        sta ty
        jsr get_solid
        bcs @done               ; ceiling
        lda py
        clc
        adc #15
        sta ty
        jsr get_tile
        cmp #T_LADDER
        bne @leave
        dec py
        inc anim
        inc moved
        lda py
        clc
        adc #15
        sta ty
        jsr get_tile
        cmp #T_LADDER
        beq @done
@leave: lda #S_GROUND           ; stepped off the top of the ladder
        sta state
        rts
@down:  lda joy
        and #JOY_DOWN
        beq @done
        lda px
        sta tx
        lda py
        clc
        adc #SPR_H
        sta ty
        jsr get_solid
        bcs @floor
        inc py
        inc anim
        inc moved
        lda py
        clc
        adc #15
        sta ty
        jsr get_tile
        cmp #T_LADDER
        beq @done
@floor: lda #S_GROUND           ; reached a floor, or the ladder ended
        sta state
@done:  rts

; ---- walking ----------------------------------------------------------------
do_horiz:
        lda joy
        and #JOY_RIGHT
        beq @left
        jmp move_right
@left:  lda joy
        and #JOY_LEFT
        beq @rts
        jmp move_left
@rts:   rts

; One step right or left if nothing solid is in the way at the head, the middle or the feet. (Stairs and chutes are
; not solid: you walk through them, and jump up onto them.)
move_right:
        lda px
        cmp #156
        bcs @blk
        clc
        adc #4                  ; right edge after the step
        sta tx
        jmp step_to
@blk:   rts

move_left:
        lda px
        beq @blk
        sec
        sbc #1
        sta tx
        jmp step_to
@blk:   rts

; Walk into pixel column tx (px moves by one: the caller has put the new edge in tx) unless blocked: a solid tile
; at the head, middle or feet row of that column blocks him, unless he is already inside a solid at that row on
; the edge he is on now (he rose into a block: he slides about in it and out of it, rather than being stuck).
step_to:
        lda tx
        cmp px
        bcc @lft
        sbc #1                  ; (carry set) moving right: the edge he is on is one pixel behind the new one
        bcs @cx
@lft:   adc #1                  ; moving left: one pixel on
@cx:    sta cx
        lda py
        jsr step_row
        bcs @blk
        lda py
        clc
        adc #8
        jsr step_row
        bcs @blk
        lda py
        clc
        adc #15
        jsr step_row
        bcs @blk
        lda tx                  ; moving right: the new edge is past px; left: it is before it
        cmp px
        bcc @left
        inc px
        jmp @moved
@left:  dec px
@moved: inc anim
        inc moved
@blk:   rts

; C set if stepping into column tx is blocked at pixel row A: a solid there, unless he is inside a solid already
; at that row on the edge he is on (cx). tx is kept.
step_row:
        sta ty
        jsr get_solid
        bcc @free
        lda tx
        pha
        lda cx
        sta tx
        jsr get_solid
        pla
        sta tx
        bcc @blocked
@free:  clc
        rts
@blocked:
        sec
        rts

; ---------------------------------------------------------------------------
; Pick up items and check for spikes.
check_tiles:
        ldx #0
@next:  lda px
        clc
        adc pt_dx,x
        sta tx
        lda py
        clc
        adc pt_dy,x
        sta ty
        stx tmp2
        jsr get_tile
        cmp #T_ITEM
        beq @item
        cmp #T_DOOR_BL          ; any of the door's six tiles ...
        bcc @skip
        cmp #T_DOOR_TR+1
        bcs @skip
        lda door_open           ; ... once it is there
        beq @skip
        jmp level_clear
@item:  lda tmp2                ; an item is only collected AT HIS LEVEL: only the feet points (the last two, py+13: the
        cmp #4                  ; row his feet are in) collect it, never the head or mid-body ones, and neither does
        bcc @skip               ; rising (the up phase of a jump or hop, or a ride up a chute): he is passing through
        lda state               ; it from below. Standing, walking, climbing, riding down and falling collect it.
        cmp #S_AIR
        bne @notair
        lda jt
        cmp #$FF
        bne @skip               ; rising in a jump
        beq @take
@notair:
        cmp #S_RIDE
        bne @take
        lda rkind
        bne @skip               ; carried up a chute
@take:  lda #T_EMPTY
        ldy #0
        sta (ptr),y             ; remove it from the screen
        jsr pickup
@skip:  ldx tmp2
        inx
        cpx #6
        bne @next

        lda py                  ; spikes: only the part of the tile from its tips down hurts (SPIKE_TOP)
        clc
        adc #15
        sta ty
        and #7
        cmp #SPIKE_TOP
        bcc @safe
        lda px
        sta tx
        jsr get_tile
        cmp #T_SPIKE
        bne @right
        jmp die
@right: lda px
        clc
        adc #3
        sta tx
        jsr get_tile
        cmp #T_SPIKE
        bne @safe
        jmp die
@safe:  rts

; An item is picked up (it is already off the screen).
pickup:
        lda #8
        sta snd
        lda #$28
        sta sndf
        lda #ITEM_POINTS
        jmp collected

; A dot is eaten.
pickup_dot:
        lda #2
        sta snd
        lda #$40
        sta sndf
        lda #DOT_POINTS
collected:
        jsr add_score
        dec left
        bne @rts
        jsr open_doors          ; that was the last one: the exit opens
        lda #14
        sta snd
        lda #$20
        sta sndf
        lda #$A8                ; cyan flash
        sta flashc
        lda #12
        sta flash
@rts:   rts

; Walking into the open door finishes the level.
level_clear:
        lda #CLEAR_BONUS
        jsr add_score
        lda #M_CLEAR
        sta mode
        lda #0
        sta mtimer
        sta drawn               ; he has gone through the door ...
        lda #$FF
        sta door_dir            ; ... which fades away behind him
        lda #FR_STAND
        sta frame
        lda #$C8                ; green flash
        sta flashc
        lda #25
        sta flash
        rts

; Everything is collected: the exit door fades in.
open_doors:
        lda #1
        sta door_open
        sta door_dir
        rts

; The door's six glyphs are redrawn from door_art with only the pixels whose fade step (door_thr) is below
; door_phase: phase 0 shows nothing, FADE_STEPS shows all of it.
door_draw:
        ldx #47
@byte:  stx d_i
        lda door_art,x
        sta d_b
        lda #0
        sta d_o
        sta d_p
@pix:   asl d_o
        asl d_o
        lda d_i                 ; threshold index = 4 * byte + pixel
        asl a
        asl a
        clc
        adc d_p
        tay
        lda d_b
        and #$C0
        sta d_t                 ; the pixel, in bits 7-6
        lda door_thr,y
        cmp door_phase
        bcs @hidden             ; not yet its turn
        lda d_t
        asl a                   ; bits 7-6 down to 1-0
        rol a
        rol a
        ora d_o
        sta d_o
@hidden:
        asl d_b
        asl d_b
        inc d_p
        lda d_p
        cmp #4
        bne @pix
        ldx d_i
        lda d_o
        sta DOOR_GLYPHS,x
        dex
        bpl @byte
        rts

; Every other frame the door takes one step towards fully there (door_dir = 1) or gone ($FF).
door_fade:
        lda door_dir
        beq @rts
        inc door_tick
        lda door_tick
        and #1
        bne @rts
        lda door_phase
        clc
        adc door_dir
        sta door_phase
        ldx #0
        cmp #FADE_STEPS
        beq @end
        cmp #0
        bne @draw
@end:   stx door_dir
@draw:  jmp door_draw
@rts:   rts

; Standing on a platform tile with a dot in it eats the dot (either foot counts).
eat_dots:
        lda state
        bne eat_end             ; only when standing
        lda px
        sta tx
        lda py
        clc
        adc #SPR_H
        sta ty
        jsr eat_at
        lda px
        clc
        adc #3
        sta tx
        lda py
        clc
        adc #SPR_H
        sta ty
eat_at: lda ty
        cmp #192
        bcs eat_end             ; off the bottom of the screen
        jsr get_tile            ; X = the byte on the screen, ptr -> its cell
        lda tile_flags,x
        and #F_DOT
        beq eat_end
        lda tile_canon,x        ; the plain tile stays behind
        ldy #0
        sta (ptr),y
        jmp pickup_dot
eat_end: rts

; A points onto the 16-bit score (stops at 65535).
add_score:
        clc
        adc score
        sta score
        bcc @r
        inc score+1
        bne @r
        lda #$FF
        sta score
        sta score+1
@r:     rts

die:
        lda mode
        cmp #M_PLAY
        bne @rts                ; already dying (or the level is done)
        lda #M_DYING
        sta mode
        lda #0
        sta mtimer
        sta dyi
        sta moved
        lda #16
        sta drawn
        lda #FR_DIE_A
        sta frame
        inc deaths
        lda #$34                ; red flash
        sta flashc
        lda #20
        sta flash
@rts:   rts

; ---------------------------------------------------------------------------
; Mode handlers: one call per frame.
mode_play:
        jsr door_fade
        jsr get_joy
        jsr update_player
        lda mode
        cmp #M_PLAY
        bne @draw
        jsr check_tiles
        lda mode
        cmp #M_PLAY
        bne @draw
        jsr arm_under           ; bomb blocks and vanishing blocks under the feet
        jsr eat_dots
        jsr update_timed
        jsr tramp_anim
        jsr update_pegs
        lda mode
        cmp #M_PLAY
        bne @draw
        jsr tp_update           ; a second on a teleporter sends him away
        lda mode
        cmp #M_PLAY
        bne @draw
        jsr choose_frame
@draw:  jsr draw_player
        jmp draw_hud

; Death: the player hops, tumbles off the bottom of the screen, then we respawn or end the game.
mode_dying:
        jsr inc_mtimer
        lda py
        cmp #200
        bcs @drawn              ; fallen out of sight
        ldx dyi
        cpx #DIE_LEN
        bcs @fast
        inc dyi
        lda die_dy,x
        bpl @add
        clc                     ; negative: do not wrap above the top of the screen
        adc py
        bcs @set
        lda #0
        beq @set
@fast:  lda #6
@add:   clc
        adc py
@set:   sta py
@drawn: lda mtimer              ; tumble between the two frames, flicker the colour
        lsr a
        lsr a
        and #1
        clc
        adc #FR_DIE_A
        sta frame
        lda mtimer
        and #2
        beq @c1
        lda #$44
        bne @c2
@c1:    lda #PAL_PLAYER
@c2:    sta PCOLR0
        lda mtimer              ; falling pitch
        cmp #44
        bcs @quiet
        lda #5
        sta snd
        lda mtimer
        asl a
        clc
        adc #30
        sta sndf
@quiet: jsr draw_player
        jsr draw_hud
        lda mtimer
        cmp #DIE_FRAMES
        bcc @r
        jmp death_done
@r:     rts

death_done:
        lda demo
        bne @again              ; the demo never runs out of lives
        dec lives
        beq @over
@again: jmp begin_level         ; same map, items restored; the score is kept
@over:  jmp enter_gameover

; Come to life: the player is drawn line by line from the top, then blinks, in changing colours.
mode_spawn:
        lda hjoy                ; keep joy current so a held button is not a fresh press later
        sta joy
        jsr inc_mtimer
        lda mtimer
        cmp #SPAWN_FRAMES/3*2
        bcs @blink
        lsr a
        clc
        adc #1
        sta drawn               ; 1..16 lines
        jmp @col
@blink: lda #16
        sta drawn
        lda mtimer
        and #2
        beq @col
        lda #0
        sta drawn               ; off for two frames, on for two
@col:   lda mtimer
        asl a
        asl a
        asl a
        and #$F0
        ora #$0E
        sta PCOLR0              ; cycling hue
        lda #4
        sta snd
        lda mtimer              ; rising pitch
        asl a
        clc
        adc mtimer
        sta tmp
        lda #190
        sec
        sbc tmp
        sta sndf
        lda #FR_STAND
        sta frame
        jsr draw_player
        jsr draw_hud
        lda mtimer
        cmp #SPAWN_FRAMES
        bcc @rts
        lda #M_PLAY
        sta mode
        lda #16
        sta drawn
        lda #PAL_PLAYER
        sta PCOLR0
@rts:   rts

; Teleporting: he dissolves for 16 frames, is moved to the next teleporter (the one-use pad he leaves is spent now) at the 17th
; and is rebuilt there over the last 16. The joystick is ignored and nothing acts on him (pegs and fuses stand still, as
; in the spawn). tp_s4 is the step of the dissolve for draw_player: 1..16 going, 16 down to 1 coming back.
mode_tele:
        lda hjoy                ; keep joy current so a held button is not a fresh press later
        sta joy
        jsr inc_mtimer
        lda mtimer
        cmp #TP_FRAMES/2+1
        bne @nomove
        jsr tp_move
@nomove:
        lda mtimer
        cmp #TP_FRAMES/2+1
        bcs @in
        asl a                   ; going: the step is the frame number
        asl a
        bne @set                ; (never 0)
@in:    lda #TP_FRAMES+1        ; coming back: 16 down to 1
        sec
        sbc mtimer
        asl a
        asl a
@set:   sta tp_s4
        lda #160                ; a sweep up and down
        sec
        sbc tp_s4
        sta sndf
        lda #3
        sta snd
        jsr draw_player
        jsr draw_hud
        lda mtimer
        cmp #TP_FRAMES
        bcc @rts
        lda #M_PLAY
        sta mode
        lda #0
        sta tp_s4
        lda #1
        sta tp_lock             ; he stands on a teleporter: step off before it charges again
@rts:   rts

; Level cleared: flash and play a rising arpeggio, then on to the next level.
mode_clear:
        jsr inc_mtimer
        jsr door_fade
        lda mtimer
        lsr a
        lsr a
        and #3
        tax
        lda clear_notes,x
        sta sndf
        lda #4
        sta snd
        lda #2
        sta flash
        jsr draw_player
        jsr draw_hud
        lda mtimer
        cmp #CLEAR_FRAMES
        bcc @r
        lda level
        cmp #99
        bcs @nolevel
        inc level
@nolevel:
        inc lvlidx
        lda lvlidx
        ldx demo
        cmp wrap_tab,x          ; a demo stays on the maps the AI can play
        bcc @go
        lda #0
        sta lvlidx
@go:    jmp begin_level
@r:     rts

mode_title:
        lda RTCLOK+2
        and #$20
        beq @off
        PUTSTR str_press, 15, 10
        jmp @chk
@off:   PUTSTR str_blank19, 15, 10
@chk:   jsr fire_edge
        bcc @t
        jmp new_game
@t:     jsr tick_timer
        bne @rts
        jmp enter_attract
@rts:   rts

mode_over:
        jsr inc_mtimer
        lda mtimer
        cmp #60
        bcc @tick               ; the screen is not skippable for a second
        lda RTCLOK+2
        and #$20
        beq @off
        PUTSTR str_press2, 18, 15
        jmp @chk
@off:   PUTSTR str_blank10, 18, 15
@chk:   jsr fire_edge
        bcc @tick
        jmp enter_title
@tick:  jsr tick_timer
        bne @rts
        jmp enter_title
@rts:   rts

; Attract mode: fire starts a real game, the timer returns to the title.
demo_tick:
        jsr fire_edge
        bcc @t
        jmp new_game
@t:     jsr tick_timer
        bne @rts
        jmp enter_title
@rts:   rts

; ---------------------------------------------------------------------------
; Mode changes.
enter_title:
        lda #M_TITLE
        sta mode
        lda #0
        sta demo
        sta mtimer
        sta flash
        sta snd
        jsr hide_player
        lda #<screen_title
        sta ptr
        lda #>screen_title
        sta ptr+1
        jsr copy_map
        jsr title_colors
        lda hiscore
        sta dn
        lda hiscore+1
        sta dn+1
        SETDST SCREEN + 18 * 40 + 22
        ldx #5
        jsr put_dec
        lda #TITLE_IDLE_SECS
        jmp set_timer_secs

enter_attract:
        lda #1
        sta demo
        lda #0
        sta score
        sta score+1
        lda demo_n
        sta lvlidx
        clc
        adc #1
        sta level
        cmp #DEMO_LEVELS
        bcc @s
        lda #0
@s:     sta demo_n              ; (level - 1) is demo_n before this call; next run uses the next map
        lda #START_LIVES
        sta lives
        lda #DEMO_SECS
        jsr set_timer_secs
        jmp begin_level

new_game:
        lda #0
        sta demo
        sta score
        sta score+1
        sta lvlidx
        lda #1
        sta level
.ifdef START_MAP                ; `task run-map -- N`: a game that starts on map N (for trying maps out)
        lda #START_MAP-1
        sta lvlidx
        lda #START_MAP
        sta level
.endif
        lda #START_LIVES
        sta lives
        jmp begin_level

enter_gameover:
        lda #M_OVER
        sta mode
        lda #0
        sta mtimer
        sta newhi
        sta flash
        jsr hide_player
        lda score+1             ; new hi-score?
        cmp hiscore+1
        bcc @nohi
        bne @hi
        lda score
        cmp hiscore
        bcc @nohi
        beq @nohi
@hi:    lda score
        sta hiscore
        lda score+1
        sta hiscore+1
        lda #1
        sta newhi
@nohi:  lda #<screen_gameover
        sta ptr
        lda #>screen_gameover
        sta ptr+1
        jsr copy_map
        jsr title_colors
        lda #$44
        sta COLOR3              ; red "game over"
        jsr pal_uniform
        lda score
        sta dn
        lda score+1
        sta dn+1
        SETDST SCREEN + 10 * 40 + 22
        ldx #5
        jsr put_dec
        lda hiscore
        sta dn
        lda hiscore+1
        sta dn+1
        SETDST SCREEN + 12 * 40 + 22
        ldx #5
        jsr put_dec
        lda newhi
        beq @s
        PUTSTR str_newhi, 15, 12
@s:     lda #14
        sta snd
        lda #$B0
        sta sndf
        lda #OVER_SECS
        jmp set_timer_secs

; Load the map for lvlidx, put the player at its start and play the "come to life" animation.
begin_level:
        ldx lvlidx
        lda level_lo,x
        sta ptr
        lda level_hi,x
        sta ptr+1
        jsr copy_map
        jsr hud_labels
        jsr clear_pm
        jsr timed_reset
        jsr load_pegs
        lda #0
        sta vx
        sta vfrac
        sta cfrac
        sta fcount
        sta gtick
        sta cacc_t
        lda #4
        sta cacc
        ldx lvlidx
        lda level_sx,x
        sta px
        lda level_sy,x
        sta py
        lda level_items,x
        sta left
        lda #S_GROUND
        sta state
        lda #$FF
        sta jt
        lda #0
        sta fall
        sta hop
        sta bn
        sta hdir
        sta rkind
        sta anim
        sta moved
        sta mtimer
        sta ai_have
        sta flash
        sta door_open           ; no door yet: it appears when everything is collected
        sta door_dir
        sta door_phase
        sta door_tick
        sta face                ; looking at you, not squashed
        sta land_t
        sta last_st
        sta tp_t                ; no teleporter charging, none to step off first, not dissolving
        sta tp_lock
        sta tp_s4
        jsr door_draw
        lda #FR_STAND
        sta frame
        lda #0
        sta drawn
        lda #M_SPAWN
        sta mode
        jsr draw_hud            ; the numbers are right from the first frame
        jmp game_colors

; Copy 1 KB from ptr to the screen.
copy_map:
        lda #<SCREEN
        sta ptr2
        lda #>SCREEN
        sta ptr2+1
        ldx #4
@page:  ldy #0
@copy:  lda (ptr),y
        sta (ptr2),y
        iny
        bne @copy
        inc ptr+1
        inc ptr2+1
        dex
        bne @page
        rts

; The play screen's colours: the score row has its own, every other row gets a hue from pal_hues (stepping
; along the list from row to row, offset by the level) plus grey, white and ice blue.
game_colors:
        lda #PAL_HUD
        sta COLOR0              ; the score row
        lda #PAL_GREY
        sta COLOR1
        lda #PAL_WHITE
        sta COLOR2
        lda #PAL_ICE
        sta COLOR3
        lda #PAL_BG
        sta COLOR4
        ldx #1
@row:   txa
        clc
        adc lvlidx
        and #7
        tay
        lda pal_hues,y
        sta pal0,x
        lda #PAL_GREY
        sta pal1,x
        lda #PAL_WHITE
        sta pal2,x
        lda #PAL_ICE
        sta pal3,x
        inx
        cpx #24
        bne @row
        lda #PAL_PLAYER
        sta PCOLR0              ; pink bubble
        lda #PAL_EYES
        sta PCOLR3              ; white eyes
        lda #$46
        sta PCOLR1              ; red pegs
        sta PCOLR2
        rts

title_colors:
        lda #$2A
        sta COLOR0
        lda #$24
        sta COLOR1
        lda #$0E
        sta COLOR2
        lda #$1E
        sta COLOR3              ; yellow title text
        lda #$00
        sta COLOR4
        ; fall through: every row gets the colours just set

; Every row of the screen uses COLOR0-3 (the title and game over screens are not banded).
pal_uniform:
        ldx #23
@l:     lda COLOR0
        sta pal0,x
        lda COLOR1
        sta pal1,x
        lda COLOR2
        sta pal2,x
        lda COLOR3
        sta pal3,x
        dex
        bpl @l
        rts

; Display-list interrupt: runs at the last line of a row; sets the colours of the next one.
dli:
        pha
        txa
        pha
        tya
        pha
.ifdef TEST
        inc dli_n
.endif
        ldx dli_row
        lda pal0,x
        ldy pal1,x
        sta WSYNC
        sta COLPF0
        sty COLPF1
        lda pal2,x
        sta COLPF2
        lda pal3,x
        sta COLPF3
        inx
        cpx #24
        bcc @keep
        ldx #1                  ; the row after the last: the next frame starts again at row 1
@keep:  stx dli_row
        pla
        tay
        pla
        tax
        pla
        rti

; Zero the player/missile RAM.
clear_pm:
        lda #<PMAREA
        sta ptr
        lda #>PMAREA
        sta ptr+1
        ldx #8
        ldy #0
        lda #0
@l:     sta (ptr),y
        iny
        bne @l
        inc ptr+1
        dex
        bne @l
        rts

hide_player:
        jsr clear_pm
        lda #0
        sta HPOSP0
        sta HPOSP3
        sta HPOSM0
        sta HPOSM0+1
        sta HPOSM0+2
        sta HPOSM0+3
        sta HPOSP1
        sta HPOSP1+1
        sta oldpy
        sta pg_n
        rts

; ---------------------------------------------------------------------------
; Which sprite frame matches what the player is doing.
choose_frame:
        lda state               ; (locked in a chute he does not turn, whatever the joystick says)
        cmp #S_RIDE
        beq @face
        lda joy                 ; he looks the way he last tried to go
        and #JOY_RIGHT
        beq @nr
        lda #1
        sta face
        bne @face
@nr:    lda joy
        and #JOY_LEFT
        beq @face
        lda #2
        sta face
@face:  lda last_st             ; landing: squash for a few frames
        cmp #S_AIR
        bne @nl
        lda state
        bne @nl                 ; (still in the air, or on a ladder)
        lda #LAND_FRAMES
        sta land_t
@nl:    lda state
        sta last_st
        cmp #S_CLIMB
        beq @climb
        cmp #S_AIR
        beq @air
        cmp #S_RIDE
        beq @ride
        lda land_t              ; on the ground
        beq @walk
        dec land_t
        lda #FR_SQUASH
        bne @fam                ; (always)
@walk:  lda moved
        beq @stand
        lda anim                ; walking: lean one way, then look that way, every 4 pixels
        and #4
        beq @stand
        lda #FR_LEAN
        ldx face
        cpx #2
        bne @set
        lda #FR_LEAN+1
@set:   sta frame
        rts
@stand: lda #FR_STAND
@fam:   clc
        adc face
        sta frame
        rts
@air:   lda #0
        sta land_t
        lda jt                  ; the first frames of a jump: squashed, then stretched out
        cmp #3
        bcs @stretch
        lda #FR_SQUASH
        bne @fam
@stretch:
        lda #FR_STRETCH
        bne @fam
@ride:  lda #0                  ; riding a chute: standing, looking the way he last went
        sta land_t
        lda #FR_STAND
        jmp @fam
@climb: lda #0
        sta land_t
        lda moved               ; wobbling up the ladder
        beq @c0
        lda anim
        lsr a
        lsr a
        and #1
        clc
        adc #FR_LEAN            ; lean right / lean left
        sta frame
        rts
@c0:    lda #FR_STAND
        sta frame
        rts

; Draw the player sprite: erase the old image, copy the first `drawn` lines of `frame`, position it. He is three
; layers: the body (Player 0), the eyes (Player 3) and the third colour (the four missiles, each 2 clocks wide, side by
; side at HPOS, +2, +4 and +6; the missile page holds 2 bits per missile per line, see spr_third). The image starts
; pfloat (1 to 3, PLAYER_FLOAT +/- the bob) lines above the top of the physics box (py), i.e. at PM byte py - pfloat +
; PM_YOFF. If py is less than pfloat (he is above the screen, as in the death hop) the subtraction wraps to 253..255 and, like any
; value of 200 or more, hides him: nothing is drawn, nothing is written above or below the 256 bytes of a player.
draw_player:
        ldx oldpy
        ldy #SPR_H
        lda #0
@erase: sta PM0Y,x
        sta PM3Y,x
        sta MISSY,x
        inx
        dey
        bne @erase
        lda px
        clc
        adc #46                 ; left edge of the playfield is colour clock 48; he is 8 wide on a 4 wide box
        sta HPOSP0
        sta HPOSP3
        sta HPOSM0
        clc
        adc #2
        sta HPOSM0+1
        adc #2
        sta HPOSM0+2
        adc #2
        sta HPOSM0+3
        lda RTCLOK+2            ; the bubble drifts up and down: 1 to 3 lines above his box, a period of 64 frames
        and #63
        tax
        lda bob_float,x
        sta pfloat
        lda py
        sec
        sbc pfloat              ; he floats above his box
        cmp #200
        bcc @on
        lda #200                ; off the screen (above or below): nothing to draw, and next time nothing to erase
@on:    sta oldpy
        cmp #200
        bcs @rts
        ldx frame
        lda spr_lo,x
        sta ptr
        lda spr_hi,x
        sta ptr+1
        lda spr_elo,x
        sta ptr2
        lda spr_ehi,x
        sta ptr2+1
        lda spr_tlo,x
        sta sptr
        lda spr_thi,x
        sta sptr+1
        ldx oldpy
        ldy #0
@draw:  cpy drawn
        bcs @rts
        lda (ptr),y
        sta PM0Y,x
        lda (ptr2),y
        sta PM3Y,x
        lda (sptr),y
        sta MISSY,x
        inx
        iny
        cpy #SPR_H
        bne @draw
        lda tp_s4
        bne tp_mask_player      ; teleporting: dissolve what was drawn
@rts:   rts

; AND the 16 lines just drawn with the dissolve step's mask (tp_mask, see build_assets.py): a row's byte is the mask
; of the body and the eyes, and rotated left by two bits it is the mask of the missiles (their bits are laid out in
; pairs the other way round, see third_cells).
tp_mask_player:
        ldx oldpy               ; (he is on the screen: draw_player got here)
        lda #0
        sta tmp
@m:     lda tmp
        and #3
        ora tp_s4
        tay
        lda tp_mask,y
        sta tmp2
        and PM0Y,x
        sta PM0Y,x
        lda tmp2
        and PM3Y,x
        sta PM3Y,x
        lda tmp2
        asl a
        adc #0
        asl a
        adc #0
        and MISSY,x
        sta MISSY,x
        inx
        inc tmp
        lda tmp
        cmp #SPR_H
        bne @m
        rts

; ---------------------------------------------------------------------------
; Text and numbers.

; Copy the $FF-terminated string at sptr to the screen at dptr.
put_str:
        ldy #0
@l:     lda (sptr),y
        cmp #$FF
        beq @d
        sta (dptr),y
        iny
        bne @l
@d:     rts

; Print dn (16 bit) as X decimal digits (1-5) at dptr.
put_dec:
        stx tmp2
        lda #5
        sec
        sbc tmp2
        tax                     ; first power of ten
        ldy #0
@digit: lda #0
        sta tmp
@sub:   lda dn
        sec
        sbc pow_lo,x
        pha
        lda dn+1
        sbc pow_hi,x
        bcc @done               ; went below zero: this digit is finished
        sta dn+1
        pla
        sta dn
        inc tmp
        bne @sub
@done:  pla
        lda tmp
        clc
        adc #T_DIGIT0
        sta (dptr),y
        iny
        inx
        cpx #5
        bne @digit
        rts

; The fixed words of the score row. (Called after the level is copied, which overwrites row 0.)
hud_labels:
        PUTSTR str_score, 0, 0
        PUTSTR str_level, 0, 12
        lda demo
        bne @demo
        PUTSTR str_lives, 0, 22
        jmp @left
@demo:  PUTSTR str_demo, 0, 22
@left:  PUTSTR str_left, 0, 31
        rts

; The numbers of the score row, every frame.
draw_hud:
        lda score
        sta dn
        lda score+1
        sta dn+1
        SETDST SCREEN + 6
        ldx #5
        jsr put_dec
        lda level
        sta dn
        lda #0
        sta dn+1
        SETDST SCREEN + 18
        ldx #2
        jsr put_dec
        lda demo
        bne @demo
        lda lives
        sta dn
        lda #0
        sta dn+1
        SETDST SCREEN + 28
        ldx #1
        jsr put_dec
        jmp @left
@demo:  lda RTCLOK+2            ; blink DEMO
        and #$20
        beq @show
        PUTSTR str_blank5, 0, 22
        jmp @left
@show:  PUTSTR str_demo, 0, 22
@left:  lda left
        sta dn
        lda #0
        sta dn+1
        SETDST SCREEN + 36
        ldx #3
        jmp put_dec

; Background flash and sound effects.
update_fx:
        lda flash
        beq @bg
        dec flash
        lda flashc
        sta COLOR4
        jmp @snd
@bg:    lda #$00
        sta COLOR4
@snd:   lda snd
        beq @off
        dec snd
        and #$0F
        ora #$A0                ; pure tone
        sta AUDC1
        lda sndf
        sta AUDF1
        rts
@off:   lda #0
        sta AUDC1
        rts

; ---------------------------------------------------------------------------
; Timed tiles: bomb blocks and vanishing blocks. Stepping on one starts a fuse; the table holds the
; blocks that are doing something. A bomb block flashes, then blows up (killing anything in the blast
; zone, one tile either side and two above, and setting off bomb blocks next to it). A vanishing
; block flickers, vanishes, and comes back once the player is out of the way.
timed_reset:
        lda #0
        sta tr_t                ; (the map is freshly copied: no trampoline is mid-bounce)
        ldx #7
        lda #$FF
@l:     sta tt_ph,x
        dex
        bpl @l
        rts

; Start the fuse of the bomb or vanishing block under the feet, if there is one.
arm_under:
        lda state
        bne @rts                ; only when standing
        lda px
        sta tx
        lda py
        clc
        adc #SPR_H
        sta ty
        jsr arm_at
        lda px
        clc
        adc #3
        sta tx
        lda py
        clc
        adc #SPR_H
        sta ty
        jmp arm_at
@rts:   rts

; Arm the tile at (tx,ty) if it is a bomb or vanishing block.
arm_at:
        jsr get_tile
        pha
        ldy #0
        lda (ptr),y             ; the byte as drawn, end caps and all
        sta tt_o
        pla
        cmp #T_EXPLOSIVE
        beq @e
        cmp #T_EXPLOSIVE_B
        beq @e
        cmp #T_VANISH
        beq @v
        cmp #T_VANISH_B
        beq @v
        rts
@e:     lda #KIND_EXPL
        sta tt_k
        lda #FUSE_EXPL
        bne @go
@v:     lda #KIND_VANISH
        sta tt_k
        lda #FUSE_VANISH
@go:    sta tt_f
        lda tx
        lsr a
        lsr a
        sta tt_c
        lda ty
        lsr a
        lsr a
        lsr a
        sta tt_r
        ; fall through

; Put tile (tt_c,tt_r) of kind tt_k in the table with fuse tt_f, unless it is already there.
arm_cell:
        ldx #7
@find:  lda tt_ph,x
        cmp #$FF
        beq @nx
        lda tt_col,x
        cmp tt_c
        bne @nx
        lda tt_row,x
        cmp tt_r
        beq @rts
@nx:    dex
        bpl @find
        ldx #7
@free:  lda tt_ph,x
        cmp #$FF
        beq @put
        dex
        bpl @free
@rts:   rts
@put:   lda tt_o
        sta tt_orig,x
        lda tt_c
        sta tt_col,x
        lda tt_r
        sta tt_row,x
        lda tt_k
        sta tt_kind,x
        lda tt_f
        sta tt_t,x
        lda #PH_FUSE
        sta tt_ph,x
        lda #3
        sta snd
        lda #$60
        sta sndf
        rts

; Write tile A into the screen cell of slot X.
set_cell:
        pha
        ldy tt_row,x
        lda row_lo,y
        clc
        adc tt_col,x
        sta ptr
        lda row_hi,y
        adc #0
        sta ptr+1
        pla
        ldy #0
        sta (ptr),y
        rts

; C set if the player overlaps the tile of slot X.
player_in_cell:
        lda tt_col,x
        asl a
        asl a
        sta ov_x
        lda tt_row,x
        asl a
        asl a
        asl a
        sta ov_y
        lda px
        clc
        adc #3
        cmp ov_x
        bcc @no
        lda ov_x
        clc
        adc #3
        cmp px
        bcc @no
        lda py
        clc
        adc #15
        cmp ov_y
        bcc @no
        lda ov_y
        clc
        adc #7
        cmp py
        bcc @no
        sec
        rts
@no:    clc
        rts

update_timed:
        ldx #7
@slot:  lda tt_ph,x
        cmp #$FF
        bne @live
        jmp @next
@live:  cmp #PH_GONE
        beq @gone
        bcs @boom               ; PH_BOOM
        dec tt_t,x              ; ---- fuse burning
        beq @burst
        lda tt_kind,x
        bne @vflick
        lda tt_t,x              ; bomb block: flash every 4 frames
        and #4
        beq @e0
        lda #T_EXPLOSIVE_B
        bne @put
@e0:    lda tt_orig,x
        bne @put
@vflick:
        lda tt_t,x              ; vanishing block: flicker every 2 frames
        and #2
        beq @v0
        lda #T_VANISH_B
        bne @put
@v0:    lda tt_orig,x
@put:   jsr set_cell
        jmp @next
@burst: lda tt_kind,x
        bne @vanish
        jsr explode
        jmp @next
@vanish:
        lda #T_EMPTY
        jsr set_cell
        lda #PH_GONE
        sta tt_ph,x
        lda #VANISH_BACK
        sta tt_t,x
        jmp @next
@gone:  dec tt_t,x
        bne @next
        jsr player_in_cell      ; do not come back inside the player
        bcs @wait
        lda tt_orig,x
        jsr set_cell
        lda #$FF
        sta tt_ph,x
        jmp @next
@wait:  lda #1
        sta tt_t,x
        jmp @next
@boom:  dec tt_t,x
        bne @next
        lda #T_EMPTY
        jsr set_cell
        lda #$FF
        sta tt_ph,x
@next:  dex
        bmi @done
        jmp @slot
@done:  rts

; ---------------------------------------------------------------------------
; Teleporters. Teleport tiles (T_TELEPORT, and T_TELEPORT_ONCE, which is spent after one use) that touch left, right, above
; or below are ONE teleporter. Stand on the ground on any tile of one for a second (fps frames in a row; walking along it
; counts, leaving it or jumping starts again) and he dissolves and is rebuilt on the NEXT teleporter: the teleporters are
; ordered by their first tile in reading order (top row first, then leftmost), the one after the last is the first, and he
; arrives standing on the next one's first tile. A one-use teleporter he leaves turns into plain brick (all of its tiles),
; which takes it out of the order. A teleporter he arrives on does not charge until he has stepped off it.
; There is no table of teleporters: the groups are found on the screen when it is needed, with a flood fill (tp_fill)
; that marks the tiles it has seen by changing their bytes (so a level poked into screen RAM works), and the marks are
; all taken off again before the game goes on (tp_clean).
; While he charges the pad flickers: every 4 frames the group's tiles are flipped between the byte and the byte + 128
; (a `glow` tile of assets/tiles.txt: the same glyph with pixel value 3 in the other colour).

; C set if his feet are on a teleport tile (the tile under px or px+3); then tp_k is its kind (the plain tile) and
; tp_c, tp_r its column and row.
tp_under:
        lda py
        clc
        adc #SPR_H
        sta ty
        lda px
        sta tx
        jsr @look
        bcs @rts
        lda px
        clc
        adc #3
        sta tx
@look:  jsr get_tile            ; (a glowing tile comes back as its plain tile)
        cmp #T_TELEPORT
        beq @yes
        cmp #T_TELEPORT_ONCE
        beq @yes
        clc
        rts
@yes:   sta tp_k
        lda tx
        lsr a
        lsr a
        sta tp_c
        lda ty
        lsr a
        lsr a
        lsr a
        sta tp_r
        sec
@rts:   rts

; One frame of play: count the seconds on a teleporter.
tp_update:
        lda state
        bne @off                ; only standing on the ground counts
        jsr tp_under
        bcc @off
        lda tp_lock
        bne @rts                ; he has just arrived: step off and on again to use it
        inc tp_t
        lda tp_t
        and #3
        bne @cmp
        jsr tp_flip             ; flicker: 4 frames one colour, 4 the other
@cmp:   lda tp_t
        cmp fps
        bcs tp_go               ; a second: away
@rts:   rts
@off:   lda #0
        sta tp_lock
        lda tp_t
        beq @rts
        and #4                  ; he stepped off (or jumped): the pad's colour back to the plain one
        beq @zero
        jsr tp_flip
@zero:  lda #0
        sta tp_t
        rts

; A second has passed: work out where he goes and start the teleport, or (no other teleporter) do nothing.
tp_go:
        lda tp_t
        and #4
        beq @plain
        jsr tp_flip             ; (plain colour again)
@plain: lda #0
        sta tp_t
        jsr tp_dest
        bcs @send
        lda #1
        sta tp_lock             ; nowhere to go: nothing to do until he steps off
        rts
@send:  lda #M_TELE
        sta mode
        lda #0
        sta mtimer
        sta vx
        sta vfrac
        sta land_t
        sta last_st
        sta moved
        lda #FR_STAND
        clc
        adc face
        sta frame
        rts

; Halfway through the teleport: he reappears at the destination (standing on the first tile of the teleporter, which is
; one tile wide as he is: px = 4 * column, his feet on the top line of the tile), and a one-use pad he left is spent.
tp_move:
        lda tp_dc
        asl a
        asl a
        sta px
        lda tp_dr
        asl a
        asl a
        asl a
        sec
        sbc #SPR_H
        sta py
        lda tp_k
        cmp #T_TELEPORT_ONCE
        bne @rts
        sta tp_a                ; the whole pad of the one he left turns into plain brick
        lda #T_BRICK
        sta tp_b
        jsr tp_start
        jmp tp_fill
@rts:   rts

; Flip the glow of the teleporter at tp_c, tp_r (its byte <-> its byte + 128, for the whole group).
tp_flip:
        jsr tp_start
        jsr tp_at
        sta tp_a
        eor #$80
        sta tp_b
        jmp tp_fill

tp_start:                       ; tcx, tcy and X, Y = tp_c, tp_r
        ldx tp_c
        stx tcx
        ldy tp_r
        sty tcy
        rts

; A = the screen byte at column X, row Y; ptr points to it, Y = 0.
tp_at:
        txa
        clc
        adc row_lo,y
        sta ptr
        lda row_hi,y
        adc #0
        sta ptr+1
        ldy #0
        lda (ptr),y
        rts

; Flood fill: every tile that touches (left, right, above, below) the one at tcx, tcy and holds tp_a, itself included,
; is changed to tp_b. Afterwards tp_mr, tp_mc are the first of them in reading order. Each tile is changed when it is put
; on the stack (two bytes: column, row, pushed here and not in a subroutine, whose return address would be in the way), so
; the stack holds at most one entry per tile of the group.
tp_fill:
        lda #$FF
        sta tp_mr
        lda #0
        sta tp_n
        lda tcx
        sta tmp
        lda tcy
        sta tmp2
        jsr tp_visit
        bcc @done
        lda tmp
        pha
        lda tmp2
        pha
        inc tp_n
@pop:   lda tp_n
        beq @done
        dec tp_n
        pla
        sta tcy
        pla
        sta tcx
        lda tcy                 ; first in reading order so far?
        cmp tp_mr
        bcc @new
        bne @nomin
        lda tcx
        cmp tp_mc
        bcs @nomin
@new:   lda tcy
        sta tp_mr
        lda tcx
        sta tp_mc
@nomin: ldx #3                  ; the four neighbours (nb_dc, nb_dr: left, right, up, down)
@dir:   lda tcx
        clc
        adc nb_dc,x
        cmp #COLS               ; (off the left edge wraps to 255)
        bcs @skip
        sta tmp
        lda tcy
        clc
        adc nb_dr,x
        cmp #ROWS
        bcs @skip
        sta tmp2
        jsr tp_visit
        bcc @skip
        lda tmp
        pha
        lda tmp2
        pha
        inc tp_n
@skip:  dex
        bpl @dir
        bmi @pop                ; (always)
@done:  rts

; C set (and the tile at column tmp, row tmp2 changed to tp_b) if it holds tp_a and the stack has room. Keeps X.
tp_visit:
        ldy tmp2
        lda row_lo,y
        clc
        adc tmp
        sta ptr
        lda row_hi,y
        adc #0
        sta ptr+1
        ldy #0
        lda (ptr),y
        cmp tp_a
        bne @no
        lda tp_n
        cmp #MAX_TP_STACK
        bcs @no
        lda tp_b
        sta (ptr),y
        sec
        rts
@no:    clc
        rts

; Find the teleporter after the one at tp_c, tp_r: C set and tp_dc, tp_dr = its first tile; clear if there is none.
; The screen is left as it was.
tp_dest:
        jsr tp_search
        php
        jsr tp_clean
        plp
        rts

; The order is by first tile in reading order, cyclic. Mark the group he stands on (T_MARK) and find its first tile
; (tp_hr, tp_hc). Pass 1: look at the tiles after it, in reading order; a teleport tile that is not marked belongs to a group
; not seen yet, which is filled with its byte + 128 (seen): if the first tile of that group is this tile it is the first
; teleporter after his (the groups come in order of their first tile, so no other group can lie in between); otherwise
; that group starts before his and has only been marked as seen. Pass 2 (none found after his): the first teleport tile on
; the screen that is not in his group (marked) is the first tile of the first teleporter.
tp_search:
        lda tp_k
        sta tp_a
        lda #T_MARK
        sta tp_b
        jsr tp_start
        jsr tp_fill
        lda tp_mr
        sta tp_hr
        sta tp_dr
        lda tp_mc
        sta tp_hc
        sta tp_dc
        inc tp_dc               ; start with the tile after it
@row:   ldy tp_dr
        cpy #ROWS
        bcs @pass2
        lda row_lo,y
        sta ptr2
        lda row_hi,y
        sta ptr2+1
        ldy tp_dc
@cell:  cpy #COLS
        bcs @next
        lda (ptr2),y
        cmp #T_TELEPORT
        beq @cand
        cmp #T_TELEPORT_ONCE
        bne @adv
@cand:  sty tp_dc
        sta tp_a
        ora #$80
        sta tp_b
        sty tcx
        lda tp_dr
        sta tcy
        jsr tp_fill
        ldy tp_dc
        lda tp_mr
        cmp tp_dr
        bne @adv
        cpy tp_mc
        beq @found              ; this tile is the first of its group
@adv:   iny
        bne @cell
@next:  lda #0
        sta tp_dc
        inc tp_dr
        bne @row
@found: sec
        rts
@pass2: lda #1
        sta tp_dr
@wrow:  ldy tp_dr
        cpy #ROWS
        bcs @none
        lda row_lo,y
        sta ptr2
        lda row_hi,y
        sta ptr2+1
        ldy #0
@wcell: lda (ptr2),y
        and #$7F                ; (seen or not)
        cmp #T_TELEPORT
        beq @wfound
        cmp #T_TELEPORT_ONCE
        beq @wfound
        iny
        cpy #COLS
        bcc @wcell
        inc tp_dr
        bne @wrow
@none:  clc
        rts
@wfound:
        sty tp_dc
        sec
        rts

; Take the marks off the screen: T_MARK back to the kind of the teleporter he stands on, bytes 253 and 254 (seen) to the
; plain tile.
tp_clean:
        lda #<SCREEN
        sta ptr
        lda #>SCREEN
        sta ptr+1
        ldx #4
@page:  ldy #0
@l:     lda (ptr),y
        cmp #T_MARK
        bne @seen
        lda tp_k
        sta (ptr),y
        bne @nx                 ; (never 0)
@seen:  cmp #T_TELEPORT|$80
        bcc @nx
        cmp #(T_TELEPORT_ONCE|$80)+1
        bcs @nx
        and #$7F
        sta (ptr),y
@nx:    iny
        bne @l
        inc ptr+1
        dex
        bne @page
        rts

; ---------------------------------------------------------------------------
; The trampoline's rubber band. When he bounces, the mat of the whole connected run he landed on (tiles of the trampoline
; family on that row, caps included in the count) sags like a stretched rubber band and wobbles back: every second frame
; the run's middle tiles are swapped for another picture (TRAMPOLINE_S1..S3, the mat 1 to 3 lines lower, or _TAUT, the
; band stretched thin), 26 frames in all, then the plain tiles go back. Only that run's screen tiles change (other
; trampolines do not move, like a vanishing block), the game treats every picture as the trampoline (tile_canon), the end
; caps are the posts it is anchored to and never change. A new bounce finishes the old animation first; a new level
; (timed_reset) clears it.
; The sag of a tile is the smallest of: the amplitude (tramp_amp), one more than its distance from the end of the run
; (tapering to the posts), and 3 - half its distance from the column he landed in (deepest there, at least 1).

; Begin the animation for the run of the tile at column tt_f, row tt_r (where he has landed).
tramp_start:
        lda tr_t
        beq @idle
        jsr tramp_restore       ; (another run, or this one again)
@idle:  lda tt_r
        sta tr_row
        lda tt_f
        sta tr_c
        jsr tramp_rowptr
        ldy tr_c                ; the left end of the run
@left:  tya
        beq @lend
        dey
        lda (ptr),y
        tax
        lda tile_canon,x
        cmp #T_TRAMPOLINE
        beq @left
        iny
@lend:  sty tr_l
        ldy tr_c                ; the right end
@right: cpy #39
        bcs @rend
        iny
        lda (ptr),y
        tax
        lda tile_canon,x
        cmp #T_TRAMPOLINE
        beq @right
        dey
@rend:  sty tr_r
        lda #1
        sta tr_t
        rts

; ptr -> the first byte of row tr_row of the screen.
tramp_rowptr:
        ldx tr_row
        lda row_lo,x
        sta ptr
        lda row_hi,x
        sta ptr+1
        rts

; One frame of the animation (called every frame of play).
tramp_anim:
        lda tr_t
        beq @rts
        sec
        sbc #1
        lsr a
        tax                     ; the step: 2 frames each
        lda tramp_amp,x
        bmi @end
        sta tr_a
        lda tr_t
        lsr a
        bcc @next               ; the second frame of a step: the picture stays
        jsr tramp_draw
@next:  inc tr_t
@rts:   rts
@end:   jmp tramp_restore

; Put the plain tiles back and stop.
tramp_restore:
        lda #0
        sta tr_a
        jsr tramp_draw
        lda #0
        sta tr_t
        rts

; Draw the run (columns tr_l..tr_r of row tr_row) at amplitude tr_a: 0 = plain, 1..3 = sagging, 4 = taut. End caps are left alone.
tramp_draw:
        jsr tramp_rowptr
        lda tr_l
        sta tr_i
@col:   ldy tr_i
        lda (ptr),y
        sec
        sbc #T_TRAMPOLINE_L
        cmp #3
        bcc @skip               ; an end cap
        ldx #4
        lda tr_a
        cmp #4
        bcs @put                ; taut: the same for every tile
        sta tmp                 ; the sag so far: the amplitude
        lda tr_i                ; distance from the nearer end of the run, plus one
        sec
        sbc tr_l
        sta tmp2
        lda tr_r
        sec
        sbc tr_i
        cmp tmp2
        bcs @e
        sta tmp2
@e:     inc tmp2
        lda tmp2
        cmp tmp
        bcs @n1
        sta tmp
@n1:    lda tr_i                ; distance from where he landed, halved
        sec
        sbc tr_c
        bcs @pos
        eor #$FF
        clc
        adc #1
@pos:   lsr a
        sta tmp2
        lda #3
        sec
        sbc tmp2
        bcc @one
        bne @have
@one:   lda #1
@have:  cmp tmp
        bcs @n2
        sta tmp
@n2:    ldx tmp
@put:   lda tramp_tile,x
        ldy tr_i
        sta (ptr),y
@skip:  inc tr_i
        lda tr_i
        cmp tr_r
        bcc @col
        beq @col
        rts

; The bomb block of slot X goes off.
explode:
        lda #PH_BOOM
        sta tt_ph,x
        lda #BOOM_FRAMES
        sta tt_t,x
        lda #T_BOOM
        jsr set_cell
        lda #14
        sta snd
        lda #$28
        sta sndf
        lda #$28                ; orange flash
        sta flashc
        lda #5
        sta flash
        lda tt_col,x            ; blast zone: from one tile left of the block to one tile right,
        asl a                   ; from two tiles above it to its bottom
        asl a
        sec
        sbc #4
        sta ov_x
        lda tt_row,x
        asl a
        asl a
        asl a
        sec
        sbc #16
        bcs @top
        lda #0
@top:   sta ov_y
        lda px
        clc
        adc #3
        cmp ov_x
        bcc @safe
        lda ov_x
        clc
        adc #11
        cmp px
        bcc @safe
        lda py
        clc
        adc #15
        cmp ov_y
        bcc @safe
        lda tt_row,x            ; ... and only his feet count: below the block, his head in it, he is safe
        asl a
        asl a
        asl a
        clc
        adc #7
        sta tmp
        lda py
        clc
        adc #15
        cmp tmp
        beq @hit
        bcs @safe
@hit:   stx tt_i
        jsr die
        ldx tt_i
@safe:  stx tt_i                ; chain reaction: bomb blocks next to this one
        ldy #3
@nb:    sty tt_j
        ldx tt_i
        lda tt_col,x
        clc
        adc nb_dc,y
        sta tt_c
        lda tt_row,x
        clc
        adc nb_dr,y
        sta tt_r
        lda tt_c
        asl a
        asl a
        sta tx
        lda tt_r
        asl a
        asl a
        asl a
        sta ty
        jsr get_tile
        pha
        ldy #0
        lda (ptr),y
        sta tt_o
        pla
        cmp #T_EXPLOSIVE
        beq @arm
        cmp #T_EXPLOSIVE_B
        bne @nbnext
@arm:   lda #KIND_EXPL
        sta tt_k
        lda #CHAIN_FUSE
        sta tt_f
        jsr arm_cell
@nbnext:
        ldy tt_j
        dey
        bpl @nb
        ldx tt_i
        rts

; ---------------------------------------------------------------------------
; Pegs (Player 1 and 2): each sweeps along its block, pausing at the ends, and carries along any
; player it overlaps from behind. Jump over it, or leave by a ladder.
load_pegs:
        ldx lvlidx
        lda level_pg_lo,x
        sta ptr
        lda level_pg_hi,x
        sta ptr+1
        lda #0
        sta HPOSP1
        sta HPOSP1+1
        ldy #0
        lda (ptr),y
        sta pg_n
        beq @rts
        iny
        ldx #0
@peg:   lda (ptr),y
        sta pg_x,x
        iny
        lda (ptr),y
        sta pg_y,x
        iny
        lda (ptr),y
        sta pg_min,x
        iny
        lda (ptr),y
        sta pg_max,x
        iny
        lda (ptr),y
        sta pg_dir,x
        iny
        lda #PEG_WAIT
        sta pg_wait,x
        inx
        cpx pg_n
        bcc @peg
        ldx #0                  ; draw the peg shapes (they never change shape or height)
@draw:  stx pg_i
        txa
        clc
        adc #>(PM0Y + $100)
        sta ptr+1
        lda #<(PM0Y + $100)
        sta ptr
        ldy pg_y,x
        ldx #0
@s:     lda peg_shape,x
        sta (ptr),y
        iny
        inx
        cpx #8
        bcc @s
        ldx pg_i
        lda pg_x,x
        clc
        adc #48
        sta HPOSP1,x
        inx
        cpx pg_n
        bcc @draw
@rts:   rts

update_pegs:
        lda pg_n
        beq @rts
        inc gtick
        ldx #0
@peg:   lda pg_wait,x
        beq @mv
        dec pg_wait,x
        jmp @push
@mv:    lda gtick               ; half a pixel per frame
        and #1
        bne @push
        lda pg_x,x
        clc
        adc pg_dir,x
        sta pg_x,x
        cmp pg_max,x
        beq @end
        cmp pg_min,x
        bne @push
@end:   lda #PEG_WAIT           ; at the end of the block: rest, then turn round
        sta pg_wait,x
        jsr peg_push            ; (one last push the way it was going, so that whoever is ahead of it at the end of
                                ; the platform is carried off the end and not left on its last pixel)
        lda pg_dir,x
        eor #$FE                ; 1 <-> $FF
        sta pg_dir,x
@push:  lda pg_x,x
        clc
        adc #48
        sta HPOSP1,x
        jsr peg_push
        inx
        cpx pg_n
        bcc @peg
@rts:   rts

; Push the player along if peg X is beside his feet and the player is ahead of the peg. The push carries him clear of
; the peg in one go (up to 4 pixels, the peg is 4 wide), so a belt or ice dragging him back (up to 2 pixels a frame) never
; wins, and whatever is in the platform - a step, a spike, a ladder, a chute, any kind of tile - does not slow it: only
; a solid beside him (walking into it, as ever) stops him, and the peg's run ends at such a solid. So he is carried, a
; peg's width ahead of it, to the end of the platform and off it. What is under his feet on the way still applies as
; usual (a spike under him still kills): he is pushed over it, not made immune.
peg_push:
        lda px                  ; overlap in x ...
        clc
        adc #3
        cmp pg_x,x
        bcc @no
        lda pg_x,x
        clc
        adc #3
        cmp px
        bcc @no
        lda py                  ; ... and in y
        clc
        adc #15
        cmp pg_y,x
        bcc @no
        lda pg_y,x
        clc
        adc #7
        sta tmp
        lda py
        clc
        adc #15
        cmp tmp
        beq @hit
        bcs @no                 ; his feet are below the peg: a peg on the block above does not touch him
@hit:   stx pg_i
        lda #4
        sta pg_k
        lda pg_dir,x
        bmi @left
@r:     lda px                  ; moving right: only while the player is not behind the peg ...
        cmp pg_x,x
        bcc @done
        lda pg_x,x
        clc
        adc #3
        cmp px
        bcc @done               ; ... and still touches it
        jsr push_right
        ldx pg_i
        dec pg_k
        bne @r
        beq @done
@left:  lda px
        cmp pg_x,x
        beq @pl
        bcs @done
@pl:    lda px
        clc
        adc #3
        cmp pg_x,x
        bcc @done               ; clear of the peg
        jsr push_left
        ldx pg_i
        dec pg_k
        bne @left
@done:  ldx pg_i
@no:    rts

; ---------------------------------------------------------------------------
; Conveyor belts: one bright pixel marches across each belt tile (right or left, at the belt's own
; pace), by rewriting two rows of the belt glyphs in the character set.
animate_belts:
        ldx #7
@k:     lda RTCLOK+2
        and conv_mask,x
        bne @next
        lda conv_dir,x
        bne @left
        inc cph,x
        jmp @draw
@left:  dec cph,x
@draw:  lda cph,x
        and #3
        tay
        lda belt_pat,y
        pha
        txa
        asl a
        asl a
        asl a
        tay
        pla
        sta CONV_GLYPHS,y       ; the belt, and its left, right and both-ends caps (ids 72-95)
        sta CONV_GLYPHS+1,y
        sta CONV_GLYPHS+64,y
        sta CONV_GLYPHS+65,y
        sta CONV_GLYPHS+128,y
        sta CONV_GLYPHS+129,y
        sta CONV_GLYPHS+192,y
        sta CONV_GLYPHS+193,y
@next:  dex
        bpl @k
        rts

; ---------------------------------------------------------------------------
; Chutes: a screw thread that turns. The thread is 16 rows tall (assets/tiles.txt: a chute tile and its twin, which
; the level puts on every second screen row, so a stack of chutes is one unbroken thread). Every second frame the
; 16 rows (helix_r / helix_l, each twice over) are written into the glyphs one row further along: the plain tile
; gets the 8 rows from the phase on, its twin the next 8. The down chute's (T_SLIDE_R) phase counts down, so its thread
; travels down the stack; the up chute's (T_SLIDE_L) counts up, so its thread travels up.
animate_chutes:
        lda RTCLOK+2
        lsr a
        bcs @done               ; odd frame: nothing to do
        and #15
        sta tmp                 ; the up chute's phase
        eor #15
        tax                     ; the down chute's
        ldy #0
@rowr:  lda helix_r,x
        sta CHUTE_R_A,y
        lda helix_r+8,x
        sta CHUTE_R_B,y
        inx
        iny
        cpy #8
        bne @rowr
        ldx tmp
        ldy #0
@rowl:  lda helix_l,x
        sta CHUTE_L_A,y
        lda helix_l+8,x
        sta CHUTE_L_B,y
        inx
        iny
        cpy #8
        bne @rowl
@done:  rts

; ---------------------------------------------------------------------------
; The AI that plays in attract mode. It produces the same joy bits a person would.
;
;   - It picks the item that is cheapest to reach (columns apart + 8 per row apart, so items on
;     the floor it stands on come first), remembers it, and picks again when it is gone.
;   - On the floor of the item it walks to it. On another floor it walks to the nearest ladder
;     that leads that way (a ladder tile in the row above its feet to go up, under its feet to
;     go down), aligns with it, and climbs.
;   - It jumps spikes (seen 7 pixels ahead) and gaps (when the next step leaves nothing under it).
ai_input:
        lda #0
        sta joy
        lda ai_have
        beq @pick
        jsr ai_valid            ; is the target still there?
        bcs @go
@pick:  jsr ai_pick
        lda ai_have
        beq @rts
@go:    lda state
        cmp #S_CLIMB
        bne @notc
        jmp ai_climb
@notc:  cmp #S_AIR
        bne @ground
        jmp ai_air
@ground:
        jmp ai_ground
@rts:   rts

; C set if the AI's target is still there. A target is an item or the open door (kind 0: the cell itself) or a
; platform tile with a dot in it (kind 1: the tile under the cell the AI stands in to eat it).
ai_valid:
        ldx ai_ir
        lda ai_kind
        beq @row
        inx
@row:   lda row_lo,x
        clc
        adc ai_ic
        sta ptr
        lda row_hi,x
        adc #0
        sta ptr+1
        ldy #0
        lda (ptr),y
        ldx ai_kind
        bne @dot
        cmp #T_ITEM
        beq @yes
        cmp #T_DOOR_BL
        bne @no
        lda door_open
        bne @yes
@no:    clc
        rts
@dot:   tax
        lda tile_flags,x
        and #F_DOT
        beq @no
@yes:   sec
        rts

; Choose the cheapest target on the screen: an item, a dot, or (once everything is collected) the open door.
; Cost = columns apart + 8 per row apart.
ai_pick:
        lda #0
        sta ai_have
        lda #255
        sta a_best
        lda px
        clc
        adc #2
        lsr a
        lsr a
        sta a_pc                ; player column
        lda py
        clc
        adc #8
        lsr a
        lsr a
        lsr a
        sta a_fp                ; player body row
        lda #1
        sta a_row
@row:   ldx a_row
        lda row_lo,x
        sta ptr
        lda row_hi,x
        sta ptr+1
        ldy #0
@col:   lda (ptr),y
        beq @next               ; empty (most cells)
        ldx #0                  ; kind 0: the cell is the target
        stx a_k
        cmp #T_ITEM
        beq @cand
        cmp #T_DOOR_BL
        bne @dotchk
        lda door_open           ; its bottom left tile, once it is there
        bne @cand
        beq @next
@dotchk:
        tax
        lda tile_flags,x
        and #F_DOT
        beq @next
        lda #1                  ; kind 1: stand in the cell above the dotted tile
        sta a_k
@cand:  lda a_row               ; the row the player stands in to get it
        sec
        sbc a_k
        sta a_tr
        tya                     ; |column - player column|
        sec
        sbc a_pc
        bcs @p
        eor #$FF
        adc #1
@p:     sta a_cost
        lda a_tr                ; 8 * |row - player row|
        sec
        sbc a_fp
        bcs @q
        eor #$FF
        adc #1
@q:     asl a
        asl a
        asl a
        clc
        adc a_cost
        bcc @cmp
        lda #254
@cmp:   cmp a_best
        bcs @next
        sta a_best
        sty ai_ic
        lda a_tr
        sta ai_ir
        lda a_k
        sta ai_kind
        lda #1
        sta ai_have
@next:  iny
        cpy #40
        bne @col
        inc a_row
        lda a_row
        cmp #24
        beq @done
        jmp @row
@done:  rts

; Find the ladder tile in row A nearest to column a_pc. C set and a_lc = its column when there is one.
ai_find_ladder:
        tax
        lda row_lo,x
        sta ptr
        lda row_hi,x
        sta ptr+1
        lda #$FF
        sta a_best
        ldy #0
@c:     lda (ptr),y
        cmp #T_LADDER
        bne @n
        tya
        sec
        sbc a_pc
        bcs @p
        eor #$FF
        adc #1
@p:     cmp a_best
        bcs @n
        sta a_best
        sty a_lc
@n:     iny
        cpy #40
        bne @c
        lda a_best
        cmp #$FF
        beq @none
        sec
        rts
@none:  clc
        rts

; Climbing: up or down depending on which floor the item is on.
ai_climb:
        lda py
        clc
        adc #SPR_H
        lsr a
        lsr a
        lsr a
        sta a_fp                ; floor row at the feet
        lda ai_ir
        clc
        adc #1                  ; floor row the item stands on
        cmp a_fp
        beq @hold
        bcc @up
        lda #JOY_DOWN
        bne @set
@up:    lda #JOY_UP
@set:   sta ai_vert
@hold:  lda ai_vert
        sta joy
        rts

; In the air: just keep heading for the goal.
ai_air:
        lda px
        cmp ai_goal
        beq @r
        bcc @right
        lda #JOY_LEFT
        sta joy
        rts
@right: lda #JOY_RIGHT
        sta joy
@r:     rts

; On the ground: work out the goal, walk towards it, jump what is in the way.
ai_ground:
        lda py
        clc
        adc #SPR_H
        lsr a
        lsr a
        lsr a
        sta a_fp                ; floor row at the feet
        lda ai_ir
        clc
        adc #1
        sta a_ft                ; floor row of the item
        lda px
        clc
        adc #2
        lsr a
        lsr a
        sta a_pc
        lda ai_ic               ; default goal: the item itself
        asl a
        asl a
        sta ai_goal
        lda #0
        sta ai_vert
        lda a_fp
        cmp a_ft
        beq @horiz              ; same floor
        bcc @below
        lda #JOY_UP             ; the item is higher: ladder in the row above the feet
        sta ai_vert
        lda a_fp
        sec
        sbc #1
        jmp @find
@below: lda #JOY_DOWN           ; lower: ladder top in the floor row
        sta ai_vert
        lda a_fp
@find:  jsr ai_find_ladder
        bcs @gotl
        lda #0
        sta ai_vert             ; no ladder here: head for the item anyway
        jmp @horiz
@gotl:  lda a_lc
        asl a
        asl a
        sta ai_goal
@horiz: lda px
        cmp ai_goal
        bne @notal
        jmp @aligned
@notal: bcs @goleft
        jmp @goright

@goleft:
        lda #JOY_LEFT           ; ---- walking left
        sta joy
        lda #8                  ; spike 8 pixels ahead on the way to the goal (and again 4 ahead, in case a
        sta a_k                 ; new target came up while it was passing)?
@lspk:  lda px
        sec
        sbc a_k
        sta tx
        lda py
        clc
        adc #15
        sta ty
        jsr get_tile
        ldx a_k
        cpx #4                  ; a step right in front of us (the near look only): jump up onto it
        bne @lns
        cmp #T_STAIR
        bne @lns
        jmp @jump
@lns:   cmp #T_SPIKE
        bne @lnxt
        lda tx
        and #$FC
        cmp ai_goal
        bcc @lnxt
        jmp @jump               ; the spike lies between us and the goal
@lnxt:  lda a_k
        cmp #4
        beq @lhole
        lda #4
        sta a_k
        bne @lspk               ; (always)
@lhole: lda px                  ; nothing to stand on after the next step?
        sec
        sbc #1
        sta tx
        lda py
        clc
        adc #SPR_H
        sta ty
        jsr tile_standable
        bcs @rts1
        lda px
        clc
        adc #2
        sta tx
        lda py
        clc
        adc #SPR_H
        sta ty
        jsr tile_standable
        bcs @rts1
        bcc @jump               ; (always)
@rts1:  rts

@goright:
        lda #JOY_RIGHT          ; ---- walking right
        sta joy
        lda #10                 ; spike 10 pixels ahead (and 6, as on the left)?
        sta a_k
@rspk:  lda px
        clc
        adc a_k
        sta tx
        lda py
        clc
        adc #15
        sta ty
        jsr get_tile
        ldx a_k
        cpx #6
        bne @rns
        cmp #T_STAIR
        bne @rns
        jmp @jump
@rns:   cmp #T_SPIKE
        bne @rnxt
        lda tx
        and #$FC
        cmp ai_goal
        bcs @rnxt
        jmp @jump
@rnxt:  lda a_k
        cmp #6
        beq @rhole
        lda #6
        sta a_k
        bne @rspk               ; (always)
@rhole: lda px
        clc
        adc #1
        sta tx
        lda py
        clc
        adc #SPR_H
        sta ty
        jsr tile_standable
        bcs @rts2
        lda px
        clc
        adc #4
        sta tx
        lda py
        clc
        adc #SPR_H
        sta ty
        jsr tile_standable
        bcs @rts2
@jump:  lda joy
        ora #JOY_FIRE
        sta joy
@rts2:  rts

@aligned:
        lda ai_vert             ; lined up with the ladder: climb
        sta joy
        rts

; ---------------------------------------------------------------------------
        .segment "RODATA"

        .include "gen/sprites.inc"      ; defines SPR_COUNT and spr_frames
        .include "gen/levels.inc"       ; the maps and the level tables
        .include "gen/screens.inc"      ; screen_title, screen_gameover
        .include "gen/fade.inc"         ; door_thr: when each pixel of the exit door shows
        .include "gen/dissolve.inc"     ; tp_mask: the teleport dissolve's masks
        .include "gen/helix.inc"        ; helix_r, helix_l: the thread of the chutes
        .include "gen/tileflags.inc"    ; tile_flags: bit 0 solid, bit 1 one-way

row_lo: .repeat 24, i
        .byte <(SCREEN + i * 40)
        .endrepeat
row_hi: .repeat 24, i
        .byte >(SCREEN + i * 40)
        .endrepeat

pow_lo: .byte <10000, <1000, <100, <10, <1
pow_hi: .byte >10000, >1000, >100, >10, >1

; Pixels the player rises on each frame of a jump (0 ends the rise).
jump_dy: .byte 3,3,3,3,3,2,2,2,2,1,1,1,0

; The trampoline's rubber band: the amplitude on each step of the animation (0 plain, 1..3 sag, 4 taut), $FF ends it:
; down, hold, back up, spring past plain (taut), a smaller sag, taut again, settled.
tramp_amp:  .byte 1,2,3,3,2,1,4,4,1,2,1,4,0,$FF
.assert * - tramp_amp = TR_STEPS + 1, error, "TR_STEPS is the length of tramp_amp"
; ... and the tile for each amplitude.
tramp_tile: .byte T_TRAMPOLINE, T_TRAMPOLINE_S1, T_TRAMPOLINE_S2, T_TRAMPOLINE_S3, T_TRAMPOLINE_TAUT

; Extra full-speed frames of a trampoline bounce to clear a surface k tiles up (index k, 1..BOUNCE_ROWS):
; the smallest n with 17 + 3n >= 8k + 8, i.e. ceil((8k - 9) / 3), at least 0.
bounce_n: .byte 0,0,3,5,8,11,13,16,19,21,24,27,29,32,35

; Lines he floats above his box on each of 64 frames (index RTCLOK+2 and 63): 2 + round(sin), so 1 to 3.
bob_float:
        .byte 2,2,2,2,2,2,3,3,3,3,3,3,3,3,3,3
        .byte 3,3,3,3,3,3,3,3,3,3,3,2,2,2,2,2
        .byte 2,2,2,2,2,2,1,1,1,1,1,1,1,1,1,1
        .byte 1,1,1,1,1,1,1,1,1,1,1,2,2,2,2,2

; The death hop: signed pixels per frame, then a steady fall.
die_dy:  .byte $FC,$FC,$FD,$FD,$FE,$FE,$FF,$FF,0,1,1,2,2,3,3,4,4,5,5
DIE_LEN = * - die_dy

clear_notes: .byte $79,$5F,$4B,$3C

; Belts, by tile id - 64: drift direction, drift speed (0 = accelerating), animation period - 1.
conv_dir:  .byte 0,0,0,0,1,1,1,1
conv_spd:  .byte 8,16,32,0,8,16,32,0
conv_mask: .byte 7,3,1,3,7,3,1,3
belt_pat:  .byte $EA,$BA,$AE,$AB        ; one bright pixel (3) in a row of 2s, in each of 4 places

; Ice, roller: acceleration per frame, friction per step, friction on frames where (count & mask) = 0.
slick_acc:   .byte 2,4          ; (a roller's is its length instead, see roller_len)
slick_fric:  .byte 1,2
slick_fmask: .byte 1,0

probe_dx:  .byte 2,0,3                  ; where under the feet to look: middle, left, right
peg_shape: .byte $60,$F0,$F0,$F0,$F0,$F0,$F0,$90
nb_dc:     .byte $FF,1,0,0              ; the four neighbours of a block: left, right, up, down
nb_dr:     .byte 0,0,$FF,1
wrap_tab:  .byte LEVEL_COUNT,DEMO_LEVELS

; Points (offset from px,py) that collect items.
pt_dx:  .byte 0,3,0,3,0,3
pt_dy:  .byte 3,3,8,8,13,13

spr_elo: .repeat SPR_COUNT, i
        .byte <(spr_eyes + SPR_H * i)
        .endrepeat
spr_ehi: .repeat SPR_COUNT, i
        .byte >(spr_eyes + SPR_H * i)
        .endrepeat
spr_tlo: .repeat SPR_COUNT, i
        .byte <(spr_third + SPR_H * i)
        .endrepeat
spr_thi: .repeat SPR_COUNT, i
        .byte >(spr_third + SPR_H * i)
        .endrepeat
spr_lo: .repeat SPR_COUNT, i
        .byte <(spr_frames + SPR_H * i)
        .endrepeat
spr_hi: .repeat SPR_COUNT, i
        .byte >(spr_frames + SPR_H * i)
        .endrepeat

mode_tab:
        .word mode_title, mode_play, mode_dying, mode_spawn, mode_clear, mode_over, mode_tele

str_score:   STR "SCORE"
str_level:   STR "LEVEL"
str_lives:   STR "LIVES"
str_demo:    STR "DEMO "
str_left:    STR "LEFT"
str_press:   STR "PRESS FIRE TO START"
str_press2:  STR "PRESS FIRE"
str_newhi:   STR "NEW HIGH SCORE!"
str_blank5:  BLANK 5
str_blank10: BLANK 10
str_blank19: BLANK 19

; ---------------------------------------------------------------------------
        .segment "DLIST"
dlist:
        .byte $70,$70,$70               ; 24 blank scan lines
        .byte $C4                       ; mode 4 + load memory scan + interrupt
        .word SCREEN
        .repeat 22
        .byte $84                       ; mode 4 + interrupt: sets up the next row's colours
        .endrepeat
        .byte $04
        .byte $41                       ; jump and wait for vertical blank
        .word dlist

        .include "gen/charset.inc"
