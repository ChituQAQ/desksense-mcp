Option Explicit

If WScript.Arguments.Count <> 3 Then
    WScript.Quit 64
End If

Dim shell, command, exitCode
Set shell = CreateObject("WScript.Shell")
command = Quote(WScript.Arguments(0)) & " tunnel --config " & _
    Quote(WScript.Arguments(1)) & " run " & Quote(WScript.Arguments(2))
exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function
