# 本版目录包、安装器和源码分别发布；拒绝覆盖已有发布文件。
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$releaseRoot = Join-Path $projectRoot "release\0.10.0"
$binaryRoot = Join-Path $projectRoot "dist\0.10.0\Vimoose"
$installer = Join-Path $releaseRoot "Vimoose-0.10.0-Setup.exe"
$portable = Join-Path $releaseRoot "Vimoose-0.10.0-Windows-x64.zip"
$sourceZip = Join-Path $releaseRoot "Vimoose-0.10.0-Source.zip"
if (-not (Test-Path -LiteralPath (Join-Path $binaryRoot "Vimoose.exe"))) { throw "缺少目录包" }
foreach ($path in @($installer,$portable,$sourceZip)) {
    if (Test-Path -LiteralPath $path) { throw "拒绝覆盖已有发布文件：$path" }
}
New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
foreach ($name in @("日常自动文档使用说明.md","日常模式验收记录.md")) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "docs\$name") -Destination (Join-Path $binaryRoot "_internal\docs\$name")
    Copy-Item -LiteralPath (Join-Path $projectRoot "docs\$name") -Destination $releaseRoot
}
$compiler = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path -LiteralPath $compiler)) { throw "缺少 Inno Setup 6" }
& $compiler (Join-Path $projectRoot "packaging\Vimoose.iss")
if ($LASTEXITCODE -ne 0) { throw "安装器编译失败" }
Compress-Archive -LiteralPath $binaryRoot -DestinationPath $portable -CompressionLevel Optimal
Add-Type -AssemblyName System.IO.Compression
$archive = [System.IO.Compression.ZipFile]::Open($sourceZip,[System.IO.Compression.ZipArchiveMode]::Create)
try {
    Push-Location $projectRoot
    try {
        $files = @(& rg --files gesture_mouse scripts tests packaging docs)
        $files += @("README.md","LICENSE","PRIVACY.md","THIRD_PARTY_NOTICES.md","RELEASE_NOTES_0.10.0.md","pyproject.toml","requirements.lock","Vimoose.spec")
        foreach ($relative in $files | Sort-Object -Unique) {
            if ($relative -match '(^|[\\/])__pycache__([\\/]|$)' -or $relative -match '\.pyc$') { continue }
            $absolute = Join-Path $projectRoot $relative
            if (Test-Path -LiteralPath $absolute -PathType Leaf) {
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive,$absolute,$relative.Replace('\','/')) | Out-Null
            }
        }
    } finally { Pop-Location }
} finally { $archive.Dispose() }
# 不分发原验收录像、提取的人像或逐帧关键点。
$manifest = foreach ($path in @($installer,$portable,$sourceZip)) {
    $file = Get-Item -LiteralPath $path
    [pscustomobject]@{name=$file.Name;bytes=$file.Length;sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()}
}
[System.IO.File]::WriteAllText((Join-Path $releaseRoot "SHA256SUMS.json"),($manifest | ConvertTo-Json),[System.Text.UTF8Encoding]::new($false))
Write-Host "0.10.0 发布文件已生成：$releaseRoot"
