#Requires AutoHotkey v2.0
#SingleInstance Force

; ---------------------------------------------------------------------------
; Prefer the Python port on Windows (more reliable HID I/O than the .ps1).
; Edit SCRIPT to your real path. Python always switches to channel 2 + HDMI.
; ---------------------------------------------------------------------------
SCRIPT := "C:\Path\To\mxswitch\python\mxswitch.py"

SwitchAway() {
    global SCRIPT
    if (StrLower(SubStr(SCRIPT, -4)) = ".ps1") {
        Run(Format(
            'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{1}"',
            SCRIPT), , "Hide")
    } else {
        ; pythonw = no console flash. Channel arg is ignored on Windows.
        Run(Format('pythonw.exe "{1}"', SCRIPT), , "Hide")
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
