Option Explicit

If WScript.Arguments.Count <> 2 Then
    WScript.Quit 64
End If

Dim shell, command, exitCode, powershell, launcher
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = WScript.Arguments(1)
powershell = shell.ExpandEnvironmentStrings("%WINDIR%\System32\WindowsPowerShell\v1.0\powershell.exe")
launcher = WScript.Arguments(1) & "\scripts\start.ps1"
' Keep the original two-argument interface; start.ps1 uses this root's venv.
' Wait for Python so its exit code reaches Task Scheduler; start.ps1 captures stderr.
command = Quote(powershell) & " -NoProfile -NonInteractive -ExecutionPolicy Bypass -File " & Quote(launcher) & " -Wait"
exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function
