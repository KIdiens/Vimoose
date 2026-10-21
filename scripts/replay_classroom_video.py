"""全视频课堂回放；只输出诊断数据，绝不创建 Office 后端或发送按键。"""

from __future__ import annotations
import argparse
import json
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions,vision
from gesture_mouse.classroom import ClassroomCalibration,ClassroomGestureEngine,features_for
from gesture_mouse.contracts import Landmark,HandObservation
from gesture_mouse.teacher_tracking import BodyObservation,TeacherTracker,display_landmarks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--hand",choices=["Left","Right"],default="Left")
    parser.add_argument("--sample-hz",type=float,default=15.)
    parser.add_argument("--mirror",action="store_true")
    parser.add_argument("--calibration",type=Path)
    parser.add_argument("--labels",type=Path)
    parser.add_argument("--pose-mode",choices=["video","image"],default="video")
    parser.add_argument("--gesture-only",action="store_true",help="只测视频手势，不代表教师身份保护通过")
    args = parser.parse_args(argv)
    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened(): raise RuntimeError("无法打开视频")
    cap.set(cv2.CAP_PROP_ORIENTATION_AUTO,1)
    fps = cap.get(cv2.CAP_PROP_FPS)
    directory = Path(__file__).resolve().parents[1]/"gesture_mouse"/"models"
    po = vision.PoseLandmarkerOptions(base_options=BaseOptions(model_asset_buffer=(directory/"pose_landmarker_lite.task").read_bytes()),running_mode=vision.RunningMode.IMAGE if args.pose_mode == "image" else vision.RunningMode.VIDEO,num_poses=4)
    ho = vision.HandLandmarkerOptions(base_options=BaseOptions(model_asset_buffer=(directory/"hand_landmarker.task").read_bytes()),running_mode=vision.RunningMode.VIDEO,num_hands=4)
    tracker = TeacherTracker(hand=args.hand)
    rows,features = [],[]
    selected_once = False
    reference_body = None
    count,next_sample = 0,0.
    started = time.monotonic()
    with vision.PoseLandmarker.create_from_options(po) as pose, vision.HandLandmarker.create_from_options(ho) as detector:
        while True:
            ok,frame = cap.read()
            if not ok: break
            seconds = count/fps
            count += 1
            if seconds < next_sample: continue
            next_sample += 1/args.sample_hz
            rgb = cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB,data=rgb)
            ms = round(seconds*1000)+1000
            pr = pose.detect(image) if args.pose_mode == "image" else pose.detect_for_video(image,ms)
            hr = detector.detect_for_video(image,ms)
            bodies = tuple(BodyObservation(display_landmarks(ps,args.mirror),
                tuple(float(p.visibility or 0) for p in ps)) for ps in pr.pose_landmarks)
            hands = tuple(HandObservation(display_landmarks(ps,args.mirror),
                hr.handedness[i][0].category_name,ms*1_000_000,0.) for i,ps in enumerate(hr.hand_landmarks))
            if not selected_once and len(tracker.candidates(bodies)) == 1:
                person = tracker.candidates(bodies)[0]
                reference_body = person
                selected_once = tracker.select(bodies,*person.center,ms*1_000_000-1)
            hand = tracker.update(bodies,hands,ms*1_000_000)
            if args.gesture_only:
                if reference_body is None and bodies:
                    reference_body = bodies[0]
                hand = hands[0] if len(hands) == 1 else None
            anchor = reference_body if args.gesture_only else tracker.body
            f = features_for(hand,anchor,args.mirror) if hand and anchor else None
            features.append(f)
            rows.append({"seconds":round(seconds,3),"bodies":len(bodies),"hands":len(hands),
                         "body_geometry":[{"center":b.center,"scale":b.scale,"visibility":[b.visibility[i] for i in (11,12,13,14,15,16)],"wrists":[asdict(b.points[i]) for i in (15,16)]} for b in bodies],
                         "locked":bool(tracker.lock_id),"reason":tracker.reason,
                         "features":asdict(f) if f else None})
    cap.release()
    calibration = None
    if args.calibration:
        calibration = ClassroomCalibration.from_mapping(json.loads(args.calibration.read_text(encoding="utf-8")))
        if calibration is None: raise ValueError("校准文件无效")
    engine = ClassroomGestureEngine(calibration)
    events = []
    for row,f in zip(rows,features):
        event = engine.process(f,"video-session")
        row["state"] = engine.state
        if event: events.append({"seconds":row["seconds"],"direction":event.direction})
    report = {"video":str(args.video),"mode":"仅手势隔离回放，不验证教师身份" if args.gesture_only else "完整教师锁定回放，无真实输入", "sample_hz":args.sample_hz,
              "decoded_frames":count,"sampled_frames":len(rows),"duration":count/fps,
              "wall_seconds":round(time.monotonic()-started,2),"calibrated":calibration is not None,
              "feature_frames":sum(f is not None for f in features),
              "reasons":dict(Counter(r["reason"] for r in rows)),"events":events,"frames":rows}
    if args.labels:
        labels = json.loads(args.labels.read_text(encoding="utf-8"))
        expected = labels["actions"]
        matches = [sum(a["start"] <= e["seconds"] <= a["end"] and e["direction"] == a["direction"] for e in events) for a in expected]
        outside = [e for e in events if not any(a["start"] <= e["seconds"] <= a["end"] and e["direction"] == a["direction"] for a in expected)]
        report["acceptance"] = {"expected":len(expected),"matched_once":sum(n==1 for n in matches),
                               "counts":matches,"unexpected":outside,"passed":all(n==1 for n in matches) and not outside}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k != "frames"},ensure_ascii=False))
    return 0


if __name__ == "__main__": raise SystemExit(main())
