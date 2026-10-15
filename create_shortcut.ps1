# create_shortcut.ps1 - Creates a desktop shortcut for Antigravity Accounts Switchboard
$WshShell = New-Object -ComObject WScript.Shell
$desktopPath = [System.Environment]::GetFolderPath('Desktop')
$ShortcutPath = Join-Path $desktopPath "Antigravity Accounts.lnk"

$scriptDir = $PSScriptRoot
$appScript = Join-Path $scriptDir "gui_app.py"
$iconPath = Join-Path $scriptDir "app_icon.ico"

# Locate pythonw (preferred for windowless launch) or python
$pythonwPath = $null
$cmd = Get-Command pythonw -ErrorAction SilentlyContinue
if ($cmd) {
    $pythonwPath = $cmd.Source
} else {
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pyCmd) { $pythonwPath = $pyCmd.Source }
}

if (-not $pythonwPath) {
    Write-Error "Python/pythonw executable not found in PATH."
    exit 1
}

$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $pythonwPath
$Shortcut.Arguments = "`"$appScript`""
$Shortcut.WorkingDirectory = $scriptDir
if (Test-Path $iconPath) {
    $Shortcut.IconLocation = $iconPath
}
$Shortcut.Description = "Antigravity Multi-Account Switchboard & Real-Time Quota Monitor"
$Shortcut.Save()

Write-Output "Shortcut created successfully on Desktop: $ShortcutPath"
