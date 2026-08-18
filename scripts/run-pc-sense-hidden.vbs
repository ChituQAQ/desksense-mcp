Option Explicit

If WScript.Arguments.Count <> 2 Then
    WScript.Quit 64
End If

Dim shell, command, exitCode
Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = WScript.Arguments(1)
command = Quote(WScript.Arguments(0)) & " -m pc_sense.server"
exitCode = shell.Run(command, 0, True)
WScript.Quit exitCode

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function
