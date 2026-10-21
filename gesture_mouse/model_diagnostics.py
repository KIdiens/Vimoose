"""打包后模型完整性与离线空白帧推理检查。"""
import hashlib
import json
from pathlib import Path


def verify_models(output):
    import mediapipe as mp
    import numpy as np
    from gesture_mouse.hand_guard import FaceRegions
    root=Path(__file__).parent/"models"
    expected=json.loads((root/"SHA256SUMS.json").read_text(encoding="utf-8"))
    report={}
    try:
        for name in ("hand_landmarker.task","face_detection_short_range.tflite"):
            digest=hashlib.sha256((root/name).read_bytes()).hexdigest()
            report[name]=digest==expected[name]
            if not report[name]: raise ValueError("模型校验失败："+name)
        rgb=np.zeros((240,320,3),dtype=np.uint8)
        face=FaceRegions()
        try: report["blank_faces"]=len(face.boxes(rgb))
        finally: face.close()
        options=mp.tasks.vision.HandLandmarkerOptions(base_options=mp.tasks.BaseOptions(
            model_asset_buffer=(root/"hand_landmarker.task").read_bytes()))
        with mp.tasks.vision.HandLandmarker.create_from_options(options) as detector:
            report["blank_hands"]=len(detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=rgb)).hand_landmarks)
        report["passed"]=True
    except Exception as error:
        report.update(passed=False,error=f"{type(error).__name__}: {error}")
    output=Path(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return 0 if report["passed"] else 1
