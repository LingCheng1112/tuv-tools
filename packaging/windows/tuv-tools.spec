# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys

if "collect_dynamic_libs" not in globals():
    from PyInstaller.utils.hooks import collect_dynamic_libs
if "TOC" not in globals():
    try:
        from PyInstaller.building.datastruct import TOC
    except ModuleNotFoundError:
        def TOC(entries):
            return list(entries)


repo_root = Path(SPECPATH).resolve().parents[1]
app_dist_dir_name = "TUV-Project-Document-Tool"
app_exe_stem = "TUV项目文档工具"
resources_dir = repo_root / "resources"
src_dir = repo_root / "src"
icon_path = resources_dir / "favicon.ico"
pyside_binaries = collect_dynamic_libs("PySide6") + collect_dynamic_libs("shiboken6")
excluded_runtime_binaries = {"icuuc.dll", "icudt73.dll"}
preferred_runtime_binary_names = ("libssl-3-x64.dll", "libcrypto-3-x64.dll")

if "_collect_preferred_runtime_binaries" not in globals():
    def _collect_preferred_runtime_binaries():
        # `_ssl.pyd` 必须和当前解释器环境里的 OpenSSL DLL 成对打包，避免混入 base 环境版本。
        runtime_root = Path(sys.executable).resolve().parent
        preferred = {}
        for name in preferred_runtime_binary_names:
            candidate = runtime_root / "Library" / "bin" / name
            if candidate.exists():
                preferred[name.lower()] = (name, str(candidate), "BINARY")
        return preferred


preferred_runtime_binaries = _collect_preferred_runtime_binaries()


a = Analysis(
    [str(repo_root / "main.py")],
    pathex=[str(repo_root), str(src_dir)],
    binaries=pyside_binaries,
    datas=[(str(resources_dir), "resources")],
    hiddenimports=[
        "pythoncom",
        "pywintypes",
        "win32com",
        "win32com.client",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
a.binaries = TOC(
    [
        *(
            entry
            for entry in a.binaries
            if Path(entry[0]).name.lower() not in excluded_runtime_binaries
            and Path(entry[0]).name.lower() not in preferred_runtime_binaries
        ),
        *preferred_runtime_binaries.values(),
    ]
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_exe_stem,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=app_dist_dir_name,
)
