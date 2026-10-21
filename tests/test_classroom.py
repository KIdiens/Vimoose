"""课堂安全与教师归属回归，不调用摄像头或真实 Office。"""
from dataclasses import replace, asdict
import pytest
from gesture_mouse.classroom import ClassroomCalibration,ClassroomGestureEngine,HandFeatures,CalibrationRecorder,features_for
from gesture_mouse.contracts import Landmark,HandObservation
from gesture_mouse.teacher_tracking import BodyObservation,TeacherTracker
from gesture_mouse.config import AppConfig


def body(x=.5,y=.4):
    p = [Landmark(x,y) for _ in range(33)]
    for i,dx,dy in ((11,-.1,0),(12,.1,0),(13,-.16,.06),(14,.16,.06),(15,-.2,-.05),(16,.2,-.05)):
        p[i] = Landmark(x+dx,y+dy)
    return BodyObservation(tuple(p),(1.,)*33)


def hand(x=.7,y=.35,t=1):
    return HandObservation(tuple([Landmark(x,y)]+[Landmark(x,y-.04)]*20),"Right",t,1.)


def feature(ms,x=0.,angle=0.,height=0.,opened=True):
    return HandFeatures(1_000_000_000+int(ms*1e6),x,angle,height,opened)


def warm(engine):
    for t in range(0,901,30):
        assert engine.process(feature(t),"a") is None


@pytest.mark.parametrize("direction",[1,-1])
def test_one_action_one_event_and_return_is_not_reverse(direction):
    engine = ClassroomGestureEngine(ClassroomCalibration())
    warm(engine)
    events = []
    for t in range(930,1801,30):
        e = engine.process(feature(t,.8*direction),"a")
        if e: events.append(e)
    assert [e.direction for e in events] == [direction]
    for t in range(1830,2201,30):
        assert engine.process(feature(t),"a") is None
    assert engine.state == "可翻页"


def test_missing_hand_cancels_partial_action():
    engine = ClassroomGestureEngine(ClassroomCalibration())
    warm(engine)
    engine.process(feature(930,.8),"a")
    engine.process(None,"a")
    for t in range(960,2000,30):
        assert engine.process(feature(t,.8),"a") is None


@pytest.mark.parametrize("kind",["stale","future","reverse","height","quality","no_session"])
def test_unreliable_input_never_produces_event(kind):
    engine = ClassroomGestureEngine(ClassroomCalibration())
    warm(engine)
    f,now,session = feature(930,.8),None,"a"
    if kind == "stale": now = f.timestamp_ns+200_000_000
    if kind == "future": now = f.timestamp_ns-1
    if kind == "reverse": f = feature(800,.8)
    if kind == "height": f = replace(f,height=2.)
    if kind == "quality": f = replace(f,quality=False)
    if kind == "no_session": session = ""
    assert engine.process(f,session,now) is None
    assert engine.state != "可翻页"


def test_no_calibration_is_safe():
    engine = ClassroomGestureEngine(None)
    for t in range(0,3000,30):
        assert engine.process(feature(t,.8),"a") is None


def test_teacher_array_reorder_does_not_change_identity():
    teacher,student = body(),body(.15,.8)
    tracker = TeacherTracker()
    assert tracker.select([teacher,student],.5,.4,1)
    identity = tracker.lock_id
    selected = hand(t=2)
    assert tracker.update([student,teacher],[hand(.9,.1),selected],2) == selected
    assert tracker.lock_id == identity


def test_student_higher_or_closer_does_not_take_control():
    teacher,student = body(),body(.1,.15)
    tracker = TeacherTracker()
    tracker.select([teacher],.5,.4,1)
    assert tracker.update([teacher,student],[hand(.3,.1)],2) is None
    assert tracker.lock_id


def test_body_loss_requires_manual_reselection():
    tracker = TeacherTracker()
    tracker.select([body()],.5,.4,1)
    tracker.update([],[],2)
    assert not tracker.lock_id
    assert tracker.update([body()],[hand()],3) is None
    assert tracker.select([body()],.5,.4,4)


def test_crossing_people_invalidates_identity():
    tracker = TeacherTracker()
    tracker.select([body()],.5,.4,1)
    tracker.update([body(.49),body(.51)],[hand()],2)
    assert not tracker.lock_id


def test_two_matching_hands_are_rejected():
    tracker = TeacherTracker()
    tracker.select([body()],.5,.4,1)
    assert tracker.update([body()],[hand(),hand(.71)],2) is None


def test_partial_finger_does_not_authorize_discrete_action():
    tracker = TeacherTracker()
    tracker.select([body()],.5,.4,1)
    assert tracker.update([body()],[replace(hand(),partial_finger="Index")],2) is None


def test_region_and_old_body_observation_rejected():
    tracker = TeacherTracker((.3,.2,.8,.8))
    assert not tracker.select([body(.1)],.1,.4,1)
    assert tracker.select([body()],.5,.4,1)
    tracker.update([body()],[hand()],600_000_001)
    assert not tracker.lock_id


def test_calibration_six_actions_and_configuration_signature():
    recorder = CalibrationRecorder()
    for t in range(0,1100,30): recorder.update(feature(t))
    t,result = 1110,None
    for direction in (1,-1):
        for _ in range(3):
            for _ in range(10):
                result = recorder.update(feature(t,.8*direction)); t += 30
            result = recorder.update(feature(t)); t += 30
    assert result is not None
    cfg = AppConfig(classroom_calibration=asdict(result))
    cfg.classroom_camera_signature = cfg.classroom_signature()
    cfg.validate()
    assert cfg.classroom_calibration
    cfg.camera_index += 1
    cfg.validate()
    assert not cfg.classroom_calibration


def test_config_v9_migration_preserves_mouse():
    cfg = AppConfig.from_mapping({"version":9,"pinch_engage":.51,"classroom_region":[0,0,0,0]})
    cfg.validate()
    assert cfg.version == 11 and cfg.pinch_engage == .51
    assert not cfg.classroom_enabled
    assert cfg.classroom_region == [0,0,1,1]
    assert ClassroomCalibration.from_mapping({"next_threshold":float("nan")}) is None
