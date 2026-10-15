param(
    [Parameter(Mandatory = $true)][string]$Target,
    [Parameter(Mandatory = $true)][string]$Script
)
$ErrorActionPreference = 'Stop'

# Ask Windows where the Desktop really is (handles OneDrive and renamed folders).
$folders = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))
$shell = New-Object -ComObject WScript.Shell

$root = Split-Path -Parent $Script
$icon = Join-Path $root 'assets\stems-studio.ico'
$updateBat = Join-Path $root 'Update.bat'
$updateIcon = Join-Path $root 'assets\install.ico'

foreach ($folder in $folders) {
    if (-not $folder -or -not (Test-Path $folder)) { continue }
    $link = $shell.CreateShortcut((Join-Path $folder 'Stems Studio.lnk'))
    $link.TargetPath = $Target
    $link.Arguments = '"' + $Script + '"'
    $link.WorkingDirectory = $root
    $link.Description = 'Stems Studio'
    if (Test-Path $icon) { $link.IconLocation = "$icon,0" }
    $link.Save()
    Write-Host "Shortcut created: $($link.FullName)"

    if (Test-Path $updateBat) {
        $update = $shell.CreateShortcut((Join-Path $folder 'Update Stems Studio.lnk'))
        $update.TargetPath = $updateBat
        $update.WorkingDirectory = $root
        $update.Description = 'Get the newest Stems Studio and open it'
        if (Test-Path $updateIcon) { $update.IconLocation = "$updateIcon,0" }
        $update.Save()
        Write-Host "Shortcut created: $($update.FullName)"
    }
}

# The earlier launcher (it ran git pull and kept a console window open) is no longer needed.
$oldLauncher = Join-Path $folders[0] 'Stems Studio.bat'
if ((Test-Path $oldLauncher) -and ((Get-Content $oldLauncher -Raw) -match 'server\.py|Run-Stems-Studio')) {
    Remove-Item $oldLauncher -Force
    Write-Host "Removed the old launcher: $oldLauncher"
}
