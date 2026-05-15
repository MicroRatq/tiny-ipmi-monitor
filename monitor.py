import argparse
import ctypes
import json
import logging
import math
import os
import platform
import socket
import struct
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import hid
from pythonnet import load

load("netfx")

import clr


PROTOCOL_VERSION = 1
MAGIC = 0x54494D49  # TIMI
REPORT_ID_TELEMETRY = 2
REPORT_LENGTH = 64

FLAG_CPU_USAGE_VALID = 1 << 0
FLAG_RAM_USAGE_VALID = 1 << 1
FLAG_GPU_USAGE_VALID = 1 << 2
FLAG_CPU_TEMP_VALID = 1 << 3
FLAG_GPU_TEMP_VALID = 1 << 4
FLAG_CPU_POWER_VALID = 1 << 5
FLAG_GPU_POWER_VALID = 1 << 6
FLAG_CPU_FAN_VALID = 1 << 7
FLAG_GPU_FAN_VALID = 1 << 8
FLAG_MB_TEMP_VALID = 1 << 9
FLAG_COLLECTOR_HEALTHY = 1 << 10
FLAG_PARTIAL_FAILURE = 1 << 11

SENSOR_TYPE_LOAD = "Load"
SENSOR_TYPE_TEMPERATURE = "Temperature"
SENSOR_TYPE_POWER = "Power"
SENSOR_TYPE_FAN = "Fan"
SENSOR_TYPE_DATA = "Data"
SENSOR_TYPE_SMALL_DATA = "SmallData"
SENSOR_TYPE_CLOCK = "Clock"
SENSOR_TYPE_CONTROL = "Control"
SENSOR_TYPE_VOLTAGE = "Voltage"

HARDWARE_TYPE_CPU = "Cpu"
HARDWARE_TYPE_GPU_NVIDIA = "GpuNvidia"
HARDWARE_TYPE_GPU_AMD = "GpuAmd"
HARDWARE_TYPE_GPU_INTEL = "GpuIntel"
HARDWARE_TYPE_MEMORY = "Memory"
HARDWARE_TYPE_MOTHERBOARD = "Motherboard"
HARDWARE_TYPE_STORAGE = "Storage"
HARDWARE_TYPE_SUPER_IO = "SuperIO"


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_resource_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS")).resolve()
    return get_base_dir()


def get_lib_dir() -> Path:
    external_lib_dir = get_base_dir() / "lib"
    if external_lib_dir.exists():
        return external_lib_dir
    return get_resource_dir() / "lib"


def get_default_config_path() -> Path:
    external_config_path = get_base_dir() / "monitor_config.json"
    if external_config_path.exists():
        return external_config_path
    return get_resource_dir() / "monitor_config.json"


def get_default_log_path() -> Path:
    return get_base_dir() / "monitor.log"


LIB_DIR = get_lib_dir()


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_uint32),
        ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


def scale_percent(value: Optional[float]) -> int:
    if value is None:
        return 0
    return max(0, min(10000, int(round(value * 100))))


def scale_signed_centi(value: Optional[float]) -> int:
    if value is None:
        return 0
    scaled = int(round(value * 100))
    return max(-32768, min(32767, scaled))


def scale_unsigned_centi(value: Optional[float]) -> int:
    if value is None:
        return 0
    scaled = int(round(value * 100))
    return max(0, min(65535, scaled))


def scale_u16(value: Optional[float]) -> int:
    if value is None:
        return 0
    return max(0, min(65535, int(round(value))))


@dataclass
class TelemetrySnapshot:
    hostname: str = ""
    platform_name: str = ""
    os_uptime_seconds: Optional[int] = None
    cpu_name: str = ""
    motherboard_name: str = ""
    gpu_names: List[str] = field(default_factory=list)
    cpu_usage: Optional[float] = None
    cpu_package_temp: Optional[float] = None
    cpu_core_max_temp: Optional[float] = None
    ram_usage: Optional[float] = None
    ram_used_gb: Optional[float] = None
    ram_available_gb: Optional[float] = None
    ram_total_gb: Optional[float] = None
    gpu_usage: Optional[float] = None
    gpu_memory_usage: Optional[float] = None
    cpu_temp: Optional[float] = None
    gpu_temp: Optional[float] = None
    cpu_power: Optional[float] = None
    gpu_power: Optional[float] = None
    cpu_fan: Optional[float] = None
    gpu_fan: Optional[float] = None
    motherboard_temp: Optional[float] = None
    storage_temps: Dict[str, float] = field(default_factory=dict)
    sensor_count: int = 0
    readable_sensor_count: int = 0
    sensors_seen: List[Dict[str, object]] = field(default_factory=list)
    partial_failure: bool = False


def is_running_as_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def get_memory_status() -> Dict[str, float]:
    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()
    gib = float(1024 ** 3)
    total = status.ullTotalPhys / gib
    available = status.ullAvailPhys / gib
    used = total - available
    return {
        "memory_load_percent": float(status.dwMemoryLoad),
        "total_gb": total,
        "available_gb": available,
        "used_gb": used,
    }


def get_os_uptime_seconds() -> int:
    return int(ctypes.windll.kernel32.GetTickCount64() / 1000)


def snapshot_to_dict(snapshot: TelemetrySnapshot) -> Dict[str, object]:
    return asdict(snapshot)


class TelemetryEncoder:
    def __init__(self, report_id: int, report_length: int) -> None:
        self.report_id = report_id
        self.report_length = report_length

    def encode(self, snapshot: TelemetrySnapshot, sequence_number: int, uptime_seconds: int) -> bytes:
        flags = FLAG_COLLECTOR_HEALTHY
        flags |= FLAG_CPU_USAGE_VALID if snapshot.cpu_usage is not None else 0
        flags |= FLAG_RAM_USAGE_VALID if snapshot.ram_usage is not None else 0
        flags |= FLAG_GPU_USAGE_VALID if snapshot.gpu_usage is not None else 0
        flags |= FLAG_CPU_TEMP_VALID if snapshot.cpu_temp is not None else 0
        flags |= FLAG_GPU_TEMP_VALID if snapshot.gpu_temp is not None else 0
        flags |= FLAG_CPU_POWER_VALID if snapshot.cpu_power is not None else 0
        flags |= FLAG_GPU_POWER_VALID if snapshot.gpu_power is not None else 0
        flags |= FLAG_CPU_FAN_VALID if snapshot.cpu_fan is not None else 0
        flags |= FLAG_GPU_FAN_VALID if snapshot.gpu_fan is not None else 0
        flags |= FLAG_MB_TEMP_VALID if snapshot.motherboard_temp is not None else 0
        flags |= FLAG_PARTIAL_FAILURE if snapshot.partial_failure else 0

        packet = bytearray(self.report_length)
        struct.pack_into(
            "<BHIIHHHhhHHHHh17xIII",
            packet,
            0,
            PROTOCOL_VERSION,
            flags,
            sequence_number,
            uptime_seconds,
            scale_percent(snapshot.cpu_usage),
            scale_percent(snapshot.ram_usage),
            scale_percent(snapshot.gpu_usage),
            scale_signed_centi(snapshot.cpu_temp),
            scale_signed_centi(snapshot.gpu_temp),
            scale_unsigned_centi(snapshot.cpu_power),
            scale_unsigned_centi(snapshot.gpu_power),
            scale_u16(snapshot.cpu_fan),
            scale_u16(snapshot.gpu_fan),
            scale_signed_centi(snapshot.motherboard_temp),
            flags,
            int(time.time()) & 0xFFFFFFFF,
            MAGIC,
        )
        return bytes(packet)


class LibreHardwareMonitorCollector:
    def __init__(self, dll_path: Path) -> None:
        dll_dir = str(dll_path.parent)
        if dll_dir not in sys.path:
            sys.path.insert(0, dll_dir)
        os.chdir(dll_dir)

        import System

        def resolve_assembly(_sender, args):
            assembly_name = System.Reflection.AssemblyName(args.Name).Name + ".dll"
            candidate = dll_path.parent / assembly_name
            if candidate.exists():
                return System.Reflection.Assembly.LoadFrom(str(candidate))
            return None

        System.AppDomain.CurrentDomain.AssemblyResolve += resolve_assembly

        preload_assemblies = [
            "System.Memory.dll",
            "System.Buffers.dll",
            "System.Runtime.CompilerServices.Unsafe.dll",
            "System.Numerics.Vectors.dll",
            "System.Text.Json.dll",
            "System.Text.Encodings.Web.dll",
            "System.Collections.Immutable.dll",
            "System.Reflection.Metadata.dll",
            "System.IO.Pipelines.dll",
            "System.Threading.Tasks.Extensions.dll",
            "Microsoft.Bcl.AsyncInterfaces.dll",
            "Microsoft.Bcl.HashCode.dll",
            "System.Security.AccessControl.dll",
            "System.Security.Principal.Windows.dll",
            "System.Threading.AccessControl.dll",
            "BlackSharp.Core.dll",
            "DiskInfoToolkit.dll",
            "HidSharp.dll",
            "LibreHardwareMonitorLib.dll",
        ]
        for assembly_name in preload_assemblies:
            candidate = dll_path.parent / assembly_name
            if candidate.exists():
                System.Reflection.Assembly.LoadFrom(str(candidate))

        shim_assembly = LIB_DIR / "HardwareMonitorShim.dll"
        if shim_assembly.exists():
            System.Reflection.Assembly.LoadFrom(str(shim_assembly))

        from LibreHardwareMonitor import Hardware  # type: ignore

        self._hardware = Hardware
        settings_type = None
        for assembly in System.AppDomain.CurrentDomain.GetAssemblies():
            settings_type = assembly.GetType("HardwareMonitorShim.MemorySettings")
            if settings_type is not None:
                break
        if settings_type is None:
            raise RuntimeError("HardwareMonitorShim.MemorySettings type not found")

        self._settings_proxy = System.Activator.CreateInstance(settings_type)
        self._computer = Hardware.Computer(self._settings_proxy)
        self._computer.IsCpuEnabled = True
        self._computer.IsGpuEnabled = True
        self._computer.IsMemoryEnabled = True
        self._computer.IsMotherboardEnabled = True
        self._computer.IsControllerEnabled = True
        self._computer.IsStorageEnabled = True
        self._computer.IsNetworkEnabled = False
        self._computer.Open()

        update_visitor_type = None
        for assembly in System.AppDomain.CurrentDomain.GetAssemblies():
            update_visitor_type = assembly.GetType("HardwareMonitorShim.UpdateVisitor")
            if update_visitor_type is not None:
                break
        if update_visitor_type is None:
            raise RuntimeError("HardwareMonitorShim.UpdateVisitor type not found")
        self._update_visitor = System.Activator.CreateInstance(update_visitor_type)

    def refresh(self) -> None:
        self._computer.Accept(self._update_visitor)

    def close(self) -> None:
        self._computer.Close()

    def _walk_hardware(self, hardware_items: Iterable) -> Iterable:
        for hardware in hardware_items:
            yield hardware
            for subhardware in hardware.SubHardware:
                yield subhardware

    def _sensor_value(self, sensor) -> Optional[float]:
        value = sensor.Value
        if value is None:
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(value) or math.isinf(value):
            return None
        return value

    def _append_sensor_snapshot_(self, snapshot: TelemetrySnapshot, hardware, sensor, value: Optional[float]) -> None:
        snapshot.sensor_count += 1
        if value is not None:
            snapshot.readable_sensor_count += 1
        snapshot.sensors_seen.append(
            {
                "hardware": str(hardware.Name),
                "hardware_type": str(hardware.HardwareType),
                "sensor": str(sensor.Name),
                "sensor_type": str(sensor.SensorType),
                "value": value,
            }
        )

    def list_sensors(self) -> List[Dict[str, object]]:
        sensors: List[Dict[str, object]] = []
        self.refresh()
        for hardware in self._walk_hardware(self._computer.Hardware):
            for sensor in hardware.Sensors:
                value = self._sensor_value(sensor)
                sensors.append(
                    {
                        "hardware": str(hardware.Name),
                        "hardware_type": str(hardware.HardwareType),
                        "sensor": str(sensor.Name),
                        "sensor_type": str(sensor.SensorType),
                        "value": value,
                    }
                )
        return sensors

    def collect(self) -> TelemetrySnapshot:
        snapshot = TelemetrySnapshot(
            hostname=socket.gethostname(),
            platform_name=platform.platform(),
            os_uptime_seconds=get_os_uptime_seconds(),
        )

        try:
            memory_status = get_memory_status()
            snapshot.ram_total_gb = memory_status["total_gb"]
            snapshot.ram_available_gb = memory_status["available_gb"]
            snapshot.ram_used_gb = memory_status["used_gb"]
            snapshot.ram_usage = memory_status["memory_load_percent"]
        except Exception:
            logging.exception("Failed to query Windows memory status")
            snapshot.partial_failure = True

        try:
            self.refresh()
            for hardware in self._walk_hardware(self._computer.Hardware):
                hw_type = str(hardware.HardwareType)
                hardware_name = str(hardware.Name)

                if hw_type == HARDWARE_TYPE_CPU and not snapshot.cpu_name:
                    snapshot.cpu_name = hardware_name
                elif hw_type == HARDWARE_TYPE_MOTHERBOARD and not snapshot.motherboard_name:
                    snapshot.motherboard_name = hardware_name
                elif hw_type in (HARDWARE_TYPE_GPU_NVIDIA, HARDWARE_TYPE_GPU_AMD, HARDWARE_TYPE_GPU_INTEL):
                    if hardware_name not in snapshot.gpu_names:
                        snapshot.gpu_names.append(hardware_name)

                for sensor in hardware.Sensors:
                    sensor_type = str(sensor.SensorType)
                    sensor_name = str(sensor.Name)
                    value = self._sensor_value(sensor)
                    self._append_sensor_snapshot_(snapshot, hardware, sensor, value)
                    if value is None:
                        continue

                    if hw_type == HARDWARE_TYPE_CPU:
                        if sensor_type == SENSOR_TYPE_LOAD and sensor_name == "CPU Total":
                            snapshot.cpu_usage = value
                        elif sensor_type == SENSOR_TYPE_TEMPERATURE:
                            if sensor_name in ("CPU Package", "Package"):
                                snapshot.cpu_package_temp = value
                                snapshot.cpu_temp = value
                            elif snapshot.cpu_core_max_temp is None or value > snapshot.cpu_core_max_temp:
                                snapshot.cpu_core_max_temp = value
                                if snapshot.cpu_temp is None:
                                    snapshot.cpu_temp = value
                        elif sensor_type == SENSOR_TYPE_POWER and sensor_name in ("CPU Package", "Package"):
                            snapshot.cpu_power = value
                        elif sensor_type == SENSOR_TYPE_FAN and snapshot.cpu_fan is None:
                            snapshot.cpu_fan = value
                    elif hw_type == HARDWARE_TYPE_MEMORY:
                        if sensor_type == SENSOR_TYPE_LOAD and sensor_name in ("Memory", "Memory Used") and snapshot.ram_usage is None:
                            snapshot.ram_usage = value
                        elif sensor_type in (SENSOR_TYPE_DATA, SENSOR_TYPE_SMALL_DATA):
                            if sensor_name in ("Memory Used", "Used Memory") and snapshot.ram_used_gb is None:
                                snapshot.ram_used_gb = value
                            elif sensor_name in ("Memory Available", "Available Memory") and snapshot.ram_available_gb is None:
                                snapshot.ram_available_gb = value
                    elif hw_type in (HARDWARE_TYPE_GPU_NVIDIA, HARDWARE_TYPE_GPU_AMD, HARDWARE_TYPE_GPU_INTEL):
                        if sensor_type == SENSOR_TYPE_LOAD and sensor_name in ("GPU Core", "D3D 3D", "GPU"):
                            if snapshot.gpu_usage is None or value > snapshot.gpu_usage:
                                snapshot.gpu_usage = value
                        elif sensor_type == SENSOR_TYPE_LOAD and sensor_name in ("GPU Memory", "D3D Memory", "Memory"):
                            if snapshot.gpu_memory_usage is None or value > snapshot.gpu_memory_usage:
                                snapshot.gpu_memory_usage = value
                        elif sensor_type == SENSOR_TYPE_TEMPERATURE and sensor_name in ("GPU Core", "GPU Hot Spot", "Temperature"):
                            if snapshot.gpu_temp is None or value > snapshot.gpu_temp:
                                snapshot.gpu_temp = value
                        elif sensor_type == SENSOR_TYPE_POWER and sensor_name in ("GPU Package", "GPU Core", "Total Board", "GPU"):
                            if snapshot.gpu_power is None or value > snapshot.gpu_power:
                                snapshot.gpu_power = value
                        elif sensor_type == SENSOR_TYPE_FAN and snapshot.gpu_fan is None:
                            snapshot.gpu_fan = value
                    elif hw_type == HARDWARE_TYPE_MOTHERBOARD:
                        if sensor_type == SENSOR_TYPE_TEMPERATURE and snapshot.motherboard_temp is None:
                            snapshot.motherboard_temp = value
                    elif hw_type == HARDWARE_TYPE_SUPER_IO:
                        if sensor_type == SENSOR_TYPE_FAN and sensor_name in ("CPU Fan", "CPU OPT", "CPU"):
                            if snapshot.cpu_fan is None or snapshot.cpu_fan <= 0:
                                snapshot.cpu_fan = value
                        elif sensor_type == SENSOR_TYPE_TEMPERATURE and sensor_name in (
                            "Motherboard",
                            "Mainboard",
                            "System",
                            "CPU",
                        ):
                            if snapshot.motherboard_temp is None or snapshot.motherboard_temp <= 0:
                                snapshot.motherboard_temp = value
                    elif hw_type == HARDWARE_TYPE_STORAGE:
                        if sensor_type == SENSOR_TYPE_TEMPERATURE:
                            snapshot.storage_temps[hardware_name] = value

            if snapshot.cpu_usage is None or snapshot.ram_usage is None:
                snapshot.partial_failure = True
        except Exception:
            logging.exception("Telemetry collection failed")
            snapshot.partial_failure = True

        return snapshot


class HidTransport:
    def __init__(self, config: Dict[str, object]) -> None:
        self._config = config
        self._device = None
        self._path = None
        self._write_mode = None

    def _matches(self, device_info: Dict[str, object]) -> bool:
        vendor_id = self._config.get("vendor_id")
        product_id = self._config.get("product_id")
        manufacturer_string = self._config.get("manufacturer_string")
        product_string = self._config.get("product_string")
        usage_page = self._config.get("usage_page")
        usage = self._config.get("usage")
        interface_number = self._config.get("interface_number")
        path_contains = self._config.get("path_contains")

        if vendor_id is not None and device_info.get("vendor_id") != vendor_id:
            return False
        if product_id is not None and device_info.get("product_id") != product_id:
            return False
        if manufacturer_string and device_info.get("manufacturer_string") != manufacturer_string:
            return False
        if product_string and device_info.get("product_string") != product_string:
            return False
        if usage_page is not None and device_info.get("usage_page") != usage_page:
            return False
        if usage is not None and device_info.get("usage") != usage:
            return False
        if interface_number is not None and device_info.get("interface_number") != interface_number:
            return False
        if path_contains:
            device_path = device_info.get("path")
            if not device_path or str(path_contains).lower() not in str(device_path).lower():
                return False
        return True

    def _find_device_info(self) -> Optional[Dict[str, object]]:
        for device_info in hid.enumerate():
            if self._matches(device_info):
                return device_info
        return None

    def _ensure_open(self) -> bool:
        if self._device is not None:
            return True
        device_info = self._find_device_info()
        if device_info is None:
            return False
        self._device = hid.device()
        self._path = device_info["path"]
        self._device.open_path(self._path)
        self._device.set_nonblocking(True)
        self._write_mode = None
        logging.info(
            "Connected HID device vendor=0x%04x product=0x%04x path=%s",
            device_info.get("vendor_id", 0),
            device_info.get("product_id", 0),
            self._path,
        )
        return True

    def close(self) -> None:
        if self._device is not None:
            try:
                self._device.close()
            finally:
                self._device = None
                self._path = None
                self._write_mode = None

    def _build_write_candidates(self, report: bytes) -> List[tuple]:
        report_id = int(self._config.get("report_id", REPORT_ID_TELEMETRY))
        return [
            ("raw", report),
            ("zero-prefixed", bytes([0]) + report),
            ("report-id-prefixed", bytes([report_id & 0xFF]) + report),
        ]

    def _write_once(self, payload: bytes) -> int:
        assert self._device is not None
        return int(self._device.write(payload))

    def _probe_write_mode(self, report: bytes) -> bool:
        for mode_name, payload in self._build_write_candidates(report):
            try:
                written = self._write_once(payload)
            except Exception:
                logging.exception("HID write probe failed for mode=%s", mode_name)
                continue

            logging.info(
                "HID write probe mode=%s wrote=%s expected=%s",
                mode_name,
                written,
                len(payload),
            )
            if written == len(payload):
                self._write_mode = mode_name
                logging.info("Selected HID write mode: %s", mode_name)
                return True

        return False

    def _payload_for_mode(self, mode_name: str, report: bytes) -> bytes:
        report_id = int(self._config.get("report_id", REPORT_ID_TELEMETRY))
        if mode_name == "raw":
            return report
        if mode_name == "zero-prefixed":
            return bytes([0]) + report
        if mode_name == "report-id-prefixed":
            return bytes([report_id & 0xFF]) + report
        raise ValueError(f"Unknown HID write mode: {mode_name}")

    def send_report(self, report: bytes) -> bool:
        try:
            if not self._ensure_open():
                return False

            if self._write_mode is None and not self._probe_write_mode(report):
                logging.warning("Unable to find a working HID write mode")
                return False

            payload = self._payload_for_mode(self._write_mode, report)
            written = self._write_once(payload)
            if written != len(payload):
                logging.warning("Short HID write with mode=%s: wrote %s of %s bytes", self._write_mode, written, len(payload))
                self._write_mode = None
                return False
            return True
        except Exception:
            logging.exception("Failed to send HID report, reconnecting")
            self.close()
            return False


def load_config(path: Path) -> Dict[str, object]:
    with path.open("r", encoding="utf-8") as file:
        config = json.load(file)
    return config


def setup_logging(level_name: str, log_file: Optional[Path] = None, enable_console: bool = True) -> None:
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(getattr(logging, level_name.upper(), logging.INFO))

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


class MonitorService:
    def __init__(self, config: Dict[str, object], *, log_admin_warning: bool = True) -> None:
        self._config = config
        self._log_admin_warning = log_admin_warning
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._failure: Optional[BaseException] = None

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("Monitor service already started")
        self._thread = threading.Thread(target=self._run, name="TinyIPMIMonitor", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def get_failure(self) -> Optional[BaseException]:
        return self._failure

    def run_foreground(self) -> int:
        try:
            self._run()
            return 0
        except KeyboardInterrupt:
            logging.info("Stopping hardware monitor bridge")
            return 0

    def _run(self) -> None:
        report_id = int(self._config.get("report_id", REPORT_ID_TELEMETRY))
        report_length = int(self._config.get("report_length", REPORT_LENGTH))
        interval_seconds = float(self._config.get("interval_seconds", 1.0))

        dll_path = LIB_DIR / "LibreHardwareMonitorLib.dll"
        if not dll_path.exists():
            raise FileNotFoundError(f"LibreHardwareMonitorLib.dll not found in {LIB_DIR}")

        if self._log_admin_warning and not is_running_as_admin():
            logging.warning(
                "Not running as administrator; CPU temperature, CPU power, motherboard, and fan sensors may be incomplete or zero"
            )

        collector = LibreHardwareMonitorCollector(dll_path)
        transport = HidTransport(self._config)
        encoder = TelemetryEncoder(report_id, report_length)
        sequence_number = 0
        start = time.monotonic()

        logging.info("Starting hardware monitor bridge")
        try:
            while not self._stop_event.is_set():
                snapshot = collector.collect()
                uptime_seconds = int(time.monotonic() - start)
                report = encoder.encode(snapshot, sequence_number, uptime_seconds)
                if not transport.send_report(report):
                    logging.warning("Telemetry HID device not available")
                sequence_number = (sequence_number + 1) & 0xFFFFFFFF
                self._stop_event.wait(interval_seconds)
        except KeyboardInterrupt:
            raise
        except BaseException as exc:
            self._failure = exc
            logging.exception("Hardware monitor bridge stopped unexpectedly")
            raise
        finally:
            transport.close()
            collector.close()


def load_runtime_config(config_path: Path) -> Dict[str, object]:
    if not config_path.exists():
        raise FileNotFoundError(f"Missing config file: {config_path}")
    return load_config(config_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tiny IPMI hardware monitor HID bridge")
    parser.add_argument(
        "--config",
        type=Path,
        default=get_default_config_path(),
        help="Path to monitor configuration JSON file",
    )
    parser.add_argument(
        "--dump-devices",
        action="store_true",
        help="List currently visible HID devices and exit",
    )
    parser.add_argument(
        "--dump-snapshot",
        action="store_true",
        help="Collect one snapshot and print it as JSON",
    )
    parser.add_argument(
        "--dump-sensors",
        action="store_true",
        help="Print all discovered LibreHardwareMonitor sensors as JSON",
    )
    return parser.parse_args()


def dump_devices() -> None:
    for device_info in hid.enumerate():
        print(json.dumps({
            "vendor_id": device_info.get("vendor_id"),
            "product_id": device_info.get("product_id"),
            "manufacturer_string": device_info.get("manufacturer_string"),
            "product_string": device_info.get("product_string"),
            "path": str(device_info.get("path")),
            "usage_page": device_info.get("usage_page"),
            "usage": device_info.get("usage"),
            "interface_number": device_info.get("interface_number"),
        }, ensure_ascii=True))


def print_json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=True, indent=2))


def main() -> int:
    args = parse_args()
    if args.dump_devices:
        dump_devices()
        return 0

    try:
        config = load_runtime_config(args.config)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    setup_logging(str(config.get("log_level", "INFO")))

    dll_path = LIB_DIR / "LibreHardwareMonitorLib.dll"
    if not dll_path.exists():
        logging.error("LibreHardwareMonitorLib.dll not found in %s", LIB_DIR)
        return 3

    if not is_running_as_admin():
        logging.warning("Not running as administrator; CPU temperature, CPU power, motherboard, and fan sensors may be incomplete or zero")

    collector = LibreHardwareMonitorCollector(dll_path)
    if args.dump_snapshot:
        try:
            print_json(snapshot_to_dict(collector.collect()))
            return 0
        finally:
            collector.close()

    if args.dump_sensors:
        try:
            print_json(collector.list_sensors())
            return 0
        finally:
            collector.close()

    service = MonitorService(config)
    try:
        return service.run_foreground()
    except KeyboardInterrupt:
        logging.info("Stopping hardware monitor bridge")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
