# The Clockwork Dark — bootstrap + verify script (Windows)
#
# Creates the venv if it is missing, installs requirements, and gates on the
# test suite. It does NOT start the game: two stories ship, and picking one is
# the player's call — the "next steps" below are the accurate ways in.
#
# Version: v0.2.0 [2026-08-13]

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
& $VenvPython -m pytest tests/ -q --tb=short
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "All green. Next steps:"
Write-Host ""
Write-Host "  Check the environment:   python scripts\doctor.py"
Write-Host "  Check local services:    python launcher.py --check"
Write-Host "                           (LM Studio expected at http://localhost:1234/v1)"
Write-Host "  Seed lore (first run):   python scripts\seed_lore.py"
Write-Host ""
Write-Host "  List installed games:    python launcher.py --list-games"
Write-Host "  Play the flagship:       python launcher.py --game clockwork-dark"
Write-Host "  Play the second story:   python launcher.py --game wicked-garden"
Write-Host "  With managed services:   python launcher.py --game <slug> --stack"
Write-Host ""
Write-Host "  The launcher prints its URL on start. The port comes from"
Write-Host "  scene.<name>.port in config/default.yaml (5573 by default);"
Write-Host "  override per run with --port."
