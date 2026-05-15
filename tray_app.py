import logging
import os
import subprocess
import sys
import ctypes
from pathlib import Path
from typing import Optional

import pystray
from PIL import Image

from monitor import (
    MonitorService,
    get_base_dir,
    get_default_config_path,
    get_default_log_path,
    is_running_as_admin,
    load_runtime_config,
    setup_logging,
)


TASK_NAME = "Tiny IPMI Hardware Monitor"
SW_HIDE = 0
PROCESS_PER_MONITOR_DPI_AWARE = 2
PROCESS_SYSTEM_DPI_AWARE = 1


def get_executable_path() -> Path:
    return Path(sys.executable).resolve()


def get_working_directory() -> Path:
    return get_base_dir()


def get_launch_target() -> tuple[str, Optional[str]]:
    if getattr(sys, "frozen", False):
        return str(get_executable_path()), None
    return str(get_executable_path()), str((get_base_dir() / "tray_app.py").resolve())


def get_icon_path() -> Path:
    external_icon_path = get_base_dir() / "assets" / "device-analytics.png"
    if external_icon_path.exists():
        return external_icon_path
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")) / "assets" / "device-analytics.png"
    return external_icon_path


def build_launch_command() -> tuple[str, str]:
    executable_path, argument_path = get_launch_target()
    if argument_path is None:
        return executable_path, ""
    return executable_path, f'"{argument_path}"'


def get_subprocess_startupinfo() -> subprocess.STARTUPINFO:
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = SW_HIDE
    return startupinfo


def run_hidden_powershell(command: str, check: bool) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", command],
        check=check,
        capture_output=True,
        text=True,
        startupinfo=get_subprocess_startupinfo(),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def relaunch_as_admin() -> bool:
    executable, parameters = build_launch_command()
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", executable, parameters or None, str(get_working_directory()), SW_HIDE)
    return int(result) > 32


def enable_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)
        return
    except Exception:
        pass

    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def quote_task_argument(value: str) -> str:
    return value.replace("'", "''")


def get_current_user_id() -> str:
    username = os.environ.get("USERNAME", "")
    userdomain = os.environ.get("USERDOMAIN", "")
    if userdomain and username:
        return f"{userdomain}\\{username}"
    if username:
        return username
    raise RuntimeError("Unable to determine current Windows user")


def is_autostart_enabled() -> bool:
    command = (
        "$task = Get-ScheduledTask -TaskName '"
        + quote_task_argument(TASK_NAME)
        + "' -ErrorAction SilentlyContinue; "
        + "if ($null -eq $task) { exit 1 }; "
        + "if ($task.State -eq 'Disabled') { exit 2 }; "
        + "exit 0"
    )
    result = run_hidden_powershell(command, check=False)
    return result.returncode == 0


def enable_autostart() -> None:
    executable_path, argument_path = get_launch_target()
    if getattr(sys, "frozen", False):
        launch_executable = executable_path
        launch_arguments = argument_path
    else:
        launch_executable = str(Path(sys.base_prefix) / "pythonw.exe")
        launch_arguments = argument_path

    executable = quote_task_argument(launch_executable)
    working_directory = quote_task_argument(str(get_working_directory()))
    task_name = quote_task_argument(TASK_NAME)
    user_id = quote_task_argument(get_current_user_id())
    command = (
        "$action = New-ScheduledTaskAction -Execute '"
        + executable
        + "'"
    )
    if launch_arguments is not None:
        command += " -Argument '" + quote_task_argument(launch_arguments) + "'"
    command += (
        " -WorkingDirectory '"
        + working_directory
        + "'; "
        + "$trigger = New-ScheduledTaskTrigger -AtLogOn -User '"
        + user_id
        + "'; "
        + "$principal = New-ScheduledTaskPrincipal -UserId '"
        + user_id
        + "' -LogonType Interactive -RunLevel Highest; "
        + "$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; "
        + "Register-ScheduledTask -TaskName '"
        + task_name
        + "' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null"
    )
    run_hidden_powershell(command, check=True)


def disable_autostart() -> None:
    command = (
        "Unregister-ScheduledTask -TaskName '"
        + quote_task_argument(TASK_NAME)
        + "' -Confirm:$false -ErrorAction SilentlyContinue"
    )
    run_hidden_powershell(command, check=True)


def create_icon_image() -> Image.Image:
    icon_path = get_icon_path()
    if not icon_path.exists():
        raise FileNotFoundError(f"Tray icon not found: {icon_path}")
    image = Image.open(icon_path)
    image.load()
    return image


class TrayApplication:
    def __init__(self) -> None:
        self._icon: Optional[pystray.Icon] = None
        self._service: Optional[MonitorService] = None

    def _on_toggle_autostart(self, icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        try:
            if is_autostart_enabled():
                disable_autostart()
                logging.info("Disabled scheduled-task autostart")
            else:
                enable_autostart()
                logging.info("Enabled scheduled-task autostart")
        except Exception:
            logging.exception("Failed to toggle scheduled-task autostart")
        finally:
            icon.update_menu()

    def _on_exit(self, icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        logging.info("Exit requested from tray menu")
        if self._service is not None:
            self._service.stop()
        icon.stop()

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(
                "开机自启动",
                self._on_toggle_autostart,
                checked=lambda _item: is_autostart_enabled(),
            ),
            pystray.MenuItem("退出进程", self._on_exit),
        )

    def run(self) -> int:
        if not is_running_as_admin():
            if relaunch_as_admin():
                return 0
            return 1

        config = load_runtime_config(get_default_config_path())
        setup_logging(str(config.get("log_level", "INFO")), log_file=get_default_log_path(), enable_console=False)

        self._service = MonitorService(config, log_admin_warning=False)
        self._service.start()

        if not self._service.is_alive():
            failure = self._service.get_failure()
            if failure is not None:
                raise failure
            raise RuntimeError("Monitor service failed to start")

        self._icon = pystray.Icon(
            "tiny-ipmi-monitor",
            create_icon_image(),
            "Tiny IPMI Hardware Monitor",
            self._build_menu(),
        )
        logging.info("Starting tray application")
        self._icon.run()

        if self._service is not None and self._service.is_alive():
            self._service.stop()

        failure = self._service.get_failure()
        if failure is not None:
            raise failure
        return 0


def main() -> int:
    enable_dpi_awareness()
    app = TrayApplication()
    try:
        return app.run()
    except Exception:
        log_path = get_default_log_path()
        try:
            setup_logging("INFO", log_file=log_path, enable_console=False)
        except Exception:
            pass
        logging.exception("Tray application stopped unexpectedly")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
