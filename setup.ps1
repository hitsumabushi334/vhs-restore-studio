[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot ".")).Path
$VenvPath = Join-Path $ProjectRoot ".venv"

$PyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($null -ne $PyLauncher) {
    if (-not (Test-Path -LiteralPath $VenvPath)) {
        & $PyLauncher.Source -3.12 -m venv $VenvPath
        if ($LASTEXITCODE -ne 0) {
            throw "Python 3.12 venv creation failed."
        }
    }
} else {
    $Python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $Python) {
        throw "Python 3.12 or newer is required."
    }
    if (-not (Test-Path -LiteralPath $VenvPath)) {
        & $Python.Source -m venv $VenvPath
        if ($LASTEXITCODE -ne 0) {
            throw "Python venv creation failed."
        }
    }
}

$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "The virtual environment Python executable was not created: $VenvPython"
}

& $VenvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "pip upgrade failed."
}

& $VenvPython -m pip install --editable "$ProjectRoot[dev]"
if ($LASTEXITCODE -ne 0) {
    throw "Editable package installation failed."
}

Write-Host "VHS Restore Studio environment ready: $VenvPath"
