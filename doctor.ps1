[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

function Test-Tool {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [bool]$Required
    )

    $Command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -ne $Command) {
        Write-Host "[OK]      $Name  $($Command.Source)"
        return $true
    }

    if ($Required) {
        Write-Host "[MISSING] $Name  required"
    } else {
        Write-Host "[OPTIONAL] $Name  unavailable (fallback will be used)"
    }
    return (-not $Required)
}

$Ok = $true
$Ok = (Test-Tool -Name "python" -Required $true) -and $Ok
$Ok = (Test-Tool -Name "ffmpeg" -Required $true) -and $Ok
$Ok = (Test-Tool -Name "ffprobe" -Required $true) -and $Ok
$Ok = (Test-Tool -Name "vspipe" -Required $false) -and $Ok
$Ok = (Test-Tool -Name "video2x" -Required $false) -and $Ok
$Ok = (Test-Tool -Name "realesrgan-ncnn-vulkan" -Required $false) -and $Ok

if ($Ok) {
    Write-Host "Diagnostics complete. Optional AI/QTGMC components may be absent."
    exit 0
}

Write-Host "Diagnostics found missing required tools."
exit 1
