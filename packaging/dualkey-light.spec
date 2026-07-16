# -*- mode: python ; coding: utf-8 -*-

import os
import sys

from PyInstaller.utils.hooks import collect_submodules


backend_module = {
    "win32": "bleak.backends.winrt",
    "darwin": "bleak.backends.corebluetooth",
}.get(sys.platform, "bleak.backends.bluezdbus")
hidden_imports = collect_submodules(backend_module)
project_root = os.path.abspath(os.path.join(SPECPATH, ".."))
app_version = os.environ.get("APP_VERSION", "0.2.0")

analysis = Analysis(
    [os.path.join(project_root, "host", "dualkey_light.py")],
    pathex=[os.path.join(project_root, "host")],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

python_archive = PYZ(analysis.pure)

cli = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="dualkey-light",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

executables = [cli]

if sys.platform == "win32":
    service = EXE(
        python_archive,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name="dualkey-light-service",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    executables.append(service)

bundle = COLLECT(
    *executables,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="dualkey-light",
)

if sys.platform == "darwin":
    app = BUNDLE(
        bundle,
        name="DualKey Signal Light.app",
        icon=None,
        bundle_identifier="io.github.a1az.dualkey-signal-light",
        version=app_version,
        info_plist={
            "CFBundleDisplayName": "DualKey Signal Light",
            "LSUIElement": True,
            "NSBluetoothAlwaysUsageDescription": (
                "DualKey Signal Light uses Bluetooth to update the LEDs on your "
                "M5Stack Chain DualKey."
            ),
        },
    )
