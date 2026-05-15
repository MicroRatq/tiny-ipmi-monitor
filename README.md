# Tiny-IPMI-Monitor

A Windows hardware telemetry bridge for ESP32-based companion firmware that exposes a vendor-defined USB HID telemetry interface. The host application collects local sensor data through LibreHardwareMonitor and forwards it to the device.

## Requirements

- Windows
- A conda environment with Python available
- .NET SDK for rebuilding the shim
- A target device or firmware that exposes a compatible HID telemetry interface

## Project Layout

- `monitor.py`: command-line telemetry bridge
- `tray_app.py`: tray-mode Windows entry point
- `monitor_config.json`: runtime device matching and interval configuration
- `shim/`: C# source for the LibreHardwareMonitor helper shim
- `tray_app.spec`: PyInstaller spec for the packaged tray executable

## Quick Start

1. Install Python dependencies.

   `conda run -n <env-name> python -m pip install -r requirements.txt pyinstaller`

2. Build the C# shim.

   `./build-shim.ps1`

3. Restore the LibreHardwareMonitor runtime DLLs if `lib/` is empty.

   `./bootstrap-lib.ps1`

4. Start the command-line bridge.

   `conda run -n <env-name> python monitor.py --config monitor_config.json`

5. Or start the tray application.

   `conda run -n <env-name> python tray_app.py`

## Configuration

- `monitor_config.json` defines the HID match rules and reporting interval.
- Adjust the configuration if your firmware uses different HID identifiers or interface values.
- The bridge probes compatible HID write formats automatically on Windows.

## CLI Modes

- `--dump-devices`: print visible HID devices and exit
- `--dump-snapshot`: collect one telemetry snapshot and print it as JSON
- `--dump-sensors`: print all discovered LibreHardwareMonitor sensors as JSON

## Examples

- `conda run -n <env-name> python monitor.py --config monitor_config.json --dump-devices`
- `conda run -n <env-name> python monitor.py --config monitor_config.json --dump-snapshot`
- `conda run -n <env-name> python monitor.py --config monitor_config.json --dump-sensors`
- `conda run -n <env-name> python monitor.py --config monitor_config.json`
- `conda run -n <env-name> python tray_app.py`

## Permissions

- Many GPU and memory fields are available without elevation.
- For more reliable CPU temperature, CPU power, motherboard, and fan readings, run elevated.
- The packaged tray executable relaunches itself with `runas` when elevation is required.

## Tray Application

- Runs without a console window
- Writes logs to `monitor.log` beside the executable
- Provides `Open at login` and `Exit` in the tray menu
- Uses a scheduled task for Windows login autostart

## Build

- Build the shim into `lib/`:

  `./build-shim.ps1`

- Restore the external LibreHardwareMonitor runtime DLLs into `lib/`:

  `./bootstrap-lib.ps1`

- Build the final tray package into `build/tiny-ipmi-monitor/`:

  `./build-tray-exe.ps1`

- If needed, force a specific conda environment for packaging:

  `./build-tray-exe.ps1 -CondaEnvName <env-name>`

## Output

- Final packaged output is written to `build/tiny-ipmi-monitor/`.
- The package contains the tray executable, runtime configuration, icon assets, and required external DLLs.

## Release Automation

- GitHub Actions builds tagged releases on Windows.
- Release assets include a packaged application ZIP and a standalone `HardwareMonitorShim.dll`.
