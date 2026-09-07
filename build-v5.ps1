param([switch]$SkipTests, [switch]$Archive)
$ErrorActionPreference = 'Stop'
$pmRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pmPython = Join-Path $pmRoot '.venv/Scripts/python.exe'
$pmBuild = Join-Path $pmRoot 'build/v5-package'
$pmName = 'PriceMonitor-v5.0.19-windows-x64-portable'
$pmPortable = Join-Path (Join-Path $pmRoot 'dist') $pmName
Push-Location $pmRoot
try {
    $env:PYTHONPATH = Join-Path $pmRoot 'src'
    if (-not $SkipTests) {
        $pmTestTemp = Join-Path $pmBuild 'pytest'
        New-Item -ItemType Directory -Path $pmTestTemp -Force | Out-Null
        & $pmPython -m pytest -q -p no:cacheprovider --basetemp $pmTestTemp
        if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
    }
    & $pmPython -m PyInstaller --noconfirm --clean --onedir --windowed --noupx --name PriceMonitor `
        --paths (Join-Path $pmRoot 'src') `
        --add-data ((Join-Path $pmRoot 'src/price_monitor_v5/static') + ';price_monitor_v5/static') `
        --version-file (Join-Path $pmRoot 'packaging/version_info_v5.txt') `
        --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto `
        --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto `
        --hidden-import uvicorn.lifespan.on --distpath (Join-Path $pmBuild 'dist') `
        --workpath (Join-Path $pmBuild 'work') --specpath $pmBuild (Join-Path $pmRoot 'launcher_v5_entry.py')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
    New-Item -ItemType Directory -Path $pmPortable -Force | Out-Null
    # Update only v5 program assets. Keep v4 and the independent v5 catalog intact.
    foreach ($pmAsset in @('PriceMonitor.exe','_internal','edge-extension')) {
        $pmTarget = [IO.Path]::GetFullPath((Join-Path $pmPortable $pmAsset))
        if (-not $pmTarget.StartsWith([IO.Path]::GetFullPath($pmPortable) + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe asset path' }
        if (Test-Path -LiteralPath $pmTarget) { Remove-Item -LiteralPath $pmTarget -Recurse -Force }
    }
    Get-ChildItem -LiteralPath (Join-Path $pmBuild 'dist/PriceMonitor') -Force | Copy-Item -Destination $pmPortable -Recurse -Force
    Copy-Item -LiteralPath (Join-Path $pmRoot 'README-v5-RU.md') -Destination (Join-Path $pmPortable 'README-RU.md') -Force
    Copy-Item -LiteralPath (Join-Path $pmRoot 'packaging/v5.env.example') -Destination (Join-Path $pmPortable '.env.example') -Force
    Copy-Item -LiteralPath (Join-Path $pmRoot 'edge-extension-v5') -Destination (Join-Path $pmPortable 'edge-extension') -Recurse -Force
    if ($Archive) {
        # Never include the user's catalog, history or settings in a shareable ZIP.
        $pmStage = Join-Path $pmBuild ('share-' + [guid]::NewGuid().ToString('N'))
        $pmStagePortable = Join-Path $pmStage $pmName
        New-Item -ItemType Directory -Path $pmStagePortable -Force | Out-Null
        Get-ChildItem -LiteralPath $pmPortable -Force | Where-Object { $_.Name -notin @('var','.env') } | Copy-Item -Destination $pmStagePortable -Recurse
        $pmZip = Join-Path (Join-Path $pmRoot 'dist') ($pmName + '.zip')
        Compress-Archive -LiteralPath $pmStagePortable -DestinationPath $pmZip -Force
        Get-FileHash -LiteralPath $pmZip -Algorithm SHA256
    }
    Write-Output (Join-Path $pmPortable 'PriceMonitor.exe')
} finally { Pop-Location }
