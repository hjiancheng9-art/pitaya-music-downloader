' mget GUI 启动器 - 双击即可运行
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptPath = fso.GetParentFolderName(WScript.ScriptFullName)

' 尝试 pythonw (无控制台窗口), 回退到 python
pythonwPath = WshShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Programs\Python\Python311\pythonw.exe"
If Not fso.FileExists(pythonwPath) Then
    pythonwPath = "pythonw"
End If

cmd = """" & pythonwPath & """ """ & scriptPath & "\gui.py"""
WshShell.Run cmd, 1, False
Set WshShell = Nothing
