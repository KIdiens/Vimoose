# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

root = Path(SPECPATH)
datas = [
    (
        str(root / "gesture_mouse" / "models" / "hand_landmarker.task"),
        "gesture_mouse/models",
    ),
    (str(root / "README.md"), "."),
    (str(root / "LICENSE"), "."),
    (str(root / "PRIVACY.md"), "."),
    (str(root / "THIRD_PARTY_NOTICES.md"), "."),
]
binaries = collect_dynamic_libs("mediapipe")
binaries += collect_dynamic_libs("uiautomation")
hiddenimports = [
    "mediapipe.tasks.python.vision.hand_landmarker",
    "mediapipe.tasks.python.vision.core.base_vision_task_api",
]
hiddenimports += collect_submodules("uiautomation")
hiddenimports += [
    "comtypes.gen.UIAutomationClient",
    "comtypes.gen.stdole",
]

a = Analysis(
    ["gesture_mouse/app.py"],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "jax",
        "jaxlib",
        "scipy",
        "matplotlib",
        "pandas",
        "PIL",
        "sounddevice",
        "sentencepiece",
        "torch",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtPdf",
        "PySide6.QtMultimedia",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Vimoose",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(root / "packaging" / "Vimoose.ico"),
    version=str(root / "packaging" / "Vimoose.version"),
    manifest=str(root / "packaging" / "Vimoose.manifest"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Vimoose",
)
