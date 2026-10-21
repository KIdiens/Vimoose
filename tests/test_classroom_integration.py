"""课堂流水线隔离、镜像和 UI 坐标边界验证。"""
from dataclasses import asdict,replace
from types import SimpleNamespace
import time
import pytest
from gesture_mouse.classroom import ClassroomCalibration,ClassroomGestureEngine,CalibrationRecorder,features_for,angle_delta
from gesture_mouse.classroom_runtime import ClassroomRuntime
from gesture_mouse.config import AppConfig
from gesture_mouse.teacher_tracking import display_landmarks,BodyObservation,TeacherTracker
from gesture_mouse.contracts import Landmark,HandObservation
from test_classroom import body,hand,feature,warm
from conftest import open_palm_points


def test_mirror_retains_physical_hand_and_relative_rotation():
    b = body()
    points = tuple(replace(p,z=(p.x-.5)*.2) for p in open_palm_points())
    h = HandObservation(points,"Right",1,0.)
    turned = replace(h,landmarks=tuple(replace(p,z=p.z+(p.x-.5)*.7) for p in points))
    original = [features_for(v,b,False) for v in (h,turned)]
    mirrored_body = BodyObservation(display_landmarks(b.points,True),b.visibility)
    mirrored = [features_for(replace(v,landmarks=display_landmarks(v.landmarks,True)),mirrored_body,True)
                for v in (h,turned)]
    assert original[1].lateral-original[0].lateral == pytest.approx(mirrored[1].lateral-mirrored[0].lateral)
    assert angle_delta(original[1].palm_angle,original[0].palm_angle) == pytest.approx(
        angle_delta(mirrored[1].palm_angle,mirrored[0].palm_angle))
    assert mirrored_body.points[16].x == pytest.approx(1-b.points[16].x)


def test_whole_body_translation_is_not_wrist_motion():
    b,h = body(),HandObservation(open_palm_points(),"Right",1,0.)
    shift = lambda points: tuple(replace(p,x=p.x+.1,y=p.y+.05) for p in points)
    first = features_for(h,b,False)
    second = features_for(replace(h,landmarks=shift(h.landmarks)),BodyObservation(shift(b.points),b.visibility),False)
    assert second.lateral == pytest.approx(first.lateral)
    assert second.palm_angle == pytest.approx(first.palm_angle)
    assert second.height == pytest.approx(first.height)


def test_control_side_ignores_other_hand():
    b = body()
    tracker = TeacherTracker(hand="Right")
    tracker.select([b],.5,.4,1)
    left,right = hand(.3,t=2),hand(.7,t=2)
    assert tracker.update([b],[left,right],2) == right


def test_old_hand_and_cropped_shoulders_are_not_authorized():
    tracker = TeacherTracker()
    tracker.select([body()],.5,.4,1)
    assert tracker.update([body()],[hand(t=1)],2) is None
    assert not body(.95).reliable()


def test_reversing_before_completion_cancels_action():
    e = ClassroomGestureEngine(ClassroomCalibration())
    warm(e)
    e.process(feature(930,.8),"a")
    e.process(feature(960,-.8),"a")
    for t in range(990,1801,30):
        assert e.process(feature(t,-.8),"a") is None


def test_long_ambiguous_action_does_not_accumulate():
    e = ClassroomGestureEngine(ClassroomCalibration())
    warm(e)
    for t in range(930,2301,30):
        assert e.process(feature(t,.45),"a") is None
    assert e.process(feature(2330,.9),"a") is None


def test_calibration_requires_complete_independent_directions():
    assert ClassroomCalibration.from_mapping({}) is None
    c = asdict(ClassroomCalibration())
    assert ClassroomCalibration.from_mapping(c) is not None
    c["previous_vector"] = [1,0]
    assert ClassroomCalibration.from_mapping(c) is None


def test_calibration_moving_neutral_does_not_finish():
    r = CalibrationRecorder()
    for t in range(0,3000,50):
        r.update(feature(t,.5 if t % 100 == 0 else -.5))
    assert r.calibration is None


def test_runtime_calibration_and_pause_revoke_office():
    r = ClassroomRuntime(AppConfig(),safe_mode=True)
    stamp = time.monotonic_ns()
    r.bodies,r.frame_ns = (body(),),stamp
    assert r.select(.5,.4)
    assert r.calibrate()
    assert r.office.owner == ""
    r.set_paused(True)
    assert r.recorder is None and not r.office.owner
    r.tracker.invalidate()
    r.set_paused(False)
    assert not r.tracker.lock_id and not r.office.owner


def test_calibration_does_not_resume_a_paused_classroom():
    r = ClassroomRuntime(AppConfig(),safe_mode=True)
    r.bodies,r.frame_ns = (body(),),time.monotonic_ns()
    assert r.select(.5,.4)
    r.set_paused(True)
    assert r.calibrate()
    assert r.paused and not r.office.owner


def test_legacy_classroom_option_cannot_bypass_daily_hotkey():
    from gesture_mouse.pipeline import GesturePipeline
    from gesture_mouse.mouse import MouseController,NullMouseBackend
    p = GesturePipeline(AppConfig(classroom_enabled=True),MouseController(NullMouseBackend()))
    p.engine.paused = True
    assert not p.config.classroom_enabled
    p.toggle_paused()
    assert not p.engine.paused
    p.toggle_paused()
    assert p.engine.paused


def test_stale_or_future_runtime_observations_revoke_office():
    for stamp in (time.monotonic_ns()-250_000_000,time.monotonic_ns()+1_000_000_000):
        r = ClassroomRuntime(AppConfig(),safe_mode=True)
        r.office.authorize("old",time.monotonic_ns())
        assert r.process((body(),),(hand(t=stamp),),stamp) is None
        assert not r.office.owner


def test_preview_letterbox_coordinates():
    from PySide6.QtCore import QPointF,QSizeF
    from gesture_mouse.classroom_ui import preview_position
    pix = SimpleNamespace(isNull=lambda:False,deviceIndependentSize=lambda:QSizeF(400,300))
    label = SimpleNamespace(pixmap=lambda:pix,width=lambda:600,height=lambda:300)
    assert preview_position(label,QPointF(50,150)) is None
    assert preview_position(label,QPointF(300,150)) == (.5,.5)


def test_legacy_classroom_config_starts_only_daily_threads(monkeypatch,tmp_path):
    from gesture_mouse.pipeline import GesturePipeline
    from gesture_mouse.mouse import MouseController,NullMouseBackend
    import gesture_mouse.pipeline as pipeline_module
    import gesture_mouse.classroom_runtime as runtime_module
    started = []
    class Thread:
        def __init__(self,*a,**k): pass
        def start(self): started.append(type(self).__name__)
        def is_alive(self): return False
    class Camera(Thread): pass
    class HandVision(Thread): pass
    class Control(Thread): pass
    monkeypatch.setattr(pipeline_module,"CameraWorker",Camera)
    monkeypatch.setattr(runtime_module.OfficeWorker,"start",lambda self:started.append("Office"))
    monkeypatch.setattr(pipeline_module,"ControlWorker",Control)
    monkeypatch.setattr(pipeline_module,"HandLandmarkerWorker",HandVision)
    # 使用仓库内真实模型路径，仅替换线程，不加载摄像头或模型。
    p = GesturePipeline(AppConfig(classroom_enabled=True),MouseController(NullMouseBackend()))
    assert p.start()
    assert started == ["Office","Camera","HandVision","Control"]
    p.emergency_stop()
    assert p.engine.paused
    p.stop()
