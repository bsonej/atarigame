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
        .exportzp px, py, state, jt, fall, score, hiscore, left, lives, level, lvlidx
        .exportzp mode, demo, demo_n, timer, mtimer, frame, drawn, deaths, joy, anim, moved, flash
        .exportzp ai_have, ai_ic, ai_ir, ai_goal

        .include "gen/tiles.inc"
        .include "gen/font.inc"                 ; .charmap: .byte "TEXT" gives glyph ids

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
COLOR0  = $02C4         ; playfield colour for pixel value 1
COLOR1  = $02C5         ; ... value 2
COLOR2  = $02C6         ; ... value 3
COLOR3  = $02C7         ; ... value 3 in a glyph with bit 7 set (lowercase text)
COLOR4  = $02C8         ; background
CHBAS   = $02F4
HPOSP0  = $D000
SIZEP0  = $D008
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

; ---- game constants --------------------------------------------------------
S_GROUND = 0
S_AIR    = 1
S_CLIMB  = 2

M_TITLE  = 0
M_PLAY   = 1
M_DYING  = 2
M_SPAWN  = 3
M_CLEAR  = 4
M_OVER   = 5

FR_STAND  = 0           ; sprite frames, in the order of assets/sprites.txt
FR_WALK_A = 1
FR_AIR    = 2
FR_CLIMB  = 3
FR_DIE_A  = 5
FR_DIE_B  = 6

JOY_UP    = $01
JOY_DOWN  = $02
JOY_LEFT  = $04
JOY_RIGHT = $08
JOY_FIRE  = $10

MAX_FALL   = 64         ; falling further than this (pixels) kills
SPR_H      = 16
START_LIVES = 3
ITEM_POINTS = 10
CLEAR_BONUS = 100
SPAWN_FRAMES = 48       ; length of the "come to life" animation
DIE_FRAMES   = 80       ; length of the death animation
CLEAR_FRAMES = 60
TITLE_IDLE_SECS = 10
DEMO_SECS    = 30
OVER_SECS    = 10

        .export SCREEN, PM0, M_TITLE, M_PLAY, M_DYING, M_SPAWN, M_CLEAR, M_OVER

; ---------------------------------------------------------------------------
        .segment "ZEROPAGE"
px:       .res 1
py:       .res 1
oldpy:    .res 1
state:    .res 1
jt:       .res 1        ; index into jump_dy, $FF = not rising
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
        lda #16
        sta drawn
        lda PAL
        and #$0E
        beq @pal
        lda #60
        bne @fps
@pal:   lda #50
@fps:   sta fps

        jsr clear_pm
        lda #<dlist
        sta SDLSTL
        lda #>dlist
        sta SDLSTL+1
        lda #>CHARSET_ADDR
        sta CHBAS
        lda #1
        sta GPRIOR              ; players in front of the playfield
        lda #0
        sta SIZEP0
        lda #>PMAREA
        sta PMBASE
        lda #3
        sta GRACTL              ; enable players and missiles
        jsr enter_title
        lda #$3A                ; DL DMA + single-line PM + players + normal width
        sta SDMCTL

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
; Tile lookup. In: tx, ty (pixels). Out: A = tile id, ptr -> its screen byte.
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
        rts
@solid: lda #T_BRICK
        rts

; C set if the tile at (tx,ty) can be stood on: brick, or the very top of a ladder.
tile_standable:
        jsr get_tile
        cmp #T_BRICK
        beq @yes
        cmp #T_LADDER
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
        bne @ground
        jmp up_air

@ground:
        jsr ground_below
        bcs @standing
        lda #S_AIR              ; walked off an edge
        sta state
        lda #0
        sta fall
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
        beq @walk
        lda joyprev
        and #JOY_FIRE
        bne @walk               ; need a fresh press
        lda #0
        sta jt
        sta fall
        lda #S_AIR
        sta state
@walk:  jmp do_horiz

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
        jsr do_horiz
        lda jt
        cmp #$FF
        beq air_fall

        tax                     ; rising: jump_dy[jt] pixels this frame
        lda jump_dy,x
        beq @apex
        sta tmp2
@rise:  lda px
        sta tx
        lda py
        sec
        sbc #1
        sta ty
        jsr get_tile
        cmp #T_BRICK
        beq @apex               ; bumped our head
        lda px
        clc
        adc #3
        sta tx
        jsr get_tile
        cmp #T_BRICK
        beq @apex
        dec py
        dec tmp2
        bne @rise
        inc jt
        rts
@apex:  lda #$FF
        sta jt
        rts

air_fall:
        lda #2                  ; fall 2 pixels per frame, one at a time
        sta tmp2
@step:  jsr ground_below
        bcs @land
        inc py
        inc fall
        dec tmp2
        bne @step
        rts
@land:  lda fall
        cmp #MAX_FALL+1
        bcc @safe
        jmp die
@safe:  lda #S_GROUND
        sta state
        lda #0
        sta fall
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
        jsr get_tile
        cmp #T_BRICK
        beq @done               ; ceiling
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
        jsr get_tile
        cmp #T_BRICK
        beq @floor
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

move_right:
        lda px
        cmp #156
        bcs @blk
        clc
        adc #4                  ; right edge after the step
        sta tx
        lda py
        sta ty
        jsr get_tile
        cmp #T_BRICK
        beq @blk
        lda py
        clc
        adc #8
        sta ty
        jsr get_tile
        cmp #T_BRICK
        beq @blk
        lda py
        clc
        adc #15
        sta ty
        jsr get_tile
        cmp #T_BRICK
        beq @blk
        inc px
        inc anim
        inc moved
@blk:   rts

move_left:
        lda px
        beq @blk
        sec
        sbc #1
        sta tx
        lda py
        sta ty
        jsr get_tile
        cmp #T_BRICK
        beq @blk
        lda py
        clc
        adc #8
        sta ty
        jsr get_tile
        cmp #T_BRICK
        beq @blk
        lda py
        clc
        adc #15
        sta ty
        jsr get_tile
        cmp #T_BRICK
        beq @blk
        dec px
        inc anim
        inc moved
@blk:   rts

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
        bne @skip
        lda #T_EMPTY
        ldy #0
        sta (ptr),y             ; remove it from the screen
        jsr pickup
@skip:  ldx tmp2
        inx
        cpx #6
        bne @next

        lda py                  ; spikes: only the lower part of the tile hurts
        clc
        adc #15
        sta ty
        and #7
        cmp #2
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

pickup:
        lda #ITEM_POINTS
        jsr add_score
        dec left
        lda #8
        sta snd
        lda #$28
        sta sndf
        lda left
        bne @rts
        lda #CLEAR_BONUS        ; level cleared
        jsr add_score
        lda #M_CLEAR
        sta mode
        lda #0
        sta mtimer
        lda #FR_STAND
        sta frame
        lda #$C8                ; green flash
        sta flashc
        lda #25
        sta flash
@rts:   rts

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
        jsr get_joy
        jsr update_player
        lda mode
        cmp #M_PLAY
        bne @draw
        jsr check_tiles
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
@c1:    lda #$1E
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
        lda #$1E
        sta PCOLR0
@rts:   rts

; Level cleared: flash and play a rising arpeggio, then on to the next level.
mode_clear:
        jsr inc_mtimer
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
        cmp #LEVEL_COUNT
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
        cmp #LEVEL_COUNT
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
        sta anim
        sta moved
        sta mtimer
        sta ai_have
        sta flash
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

game_colors:
        lda #$2A
        sta COLOR0              ; bright orange
        lda #$24
        sta COLOR1              ; brown
        lda #$0E
        sta COLOR2              ; white
        lda #$96
        sta COLOR3
        lda #$00
        sta COLOR4              ; black
        lda #$1E
        sta PCOLR0              ; yellow player
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
        rts

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
        sta oldpy
        rts

; ---------------------------------------------------------------------------
; Which sprite frame matches what the player is doing.
choose_frame:
        lda state
        cmp #S_CLIMB
        beq @climb
        cmp #S_AIR
        beq @air
        lda moved               ; on the ground
        beq @stand
        lda anim
        lsr a
        lsr a
        and #1
        clc
        adc #FR_WALK_A          ; walk A / walk B
        sta frame
        rts
@stand: lda #FR_STAND
        sta frame
        rts
@air:   lda #FR_AIR
        sta frame
        rts
@climb: lda moved
        beq @c0
        lda anim
        lsr a
        lsr a
        and #1
        clc
        adc #FR_CLIMB           ; climb A / climb B
        sta frame
        rts
@c0:    lda #FR_CLIMB
        sta frame
        rts

; Draw the player sprite: erase the old image, copy the first `drawn` lines of `frame`, position it.
draw_player:
        ldx oldpy
        ldy #SPR_H
        lda #0
@erase: sta PM0Y,x
        inx
        dey
        bne @erase
        lda px
        clc
        adc #48                 ; left edge of the playfield is colour clock 48
        sta HPOSP0
        lda py
        sta oldpy
        cmp #200
        bcs @rts                ; below the screen
        ldx frame
        lda spr_lo,x
        sta ptr
        lda spr_hi,x
        sta ptr+1
        ldx py
        ldy #0
@draw:  cpy drawn
        bcs @rts
        lda (ptr),y
        sta PM0Y,x
        inx
        iny
        cpy #SPR_H
        bne @draw
@rts:   rts

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
        ldx #2
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
        ldx ai_ir               ; is the target still there?
        lda row_lo,x
        clc
        adc ai_ic
        sta ptr
        lda row_hi,x
        adc #0
        sta ptr+1
        ldy #0
        lda (ptr),y
        cmp #T_ITEM
        beq @go
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

; Choose the cheapest item on the screen.
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
        ldx #1
@row:   lda row_lo,x
        sta ptr
        lda row_hi,x
        sta ptr+1
        ldy #0
@col:   lda (ptr),y
        cmp #T_ITEM
        bne @next
        tya                     ; |column - player column|
        sec
        sbc a_pc
        bcs @p
        eor #$FF
        adc #1
@p:     sta a_cost
        txa                     ; 8 * |row - player row|
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
        stx ai_ir
        lda #1
        sta ai_have
@next:  iny
        cpy #40
        bne @col
        inx
        cpx #24
        bne @row
        rts

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
        lda px                  ; spike 8 pixels ahead on the way to the goal?
        sec
        sbc #8
        sta tx
        lda py
        clc
        adc #15
        sta ty
        jsr get_tile
        cmp #T_SPIKE
        bne @lhole
        lda tx
        and #$FC
        cmp ai_goal
        bcs @jump               ; the spike lies between us and the goal
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
        lda px
        clc
        adc #10
        sta tx
        lda py
        clc
        adc #15
        sta ty
        jsr get_tile
        cmp #T_SPIKE
        bne @rhole
        lda tx
        and #$FC
        cmp ai_goal
        bcc @jump
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

row_lo: .repeat 24, i
        .byte <(SCREEN + i * 40)
        .endrepeat
row_hi: .repeat 24, i
        .byte >(SCREEN + i * 40)
        .endrepeat

pow_lo: .byte <10000, <1000, <100, <10, <1
pow_hi: .byte >10000, >1000, >100, >10, >1

; Pixels the player rises on each frame of a jump (0 ends the rise).
jump_dy: .byte 3,3,3,2,2,2,1,1,1,0

; The death hop: signed pixels per frame, then a steady fall.
die_dy:  .byte $FC,$FC,$FD,$FD,$FE,$FE,$FF,$FF,0,1,1,2,2,3,3,4,4,5,5
DIE_LEN = * - die_dy

clear_notes: .byte $79,$5F,$4B,$3C

; Points (offset from px,py) that collect items.
pt_dx:  .byte 0,3,0,3,0,3
pt_dy:  .byte 3,3,8,8,13,13

spr_lo: .repeat SPR_COUNT, i
        .byte <(spr_frames + SPR_H * i)
        .endrepeat
spr_hi: .repeat SPR_COUNT, i
        .byte >(spr_frames + SPR_H * i)
        .endrepeat

mode_tab:
        .word mode_title, mode_play, mode_dying, mode_spawn, mode_clear, mode_over

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
        .byte $44                       ; mode 4 + load memory scan
        .word SCREEN
        .repeat 23
        .byte $04
        .endrepeat
        .byte $41                       ; jump and wait for vertical blank
        .word dlist

        .include "gen/charset.inc"
