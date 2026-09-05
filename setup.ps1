[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot ".")).Path
$VenvPath = Join-Path $ProjectRoot ".venv"

function Assert-PythonVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PythonPath
    )

    $VersionText = & $PythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to determine the fallback Python version."
    }

    try {
        $PythonVersion = [version]::Parse($VersionText.Trim())
    } catch {
        throw "Unable to parse the fallback Python version: $VersionText"
    }

    if (($PythonVersion.Major -lt 3) -or (($PythonVersion.Major -eq 3) -and ($PythonVersion.Minor -lt 12))) {
        throw "Python 3.12 or newer is required; found $PythonVersion."
    }
}

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
    Assert-PythonVersion -PythonPath $Python.Source
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

$VenvScripts = Split-Path -Parent $VenvPython
$env:PATH = "$VenvScripts;$env:PATH"
$SourceRoot = Join-Path $ProjectRoot "src"
if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $env:PYTHONPATH = $SourceRoot
} else {
    $env:PYTHONPATH = "$SourceRoot;$env:PYTHONPATH"
}

Write-Host "Running dependency diagnostics."
& $VenvPython -m vhs_restore.utils.deps
if ($LASTEXITCODE -ne 0) {
    throw "Required local dependencies are missing; run .\doctor.ps1 for details."
}

Write-Host "VHS Restore Studio environment ready: $VenvPath"
