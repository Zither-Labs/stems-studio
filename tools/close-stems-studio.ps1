# Closes a running Stems Studio so an update can replace its files.
# Stops the app's own Python and its private browser window. Other Chrome windows stay open.
param([Parameter(Mandatory = $true)][string]$Root)

$ErrorActionPreference = 'SilentlyContinue'
$root = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
$mine = $PID

Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $mine -and $_.CommandLine -and (
        ($_.CommandLine -like "*$root*app.py*") -or
        ($_.CommandLine -like "*$root*server.py*") -or
        ($_.CommandLine -like '*\StemsStudio\window-profile*')
    )
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force
}

# The engine sometimes stays up when its command line is hidden. Anything still
# listening on the app port is that engine; leaving it up makes the next launch
# reopen the old code.
Get-NetTCPConnection -LocalPort 8099 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    if ($_.OwningProcess -and $_.OwningProcess -ne $mine) {
        Stop-Process -Id $_.OwningProcess -Force
    }
}

Start-Sleep -Seconds 2
