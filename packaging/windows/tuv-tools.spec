# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


repo_root = Path(SPECPATH).resolve().parents[1]
resources_dir = repo_root / "resources"
src_dir = repo_root / "src"
icon_path = resources_dir / "favicon.ico"


a = Analysis(
    [str(repo_root / "main.py")],
    pathex=[str(repo_root), str(src_dir)],
    binaries=[],
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
