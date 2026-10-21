from gesture_mouse.hand_guard import HandGuard
from gesture_mouse.contracts import Landmark
from conftest import pointer_points


def test_small_nose_skeleton_inside_face_never_acquires_control():
    guard = HandGuard()
    nose = tuple(Landmark(.48+(p.x-.5)*.2,.48+(p.y-.5)*.2,p.z) for p in pointer_points())
    for t in range(0, 2000, 33):
        assert not guard.accept(nose,t,[(.15,.05,.85,.95)])


def test_real_hand_overlapping_face_is_not_blanket_masked():
    guard = HandGuard()
    assert not guard.accept(pointer_points(),0,[(.15,.05,.85,.95)])
    assert not guard.accept(pointer_points(),80,[(.15,.05,.85,.95)])
    assert guard.accept(pointer_points(),170,[(.15,.05,.85,.95)])


def test_one_frame_or_new_identity_cannot_move_pointer():
    guard = HandGuard()
    assert not guard.accept(pointer_points(),0,[])
    assert not guard.accept(pointer_points(),1000,[])
    assert guard.accept(pointer_points(),1170,[])
    other = tuple(Landmark(p.x-.5,p.y,p.z) for p in pointer_points())
    assert not guard.accept(other,1200,[])


def test_invalid_coordinates_and_collapsed_palm_rejected():
    assert not HandGuard().accept(tuple(Landmark(.5,.5) for _ in range(21)),0,[])
    p = list(pointer_points())
    p[8] = Landmark(float('nan'),0)
    assert not HandGuard().accept(tuple(p),0,[])
