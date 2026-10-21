from dataclasses import replace
from gesture_mouse.document_gestures import DocumentGestures
from gesture_mouse.config import AppConfig
from gesture_mouse.contracts import Landmark
from conftest import observation,open_palm_points,pointer_points


def hand(t,dx=0,dy=0,mirror=True):
    # 缩小合成手，让左右移动仍位于画面内部。
    points = tuple(Landmark(.5+(p.x-.5)*.5+dx,.5+(p.y-.5)*.5+dy,p.z*.5)
                   for p in open_palm_points())
    if not mirror:
        points = tuple(replace(p,x=1-p.x) for p in points)
    return observation(points,(t+1000)*1_000_000)


def warm(engine,kind="ppt",mirror=True):
    for t in range(0,361,30):
        assert engine.process(hand(t,mirror=mirror),"session",kind)[1] is None


def test_once_and_return_never_reverses():
    e = DocumentGestures()
    warm(e)
    events=[]
    for t in range(390,701,30):
        event=e.process(hand(t,dx=-.15),"session","ppt")[1]
        if event: events.append(event)
    assert len(events)==1 and events[0].direction==1
    for t in range(720,1501,30):
        assert e.process(hand(t),"session","ppt")[1] is None


def test_word_vertical_screen_scroll():
    e=DocumentGestures()
    warm(e,"word")
    events=[e.process(hand(t,dy=.15),"session","word")[1] for t in range(390,571,30)]
    assert [v.direction for v in events if v]==[1]


def test_mirror_keeps_physical_direction():
    for mirror in (True,False):
        e=DocumentGestures(mirror)
        warm(e,mirror=mirror)
        events=[e.process(hand(t,dx=-.15,mirror=mirror),"session","ppt")[1] for t in range(390,571,30)]
        assert [v.direction for v in events if v]==[1]


def test_no_token_hand_loss_and_out_of_order_cannot_page():
    e=DocumentGestures()
    warm(e)
    assert e.process(hand(300,dx=-.2),"session","ppt")[1] is None
    assert e.process(hand(390,dx=-.2),"","ppt")== (False,None)
    assert e.process(None,"session","ppt")== (False,None)
    assert e.process(hand(420,dx=-.2),"session","ppt")[1] is None


def test_pointer_remains_available_in_document():
    e=DocumentGestures()
    assert e.process(observation(pointer_points(),1),"session","ppt")== (False,None)


def test_old_classroom_config_migrates_to_daily_without_losing_mouse_settings():
    c=AppConfig.from_mapping(dict(version=10,classroom_enabled=True,partial_finger_tracking=True,
        pointer_response=.91,camera_index=3,pinch_engage=.39))
    assert c.version==11 and not c.classroom_enabled and not c.partial_finger_tracking
    assert c.auto_office_enabled and c.camera_index==3 and c.pointer_response==.91 and c.pinch_engage==.39
