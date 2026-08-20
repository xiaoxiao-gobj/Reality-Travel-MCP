$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Reality Travel virtual environment is missing. Run setup-reality-travel.ps1 first.'
}
Set-Location -LiteralPath $Root
& $Python -m reality_travel.server
