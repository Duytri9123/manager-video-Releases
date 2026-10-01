' ================================================================
' Khởi chạy ngầm Backend Flask & Cloudflare Tunnel (ToolVideo)
' Tên miền: https://toolvideo.dgpelectric.top -> Port 9123
' Không hiển thị bất kỳ cửa sổ CMD nào (Hoàn toàn ẩn dưới nền)
' ================================================================
Option Explicit

Dim WshShell, fso, scriptPath, baseDir, psScript, psCmd

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

scriptPath = WScript.ScriptFullName
baseDir = fso.GetParentFolderName(scriptPath)
psScript = baseDir & "\tools\start_silent.ps1"

psCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & psScript & """"
WshShell.Run psCmd, 0, False
