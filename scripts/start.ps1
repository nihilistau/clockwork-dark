# The Clockwork Dark — bootstrap + verify script (Windows)
#
# Creates the venv if it is missing, installs requirements under
# constraints.txt (the versions the suite was proven green on), and gates on
# the test suite. It does NOT start the game: six stories ship, and picking
# one is the player's call — the "next steps" below are the accurate ways in.
#
# scripts/start.sh is the POSIX twin, line for line. Their "Next steps" blocks
# list the same commands, modulo the interpreter path, and
# tests/test_start_scripts.py holds them to it: change one, change both.
#
# Version: v0.20.0 [2026-09-30]

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "Creating venv..."
    python -m venv .venv
}

& $VenvPython -m pip install -q -r requirements.txt -c constraints.txt
Write-Host "Running tests..."
& $VenvPython -m pytest tests/ -q --tb=short
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# The configured model server, read from the config the engine itself reads
# (config/default.yaml under config/local.yaml), never written here.
$ModelServer = & $VenvPython -c 'from engine.config import get_config; c = get_config(); print(c.get(''llm.provider''), ''expected at'', c.get(''llm.base_url''))'
if ($LASTEXITCODE -ne 0 -or -not $ModelServer) { $ModelServer = "(could not read llm.provider from the config)" }

Write-Host ""
Write-Host "All green. Next steps:"
Write-Host ""
Write-Host "  Check the environment:   .\.venv\Scripts\python.exe scripts\doctor.py"
Write-Host "  Check local services:    .\.venv\Scripts\python.exe launcher.py --check"
Write-Host "                           (model server: $ModelServer)"
Write-Host "  Seed lore (first run):   .\.venv\Scripts\python.exe scripts\seed_lore.py"
Write-Host ""
Write-Host "  List installed games:    .\.venv\Scripts\python.exe launcher.py --list-games"
Write-Host "  Play the flagship:       .\.venv\Scripts\python.exe launcher.py --game clockwork-dark"
Write-Host "  Play another story:      .\.venv\Scripts\python.exe launcher.py --game hue-and-cry"
Write-Host "  With managed services:   .\.venv\Scripts\python.exe launcher.py --game <slug> --stack"
Write-Host ""
Write-Host "  The launcher prints its URL on start. The port comes from"
Write-Host "  scene.<name>.port in config/default.yaml (5573 by default);"
Write-Host "  override per run with --port."
