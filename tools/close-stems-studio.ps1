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

Start-Sleep -Seconds 2
