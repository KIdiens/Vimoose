# 将已验证目录包、源码和证据打包到独立版本目录；已有发布文件不覆盖。
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$releaseRoot = Join-Path $projectRoot "release\0.9.0"
$binaryRoot = Join-Path $projectRoot "dist\0.9.0\Vimoose"
$installer = Join-Path $releaseRoot "Vimoose-0.9.0-Setup.exe"
$portable = Join-Path $releaseRoot "Vimoose-0.9.0-Windows-x64.zip"
$sourceZip = Join-Path $releaseRoot "Vimoose-0.9.0-Source.zip"
if (-not (Test-Path -LiteralPath (Join-Path $binaryRoot "Vimoose.exe"))) { throw "缺少目录包" }
foreach ($path in @($installer,$portable,$sourceZip)) {
    if (Test-Path -LiteralPath $path) { throw "发布文件已经存在，拒绝覆盖：$path" }
}
New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
# 数据文档可在二进制测试后更新，装配时同步最终验收结论。
foreach ($name in @("课堂演示使用说明.md","课堂演示验收记录.md")) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "docs\$name") -Destination (Join-Path $binaryRoot "_internal\docs\$name")
}
$compiler = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path -LiteralPath $compiler)) { throw "请安装 Inno Setup 6" }
& $compiler (Join-Path $projectRoot "packaging\Vimoose.iss")
if ($LASTEXITCODE -ne 0) { throw "安装器编译失败" }
Compress-Archive -LiteralPath $binaryRoot -DestinationPath $portable -CompressionLevel Optimal

Add-Type -AssemblyName System.IO.Compression
$archive = [System.IO.Compression.ZipFile]::Open($sourceZip,[System.IO.Compression.ZipArchiveMode]::Create)
try {
    Push-Location $projectRoot
    try {
        $files = @(& rg --files gesture_mouse scripts tests packaging docs)
        $files += @("README.md","LICENSE","PRIVACY.md","THIRD_PARTY_NOTICES.md", "RELEASE_NOTES_0.9.0.md", "pyproject.toml", "requirements.lock", "Vimoose.spec")
        foreach ($relative in $files | Sort-Object -Unique) {
            if ($relative -match '(^|[\\/])__pycache__([\\/]|$)' -or $relative -match '\.pyc$') { continue }
            $absolute = Join-Path $projectRoot $relative
            if (Test-Path -LiteralPath $absolute -PathType Leaf) {
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive,$absolute,$relative.Replace('\','/')) | Out-Null
            }
        }
    } finally { Pop-Location }
} finally { $archive.Dispose() }

# 不分发包含师生图像或详细人体关键点的回放诊断文件。
Copy-Item -LiteralPath (Join-Path $projectRoot "docs\课堂演示使用说明.md") -Destination $releaseRoot
Copy-Item -LiteralPath (Join-Path $projectRoot "docs\课堂演示验收记录.md") -Destination $releaseRoot
$manifest = foreach ($path in @($installer,$portable,$sourceZip)) {
    $file = Get-Item -LiteralPath $path
    [pscustomobject]@{name=$file.Name;bytes=$file.Length;sha256=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()}
}
[System.IO.File]::WriteAllText((Join-Path $releaseRoot "SHA256SUMS.json"),($manifest | ConvertTo-Json),[System.Text.UTF8Encoding]::new($false))
Write-Host "发布文件已生成：$releaseRoot（课堂待验收，不是正式课堂通过版）"
