param(
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$shimDir = Join-Path $projectDir "shim"
$libDir = Join-Path $projectDir "lib"
$shimProject = Join-Path $shimDir "HardwareMonitorShim.csproj"
$opencodeTempRoot = Join-Path $env:LOCALAPPDATA "Temp\opencode"
$tempRootDir = Join-Path $opencodeTempRoot "hardware-monitor-shim"
$tempOutputDir = Join-Path $tempRootDir "publish"

Test-Path -LiteralPath $shimProject | Out-Null
Test-Path -LiteralPath $libDir | Out-Null

if (Test-Path -LiteralPath $tempRootDir) {
    Remove-Item -LiteralPath $tempRootDir -Recurse -Force
}

New-Item -ItemType Directory -Path $tempRootDir | Out-Null
New-Item -ItemType Directory -Path $tempOutputDir | Out-Null

& "dotnet" build $shimProject -c $Configuration -o $tempOutputDir
if (-not $?) {
    exit 1
}

$builtDll = Join-Path $tempOutputDir "HardwareMonitorShim.dll"
$builtPdb = Join-Path $tempOutputDir "HardwareMonitorShim.pdb"

if (-not (Test-Path -LiteralPath $builtDll)) {
    throw "Build succeeded but HardwareMonitorShim.dll was not found in $tempOutputDir"
}

Copy-Item -LiteralPath $builtDll -Destination (Join-Path $libDir "HardwareMonitorShim.dll") -Force

if (Test-Path -LiteralPath $builtPdb) {
    Copy-Item -LiteralPath $builtPdb -Destination (Join-Path $libDir "HardwareMonitorShim.pdb") -Force
}

if (Test-Path -LiteralPath $tempRootDir) {
    Remove-Item -LiteralPath $tempRootDir -Recurse -Force
}
