; ---------------------------------------------------------------------------
; atarigame - single-screen puzzle/platformer for the Atari XL/XE (ca65)
;
; Screen : ANTIC mode 4, 40x24 tiles of 4x8 pixels (160x192, 4 colours).
; Player : hardware Player 0, 4 pixels wide x 16 lines tall (two tiles high).
; Coordinates: px = 0..156 (colour clocks from the left edge of the playfield),
;              py = 0..191 (scan lines from the top of the playfield).
; ---------------------------------------------------------------------------

        .setcpu "6502"
        .export start
        .export frame_end                       ; breakpoint target for tools/headless.py
        .exportzp px, py, state, jt, fall, score, left, joy, anim, moved, flash

        .include "gen/tiles.inc"

; ---- OS and hardware registers --------------------------------------------
RTCLOK  = $12           ; frame counter, low byte at RTCLOK+2
ATRACT  = $4D           ; attract-mode timer (reset every frame)
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
COLOR3  = $02C7
COLOR4  = $02C8         ; background
CHBAS   = $02F4
HPOSP0  = $D000
SIZEP0  = $D008
GRACTL  = $D01D
AUDF1   = $D200
AUDC1   = $D201
PMBASE  = $D407

; ---- memory layout (must match cfg/atari-xex.cfg) --------------------------
CHARSET_ADDR = $4000
SCREEN  = $4500         ; 24 rows x 40 columns (1 KB reserved)
PMAREA  = $5000         ; 2 KB aligned, single-line resolution
PM0     = PMAREA + $0400
PM_YOFF = 32            ; PM byte index of the first playfield scan line
PM0Y    = PM0 + PM_YOFF

; ---- game constants --------------------------------------------------------
S_GROUND = 0
S_AIR    = 1
S_CLIMB  = 2

JOY_UP    = $01
JOY_DOWN  = $02
JOY_LEFT  = $04
JOY_RIGHT = $08
JOY_FIRE  = $10

MAX_FALL = 64           ; falling further than this (pixels) kills
SPR_H    = 16

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
joy:      .res 1
joyprev:  .res 1
tx:       .res 1        ; pixel being queried by get_tile
ty:       .res 1
tmp:      .res 1
tmp2:     .res 1
score:    .res 1
left:     .res 1        ; items still to collect
snd:      .res 1        ; sound timer / volume
sndf:     .res 1        ; sound pitch
flash:    .res 1        ; background flash timer
flashc:   .res 1        ; background flash colour
ptr:      .res 2
ptr2:     .res 2

; ---------------------------------------------------------------------------
        .segment "CODE"

start:
        cld
        lda #0
        sta score
        sta oldpy
        sta joy
        sta flash
        sta snd
        jsr clear_pm

        lda #<dlist
        sta SDLSTL
        lda #>dlist
        sta SDLSTL+1
        lda #>CHARSET_ADDR
        sta CHBAS

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
        lda #1
        sta GPRIOR              ; players in front of the playfield
        lda #0
        sta SIZEP0
        lda #>PMAREA
        sta PMBASE
        lda #3
        sta GRACTL              ; enable players and missiles
        jsr load_level
        lda #$3A                ; DL DMA + single-line PM + players + normal width
        sta SDMCTL

mainloop:
        jsr vwait
        lda #0
        sta ATRACT
        jsr read_input
        jsr update_player
        jsr check_tiles
        jsr draw_player
        jsr draw_hud
        jsr update_fx
frame_end:
        jmp mainloop

; Wait for the next frame.
vwait:
        lda RTCLOK+2
@w:     cmp RTCLOK+2
        beq @w
        rts

; ---------------------------------------------------------------------------
; Input: joy bit set = pressed (see JOY_*).
read_input:
        lda joy
        sta joyprev
        lda STICK0
        eor #$0F
        and #$0F
        sta joy
        lda STRIG0
        bne @nofire
        lda joy
        ora #JOY_FIRE
        sta joy
@nofire:
        rts

; ---------------------------------------------------------------------------
; Tile lookup. In: tx, ty (pixels). Out: A = tile id, ptr -> its screen byte.
; Anything outside the screen counts as brick so the player cannot leave it.
get_tile:
        lda ty
        cmp #192
        bcs @solid
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
        inc score
        dec left
        lda #8
        sta snd
        lda #$28
        sta sndf
        lda left
        bne @rts
        lda #$C8                ; level cleared: green flash, then start over
        sta flashc
        lda #25
        sta flash
        lda #14
        sta snd
        lda #$18
        sta sndf
        jsr load_level
@rts:   rts

die:
        lda #0
        sta score
        lda #$34                ; red flash
        sta flashc
        lda #20
        sta flash
        lda #14
        sta snd
        lda #$B0
        sta sndf
        jmp load_level

; ---------------------------------------------------------------------------
; Copy the level to the screen and put the player at the start.
load_level:
        lda #<level1
        sta ptr
        lda #>level1
        sta ptr+1
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

        lda level1_spawn
        asl a
        asl a
        sta px
        lda level1_spawn+1
        asl a
        asl a
        asl a
        sta py
        lda #LEVEL1_ITEMS
        sta left
        lda #S_GROUND
        sta state
        lda #$FF
        sta jt
        lda #0
        sta fall
        sta anim
        sta moved
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

; ---------------------------------------------------------------------------
; Draw the player sprite: erase the old image, pick a frame, copy it, position it.
draw_player:
        ldx oldpy
        ldy #SPR_H
        lda #0
@erase: sta PM0Y,x
        inx
        dey
        bne @erase

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
        adc #1                  ; walk A / walk B
        jmp @setframe
@stand: lda #0
        jmp @setframe
@air:   lda #2
        jmp @setframe
@climb: lda moved
        beq @c0
        lda anim
        lsr a
        lsr a
        and #1
        clc
        adc #3                  ; climb A / climb B
        jmp @setframe
@c0:    lda #3
@setframe:
        tax
        lda spr_lo,x
        sta ptr
        lda spr_hi,x
        sta ptr+1
        ldx py
        ldy #0
@draw:  lda (ptr),y
        sta PM0Y,x
        inx
        iny
        cpy #SPR_H
        bne @draw

        lda px
        clc
        adc #48                 ; left edge of the playfield is colour clock 48
        sta HPOSP0
        lda py
        sta oldpy
        rts

; ---------------------------------------------------------------------------
; Score (left) and items remaining (right), written into row 0 of the screen.
draw_hud:
        lda score
        ldx #1
        jsr hud_num3
        lda left
        ldx #36
        ; fall through

; In: A = 0..255, X = screen column. Writes three digit tiles.
hud_num3:
        sta tmp
        ldy #0
@h:     lda tmp
        cmp #100
        bcc @hd
        sbc #100
        sta tmp
        iny
        bne @h
@hd:    tya
        clc
        adc #T_DIGIT0
        sta SCREEN,x
        inx
        ldy #0
@t:     lda tmp
        cmp #10
        bcc @td
        sbc #10
        sta tmp
        iny
        bne @t
@td:    tya
        clc
        adc #T_DIGIT0
        sta SCREEN,x
        inx
        lda tmp
        clc
        adc #T_DIGIT0
        sta SCREEN,x
        rts

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
        .segment "RODATA"

        .include "gen/sprites.inc"      ; defines SPR_COUNT and spr_frames
        .include "gen/levels.inc"

row_lo: .repeat 24, i
        .byte <(SCREEN + i * 40)
        .endrepeat
row_hi: .repeat 24, i
        .byte >(SCREEN + i * 40)
        .endrepeat

; Pixels the player rises on each frame of a jump (0 ends the rise).
jump_dy: .byte 3,3,3,2,2,2,1,1,1,0

; Points (offset from px,py) that collect items.
pt_dx:  .byte 0,3,0,3,0,3
pt_dy:  .byte 3,3,8,8,13,13

spr_lo: .repeat SPR_COUNT, i
        .byte <(spr_frames + SPR_H * i)
        .endrepeat
spr_hi: .repeat SPR_COUNT, i
        .byte >(spr_frames + SPR_H * i)
        .endrepeat


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
