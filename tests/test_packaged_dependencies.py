"""存在目录包时验证 Qt 所需 ICU 符号，防止构建工具链同名 DLL 污染。"""
from pathlib import Path
import os
import pytest


def test_packaged_icu_exports_match_qt():
    root = Path(__file__).resolve().parents[1]/"dist"/"0.10.0"/"Vimoose"/"_internal"
    qt,icu = root/"PySide6"/"Qt6Core.dll",root/"icuuc.dll"
    if not qt.exists() or os.name != "nt":
        pytest.skip("无 Windows 目录包")
    if not icu.exists():
        icu = Path(os.environ.get("SystemRoot","C:/Windows"))/"System32"/"icuuc.dll"
    pefile = pytest.importorskip("pefile")
    with pefile.PE(str(qt)) as q,pefile.PE(str(icu)) as lib:
        required = {e.name for d in q.DIRECTORY_ENTRY_IMPORT if d.dll.lower() == b"icuuc.dll" for e in d.imports if e.name}
        provided = {e.name for e in lib.DIRECTORY_ENTRY_EXPORT.symbols if e.name}
    assert not required-provided, "打包 ICU 与 Qt 不兼容，可能误用了工具运行库中的同名 DLL"
