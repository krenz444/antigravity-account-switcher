# ai_switch.ps1 - Fast PowerShell 5.1 / 7 helper for Antigravity account switching & quota rotation
param(
    [Parameter(Position=0)]
    [string]$Command = "status",

    [Parameter(Position=1, ValueFromRemainingArguments=$true)]
    [string[]]$RemainingArgs
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$routerScript = Join-Path $scriptDir "router.py"
$guiScript = Join-Path $scriptDir "gui_app.py"

$pythonw = "pythonw"
$cmd = Get-Command pythonw -ErrorAction SilentlyContinue
if ($cmd) {
    $pythonw = $cmd.Source
} else {
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pyCmd) { $pythonw = $pyCmd.Source }
}

if (-not (Test-Path $routerScript)) {
    Write-Error "Cannot find router.py at $routerScript"
    exit 1
}

if ($Command -eq "app" -or $Command -eq "gui") {
    Start-Process $pythonw -ArgumentList "`"$guiScript`"" -WorkingDirectory $scriptDir
    Write-Output "Launched Antigravity Accounts Switchboard!"
    exit 0
}

# Allow direct numeric shortcuts: "ai_switch.ps1 1" -> "switch 1"
if ($Command -match '^\d+$') {
    $target = $Command
    if ($RemainingArgs) {
        & python -I $routerScript switch $target @RemainingArgs
    } else {
        & python -I $routerScript switch $target
    }
    exit $LASTEXITCODE
}

if ($RemainingArgs) {
    & python -I $routerScript $Command @RemainingArgs
} else {
    & python -I $routerScript $Command
}
