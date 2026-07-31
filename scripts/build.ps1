$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    py -3.11 -m venv (Join-Path $projectRoot ".venv")
    if ($LASTEXITCODE -ne 0) {
        $uvRoot = Join-Path $env:APPDATA "uv\python"
        $uvPython = Get-ChildItem -LiteralPath $uvRoot -Directory -Filter "cpython-3.11*-windows-x86_64-none" -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            Select-Object -First 1 |
            ForEach-Object { Join-Path $_.FullName "python.exe" }
        if (-not $uvPython -or -not (Test-Path -LiteralPath $uvPython)) {
            throw "未找到 Python 3.11。请先安装 Python 3.11 x64。"
        }
        & $uvPython -m venv (Join-Path $projectRoot ".venv")
    }
}

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -e "$projectRoot[dev]"
& (Join-Path $PSScriptRoot "download_model.ps1")
& $venvPython -m pytest
& $venvPython -m PyInstaller --noconfirm --clean (Join-Path $projectRoot "Vimoose.spec")

Write-Host "构建完成：$projectRoot\dist\Vimoose"
Write-Host "如已安装 Inno Setup，可继续编译 packaging\Vimoose.iss。"
