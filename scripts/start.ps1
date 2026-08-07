# The Clockwork Dark — start script (Windows)
# Version: v0.1.0 [2026-06-20]

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating venv..."
    python -m venv .venv
}

& $VenvPython -m pip install -q -r requirements.txt
Write-Host "Running tests..."
& $VenvPython -m pytest tests/ -v --tb=short
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "Seed lore (first run): python scripts/seed_lore.py"
Write-Host "LM Studio expected at http://localhost:1234/v1"
Write-Host "Launch game: python launcher.py clockwork"
Write-Host "Open: http://localhost:5573"