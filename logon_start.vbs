Option Explicit
Dim sh, fs, launcher
Set sh = CreateObject("WScript.Shell")
Set fs = CreateObject("Scripting.FileSystemObject")
launcher = fs.BuildPath(fs.GetParentFolderName(WScript.ScriptFullName), "start_jarvis.vbs")
sh.Run "wscript.exe """ & launcher & """", 0, False
