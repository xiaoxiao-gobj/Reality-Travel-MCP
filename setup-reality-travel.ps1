$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root '.venv'
if (-not (Test-Path -LiteralPath $Venv)) {
    $RegisteredPython = py -0p | Select-String '3\.11' | Select-Object -First 1
    if (-not $RegisteredPython) {
        throw 'Python 3.11 is required but was not found by the Python launcher.'
    }
    $PythonPath = ($RegisteredPython.Line -replace '^\s*-V:[^\s]+\s+', '').Trim()
    & $PythonPath -m venv $Venv
}
$Python = Join-Path $Venv 'Scripts\python.exe'
& $Python -m pip install --upgrade pip
& $Python -m pip install -e "$Root[dev]"
Write-Host "Reality Travel is ready. Start with: $Root\start-reality-travel.ps1"
