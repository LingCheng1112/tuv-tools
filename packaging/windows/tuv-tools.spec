# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

if "collect_dynamic_libs" not in globals():
    from PyInstaller.utils.hooks import collect_dynamic_libs
if "TOC" not in globals():
    try:
        from PyInstaller.building.datastruct import TOC
    except ModuleNotFoundError:
        def TOC(entries):
            return list(entries)


repo_root = Path(SPECPATH).resolve().parents[1]
resources_dir = repo_root / "resources"
src_dir = repo_root / "src"
icon_path = resources_dir / "favicon.ico"
pyside_binaries = collect_dynamic_libs("PySide6") + collect_dynamic_libs("shiboken6")
excluded_runtime_binaries = {"icuuc.dll", "icudt73.dll"}


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
    entry
    for entry in a.binaries
    if Path(entry[0]).name.lower() not in excluded_runtime_binaries
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TUV-Tools",
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
    name="TUV-Tools",
)
