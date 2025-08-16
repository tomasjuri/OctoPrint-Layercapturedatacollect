
; Retract filament before pause to prevent oozing
G91                    ; Relative positioning
G1 E-20 F14000          ; Retract 20mm at 1800mm/min
G1 Z5 F300             ; Lift Z 5mm to clear print
G90                    ; Absolute positioning
M601                   ; pause print

M240 Z[layer_z] ZN[layer_num] MIN0[first_layer_print_min_0] MAX0[first_layer_print_max_0] MIN1[first_layer_print_min_1] MAX1[first_layer_print_max_1]    ; Start layer capture sequence


; Start position - lift Z 30mm from current position
G91 ; Relative positioning
G1 Z30 F300 ; Lift Z 30mm from current position
G90 ; Absolute positioning

; Corner 1: Top-Left
G1 X100 Y130 F3000 ; Move to top-left corner
G4 P2000 ; Wait 2 seconds (2000ms)

; Corner 2: Top-Right  
G1 X150 Y130 F3000 ; Move to top-right corner
G4 P2000 ; Wait 2 seconds

; Corner 3: Bottom-Right
G1 X150 Y80 F3000 ; Move to bottom-right corner  
G4 P2000 ; Wait 2 seconds

; Corner 4: Bottom-Left
G1 X100 Y80 F3000 ; Move to bottom-left corner
G4 P2000 ; Wait 2 seconds

;M602 ; resume print

G91                    ; Relative positioning
G1 E15 F14000          ; Prime the nozzle
G90                    ; Absolute positioning

G1 E21 F14000          ; Retract 3mm at 1800mm/min

