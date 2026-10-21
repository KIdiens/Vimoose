"""按时间顺序回放验收录屏中的摄像头区域，调用实际视觉回调与手势引擎。"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from collections import Counter
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gesture_mouse.config import AppConfig
from gesture_mouse.contracts import Landmark
from gesture_mouse.gestures import GestureEngine
from gesture_mouse.latest_slot import LatestSlot
from gesture_mouse.vision import HandLandmarkerWorker, prepare_recognition_frame, default_model_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start", type=float, default=6)
    parser.add_argument("--end", type=float, default=57)
    parser.add_argument("--crop", default="770,420,790,448")
    parser.add_argument("--pipeline",action="store_true",help="同时经过实际控制线程边界，验证空检测立即取消")
    args = parser.parse_args()
    config = AppConfig(recognition_zoom=1)
    output = LatestSlot()
    worker = HandLandmarkerWorker(config, default_model_path(), LatestSlot(), output,
        threading.Event(), print, lambda p: None, lambda: False)
    engine = GestureEngine(config)
    from gesture_mouse.pipeline import ControlWorker
    from gesture_mouse.mouse import MouseController,NullMouseBackend
    control=ControlWorker(LatestSlot(),engine,MouseController(NullMouseBackend()),threading.Event(),lambda *a:None,42)
    cap = cv2.VideoCapture(str(args.video))
    fps = cap.get(cv2.CAP_PROP_FPS)
    crop = tuple(map(int, args.crop.split(",")))
    options = mp.tasks.vision.HandLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_buffer=default_model_path().read_bytes()),
        running_mode=mp.tasks.vision.RunningMode.VIDEO, num_hands=1,
        min_hand_detection_confidence=config.min_detection_confidence,
        min_hand_presence_confidence=config.min_presence_confidence,
        min_tracking_confidence=config.min_tracking_confidence)
    rows = []
    index = -1
    try:
        with mp.tasks.vision.HandLandmarker.create_from_options(options) as model:
            while cap.grab():
                index += 1
                seconds = index/fps
                if seconds >= args.end:
                    break
                if seconds < args.start or index % 2:
                    continue
                ok, frame = cap.retrieve()
                if not ok:
                    continue
                x,y,w,h = crop
                frame = frame[y:y+h,x:x+w]
                rgb = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                t = round(seconds*1000)
                result = model.detect_for_video(image,t)
                _, transform = prepare_recognition_frame(frame,1)
                worker._submitted_at[t] = (t*1_000_000,transform)
                worker._callback(result,image,t)
                packet, _ = output.get_latest()
                obs = packet.observations[0] if packet and packet.observations else None
                if args.pipeline:
                    commands=control._commands_for_packet(packet,t*1_000_000)
                else:
                    commands = engine.process(obs) if obs else engine.tick(t*1_000_000)
                rows.append(dict(time=seconds, raw=len(result.hand_landmarks),
                    accepted=bool(obs), partial=obs.partial_finger if obs else None,
                    state=engine.current_gesture.value,
                    commands=[dict(kind=c.kind.value,x=c.x,y=c.y) for c in commands],
                    landmarks=[(p.x,p.y,p.z) for p in result.hand_landmarks[0]] if result.hand_landmarks else []))
    finally:
        cap.release()
        if hasattr(worker,"_face_guard") and worker._face_guard:
            worker._face_guard.close()
    no_hand = [r for r in rows if 44 <= r["time"] < 55]
    summary = dict(samples=len(rows),states=dict(Counter(r["state"] for r in rows)),
        no_hand_samples=len(no_hand),no_hand_raw=sum(r["raw"]>0 for r in no_hand),
        no_hand_accepted=sum(r["accepted"] for r in no_hand),
        no_hand_commands=sum(len(r["commands"]) for r in no_hand),
        contact_moves=sum(any(c["kind"]=="move" for c in r["commands"])
            for r in rows if r["state"] in ("left_pinch","right_pinch","pinch_armed")))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(dict(summary=summary,rows=rows),ensure_ascii=False),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
