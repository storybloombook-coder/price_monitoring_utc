param(
    [switch]$Test,
    [switch]$NoBrowser
)

$pmRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pmPython = Join-Path $pmRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pmPython)) {
    throw 'Run: <workspace Python> -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt'
}

Push-Location $pmRoot
try {
    $env:PYTHONPATH = Join-Path $pmRoot 'src'
    if ($Test) {
        & $pmPython -m pytest -q
    } else {
        if ($NoBrowser) { $env:OPEN_BROWSER = 'false' }
        & $pmPython -m price_monitor_v4.launcher
    }
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
