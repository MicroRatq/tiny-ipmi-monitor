# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys


project_dir = Path(SPECPATH)
lib_dir = project_dir / "lib"
config_path = project_dir / "monitor_config.json"
icon_png_path = project_dir / "assets" / "device-analytics.png"
icon_ico_path = project_dir / "assets" / "device-analytics.ico"
python_dir = Path(sys.executable).resolve().parent
conda_bin_dir = python_dir.parent / "Library" / "bin"

datas = [
    (str(config_path), "."),
    (str(icon_png_path), "assets"),
]

binaries = []

for dll_name in (
    "ffi-8.dll",
    "libexpat.dll",
    "libbz2.dll",
    "liblzma.dll",
    "libcrypto-3-x64.dll",
    "libssl-3-x64.dll",
):
    dll_path = conda_bin_dir / dll_name
    if dll_path.exists():
        binaries.append((str(dll_path), "."))

hiddenimports = [
    "clr",
    "pythonnet",
    "hid",
    "PIL._imaging",
]


a = Analysis(
    ["tray_app.py"],
    pathex=[str(project_dir)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    exclude_binaries=False,
    name="tiny-ipmi-monitor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(icon_ico_path),
)
