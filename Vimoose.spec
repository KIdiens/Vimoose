# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os
import sys
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

root = Path(SPECPATH)
# 构建进程只搜索 Python 与 Windows 系统目录；外部 PDF/EDA 工具的同名
# ICU DLL 可能缺少 Qt 需要的未加版本后缀符号，不能从桌面工具 PATH 打入包。
if os.name == "nt":
    system_root = Path(os.environ.get("SystemRoot", "C:/Windows"))
    os.environ["PATH"] = os.pathsep.join((str(Path(sys.executable).parent),
                                        str(system_root / "System32"), str(system_root)))
datas = [
    (str(root / "gesture_mouse" / "models" / "face_detection_short_range.tflite"), "gesture_mouse/models"),
    (str(root / "gesture_mouse" / "models" / "SHA256SUMS.json"), "gesture_mouse/models"),
    (str(root / "docs" / "日常自动文档使用说明.md"), "docs"),
    (str(root / "docs" / "日常模式验收记录.md"), "docs"),
    (str(root / "RELEASE_NOTES_0.10.0.md"), "."),
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
    "mediapipe.tasks.python.vision.face_detector",
    "comtypes.client.dynamic",
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
