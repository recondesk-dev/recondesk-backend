# Build ReconDeskTallyBridge.exe (Windows one-file) with PyInstaller.
# Run from this directory on Windows (or via GitHub Actions windows-latest):
#   powershell -ExecutionPolicy Bypass -File .\build.ps1

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "Installing build requirements..."
python -m pip install --upgrade pip
python -m pip install -r requirements-build.txt

Write-Host "Running PyInstaller..."
python -m PyInstaller --clean --noconfirm ReconDeskTallyBridge.spec

$exe = Join-Path $PSScriptRoot "dist\ReconDeskTallyBridge.exe"
if (-not (Test-Path $exe)) {
    throw "Build failed: $exe not found"
}

$sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 2)
Write-Host "OK: $exe ($sizeMb MB)"
Write-Host "Place tally_bridge.config.json next to the .exe before running."
