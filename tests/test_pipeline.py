import threading
import time

from gesture_mouse.config import AppConfig
from gesture_mouse.contracts import (
    DetectionPacket,
    GestureType,
    Landmark,
    MouseCommand,
    MouseCommandType,
)
from gesture_mouse.gestures import GestureEngine
from gesture_mouse.latest_slot import LatestSlot
from gesture_mouse.mouse import MouseController, NullMouseBackend
from gesture_mouse.pipeline import ControlWorker, GesturePipeline

from conftest import observation, open_palm_points, pointer_points, right_pinch_points, left_pinch_points


def test_click_contact_cannot_move_actual_backend_then_clicks_same_position():
    backend=NullMouseBackend()
    engine=GestureEngine(AppConfig())
    worker=ControlWorker(LatestSlot(),engine,MouseController(backend),threading.Event(),lambda *a:None,42)
    base=time.monotonic_ns()
    points=pointer_points()
    worker._execute_commands(engine.process(observation(points,base)))
    before=list(backend.commands)
    contact=tuple(Landmark(p.x+.08,p.y+.05,p.z) for p in left_pinch_points())
    worker._execute_commands(engine.process(observation(contact,base+45_000_000)))
    worker._advance_motion(base+60_000_000)
    assert backend.commands==before
    worker._execute_commands(engine.process(observation(pointer_points(),base+110_000_000)))
    assert backend.commands[-1][0]=="left_click"
    assert [c for c in backend.commands if c[0]=="move"]==[c for c in before if c[0]=="move"]


def test_explicit_empty_detection_cancels_click_without_waiting_for_timeout():
    engine=GestureEngine(AppConfig())
    worker=ControlWorker(LatestSlot(),engine,MouseController(NullMouseBackend()),threading.Event(),lambda *a:None,42)
    t=time.monotonic_ns()
    for offset in (0,50):
        worker._commands_for_packet(DetectionPacket((observation(left_pinch_points(),t+offset*1_000_000),),t+offset*1_000_000,0),t+offset*1_000_000)
    assert not worker._commands_for_packet(DetectionPacket((),t+70_000_000,0),t+70_000_000)
    commands=worker._commands_for_packet(DetectionPacket((observation(pointer_points(),t+100_000_000),),t+100_000_000,0),t+100_000_000)
    assert MouseCommandType.LEFT_CLICK not in [c.kind for c in commands]


def test_document_adapter_cannot_bypass_selected_control_hand():
    from types import SimpleNamespace
    revoked=[]
    office=SimpleNamespace(revoke=lambda:revoked.append(True))
    engine=GestureEngine(AppConfig(handedness="Left"))
    worker=ControlWorker(LatestSlot(),engine,MouseController(NullMouseBackend()),threading.Event(),lambda *a:None,42,office=office)
    t=time.monotonic_ns()
    wrong=observation(open_palm_points(),t)
    assert wrong.handedness=="Right"
    assert worker._commands_for_packet(DetectionPacket((wrong,),t,0),t)==[]
    assert revoked


def test_pinch_lock_cancels_pending_cursor_interpolation() -> None:
    backend = NullMouseBackend()
    engine = GestureEngine(AppConfig())
    worker = ControlWorker(
        LatestSlot(),
        engine,
        MouseController(backend),
        threading.Event(),
        lambda _gesture, _paused: None,
        interpolation_ms=42,
    )
    now = time.monotonic_ns()
    worker._execute_commands(
        [MouseCommand(MouseCommandType.MOVE, now, x=0.20, y=0.30)],
    )
    worker._execute_commands(
        [MouseCommand(MouseCommandType.MOVE, now + 1, x=0.80, y=0.70)],
    )
    moves_before_lock = [item for item in backend.commands if item[0] == "move"]

    engine.current_gesture = GestureType.PINCH_ARMED
    worker._advance_motion(now + 12_000_000)
    moves_after_lock = [item for item in backend.commands if item[0] == "move"]

    assert moves_after_lock == moves_before_lock


def test_stale_detection_packet_is_dropped_before_state_machine() -> None:
    config = AppConfig(hand_lost_ms=200)
    engine = GestureEngine(config)
    worker = ControlWorker(
        LatestSlot(),
        engine,
        MouseController(NullMouseBackend()),
        threading.Event(),
        lambda _gesture, _paused: None,
        interpolation_ms=42,
    )
    now = time.monotonic_ns()
    stale_ns = now - 350_000_000
    hand = observation(pointer_points(), stale_ns)
    packet = DetectionPacket(
        observations=(hand,),
        timestamp_ns=stale_ns,
        inference_ms=350.0,
    )

    commands = worker._commands_for_packet(packet, now)

    assert commands == []
    assert engine.current_gesture == GestureType.NONE


def test_packet_older_than_latency_budget_cannot_start_discrete_gesture() -> None:
    """仍未到丢手时限、但已超过100ms响应预算的捏合不能进入状态机。"""

    config = AppConfig(hand_lost_ms=200)
    engine = GestureEngine(config)
    worker = ControlWorker(
        LatestSlot(),
        engine,
        MouseController(NullMouseBackend()),
        threading.Event(),
        lambda _gesture, _paused: None,
        interpolation_ms=42,
    )
    now = time.monotonic_ns()
    delayed_ns = now - 110_000_000
    packet = DetectionPacket(
        observations=(observation(right_pinch_points(), delayed_ns),),
        timestamp_ns=delayed_ns,
        inference_ms=110.0,
    )

    commands = worker._commands_for_packet(packet, now)

    assert commands == []
    assert engine.current_gesture == GestureType.NONE


def test_out_of_order_detection_packet_cannot_change_gesture_state() -> None:
    """异步回调时间戳倒退时，旧捏合不得覆盖更新的指向状态。"""

    engine = GestureEngine(AppConfig(hand_lost_ms=200))
    worker = ControlWorker(
        LatestSlot(),
        engine,
        MouseController(NullMouseBackend()),
        threading.Event(),
        lambda _gesture, _paused: None,
        interpolation_ms=42,
    )
    base = time.monotonic_ns()

    for offset_ms in (0, 40, 80):
        timestamp_ns = base + offset_ms * 1_000_000
        packet = DetectionPacket(
            observations=(observation(pointer_points(), timestamp_ns),),
            timestamp_ns=timestamp_ns,
            inference_ms=12.0,
        )
        worker._commands_for_packet(packet, timestamp_ns + 12_000_000)

    delayed_timestamp_ns = base + 40_000_000
    delayed = DetectionPacket(
        observations=(
            observation(right_pinch_points(), delayed_timestamp_ns),
        ),
        timestamp_ns=delayed_timestamp_ns,
        inference_ms=12.0,
    )
    delayed_commands = worker._commands_for_packet(
        delayed,
        base + 150_000_000,
    )
    latest_timestamp_ns = base + 180_000_000
    latest = DetectionPacket(
        observations=(observation(pointer_points(), latest_timestamp_ns),),
        timestamp_ns=latest_timestamp_ns,
        inference_ms=12.0,
    )
    latest_commands = worker._commands_for_packet(
        latest,
        latest_timestamp_ns + 12_000_000,
    )

    assert delayed_commands == []
    assert MouseCommandType.RIGHT_CLICK not in [
        command.kind for command in latest_commands
    ]
    assert engine.current_gesture == GestureType.POINTER


def test_side_view_hand_size_metric_uses_robust_scale() -> None:
    backend = NullMouseBackend()
    pipeline = GesturePipeline(AppConfig(), MouseController(backend))
    points = open_palm_points()
    center_x = points[9].x
    side = tuple(
        Landmark(
            center_x + (point.x - center_x) * 0.10,
            point.y,
            point.z,
        )
        for point in points
    )
    now = time.monotonic_ns()
    packet = DetectionPacket(
        observations=(observation(side, now),),
        timestamp_ns=now,
        inference_ms=10.0,
    )

    pipeline._on_detection(packet)

    assert pipeline.snapshot().metrics.palm_width_percent >= 9.0
