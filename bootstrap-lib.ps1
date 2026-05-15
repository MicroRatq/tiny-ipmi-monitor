param(
    [string]$LibreHardwareMonitorVersion = "v0.9.6",
    [string]$AssetName = "LibreHardwareMonitor.NET.10.zip"
)

$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$libDir = Join-Path $projectDir "lib"
$opencodeTempRoot = Join-Path $env:LOCALAPPDATA "Temp\opencode"
$tempRootDir = Join-Path $opencodeTempRoot "hardware-monitor-lib"
$zipPath = Join-Path $tempRootDir $AssetName
$extractDir = Join-Path $tempRootDir "extract"
$downloadUrl = "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/$LibreHardwareMonitorVersion/$AssetName"

if (Test-Path -LiteralPath $tempRootDir) {
    Remove-Item -LiteralPath $tempRootDir -Recurse -Force
}

New-Item -ItemType Directory -Path $tempRootDir | Out-Null
New-Item -ItemType Directory -Path $extractDir | Out-Null

Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath
Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force

if (Test-Path -LiteralPath $libDir) {
    Remove-Item -LiteralPath $libDir -Recurse -Force
}

New-Item -ItemType Directory -Path $libDir | Out-Null

$rootDlls = @(Get-ChildItem -LiteralPath $extractDir -Filter *.dll -File)
if ($rootDlls.Count -gt 0) {
    Copy-Item -LiteralPath $rootDlls.FullName -Destination $libDir -Force
} else {
    $allDlls = @(Get-ChildItem -LiteralPath $extractDir -Recurse -Filter *.dll -File)
    if ($allDlls.Count -eq 0) {
        throw "No DLL files were found in extracted LibreHardwareMonitor asset"
    }
    Copy-Item -LiteralPath $allDlls.FullName -Destination $libDir -Force
}

if (Test-Path -LiteralPath $tempRootDir) {
    Remove-Item -LiteralPath $tempRootDir -Recurse -Force
}
