Option Explicit
Dim sh, fs, root, py, script
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
root = fs.GetParentFolderName(WScript.ScriptFullName)
py = fs.BuildPath(root, ".venv\Scripts\pythonw.exe")
script = fs.BuildPath(root, "src\jarvis_supervisor.py")
If Not fs.FileExists(py) Then
    MsgBox "Create .venv and install requirements first; see docs/SETUP_WINDOWS.md.", 48, "Jarvis"
    WScript.Quit 1
End If
sh.CurrentDirectory = root
sh.Run """" & py & """ """ & script & """", 0, False
