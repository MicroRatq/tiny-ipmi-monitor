param(
    [string]$LibreHardwareMonitorVersion = "v0.9.6",
    [string]$AssetName = "LibreHardwareMonitor.zip",
    [string]$OutputDir = "",
    [switch]$KeepTemp
)

$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$libDir = if ([string]::IsNullOrWhiteSpace($OutputDir)) { Join-Path $projectDir "lib" } else { $OutputDir }
$opencodeTempRoot = Join-Path $env:LOCALAPPDATA "Temp\opencode"
$tempRootDir = Join-Path $opencodeTempRoot "hardware-monitor-lib"
$zipPath = Join-Path $tempRootDir $AssetName
$extractDir = Join-Path $tempRootDir "extract"
$downloadUrl = "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/$LibreHardwareMonitorVersion/$AssetName"

$requiredDlls = @(
    "BlackSharp.Core.dll",
    "DiskInfoToolkit.dll",
    "HidSharp.dll",
    "LibreHardwareMonitorLib.dll",
    "Microsoft.Bcl.AsyncInterfaces.dll",
    "Microsoft.Bcl.HashCode.dll",
    "RAMSPDToolkit-NDD.dll",
    "System.Buffers.dll",
    "System.CodeDom.dll",
    "System.Collections.Immutable.dll",
    "System.Formats.Nrbf.dll",
    "System.IO.Pipelines.dll",
    "System.Memory.dll",
    "System.Numerics.Vectors.dll",
    "System.Reflection.Metadata.dll",
    "System.Resources.Extensions.dll",
    "System.Runtime.CompilerServices.Unsafe.dll",
    "System.Security.AccessControl.dll",
    "System.Security.Principal.Windows.dll",
    "System.Text.Encodings.Web.dll",
    "System.Text.Json.dll",
    "System.Threading.AccessControl.dll",
    "System.Threading.Tasks.Extensions.dll"
)

if (-not $KeepTemp -and (Test-Path -LiteralPath $tempRootDir)) {
    Remove-Item -LiteralPath $tempRootDir -Recurse -Force
}

if (-not (Test-Path -LiteralPath $tempRootDir)) {
    New-Item -ItemType Directory -Path $tempRootDir | Out-Null
}
if (Test-Path -LiteralPath $extractDir) {
    Remove-Item -LiteralPath $extractDir -Recurse -Force
}
New-Item -ItemType Directory -Path $extractDir | Out-Null

Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath
Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force

if (Test-Path -LiteralPath $libDir) {
    Remove-Item -LiteralPath $libDir -Recurse -Force
}

New-Item -ItemType Directory -Path $libDir | Out-Null

$copied = @()
foreach ($dllName in $requiredDlls) {
    $match = Get-ChildItem -LiteralPath $extractDir -Recurse -Filter $dllName -File | Select-Object -First 1
    if ($null -eq $match) {
        throw "Required DLL was not found in extracted LibreHardwareMonitor asset: $dllName"
    }
    Copy-Item -LiteralPath $match.FullName -Destination (Join-Path $libDir $dllName) -Force
    $copied += $dllName
}

"Restored {0} DLLs into {1}" -f $copied.Count, $libDir

if (-not $KeepTemp -and (Test-Path -LiteralPath $tempRootDir)) {
    Remove-Item -LiteralPath $tempRootDir -Recurse -Force
}
