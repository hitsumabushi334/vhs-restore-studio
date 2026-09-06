[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot ".")).Path
$VenvPath = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"

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

function Ensure-ProjectVenv {
    if (Test-Path -LiteralPath $VenvPython) {
        return
    }

    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($null -ne $PyLauncher) {
        & $PyLauncher.Source -3.12 -m venv $VenvPath
        if ($LASTEXITCODE -ne 0) {
            throw "Python 3.12 venv creation failed."
        }
        return
    }

    $Python = Get-Command python -ErrorAction SilentlyContinue
    if ($null -eq $Python) {
        throw "Python 3.12 or newer is required. Run .\setup.ps1 first."
    }

    Assert-PythonVersion -PythonPath $Python.Source
    & $Python.Source -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Python venv creation failed."
    }
}

try {
    Ensure-ProjectVenv
} catch {
    Write-Host "[FAIL]    $($_.Exception.Message)"
    exit 1
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "[FAIL]    Virtual environment Python executable was not created: $VenvPython"
    Write-Host "Run .\setup.ps1 first."
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

Write-Host "Installing optional vendor backends (best effort)."
& $VenvPython -m vhs_restore.utils.bootstrap
if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARN]    Optional backend bootstrap reported a non-zero exit code; continuing."
}

exit 0
