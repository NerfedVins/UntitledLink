' Launches run.bat without a console window. Double-click this one for a
' start with nothing on screen but the app.
'
' A .bat cannot manage that: double-clicking one opens cmd for a second while
' Windows starts it, whatever the batch file has been trimmed down to. run.bat
' still works and hands straight over to this, so the console it opens is as
' short as Windows allows - but this file never opens one at all.
'
' The install is the exception. It takes a while and is worth watching, so
' run.bat answers 2 when it finds work to do and this re-runs it in a real
' console, where pip can say what it is doing.

Set shell = CreateObject("WScript.Shell")
folder = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
bat = folder & "run.bat"

If shell.Run("""" & bat & """ quiet", 0, True) = 2 Then
    shell.Run """" & bat & """ setup", 1, False
End If
