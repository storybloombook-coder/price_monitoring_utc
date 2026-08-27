param(
    [switch]$SkipTests,
    [switch]$Archive
)

$ErrorActionPreference = 'Stop'

$pmRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pmPython = Join-Path $pmRoot '.venv\Scripts\python.exe'
$pmBuildRoot = Join-Path $pmRoot 'build\v4'
$pmPyInstallerDist = Join-Path $pmBuildRoot 'dist'
$pmPyInstallerWork = Join-Path $pmBuildRoot 'work'
$pmPortableName = 'PriceMonitor-v4.0.0-windows-x64-portable'
$pmPortableRoot = Join-Path (Join-Path $pmRoot 'dist') $pmPortableName
$pmArchive = Join-Path (Join-Path $pmRoot 'dist') ($pmPortableName + '.zip')

if (-not (Test-Path -LiteralPath $pmPython)) {
    throw 'Missing .venv. Install requirements-dev.txt first.'
}
if (-not (Test-Path -LiteralPath (Join-Path $pmRoot 'PriceMonitor.exe'))) {
    throw 'The supplied v3 PriceMonitor.exe is required as the temporary marketplace engine.'
}
if (-not (Test-Path -LiteralPath (Join-Path $pmRoot '_internal'))) {
    throw 'The supplied v3 _internal directory is required.'
}

Push-Location $pmRoot
try {
    if (-not $SkipTests) {
        $env:PYTHONPATH = Join-Path $pmRoot 'src'
        & $pmPython -m pytest -q --basetemp (Join-Path $pmBuildRoot 'pytest-temp') -p no:cacheprovider
        if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    }

    $pmCleanupTargets = @($pmBuildRoot)
    if ($Archive) { $pmCleanupTargets += $pmArchive }
    foreach ($pmTarget in $pmCleanupTargets) {
        if (Test-Path -LiteralPath $pmTarget) {
            $pmResolvedTarget = [IO.Path]::GetFullPath($pmTarget)
            $pmResolvedRoot = [IO.Path]::GetFullPath($pmRoot)
            if (-not $pmResolvedTarget.StartsWith($pmResolvedRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Unsafe build cleanup target: $pmResolvedTarget"
            }
            Remove-Item -LiteralPath $pmResolvedTarget -Recurse -Force
        }
    }

    New-Item -ItemType Directory -Path $pmBuildRoot, $pmPyInstallerDist, $pmPyInstallerWork | Out-Null
    & $pmPython -m PyInstaller `
        --noconfirm `
        --clean `
        --onedir `
        --windowed `
        --noupx `
        --name PriceMonitor `
        --paths (Join-Path $pmRoot 'src') `
        --add-data ((Join-Path $pmRoot 'src\price_monitor_v4\static') + ';price_monitor_v4\static') `
        --version-file (Join-Path $pmRoot 'packaging\version_info.txt') `
        --hidden-import uvicorn.logging `
        --hidden-import uvicorn.loops.auto `
        --hidden-import uvicorn.protocols.http.auto `
        --hidden-import uvicorn.protocols.websockets.auto `
        --hidden-import uvicorn.lifespan.on `
        --distpath $pmPyInstallerDist `
        --workpath $pmPyInstallerWork `
        --specpath $pmBuildRoot `
        (Join-Path $pmRoot 'launcher_entry.py')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }

    New-Item -ItemType Directory -Path $pmPortableRoot -Force | Out-Null
    foreach ($pmBuildAsset in @('PriceMonitor.exe', '_internal', 'legacy', 'README.md', '.env.example')) {
        $pmAssetPath = Join-Path $pmPortableRoot $pmBuildAsset
        if (Test-Path -LiteralPath $pmAssetPath) {
            Remove-Item -LiteralPath $pmAssetPath -Recurse -Force
        }
    }

    Get-ChildItem -LiteralPath (Join-Path $pmPyInstallerDist 'PriceMonitor') -Force |
        Copy-Item -Destination $pmPortableRoot -Recurse -Force
    $pmLegacyRoot = Join-Path $pmPortableRoot 'legacy'
    New-Item -ItemType Directory -Path $pmLegacyRoot | Out-Null
    Copy-Item -LiteralPath (Join-Path $pmRoot 'PriceMonitor.exe') -Destination (Join-Path $pmLegacyRoot 'PriceMonitor-v3.exe')
    Copy-Item -LiteralPath (Join-Path $pmRoot '_internal') -Destination (Join-Path $pmLegacyRoot '_internal') -Recurse
    Copy-Item -LiteralPath (Join-Path $pmRoot 'README.md') -Destination $pmPortableRoot
    Copy-Item -LiteralPath (Join-Path $pmRoot '.env.example') -Destination $pmPortableRoot

    $pmResult = [ordered]@{
        Executable = Join-Path $pmPortableRoot 'PriceMonitor.exe'
        PortableFolder = $pmPortableRoot
    }
    if ($Archive) {
        Compress-Archive -LiteralPath $pmPortableRoot -DestinationPath $pmArchive -CompressionLevel Optimal
        $pmHash = Get-FileHash -LiteralPath $pmArchive -Algorithm SHA256
        $pmResult.Archive = $pmArchive
        $pmResult.ArchiveSizeMB = [math]::Round((Get-Item -LiteralPath $pmArchive).Length / 1MB, 2)
        $pmResult.ArchiveSHA256 = $pmHash.Hash
    }
    [PSCustomObject]$pmResult | Format-List
} finally {
    Pop-Location
}
