' Launches run.bat without a console window.
'
' A .bat cannot avoid one: double-clicking it opens cmd, and everything the
' launcher does - checking that the packages are in place, starting python -
' happens in full view before the app appears. Run through here instead and
' the only window that opens is the app's.
'
' The install is the exception. It takes a while and is worth watching, so
' run.bat answers 2 when it finds work to do and this re-runs it in a real
' console, where pip can say what it is doing.

Set shell = CreateObject("WScript.Shell")
bat = Left(WScript.ScriptFullName, Len(WScript.ScriptFullName) - 4) & ".bat"

If shell.Run("""" & bat & """ quiet", 0, True) = 2 Then
    shell.Run """" & bat & """ setup", 1, False
End If
