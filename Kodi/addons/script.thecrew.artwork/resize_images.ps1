# Batch resize PNG images to reduce file size
# This will resize images to 50% of original size (1020x1024 -> 510x512)

param(
    [string]$SourceDir = "resources\media\modern",
    [int]$Percentage = 50,
    [switch]$Backup = $true
)

Add-Type -AssemblyName System.Drawing

$pngFiles = Get-ChildItem -Path $SourceDir -Filter "*.png" -File
$total = $pngFiles.Count
$processed = 0

Write-Host "Found $total PNG files to resize" -ForegroundColor Cyan
Write-Host "Resizing to $Percentage% of original size`n" -ForegroundColor Yellow

# Create backup directory if requested
if ($Backup) {
    $backupDir = Join-Path $SourceDir "backup_originals"
    if (-not (Test-Path $backupDir)) {
        New-Item -Path $backupDir -ItemType Directory | Out-Null
        Write-Host "Created backup directory: $backupDir`n" -ForegroundColor Green
    }
}

foreach ($file in $pngFiles) {
    $processed++
    Write-Host "[$processed/$total] Processing: $($file.Name)" -NoNewline

    try {
        # Load original image
        $originalImage = [System.Drawing.Image]::FromFile($file.FullName)
        $originalWidth = $originalImage.Width
        $originalHeight = $originalImage.Height

        # Calculate new dimensions
        $newWidth = [int]($originalWidth * ($Percentage / 100))
        $newHeight = [int]($originalHeight * ($Percentage / 100))

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
        Write-Host " -> $($originalWidth)x$($originalHeight) to $($newWidth)x$($newHeight) [$([math]::Round($newSize/1KB, 0)) KB]" -ForegroundColor Green

    } catch {
        Write-Host " -> ERROR: $_" -ForegroundColor Red
    }
}

Write-Host "`n=== Summary ===" -ForegroundColor Cyan
$finalSize = (Get-ChildItem -Path $SourceDir -Filter "*.png" -File | Measure-Object -Property Length -Sum).Sum
Write-Host "Processed: $processed files" -ForegroundColor Green
Write-Host "Total size now: $([math]::Round($finalSize/1MB, 2)) MB" -ForegroundColor Green
if ($Backup) {
    Write-Host "Originals backed up to: $backupDir" -ForegroundColor Yellow
}
