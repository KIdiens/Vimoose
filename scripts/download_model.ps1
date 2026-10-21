$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$modelDirectory = Join-Path $projectRoot "gesture_mouse\models"
$modelPath = Join-Path $modelDirectory "hand_landmarker.task"
$modelUrl = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"

New-Item -ItemType Directory -Force -Path $modelDirectory | Out-Null

$hashes = Get-Content -Raw -LiteralPath (Join-Path $modelDirectory "SHA256SUMS.json") | ConvertFrom-Json
$models = @{
    "hand_landmarker.task" = $modelUrl
    "face_detection_short_range.tflite" = "https://storage.googleapis.com/mediapipe-assets/face_detection_short_range.tflite"
}
foreach ($name in $models.Keys) {
    $targetPath = Join-Path $modelDirectory $name
    if (-not (Test-Path -LiteralPath $targetPath)) {
        Invoke-WebRequest -Uri $models[$name] -OutFile $targetPath
    }
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $targetPath).Hash.ToLowerInvariant()
    if ($actual -ne $hashes.$name) { throw "模型校验失败：$name；已保留文件，请检查来源。" }
    Write-Host "模型已验证：$name SHA256=$actual"
}
