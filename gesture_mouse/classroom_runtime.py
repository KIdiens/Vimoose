"""课堂专用流水线：同帧人体和手部识别，不进入普通鼠标状态机。"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict

from gesture_mouse.classroom import (
    CalibrationRecorder, ClassroomCalibration, ClassroomGestureEngine, features_for,
)
from gesture_mouse.contracts import Landmark, HandObservation, DetectionPacket
from gesture_mouse.teacher_tracking import BodyObservation, TeacherTracker, display_landmarks
from gesture_mouse.office_bridge import OfficeWorker


class ClassroomRuntime:
    def __init__(self, config, safe_mode=False):
        self.config = config
        self.lock = threading.RLock()
        self.tracker = TeacherTracker(config.classroom_region,config.classroom_hand)
        calibration = (ClassroomCalibration.from_mapping(config.classroom_calibration)
                       if config.classroom_signature() == config.classroom_camera_signature else None)
        self.engine = ClassroomGestureEngine(calibration)
        self.office = OfficeWorker(safe_mode)
        self.bodies = ()
        self.frame_ns = 0
        self.paused = False
        self.recorder = None
        self.completed_calibration = None
        self.message = "待锁定：启动后在预览中点选老师"
        self._last_token = ""
        self.last_features = None

    def select(self, x, y):
        with self.lock:
            self.office.revoke()
            self.engine.cancel()
            self.recorder = None
            if time.monotonic_ns()-self.frame_ns > 300_000_000:
                self.message = "预览过期，请等待实时画面"
                return False
            ok = self.tracker.select(self.bodies,x,y,self.frame_ns)
            self.message = self.tracker.reason
            return ok

    def set_paused(self, paused):
        self.office.revoke()
        with self.lock:
            self.paused = paused
            self.engine.cancel()
            self.recorder = None
            self.message = "用户已暂停" if paused else "已恢复，请正掌准备"

    def calibrate(self):
        with self.lock:
            if not self.tracker.lock_id:
                self.message = "请先点选并锁定老师"
                return False
            self.office.revoke()
            self.engine.cancel()
            self.recorder = CalibrationRecorder()
            # 校准允许采集，但不能悄悄恢复用户已暂停的课堂输出。
            return True

    def stop(self):
        self.office.stop()
        with self.lock:
            self.tracker.invalidate("课堂已停止，请重新点选老师")
            self.recorder = None
            self.engine.cancel()

    def snapshot(self):
        with self.lock:
            message = self.message
            if self.frame_ns and time.monotonic_ns()-self.frame_ns > 300_000_000:
                message = "摄像头／识别等待响应，控制已暂停"
            return {"bodies":self.tracker.candidates(self.bodies),
                    "locked":self.tracker.body,"teacher_id":self.tracker.lock_id,
                    "message":message,"state":self.engine.state,
                    "calibrating":self.recorder is not None,"paused":self.paused}

    def consume_calibration(self):
        with self.lock:
            result = self.completed_calibration
            self.completed_calibration = None
            return result

    def process(self, bodies, hands, timestamp_ns):
        with self.lock:
            if timestamp_ns <= self.frame_ns:
                self.office.revoke()
                self.engine.cancel()
                return None
            self.bodies, self.frame_ns = bodies,timestamp_ns
            if not 0 <= time.monotonic_ns()-timestamp_ns < 200_000_000:
                self.office.revoke()
                self.engine.cancel()
                self.message = "识别结果过期，已暂停"
                return None
            hand = self.tracker.update(bodies,hands,timestamp_ns)
            f = features_for(hand,self.tracker.body,self.config.mirror) if hand else None
            self.last_features = f
            if not self.tracker.lock_id:
                self.recorder = None
            if self.recorder is not None:
                self.office.revoke()
                result = self.recorder.update(f)
                self.message = self.recorder.message
                if result:
                    self.engine = ClassroomGestureEngine(result)
                    self.completed_calibration = asdict(result)
                    self.recorder = None
                return hand
            allowed = bool(f and f.quality and self.tracker.lock_id and not self.paused
                           and self.engine.calibration is not None)
            self.office.authorize(self.tracker.lock_id if allowed else "", timestamp_ns)
            office = self.office.snapshot()
            if office.token != self._last_token:
                self.engine.cancel()
                self._last_token = office.token
            event = self.engine.process(f if allowed else None,office.token,time.monotonic_ns())
            if event:
                self.office.submit(event)
            if self.paused:
                self.message = "用户已暂停"
            elif not self.tracker.lock_id or hand is None:
                self.message = self.tracker.reason
            elif self.engine.calibration is None:
                self.message = "老师已锁定，请完成课堂动作校准"
            elif not office.token:
                self.message = office.message
            else:
                self.message = f"{office.target.label} · {self.engine.state}"
            return hand


class ClassroomVisionWorker(threading.Thread):
    def __init__(self, runtime, model_path, frames, detections, stop_event, on_detection, on_error):
        super().__init__(name="classroom-vision",daemon=True)
        self.runtime,self.model_path = runtime,model_path
        self.frames,self.detections = frames,detections
        self.stop_event,self.on_detection,self.on_error = stop_event,on_detection,on_error

    def run(self):
        import cv2
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        try:
            pose_path = self.model_path.parent / "pose_landmarker_lite.task"
            po = vision.PoseLandmarkerOptions(
                base_options=BaseOptions(model_asset_buffer=pose_path.read_bytes()),
                running_mode=vision.RunningMode.VIDEO,num_poses=4,
                min_pose_detection_confidence=.5,min_pose_presence_confidence=.5,
                min_tracking_confidence=.5)
            ho = vision.HandLandmarkerOptions(
                base_options=BaseOptions(model_asset_buffer=self.model_path.read_bytes()),
                running_mode=vision.RunningMode.VIDEO,num_hands=4,
                min_hand_detection_confidence=.5,min_hand_presence_confidence=.5,
                min_tracking_confidence=.5)
            with vision.PoseLandmarker.create_from_options(po) as pose, \
                    vision.HandLandmarker.create_from_options(ho) as hands:
                revision,last_ms = 0,0
                while not self.stop_event.is_set():
                    packet,revision = self.frames.wait_next(revision,timeout=.1)
                    if packet is None:
                        self.runtime.office.revoke()
                        continue
                    # CameraWorker 已为预览镜像；模型输入还原为摄像头原始方向。
                    canonical = cv2.flip(packet.frame,1) if self.runtime.config.mirror else packet.frame
                    rgb = cv2.cvtColor(canonical,cv2.COLOR_BGR2RGB)
                    image = mp.Image(image_format=mp.ImageFormat.SRGB,data=rgb)
                    ms = max(last_ms+1,packet.captured_ns//1_000_000)
                    last_ms = ms
                    start = time.monotonic_ns()
                    pr = pose.detect_for_video(image,ms)
                    hr = hands.detect_for_video(image,ms)
                    elapsed = (time.monotonic_ns()-start)/1e6
                    bodies = tuple(BodyObservation(
                        display_landmarks(points,self.runtime.config.mirror),
                        tuple(float(p.visibility or 0) for p in points)) for points in pr.pose_landmarks)
                    observations = tuple(HandObservation(
                        display_landmarks(points,self.runtime.config.mirror),
                        hr.handedness[i][0].category_name,packet.captured_ns,elapsed,
                        handedness_score=float(hr.handedness[i][0].score))
                        for i,points in enumerate(hr.hand_landmarks))
                    if self.stop_event.is_set():
                        break
                    selected = self.runtime.process(bodies,observations,packet.captured_ns)
                    detection = DetectionPacket((selected,) if selected else (),packet.captured_ns,elapsed)
                    self.detections.put(detection)
                    self.on_detection(detection)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("课堂视觉线程异常")
            self.runtime.office.revoke()
            self.on_error("课堂人体模型初始化或识别失败，请查看日志")
