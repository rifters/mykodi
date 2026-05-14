# Batch resize PNG images to maximum 512x512 (maintaining aspect ratio)
# Images smaller than 512x512 are left unchanged

param(
    [string]$SourceDir = "resources\media\modern",
    [int]$MaxSize = 512,
    [switch]$Backup = $true
)

Add-Type -AssemblyName System.Drawing

$pngFiles = Get-ChildItem -Path $SourceDir -Filter "*.png" -File
$total = $pngFiles.Count
$processed = 0
$resized = 0
$skipped = 0

Write-Host "Found $total PNG files to process" -ForegroundColor Cyan
Write-Host "Maximum dimensions: $MaxSize x $MaxSize (maintaining aspect ratio)`n" -ForegroundColor Yellow

# Create backup directory if requested
if ($Backup) {
    $backupDir = Join-Path $SourceDir "backup_originals_max512"
    if (-not (Test-Path $backupDir)) {
        New-Item -Path $backupDir -ItemType Directory | Out-Null
        Write-Host "Created backup directory: $backupDir`n" -ForegroundColor Green
    }
}

foreach ($file in $pngFiles) {
    $processed++

    try {
        # Load original image
        $originalImage = [System.Drawing.Image]::FromFile($file.FullName)
        $originalWidth = $originalImage.Width
        $originalHeight = $originalImage.Height

        # Check if resize is needed
        if ($originalWidth -le $MaxSize -and $originalHeight -le $MaxSize) {
            Write-Host "[$processed/$total] Skipped: $($file.Name) ($($originalWidth)x$($originalHeight) - already small enough)" -ForegroundColor Gray
            $originalImage.Dispose()
            $skipped++
            continue
        }

        Write-Host "[$processed/$total] Resizing: $($file.Name) ($($originalWidth)x$($originalHeight))" -NoNewline

        # Calculate new dimensions maintaining aspect ratio
        $ratio = [Math]::Min($MaxSize / $originalWidth, $MaxSize / $originalHeight)
        $newWidth = [int]($originalWidth * $ratio)
        $newHeight = [int]($originalHeight * $ratio)

        # Create new bitmap with resized dimensions
        $newBitmap = New-Object System.Drawing.Bitmap($newWidth, $newHeight)
        $graphics = [System.Drawing.Graphics]::FromImage($newBitmap)

        # High quality resize settings
        $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
        $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality

        # Draw resized image
        $graphics.DrawImage($originalImage, 0, 0, $newWidth, $newHeight)

        # Backup original if requested
        if ($Backup) {
            $backupPath = Join-Path $backupDir $file.Name
            Copy-Item -Path $file.FullName -Destination $backupPath -Force
        }

        # Save resized image (replace original)
        $originalImage.Dispose()
        $graphics.Dispose()

        # Delete original and save new
        Remove-Item -Path $file.FullName -Force
        $newBitmap.Save($file.FullName, [System.Drawing.Imaging.ImageFormat]::Png)
        $newBitmap.Dispose()

        $newSize = (Get-Item $file.FullName).Length
        Write-Host " -> $($newWidth)x$($newHeight) [$([math]::Round($newSize/1KB, 0)) KB]" -ForegroundColor Green
        $resized++

    } catch {
        Write-Host " -> ERROR: $_" -ForegroundColor Red
    }
}

Write-Host "`n=== Summary ===" -ForegroundColor Cyan
$finalSize = (Get-ChildItem -Path $SourceDir -Filter "*.png" -File | Measure-Object -Property Length -Sum).Sum
Write-Host "Processed: $processed files" -ForegroundColor White
Write-Host "Resized: $resized files" -ForegroundColor Green
Write-Host "Skipped: $skipped files (already ≤ $MaxSize px)" -ForegroundColor Gray
Write-Host "Total size now: $([math]::Round($finalSize/1MB, 2)) MB" -ForegroundColor Cyan
if ($Backup) {
    Write-Host "Originals backed up to: $backupDir" -ForegroundColor Yellow
}
