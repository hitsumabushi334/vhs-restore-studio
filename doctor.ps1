[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot ".")).Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Test-VenvPython {
    if (Test-Path -LiteralPath $VenvPython) {
        Write-Host "[OK]      python (venv)  $VenvPython"
        return $true
    }

    Write-Host "[MISSING] python (venv)  required; run .\setup.ps1 first"
    return $false
}

if (-not (Test-VenvPython)) {
    exit 1
}

$VendorRoots = @(
    (Join-Path $ProjectRoot "vendor\video2x"),
    (Join-Path $ProjectRoot "vendor\realesrgan-ncnn-vulkan"),
    (Join-Path $ProjectRoot "vendor\vapoursynth")
)

$VenvScripts = Split-Path -Parent $VenvPython
$SourceRoot = Join-Path $ProjectRoot "src"
if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $env:PYTHONPATH = $SourceRoot
} else {
    $env:PYTHONPATH = "$SourceRoot;$env:PYTHONPATH"
}

$env:PATH = (@($VenvScripts) + $VendorRoots + @($env:PATH)) -join ";"
& $VenvPython -m vhs_restore.utils.deps
$DependencyExitCode = $LASTEXITCODE

if ($DependencyExitCode -eq 0) {
    Write-Host "Diagnostics complete. Optional AI/QTGMC components may be absent."
    exit 0
}

Write-Host "Diagnostics found missing required tools."
exit $DependencyExitCode
