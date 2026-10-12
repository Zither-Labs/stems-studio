# Draws the Stems Studio desktop icons (assets\stems-studio.ico and assets\install.ico).
# Run:  powershell -ExecutionPolicy Bypass -File tools\make_icons.ps1
Add-Type -AssemblyName System.Drawing

$root = Split-Path -Parent $PSScriptRoot
$assets = Join-Path $root "assets"
New-Item -ItemType Directory -Force -Path $assets | Out-Null

function New-RoundedPath([float]$x, [float]$y, [float]$w, [float]$h, [float]$r) {
    $p = New-Object System.Drawing.Drawing2D.GraphicsPath
    $d = $r * 2
    $p.AddArc($x, $y, $d, $d, 180, 90)
    $p.AddArc($x + $w - $d, $y, $d, $d, 270, 90)
    $p.AddArc($x + $w - $d, $y + $h - $d, $d, $d, 0, 90)
    $p.AddArc($x, $y + $h - $d, $d, $d, 90, 90)
    $p.CloseFigure()
    return $p
}

function New-IconBitmap([bool]$install) {
    $size = 256
    $bmp = New-Object System.Drawing.Bitmap $size, $size, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = 'AntiAlias'
    $g.Clear([System.Drawing.Color]::Transparent)

    # Background tile: deep indigo to violet
    $tile = New-RoundedPath 8 8 240 240 56
    $bg = New-Object System.Drawing.Drawing2D.LinearGradientBrush ([System.Drawing.Point]::new(0, 0)), ([System.Drawing.Point]::new(256, 256)), ([System.Drawing.Color]::FromArgb(255, 24, 20, 64)), ([System.Drawing.Color]::FromArgb(255, 109, 40, 217))
    $g.FillPath($bg, $tile)
    $glow = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(90, 255, 255, 255)), 3
    $g.DrawPath($glow, $tile)

    # Stem bars, one colour per stem (vocals, percussion, bass, guitar, keys)
    $colors = @(
        [System.Drawing.Color]::FromArgb(255, 244, 63, 94),
        [System.Drawing.Color]::FromArgb(255, 251, 146, 60),
        [System.Drawing.Color]::FromArgb(255, 56, 189, 248),
        [System.Drawing.Color]::FromArgb(255, 52, 211, 153),
        [System.Drawing.Color]::FromArgb(255, 250, 204, 21)
    )
    if ($install) { $heights = @(70, 104, 84, 112, 62); $baseY = 150 } else { $heights = @(104, 160, 128, 176, 92); $baseY = 202 }
    $barW = 30; $gap = 12
    $startX = (256 - (5 * $barW + 4 * $gap)) / 2
    for ($i = 0; $i -lt 5; $i++) {
        $h = $heights[$i]
        $x = $startX + $i * ($barW + $gap)
        $path = New-RoundedPath $x ($baseY - $h) $barW $h 15
        $brush = New-Object System.Drawing.SolidBrush $colors[$i]
        $g.FillPath($brush, $path)
        $shine = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(70, 255, 255, 255))
        $g.FillPath($shine, (New-RoundedPath ($x + 5) ($baseY - $h + 6) 7 ([Math]::Max(10, $h - 24)) 3.5))
    }

    if ($install) {
        # Download badge: green circle, white arrow into a tray
        $badge = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 34, 197, 94))
        $ring = New-Object System.Drawing.Pen ([System.Drawing.Color]::White), 8
        $g.FillEllipse($badge, 108, 138, 120, 120)
        $g.DrawEllipse($ring, 108, 138, 120, 120)
        $w = New-Object System.Drawing.Pen ([System.Drawing.Color]::White), 13
        $w.StartCap = 'Round'; $w.EndCap = 'Round'; $w.LineJoin = 'Round'
        $g.DrawLine($w, 168, 164, 168, 204)
        $g.DrawLines($w, @([System.Drawing.PointF]::new(148, 188), [System.Drawing.PointF]::new(168, 208), [System.Drawing.PointF]::new(188, 188)))
        $g.DrawLine($w, 146, 228, 190, 228)
    }
    $g.Dispose()
    return $bmp
}

function Write-Ico([System.Drawing.Bitmap]$source, [string]$path) {
    $frames = @()
    foreach ($s in 256, 48, 32, 16) {
        $small = New-Object System.Drawing.Bitmap $s, $s, ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $sg = [System.Drawing.Graphics]::FromImage($small)
        $sg.InterpolationMode = 'HighQualityBicubic'
        $sg.PixelOffsetMode = 'HighQuality'
        $sg.DrawImage($source, 0, 0, $s, $s)
        $sg.Dispose()
        $ms = New-Object System.IO.MemoryStream
        $small.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
        $frames += , @{ Size = $s; Bytes = $ms.ToArray() }
        $small.Dispose()
    }
    $out = New-Object System.IO.MemoryStream
    $w = New-Object System.IO.BinaryWriter $out
    $w.Write([UInt16]0); $w.Write([UInt16]1); $w.Write([UInt16]$frames.Count)
    $offset = 6 + 16 * $frames.Count
    foreach ($f in $frames) {
        $dim = if ($f.Size -ge 256) { 0 } else { $f.Size }
        $w.Write([byte]$dim); $w.Write([byte]$dim); $w.Write([byte]0); $w.Write([byte]0)
        $w.Write([UInt16]1); $w.Write([UInt16]32)
        $w.Write([UInt32]$f.Bytes.Length); $w.Write([UInt32]$offset)
        $offset += $f.Bytes.Length
    }
    foreach ($f in $frames) { $w.Write($f.Bytes) }
    $w.Flush()
    [System.IO.File]::WriteAllBytes($path, $out.ToArray())
}

$app = New-IconBitmap $false
Write-Ico $app (Join-Path $assets "stems-studio.ico")
$app.Save((Join-Path $assets "stems-studio.png"), [System.Drawing.Imaging.ImageFormat]::Png)
$inst = New-IconBitmap $true
Write-Ico $inst (Join-Path $assets "install.ico")
$inst.Save((Join-Path $assets "install.png"), [System.Drawing.Imaging.ImageFormat]::Png)
Write-Output "Icons written to $assets"
