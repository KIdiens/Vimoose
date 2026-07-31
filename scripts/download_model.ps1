$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$modelDirectory = Join-Path $projectRoot "gesture_mouse\models"
$modelPath = Join-Path $modelDirectory "hand_landmarker.task"
$modelUrl = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"

New-Item -ItemType Directory -Force -Path $modelDirectory | Out-Null

if (Test-Path -LiteralPath $modelPath) {
    Write-Host "模型已存在：$modelPath"
    exit 0
}

Write-Host "正在下载 MediaPipe Hand Landmarker 模型..."
Invoke-WebRequest -Uri $modelUrl -OutFile $modelPath

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $modelPath).Hash
Write-Host "模型下载完成：$modelPath"
Write-Host "SHA256：$hash"

