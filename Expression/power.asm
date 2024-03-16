.MODEL SMALL
.DATA
    BASE DW ?
    POW DB ?
    NL1 DB 0AH,0DH,'ENTER BASE: ','$'
    NL2 DB 0AH,0DH,'ENTER POWER: ','$'
    RESULT DB 6 DUP('$')

.CODE
MAIN PROC

    MOV AX,@DATA
    MOV DS,AX

    CALL ENTER_BASE
    CALL ENTER_POWER

    MOV AX, BASE
    MOV BX, POW
    CALL POWER

    MOV AH, 09H     ; Print result
    LEA DX, RESULT
    INT 21H

    MOV AH,4CH      ; Exit program
    INT 21H

ENTER_BASE:
    LEA DX, NL1     ; Display prompt
    MOV AH, 09H
    INT 21H

    CALL READ_NUMBER ; Read base
    MOV BASE, AX
    RET

ENTER_POWER:
    LEA DX, NL2     ; Display prompt
    MOV AH, 09H
    INT 21H

    CALL READ_NUMBER ; Read power
    MOV POW, AL
    RET

READ_NUMBER:
    XOR AX, AX      ; Clear AX
    MOV CX, 10      ; Multiplier
READ_LOOP:
    MOV AH, 01H     ; Read a character
    INT 21H

    CMP AL, 0DH     ; Check for Enter key
    JE DONE_READ    ; If Enter, finish reading

    SUB AL, 30H     ; Convert ASCII to digit
    MUL CX          ; Multiply current number by 10
    ADD AX, DX      ; Add new digit
    MOV DX, AX      ; Store result

    JMP READ_LOOP   ; Repeat

DONE_READ:
    RET

POWER PROC
    MOV CX, POW     ; Move power to CX
    MOV DX, 0       ; Clear DX (result)
    MOV AX, 1       ; Set AX to 1 (base case)

POWER_LOOP:
    TEST CX, 1      ; Check if power is odd
    JZ EVEN_POWER   ; If not odd, skip

    MUL BX          ; Multiply result by base
    DEC CX          ; Decrement power

EVEN_POWER:
    SHR CX, 1       ; Divide power by 2
    JZ POWER_DONE   ; If power is zero, finish

    MUL BX          ; Multiply base by itself
    JMP POWER_LOOP  ; Repeat

POWER_DONE:
    MOV AX, DX      ; Move result to AX
    RET
POWER ENDP

MAIN ENDP
END MAIN
