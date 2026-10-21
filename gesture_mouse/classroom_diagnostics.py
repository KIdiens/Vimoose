"""显式请求的离线模型自检，不启动摄像头、Office 或输入后端。"""
from __future__ import annotations
import hashlib
import json
import platform
import time
from pathlib import Path


def verify_models(report_path: Path) -> int:
    from gesture_mouse.vision import default_model_path
    from gesture_mouse import __version__
    report = {"version":__version__,"platform":platform.platform(),
              "passed":False,"system_input":False,"models":{}}
    try:
        import mediapipe as mp
        import numpy as np
        from mediapipe.tasks.python import BaseOptions,vision
        directory = default_model_path().parent
        expected = json.loads((directory/"SHA256SUMS.json").read_text(encoding="utf-8"))
        buffers = {}
        for name in ("hand_landmarker.task","pose_landmarker_lite.task"):
            buffers[name] = (directory/name).read_bytes()
            digest = hashlib.sha256(buffers[name]).hexdigest()
            report["models"][name] = digest
            if digest != expected[name]:
                raise ValueError(f"模型校验失败：{name}")
        po = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_buffer=buffers["pose_landmarker_lite.task"]),
            running_mode=vision.RunningMode.VIDEO,num_poses=4)
        ho = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_buffer=buffers["hand_landmarker.task"]),
            running_mode=vision.RunningMode.VIDEO,num_hands=4)
        image = mp.Image(image_format=mp.ImageFormat.SRGB,data=np.zeros((480,640,3),dtype=np.uint8))
        start = time.monotonic()
        with vision.PoseLandmarker.create_from_options(po) as pose,vision.HandLandmarker.create_from_options(ho) as hands:
            pose.detect_for_video(image,1000)
            hands.detect_for_video(image,1000)
        report.update(passed=True,load_and_blank_inference_ms=round((time.monotonic()-start)*1000,1))
    except Exception as error:
        report["error"] = type(error).__name__+": "+str(error)
    report_path.parent.mkdir(parents=True,exist_ok=True)
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    return 0 if report["passed"] else 3
