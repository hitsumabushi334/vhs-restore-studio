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

$VenvScripts = Split-Path -Parent $VenvPython
$env:PATH = "$VenvScripts;$env:PATH"
$SourceRoot = Join-Path $ProjectRoot "src"
if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $env:PYTHONPATH = $SourceRoot
} else {
    $env:PYTHONPATH = "$SourceRoot;$env:PYTHONPATH"
}

Write-Host "Running dependency diagnostics with the project venv."
& $VenvPython -m vhs_restore.utils.deps
$DependencyExitCode = $LASTEXITCODE

if ($DependencyExitCode -eq 0) {
    Write-Host "Diagnostics complete. Optional AI/QTGMC components may be absent."
    exit 0
}

Write-Host "Diagnostics found missing required tools."
exit $DependencyExitCode
