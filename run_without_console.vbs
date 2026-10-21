' Starts the source version without a console window. Requires Python 3.12.
' To diagnose startup errors, run start.bat instead.
Option Explicit
Dim shell, fso, folder, scriptPath, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
folder = fso.GetParentFolderName(WScript.ScriptFullName)
scriptPath = folder & "\main.py"
shell.CurrentDirectory = folder
command = "pyw -3.12 """ & scriptPath & """"
shell.Run command, 0, False
