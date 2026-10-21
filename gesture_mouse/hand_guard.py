"""手部准入检查：过滤面部小骨架，稳定后才允许取得控制权。"""
from __future__ import annotations

from math import hypot, isfinite
from pathlib import Path


class HandGuard:
    def __init__(self):
        self.since = None
        self.previous = None
        self.last_ms = -1

    def reset(self):
        self.since = None
        self.previous = None

    def accept(self, points, timestamp_ms, faces):
        if timestamp_ms <= self.last_ms:
            return False
        gap = timestamp_ms-self.last_ms
        self.last_ms = timestamp_ms
        if len(points) != 21 or not all(isfinite(v) for p in points for v in (p.x,p.y,p.z)):
            self.reset()
            return False
        palm = hypot(points[0].x-points[9].x,points[0].y-points[9].y)
        x0,x1 = min(p.x for p in points),max(p.x for p in points)
        y0,y1 = min(p.y for p in points),max(p.y for p in points)
        # 不把整张脸涂黑：仅拒绝完全落在面部内部的小骨架，允许真手遮脸。
        on_face = any(x0 >= a and x1 <= c and y0 >= b and y1 <= d
                      and x1-x0 < (c-a)*.65 and y1-y0 < (d-b)*.55
                      for a,b,c,d in faces)
        if palm < .055 or on_face:
            self.reset()
            return False
        wrist = points[0]
        discontinuous = self.previous is not None and (
            hypot(wrist.x-self.previous[0],wrist.y-self.previous[1]) > max(.16,palm*.8)
            or not .55 < palm/self.previous[2] < 1.8)
        if gap > 180 or discontinuous or self.since is None:
            self.since = timestamp_ms
        self.previous = wrist.x,wrist.y,palm
        return timestamp_ms-self.since >= 150


class FaceRegions:
    """离线面部定位，仅在内存中产生矩形，不识别人名、不保存图像。"""
    def __init__(self):
        import mediapipe as mp
        self.mp = mp
        model = Path(__file__).parent / "models" / "face_detection_short_range.tflite"
        self.detector = mp.tasks.vision.FaceDetector.create_from_options(
            mp.tasks.vision.FaceDetectorOptions(
                base_options=mp.tasks.BaseOptions(model_asset_buffer=model.read_bytes()),
                min_detection_confidence=.5))

    def boxes(self, rgb):
        h,w = rgb.shape[:2]
        result = self.detector.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB,data=rgb))
        boxes = []
        for item in result.detections:
            b = item.bounding_box
            boxes.append((b.origin_x/w,b.origin_y/h,(b.origin_x+b.width)/w,(b.origin_y+b.height)/h))
        return boxes

    def close(self):
        self.detector.close()
