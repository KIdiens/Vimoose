"""当前用户级Windows开机自启。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Vimoose"


def _startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}" --minimized'
    executable = Path(sys.executable)
    pythonw = executable.with_name("pythonw.exe")
    runner = pythonw if pythonw.exists() else executable
    return f'"{runner.resolve()}" -m gesture_mouse --minimized'


def set_start_with_windows(enabled: bool) -> None:
    """写入或删除HKCU启动项，不请求管理员权限。"""

    if os.name != "nt":
        return
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        RUN_KEY,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            winreg.SetValueEx(
                key,
                VALUE_NAME,
                0,
                winreg.REG_SZ,
                _startup_command(),
            )
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass


def open_log_directory(path: Path) -> None:
    """在资源管理器中打开日志目录。"""

    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])
