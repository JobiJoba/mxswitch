#Requires AutoHotkey v2.0
#SingleInstance Force

; ---------------------------------------------------------------------------
; Edit this path to windows\mxswitch.ps1 (preferred) or python\mxswitch.py.
; The PowerShell build always switches to channel 2; -Channel is ignored.
; ---------------------------------------------------------------------------
SCRIPT := "C:\Path\To\mxswitch\windows\mxswitch.ps1"

SwitchAway() {
    global SCRIPT
    if (StrLower(SubStr(SCRIPT, -4)) = ".ps1") {
        Run(Format(
            'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{1}"',
            SCRIPT), , "Hide")
    } else {
        ; Python port still needs an explicit channel (2 = Mac on this setup).
        Run(Format('pythonw.exe "{1}" 2', SCRIPT), , "Hide")
    }
}

; Ctrl+Alt+M  ->  hand devices over to the other machine
^!m::SwitchAway()

; Ctrl+Alt+Shift+M  ->  hand them over and lock this machine behind you
^!+m:: {
    SwitchAway()
    Sleep 500                                ; let the frame go out first
    DllCall("user32\LockWorkStation")
}
