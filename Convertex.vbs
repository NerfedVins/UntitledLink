' Starts the app with nothing else on screen. Double-click this one.
'
' A .bat cannot manage that: double-clicking one opens cmd for a second while
' Windows starts it, whatever the batch file has been trimmed down to. This
' also does the everyday check itself - is the stamp file at least as new as
' requirements.txt - which used to cost a whole python startup to compare two
' dates. On the usual launch nothing runs here but the app.
'
' Installing is the exception. It takes a while and is worth watching, so that
' goes to run.bat in a real console where pip can say what it is doing. Same if
' pythonw cannot be started at all: the batch file is where that gets said.

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

folder = fso.GetParentFolderName(WScript.ScriptFullName)
stamp = fso.BuildPath(folder, ".deps-ok")
needs = fso.BuildPath(folder, "requirements.txt")

ready = False
If fso.FileExists(stamp) And fso.FileExists(needs) Then
    If fso.GetFile(stamp).DateLastModified >= fso.GetFile(needs).DateLastModified Then
        ready = True
    End If
End If

If ready Then
    shell.CurrentDirectory = folder
    On Error Resume Next
    shell.Run "pythonw convertex.py", 0, False
    If Err.Number = 0 Then
        WScript.Quit
    End If
    On Error GoTo 0
End If

shell.Run """" & fso.BuildPath(folder, "run.bat") & """ setup", 1, False
