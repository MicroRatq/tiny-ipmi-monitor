param(
    [string]$CondaEnvName = $env:CONDA_DEFAULT_ENV
)

$ErrorActionPreference = "Stop"

$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$buildRootDir = Join-Path $projectDir "build"
$finalOutputDir = Join-Path $buildRootDir "tiny-ipmi-monitor"
$finalLibDir = Join-Path $finalOutputDir "lib"
$finalAssetsDir = Join-Path $finalOutputDir "assets"
$legacyDistDir = Join-Path $projectDir "dist"
$opencodeTempRoot = Join-Path $env:LOCALAPPDATA "Temp\opencode"
$tempRootDir = Join-Path $opencodeTempRoot "hardware-monitor-package"
$tempDistDir = Join-Path $tempRootDir "dist"
$tempWorkDir = Join-Path $tempRootDir "work"
$stagingDir = Join-Path $tempRootDir "tiny-ipmi-monitor.staging"
$stagingLibDir = Join-Path $stagingDir "lib"
$stagingAssetsDir = Join-Path $stagingDir "assets"

Test-Path -LiteralPath $projectDir | Out-Null

if (Test-Path -LiteralPath $tempRootDir) {
    Remove-Item -LiteralPath $tempRootDir -Recurse -Force
}

New-Item -ItemType Directory -Path $tempRootDir | Out-Null
New-Item -ItemType Directory -Path $tempDistDir | Out-Null
New-Item -ItemType Directory -Path $tempWorkDir | Out-Null

$pythonLauncher = "python"
$pythonArgs = @("-m", "PyInstaller", (Join-Path $projectDir "tray_app.spec"), "--noconfirm", "--clean", "--distpath", $tempDistDir, "--workpath", $tempWorkDir)
$condaCommand = Get-Command "conda" -ErrorAction SilentlyContinue

if ($CondaEnvName -and $null -ne $condaCommand) {
    & "conda" run -n $CondaEnvName $pythonLauncher @pythonArgs
} else {
    & $pythonLauncher @pythonArgs
}

if (-not $?) {
    exit 1
}

if (Test-Path -LiteralPath $stagingDir) {
    Remove-Item -LiteralPath $stagingDir -Recurse -Force
}

New-Item -ItemType Directory -Path $stagingDir | Out-Null
New-Item -ItemType Directory -Path $stagingLibDir | Out-Null
New-Item -ItemType Directory -Path $stagingAssetsDir | Out-Null

Copy-Item -LiteralPath (Join-Path $tempDistDir "tiny-ipmi-monitor.exe") -Destination (Join-Path $stagingDir "tiny-ipmi-monitor.exe")
Copy-Item -LiteralPath (Join-Path $projectDir "monitor_config.json") -Destination (Join-Path $stagingDir "monitor_config.json")
Copy-Item -Path (Join-Path $projectDir "lib\*.dll") -Destination $stagingLibDir
Copy-Item -LiteralPath (Join-Path $projectDir "assets\device-analytics.png") -Destination (Join-Path $stagingAssetsDir "device-analytics.png")
Copy-Item -LiteralPath (Join-Path $projectDir "assets\device-analytics.ico") -Destination (Join-Path $stagingAssetsDir "device-analytics.ico")

if (Test-Path -LiteralPath $finalOutputDir) {
    Remove-Item -LiteralPath $finalOutputDir -Recurse -Force
}

if (-not (Test-Path -LiteralPath $buildRootDir)) {
    New-Item -ItemType Directory -Path $buildRootDir | Out-Null
}

$finalBackupDir = Join-Path $buildRootDir "tiny-ipmi-monitor.backup"
if (Test-Path -LiteralPath $finalBackupDir) {
    Remove-Item -LiteralPath $finalBackupDir -Recurse -Force
}

if (Test-Path -LiteralPath $finalOutputDir) {
    Move-Item -LiteralPath $finalOutputDir -Destination $finalBackupDir
}

try {
    Move-Item -LiteralPath $stagingDir -Destination $finalOutputDir
    if (Test-Path -LiteralPath $finalBackupDir) {
        Remove-Item -LiteralPath $finalBackupDir -Recurse -Force
    }
} catch {
    Write-Warning "Could not replace existing build output, likely because files are in use. New package is available at: $stagingDir"
    throw
}

if (Test-Path -LiteralPath $legacyDistDir) {
    Remove-Item -LiteralPath $legacyDistDir -Recurse -Force
}

$legacyBuildWorkDir = Join-Path $buildRootDir "tray_app"
if (Test-Path -LiteralPath $legacyBuildWorkDir) {
    Remove-Item -LiteralPath $legacyBuildWorkDir -Recurse -Force
}

$legacyBuildSpecFile = Join-Path $buildRootDir "tray_app.spec"
if (Test-Path -LiteralPath $legacyBuildSpecFile) {
    Remove-Item -LiteralPath $legacyBuildSpecFile -Force
}

if (Test-Path -LiteralPath $tempRootDir) {
    Remove-Item -LiteralPath $tempRootDir -Recurse -Force
}
