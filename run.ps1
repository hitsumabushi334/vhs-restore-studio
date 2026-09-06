[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot ".")).Path
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "Virtual environment not found. Run .\setup.ps1 first."
}

$VenvScripts = Split-Path -Parent $VenvPython
$VendorRoots = @(
    (Join-Path $ProjectRoot "vendor\video2x"),
    (Join-Path $ProjectRoot "vendor\realesrgan-ncnn-vulkan"),
    (Join-Path $ProjectRoot "vendor\vapoursynth")
)
$env:PATH = (@($VenvScripts) + $VendorRoots + @($env:PATH)) -join ";"

& $VenvPython -m vhs_restore @Arguments
exit $LASTEXITCODE
