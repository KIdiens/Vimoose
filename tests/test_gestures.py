from gesture_mouse.config import AppConfig
from gesture_mouse.contracts import HandObservation, Landmark, MouseCommandType
from gesture_mouse.gestures import ControlState, GestureEngine

from conftest import (
    bent_middle_right_pinch_points,
    ambiguous_right_pinch_points,
    collapsed_index_near_thumb_points,
    fist_like_left_pinch_points,
    fist_points,
    left_pinch_points,
    middle_tucked_pointer_points,
    observation,
    open_palm_points,
    pointer_points,
    right_pinch_from_open_points,
    right_pinch_points,
    rotated_projected_closed_points,
    rotated_scroll_points,
    thumb_outside_fist_points,
    thumb_outside_left_contact_points,
    thumb_outside_open_palm_points,
    thumb_outside_right_contact_points,
    translate_points,
)


BASE = 1_000_000_000


def kinds(commands):
    return [command.kind for command in commands]


def compress_hand_width(points, factor: float = 0.25):
    """模拟侧手时掌宽在图像平面中明显缩短。"""

    center_x = points[9].x
    return tuple(
        Landmark(
            center_x + (point.x - center_x) * factor,
            point.y,
            point.z,
        )
        for point in points
    )


def left_ratio_points(ratio: float):
    """生成指定拇指—食指归一化距离的完整手部。"""

    points = list(pointer_points())
    palm_width = ((points[5].x - points[17].x) ** 2 + (points[5].y - points[17].y) ** 2) ** 0.5
    palm_length = ((points[0].x - points[9].x) ** 2 + (points[0].y - points[9].y) ** 2) ** 0.5
    scale = max(palm_width, palm_length * 0.75)
    points[4] = Landmark(points[8].x - ratio * scale, points[8].y, points[4].z)
    return tuple(points)


def side_right_width_ratio_points(
    ratio: float,
    *,
    opened: bool = False,
    factor: float = 0.10,
):
    """生成侧手投影下指定拇指—中指掌宽比的手部。"""

    source = open_palm_points() if opened else right_pinch_from_open_points()
    points = list(compress_hand_width(source, factor=factor))
    palm_width = (
        (points[5].x - points[17].x) ** 2
        + (points[5].y - points[17].y) ** 2
    ) ** 0.5
    points[4] = Landmark(
        points[12].x - ratio * palm_width,
        points[12].y,
        points[4].z,
    )
    return tuple(points)


def shrink_palm_width_only(points, factor: float):
    """只改变5–17掌宽估计，保持拇指—中指实际距离不变。"""

    narrowed = list(points)
    center_x = (narrowed[5].x + narrowed[17].x) / 2
    center_y = (narrowed[5].y + narrowed[17].y) / 2
    for index in (5, 17):
        point = narrowed[index]
        narrowed[index] = Landmark(
            center_x + (point.x - center_x) * factor,
            center_y + (point.y - center_y) * factor,
            point.z,
        )
    return tuple(narrowed)


def scale_hand_about_wrist(points, factor: float):
    """模拟手靠近镜头时整只手按同一比例放大。"""

    wrist = points[0]
    return tuple(
        Landmark(
            wrist.x + (point.x - wrist.x) * factor,
            wrist.y + (point.y - wrist.y) * factor,
            wrist.z + (point.z - wrist.z) * factor,
        )
        for point in points
    )


def test_pointer_generates_move() -> None:
    engine = GestureEngine(AppConfig())
    commands = engine.process(observation(pointer_points(), BASE))
    assert kinds(commands) == [MouseCommandType.MOVE]
    assert 0 <= commands[0].x <= 1
    assert 0 <= commands[0].y <= 1


def test_index_identity_jump_cannot_turn_pointer_into_left_click() -> None:
    """录像复现：食指关键点瞬移到掌心不能被当成一次左捏合。"""

    engine = GestureEngine(AppConfig())
    first = engine.process(observation(pointer_points(), BASE))
    collapsed = engine.process(
        observation(collapsed_index_near_thumb_points(), BASE + 40_000_000),
    )
    recovered = engine.process(
        observation(pointer_points(), BASE + 100_000_000),
    )

    assert kinds(first) == [MouseCommandType.MOVE]
    assert collapsed == []
    assert kinds(recovered) == [MouseCommandType.MOVE]
    assert MouseCommandType.LEFT_CLICK not in kinds(collapsed + recovered)


def test_sustained_index_identity_fault_keeps_cursor_locked_until_reopen() -> None:
    """错误食指身份持续数帧时，既不能点击也不能把光标拉到掌心。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))
    first = engine.process(
        observation(collapsed_index_near_thumb_points(), BASE + 40_000_000),
    )
    second = engine.process(
        observation(collapsed_index_near_thumb_points(), BASE + 80_000_000),
    )
    third = engine.process(
        observation(collapsed_index_near_thumb_points(), BASE + 120_000_000),
    )
    recovered = engine.process(
        observation(pointer_points(), BASE + 160_000_000),
    )

    assert first + second + third == []
    assert kinds(recovered) == [MouseCommandType.MOVE]


def test_pointer_reaches_screen_edge_before_landmark_leaves_camera() -> None:
    """默认安全区内的食指位置应已能覆盖屏幕最右侧。"""

    points = list(pointer_points())
    points[6] = Landmark(0.55, 0.45)
    points[7] = Landmark(0.68, 0.33)
    points[8] = Landmark(0.81, points[8].y)
    engine = GestureEngine(AppConfig())

    commands = engine.process(observation(tuple(points), BASE))

    assert kinds(commands) == [MouseCommandType.MOVE]
    assert commands[0].x == 1.0


def test_natural_pointer_tolerates_partially_extended_middle_finger() -> None:
    points = list(pointer_points())
    points[12] = Landmark(0.51, 0.38)
    engine = GestureEngine(AppConfig())

    commands = engine.process(observation(tuple(points), BASE))

    assert kinds(commands) == [MouseCommandType.MOVE]


def test_relaxed_curved_index_still_controls_pointer() -> None:
    """手已经被模型检测到时，不应再要求用户维持僵硬的标准食指姿势。"""

    points = list(pointer_points())
    points[8] = Landmark(0.70, 0.20)
    points[12] = Landmark(0.51, 0.32)
    engine = GestureEngine(AppConfig())

    commands = engine.process(observation(tuple(points), BASE))

    assert kinds(commands) == [MouseCommandType.MOVE]


def test_pinch_ignores_unstable_depth_coordinate() -> None:
    points = list(left_pinch_points())
    points[4] = Landmark(points[4].x, points[4].y, 0.25)
    engine = GestureEngine(AppConfig())

    assert engine.process(observation(tuple(points), BASE)) == []
    commands = engine.process(observation(pointer_points(), BASE + 120_000_000))

    assert kinds(commands) == [MouseCommandType.LEFT_CLICK]


def test_pointer_extension_ignores_unstable_depth_coordinate() -> None:
    points = list(pointer_points())
    points[8] = Landmark(points[8].x, points[8].y, 0.5)
    engine = GestureEngine(AppConfig())

    commands = engine.process(observation(tuple(points), BASE))

    assert kinds(commands) == [MouseCommandType.MOVE]


def test_short_left_pinch_clicks_only_after_release() -> None:
    engine = GestureEngine(AppConfig())
    assert engine.process(observation(left_pinch_points(), BASE)) == []

    commands = engine.process(
        observation(pointer_points(), BASE + 200_000_000),
    )

    assert kinds(commands) == [MouseCommandType.LEFT_CLICK]


def test_left_pinch_must_reopen_before_noise_can_start_another_click() -> None:
    """阈值附近抖动不能把一次捏合重复解释成多次点击。"""

    engine = GestureEngine(AppConfig())
    emitted = []
    for index, ratio in enumerate((0.40, 0.56, 0.40, 0.56, 0.40, 0.56)):
        emitted.extend(
            engine.process(
                observation(left_ratio_points(ratio), BASE + index * 33_000_000),
            ),
        )

    assert kinds(emitted) == []


def test_single_frame_left_contact_is_not_a_click() -> None:
    """33ms单帧阈值跳变属于关键点噪声，不应形成首次幽灵点击。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(left_ratio_points(0.50), BASE))
    engine.process(
        observation(left_ratio_points(0.40), BASE + 33_000_000),
    )
    released = engine.process(
        observation(left_ratio_points(0.56), BASE + 66_000_000),
    )

    assert MouseCommandType.LEFT_CLICK not in kinds(released)


def test_single_frame_left_contact_at_measured_camera_interval_is_not_a_click() -> None:
    """约22fps时一帧接触已超过45ms，仍不能把阈值抖动当成左击。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(left_ratio_points(0.50), BASE))
    engine.process(
        observation(left_ratio_points(0.40), BASE + 46_000_000),
    )
    released = engine.process(
        observation(left_ratio_points(0.56), BASE + 92_000_000),
    )

    assert MouseCommandType.LEFT_CLICK not in kinds(released)


def test_single_frame_deep_left_contact_remains_responsive_at_low_fps() -> None:
    """明确深捏合即使只采到一帧，也应在松开时保持快速左击。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(left_ratio_points(0.50), BASE))
    engine.process(
        observation(left_ratio_points(0.20), BASE + 46_000_000),
    )
    released = engine.process(
        observation(left_ratio_points(0.85), BASE + 92_000_000),
    )

    assert kinds(released) == [MouseCommandType.LEFT_CLICK]


def test_left_pinch_can_click_again_after_deliberate_reopen() -> None:
    """防重复机制不能破坏用户主动张开后的双击。"""

    engine = GestureEngine(AppConfig())
    emitted = []
    sequence = (
        (0, 0.40),
        (60, 0.40),
        (120, 0.85),
        (240, 0.40),
        (300, 0.40),
        (360, 0.85),
    )
    for offset_ms, ratio in sequence:
        emitted.extend(
            engine.process(
                observation(
                    left_ratio_points(ratio),
                    BASE + offset_ms * 1_000_000,
                ),
            ),
        )

    assert [kind for kind in kinds(emitted) if kind == MouseCommandType.LEFT_CLICK] == [
        MouseCommandType.LEFT_CLICK,
        MouseCommandType.LEFT_CLICK,
    ]


def test_left_pinch_rearms_after_moderate_deliberate_reopen() -> None:
    """无需夸张张开到arm阈值，跨过稳定松开区就应允许下一次点击。"""

    engine = GestureEngine(AppConfig())
    emitted = []
    sequence = (
        (0, 0.40),
        (60, 0.40),
        (120, 0.62),
        (240, 0.40),
        (300, 0.40),
        (360, 0.62),
    )
    for offset_ms, ratio in sequence:
        emitted.extend(
            engine.process(
                observation(
                    left_ratio_points(ratio),
                    BASE + offset_ms * 1_000_000,
                ),
            ),
        )

    assert [kind for kind in kinds(emitted) if kind == MouseCommandType.LEFT_CLICK] == [
        MouseCommandType.LEFT_CLICK,
        MouseCommandType.LEFT_CLICK,
    ]


def test_partial_index_does_not_clear_left_click_rearm_requirement() -> None:
    """浅左击后的单指续跟踪不能绕过“重新张开”保护。"""

    engine = GestureEngine(AppConfig())
    first = []
    for offset_ms, ratio in ((0, 0.40), (60, 0.40), (120, 0.56)):
        first.extend(
            engine.process(
                observation(
                    left_ratio_points(ratio),
                    BASE + offset_ms * 1_000_000,
                ),
            ),
        )
    partial = HandObservation(
        landmarks=(),
        handedness="Right",
        timestamp_ns=BASE + 160_000_000,
        inference_ms=12.0,
        handedness_score=0.98,
        partial_finger="Index",
        partial_position=Landmark(0.40, 0.30),
    )
    engine.process(partial)
    engine.process(observation(left_ratio_points(0.40), BASE + 1_300_000_000))
    second_contact = engine.process(
        observation(left_ratio_points(0.40), BASE + 2_360_000_000),
    )
    second_contact += engine.process(
        observation(left_ratio_points(0.40), BASE + 2_420_000_000),
    )
    restored = engine.process(
        observation(pointer_points(), BASE + 2_480_000_000),
    )

    assert kinds(first) == [MouseCommandType.LEFT_CLICK]
    assert MouseCommandType.LEFT_CLICK not in kinds(second_contact + restored)


def test_hand_loss_does_not_clear_left_click_rearm_requirement() -> None:
    """丢手保护释放状态后，仍需看到明确张开才能再次左击。"""

    engine = GestureEngine(AppConfig())
    first = []
    for offset_ms, ratio in ((0, 0.40), (60, 0.40), (120, 0.56)):
        first.extend(
            engine.process(
                observation(
                    left_ratio_points(ratio),
                    BASE + offset_ms * 1_000_000,
                ),
            ),
        )
    engine.tick(BASE + 400_000_000)
    engine.process(observation(left_ratio_points(0.40), BASE + 1_300_000_000))
    second_contact = engine.process(
        observation(left_ratio_points(0.40), BASE + 2_360_000_000),
    )
    second_contact += engine.process(
        observation(left_ratio_points(0.40), BASE + 2_420_000_000),
    )
    restored = engine.process(
        observation(pointer_points(), BASE + 2_480_000_000),
    )

    assert kinds(first) == [MouseCommandType.LEFT_CLICK]
    assert MouseCommandType.LEFT_CLICK not in kinds(second_contact + restored)


def test_unfinished_left_pinch_cannot_resume_as_click_after_hand_loss() -> None:
    """丢手前未完成的左捏合，恢复后必须先明确张开才能重新开始。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(left_ratio_points(0.40), BASE))
    engine.process(
        observation(left_ratio_points(0.40), BASE + 60_000_000),
    )

    lost = engine.tick(BASE + 300_000_000)
    restarting = engine.process(
        observation(left_ratio_points(0.40), BASE + 400_000_000),
    )
    engine.process(
        observation(left_ratio_points(0.40), BASE + 1_400_000_000),
    )
    engine.process(
        observation(left_ratio_points(0.40), BASE + 1_460_000_000),
    )
    released = engine.process(
        observation(pointer_points(), BASE + 1_520_000_000),
    )

    assert lost == []
    assert kinds(restarting) == [MouseCommandType.MOVE]
    assert MouseCommandType.LEFT_CLICK not in kinds(released)


def test_side_view_near_pinch_uses_palm_length_when_projected_width_collapses() -> None:
    """侧手掌宽变窄时，轻捏合仍应进入左键而不是被当作普通移动。"""

    points = list(compress_hand_width(left_pinch_points()))
    points[4] = Landmark(points[8].x - 0.05, points[8].y, points[4].z)
    engine = GestureEngine(AppConfig())

    started = engine.process(observation(tuple(points), BASE))
    started_gesture = engine.current_gesture.value
    engine.process(observation(tuple(points), BASE + 80_000_000))
    released = engine.process(
        observation(compress_hand_width(pointer_points()), BASE + 160_000_000),
    )

    assert started == []
    assert started_gesture == "left_pinch"
    assert kinds(released) == [MouseCommandType.LEFT_CLICK]


def test_side_view_small_vertical_jitter_does_not_trigger_scroll() -> None:
    """侧手投影不能把很小的掌心抖动放大成一次滚轮操作。"""

    start = compress_hand_width(open_palm_points())
    engine = GestureEngine(AppConfig())
    engine.process(observation(start, BASE))

    commands = engine.process(
        observation(translate_points(start, dy=-0.012), BASE + 100_000_000),
    )

    assert commands == []


def test_side_view_deliberate_vertical_motion_still_scrolls() -> None:
    """降低侧手误滚轮后，明确的张掌移动仍必须保持灵敏。"""

    start = compress_hand_width(open_palm_points())
    engine = GestureEngine(AppConfig())
    engine.process(observation(start, BASE))

    commands = engine.process(
        observation(translate_points(start, dy=-0.035), BASE + 100_000_000),
    )

    assert kinds(commands) == [MouseCommandType.WHEEL]


def test_fist_like_left_pinch_has_priority_over_pause_confirmation() -> None:
    """录像复现：食指与拇指接触时不能先进入握拳确认。"""

    engine = GestureEngine(AppConfig(fist_hold_ms=500))
    started = engine.process(observation(fist_like_left_pinch_points(), BASE))
    held = engine.process(
        observation(fist_like_left_pinch_points(), BASE + 700_000_000),
    )
    released = engine.process(
        observation(pointer_points(), BASE + 760_000_000),
    )

    assert started == []
    assert held == []
    assert engine.paused is False
    assert kinds(released) == [MouseCommandType.LEFT_CLICK]


def test_default_drag_requires_two_seconds_of_continuous_pinch() -> None:
    """最新视频反馈要求将默认拖拽等待从5秒缩短。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(left_pinch_points(), BASE))

    before_threshold = engine.process(
        observation(left_pinch_points(), BASE + 1_900_000_000),
    )
    at_threshold = engine.process(
        observation(left_pinch_points(), BASE + 2_010_000_000),
    )

    assert before_threshold == []
    assert kinds(at_threshold) == [MouseCommandType.LEFT_DOWN, MouseCommandType.MOVE]


def test_thumb_outside_frame_cannot_start_false_left_pinch() -> None:
    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))

    commands = engine.process(
        observation(thumb_outside_left_contact_points(), BASE + 40_000_000),
    )

    assert kinds(commands) == [MouseCommandType.MOVE]
    assert engine.current_gesture.value == "pointer"


def test_thumb_outside_frame_cannot_start_false_right_pinch() -> None:
    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))

    commands = engine.process(
        observation(thumb_outside_right_contact_points(), BASE + 40_000_000),
    )

    assert kinds(commands) == [MouseCommandType.MOVE]
    assert engine.current_gesture.value == "pointer"


def test_thumb_outside_frame_cancels_pending_pinch_without_click() -> None:
    engine = GestureEngine(AppConfig())
    engine.process(observation(left_pinch_points(), BASE))

    commands = engine.process(
        observation(thumb_outside_left_contact_points(), BASE + 80_000_000),
    )

    assert MouseCommandType.LEFT_CLICK not in kinds(commands)
    assert engine.current_gesture.value == "pointer"


def test_irrelevant_pinky_outside_does_not_block_left_click() -> None:
    """左键只依赖掌心、拇指和食指，小指越界不应制造一秒死区。"""

    pinch = list(left_pinch_points())
    pinch[20] = Landmark(1.04, pinch[20].y, pinch[20].z)
    engine = GestureEngine(AppConfig())

    started = engine.process(observation(tuple(pinch), BASE))
    released = engine.process(observation(pointer_points(), BASE + 160_000_000))

    assert started == []
    assert kinds(released) == [MouseCommandType.LEFT_CLICK]


def test_incomplete_open_palm_cannot_scroll_but_does_not_poison_next_click() -> None:
    """不完整张掌不能滚轮，但无关指尖越界后可立即使用完整左键。"""

    incomplete = list(open_palm_points())
    incomplete[20] = Landmark(1.04, incomplete[20].y, incomplete[20].z)
    engine = GestureEngine(AppConfig())
    first = engine.process(observation(tuple(incomplete), BASE))
    engine.process(observation(left_pinch_points(), BASE + 80_000_000))
    released = engine.process(observation(pointer_points(), BASE + 180_000_000))

    assert MouseCommandType.WHEEL not in kinds(first)
    assert kinds(released) == [MouseCommandType.LEFT_CLICK]


def test_edge_excursion_requires_one_second_of_complete_hand_before_click() -> None:
    """录像复现：模型把出框拇指短暂猜回画面内时也不能形成假点击。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))
    engine.process(
        observation(thumb_outside_left_contact_points(), BASE + 100_000_000),
    )

    first_hallucination = engine.process(
        observation(left_pinch_points(), BASE + 200_000_000),
    )
    still_unstable = engine.process(
        observation(left_pinch_points(), BASE + 900_000_000),
    )
    rearmed = engine.process(
        observation(left_pinch_points(), BASE + 1_210_000_000),
    )
    released = engine.process(
        observation(pointer_points(), BASE + 1_350_000_000),
    )

    assert kinds(first_hallucination) == [MouseCommandType.MOVE]
    assert kinds(still_unstable) == [MouseCommandType.MOVE]
    assert rearmed == []
    assert kinds(released) == [MouseCommandType.LEFT_CLICK]


def test_incomplete_hand_cannot_pause_or_enter_scroll() -> None:
    fist_engine = GestureEngine(AppConfig(fist_hold_ms=500))
    fist_engine.process(observation(thumb_outside_fist_points(), BASE))
    held = fist_engine.process(
        observation(thumb_outside_fist_points(), BASE + 700_000_000),
    )

    scroll_engine = GestureEngine(AppConfig())
    scroll = scroll_engine.process(
        observation(thumb_outside_open_palm_points(), BASE),
    )

    assert fist_engine.paused is False
    assert MouseCommandType.PAUSE not in kinds(held)
    assert fist_engine.current_gesture.value == "pointer"
    assert kinds(scroll) == [MouseCommandType.MOVE]
    assert scroll_engine.current_gesture.value == "pointer"


def test_pre_pinch_intent_freezes_pointer_before_contact() -> None:
    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))
    near_pinch = list(pointer_points())
    near_pinch[4] = Landmark(0.42, 0.335)

    commands = engine.process(
        observation(tuple(near_pinch), BASE + 45_000_000),
    )

    assert commands == []
    assert engine.current_gesture.value == "pinch_armed"


def test_natural_thumb_gap_does_not_freeze_pointer_too_early() -> None:
    """处于release与arm之间的自然指向姿势仍应保持光标移动。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))

    commands = engine.process(
        observation(left_ratio_points(0.66), BASE + 45_000_000),
    )

    assert kinds(commands) == [MouseCommandType.MOVE]
    assert engine.current_gesture.value == "pointer"


def test_direct_pinch_keeps_aimed_position_even_when_contact_tip_moves() -> None:
    """捏合帧食指因弯曲变位时，不再把点击位置挪到新指尖。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))
    moved_contact = translate_points(left_pinch_points(), dx=0.25)

    entered = engine.process(
        observation(moved_contact, BASE + 45_000_000),
    )
    released = engine.process(
        observation(
            translate_points(pointer_points(), dx=0.25),
            BASE + 100_000_000,
        ),
    )

    assert entered == []
    assert kinds(released) == [MouseCommandType.LEFT_CLICK]


def test_long_left_pinch_becomes_drag_then_releases() -> None:
    engine = GestureEngine(AppConfig(drag_hold_ms=300))
    engine.process(observation(left_pinch_points(), BASE))

    held = engine.process(
        observation(left_pinch_points(), BASE + 310_000_000),
    )
    released = engine.process(
        observation(pointer_points(), BASE + 360_000_000),
    )

    assert kinds(held) == [MouseCommandType.LEFT_DOWN, MouseCommandType.MOVE]
    assert kinds(released) == [MouseCommandType.LEFT_UP]


def test_hand_loss_releases_active_drag_once() -> None:
    engine = GestureEngine(AppConfig(drag_hold_ms=300, hand_lost_ms=200))
    engine.process(observation(left_pinch_points(), BASE))
    engine.process(observation(left_pinch_points(), BASE + 310_000_000))

    first = engine.tick(BASE + 520_000_000)
    second = engine.tick(BASE + 800_000_000)

    assert kinds(first) == [MouseCommandType.LEFT_UP]
    assert second == []


def test_right_click_triggers_on_release() -> None:
    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))
    assert engine.process(observation(right_pinch_points(), BASE)) == []
    assert engine.state == ControlState.PINCH_PENDING
    commands = engine.process(observation(pointer_points(), BASE + 100_000_000))
    assert kinds(commands) == [MouseCommandType.RIGHT_CLICK]
    assert engine.state == ControlState.IDLE


def test_folded_middle_near_thumb_remains_pointer_instead_of_false_right_click() -> None:
    engine = GestureEngine(AppConfig())

    commands = engine.process(
        observation(middle_tucked_pointer_points(), BASE),
    )

    assert kinds(commands) == [MouseCommandType.MOVE]
    assert engine.current_gesture.value == "pointer"


def test_armed_pointer_middle_tuck_does_not_trigger_right_click() -> None:
    """普通指向武装后收拢中指再恢复，也不能形成一次右键。"""

    engine = GestureEngine(AppConfig())
    first = engine.process(observation(pointer_points(), BASE))
    tucked = engine.process(
        observation(middle_tucked_pointer_points(), BASE + 40_000_000),
    )
    restored = engine.process(
        observation(pointer_points(), BASE + 100_000_000),
    )

    assert kinds(first) == [MouseCommandType.MOVE]
    assert kinds(tucked) == [MouseCommandType.MOVE]
    assert kinds(restored) == [MouseCommandType.MOVE]
    assert MouseCommandType.RIGHT_CLICK not in kinds(first + tucked + restored)


def test_deliberate_bent_middle_reach_can_trigger_right_click() -> None:
    """真实录像中的弯中指主动前伸应保留右键灵敏度。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))
    started = engine.process(
        observation(bent_middle_right_pinch_points(), BASE + 40_000_000),
    )
    assert started == []
    assert engine.state == ControlState.PINCH_PENDING

    released = engine.process(
        observation(pointer_points(), BASE + 100_000_000),
    )

    assert engine.state == ControlState.IDLE
    assert kinds(released) == [MouseCommandType.RIGHT_CLICK]


def test_right_contact_can_finish_middle_reach_within_short_grace() -> None:
    """真实中指接触先于完整前伸一帧时，不能立即永久取消右键。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))

    first_contact = list(bent_middle_right_pinch_points())
    scale = max(
        ((first_contact[5].x - first_contact[17].x) ** 2
         + (first_contact[5].y - first_contact[17].y) ** 2) ** 0.5,
        min(
            (((first_contact[0].x - first_contact[9].x) ** 2
              + (first_contact[0].y - first_contact[9].y) ** 2) ** 0.5) * 0.75,
            (((first_contact[5].x - first_contact[17].x) ** 2
              + (first_contact[5].y - first_contact[17].y) ** 2) ** 0.5) * 2.0,
        ),
    )
    reach = 0.63 * scale
    rise = min(0.08, reach * 0.45)
    first_contact[12] = Landmark(
        first_contact[9].x + (reach**2 - rise**2) ** 0.5,
        first_contact[9].y - rise,
    )
    first_contact[4] = first_contact[12]

    waiting = engine.process(
        observation(tuple(first_contact), BASE + 40_000_000),
    )
    reached = engine.process(
        observation(bent_middle_right_pinch_points(), BASE + 130_000_000),
    )
    released = engine.process(
        observation(pointer_points(), BASE + 200_000_000),
    )

    assert waiting == []
    assert reached == []
    assert kinds(released) == [MouseCommandType.RIGHT_CLICK]


def test_right_middle_reach_grace_expires_without_resurrecting_contact() -> None:
    """接触过渡超过短宽限后，本轮右键必须失效直到重新张开。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))

    first_contact = list(bent_middle_right_pinch_points())
    palm_width = (
        (first_contact[5].x - first_contact[17].x) ** 2
        + (first_contact[5].y - first_contact[17].y) ** 2
    ) ** 0.5
    palm_length = (
        (first_contact[0].x - first_contact[9].x) ** 2
        + (first_contact[0].y - first_contact[9].y) ** 2
    ) ** 0.5
    scale = max(palm_width, min(palm_length * 0.75, palm_width * 2.0))
    reach = 0.63 * scale
    rise = min(0.08, reach * 0.45)
    first_contact[12] = Landmark(
        first_contact[9].x + (reach**2 - rise**2) ** 0.5,
        first_contact[9].y - rise,
    )
    first_contact[4] = first_contact[12]
    delayed_contact = tuple(first_contact)

    waiting = engine.process(
        observation(delayed_contact, BASE + 40_000_000),
    )
    expired = engine.process(
        observation(delayed_contact, BASE + 180_000_000),
    )
    late_reach = engine.process(
        observation(bent_middle_right_pinch_points(), BASE + 220_000_000),
    )
    released = engine.process(
        observation(pointer_points(), BASE + 280_000_000),
    )

    assert waiting == []
    assert MouseCommandType.RIGHT_CLICK not in kinds(expired + late_reach + released)


def test_open_to_pointer_transition_with_short_index_cannot_start_right_click() -> None:
    """张掌收成指向时食指尚未伸稳，拇指掠过中指不能被当成右键。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(open_palm_points(), BASE))

    transition = list(bent_middle_right_pinch_points())
    palm_width = (
        (transition[5].x - transition[17].x) ** 2
        + (transition[5].y - transition[17].y) ** 2
    ) ** 0.5
    palm_length = (
        (transition[0].x - transition[9].x) ** 2
        + (transition[0].y - transition[9].y) ** 2
    ) ** 0.5
    scale = max(palm_width, min(palm_length * 0.75, palm_width * 2.0))
    transition[8] = Landmark(
        transition[5].x,
        transition[5].y - scale,
    )

    contacted = engine.process(
        observation(tuple(transition), BASE + 40_000_000),
    )
    released = engine.process(
        observation(open_palm_points(), BASE + 100_000_000),
    )

    assert kinds(contacted) == [MouseCommandType.MOVE]
    assert MouseCommandType.RIGHT_CLICK not in kinds(contacted + released)


def test_folded_middle_projection_cannot_start_right_click() -> None:
    """中指尖虽离掌根较远，但关节仍明显折叠时不构成右键意图。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(open_palm_points(), BASE))

    folded = list(pointer_points())
    folded[10] = Landmark(0.50, 0.48)
    folded[11] = Landmark(0.62, 0.54)
    folded[12] = Landmark(0.74, 0.60)
    folded[4] = folded[12]

    contacted = engine.process(
        observation(tuple(folded), BASE + 40_000_000),
    )
    released = engine.process(
        observation(open_palm_points(), BASE + 100_000_000),
    )

    assert kinds(contacted) == [MouseCommandType.MOVE]
    assert MouseCommandType.RIGHT_CLICK not in kinds(contacted + released)


def test_deliberate_right_contact_near_release_threshold_still_clicks() -> None:
    """录像复现：时序和手型明确时，右键不应要求中指捏得过紧。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))
    started = engine.process(
        observation(
            bent_middle_right_pinch_points(contact_ratio=0.58),
            BASE + 40_000_000,
        ),
    )
    assert started == []
    assert engine.state == ControlState.PINCH_PENDING

    released = engine.process(
        observation(pointer_points(), BASE + 100_000_000),
    )

    assert kinds(released) == [MouseCommandType.RIGHT_CLICK]


def test_unconfirmed_left_transition_can_handoff_to_deliberate_right() -> None:
    """录像复现：单帧左键过渡不能吞掉紧随其后的明确右键。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))
    transient_left = engine.process(
        observation(left_ratio_points(0.40), BASE + 40_000_000),
    )
    right_contact = engine.process(
        observation(
            bent_middle_right_pinch_points(contact_ratio=0.58),
            BASE + 80_000_000,
        ),
    )
    released = engine.process(
        observation(pointer_points(), BASE + 140_000_000),
    )

    assert transient_left == []
    assert right_contact == []
    assert kinds(released) == [MouseCommandType.RIGHT_CLICK]


def test_left_release_pointer_frame_rearms_immediate_right_sequence() -> None:
    """左击松开的指向帧也应能为紧随其后的右键完成预备。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))
    engine.process(observation(left_pinch_points(), BASE + 40_000_000))
    engine.process(observation(left_pinch_points(), BASE + 80_000_000))
    left_released = engine.process(
        observation(pointer_points(), BASE + 120_000_000),
    )
    right_contact = engine.process(
        observation(
            bent_middle_right_pinch_points(contact_ratio=0.58),
            BASE + 160_000_000,
        ),
    )
    right_released = engine.process(
        observation(pointer_points(), BASE + 220_000_000),
    )

    assert kinds(left_released) == [MouseCommandType.LEFT_CLICK]
    assert right_contact == []
    assert kinds(right_released) == [MouseCommandType.RIGHT_CLICK]


def test_tucked_middle_cannot_later_resurrect_right_click_without_reopen() -> None:
    """首次接近若只是收拢姿势，本轮预备必须失效直到重新张开。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))
    tucked = engine.process(
        observation(middle_tucked_pointer_points(), BASE + 40_000_000),
    )
    later_geometry_spike = engine.process(
        observation(right_pinch_points(), BASE + 80_000_000),
    )
    released = engine.process(
        observation(pointer_points(), BASE + 140_000_000),
    )

    assert kinds(tucked) == [MouseCommandType.MOVE]
    assert MouseCommandType.RIGHT_CLICK not in kinds(
        later_geometry_spike + released,
    )


def test_right_pinch_requires_deliberate_open_then_close_sequence() -> None:
    engine = GestureEngine(AppConfig())
    engine.process(observation(middle_tucked_pointer_points(), BASE))

    still_pointer = engine.process(
        observation(middle_tucked_pointer_points(), BASE + 40_000_000),
    )

    assert kinds(still_pointer) == [MouseCommandType.MOVE]
    engine.process(observation(pointer_points(), BASE + 80_000_000))
    assert engine.process(
        observation(right_pinch_points(), BASE + 120_000_000),
    ) == []
    released = engine.process(
        observation(pointer_points(), BASE + 180_000_000),
    )
    assert kinds(released) == [MouseCommandType.RIGHT_CLICK]


def test_deliberate_right_pinch_can_start_from_open_palm() -> None:
    """自然张掌后直接用拇指和中指捏合，应被识别为右键。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(open_palm_points(), BASE))

    started = engine.process(
        observation(right_pinch_from_open_points(), BASE + 100_000_000),
    )
    released = engine.process(
        observation(pointer_points(), BASE + 180_000_000),
    )

    assert started == []
    assert kinds(released) == [MouseCommandType.RIGHT_CLICK]


def test_side_view_right_pinch_arms_from_projected_open_distance() -> None:
    """侧手补偿不能把自然张开的中指距离压到右键预备阈值之下。"""

    engine = GestureEngine(AppConfig())
    opened = list(compress_hand_width(open_palm_points(), factor=0.10))
    projected_width = (
        (opened[5].x - opened[17].x) ** 2
        + (opened[5].y - opened[17].y) ** 2
    ) ** 0.5
    opened[4] = Landmark(
        opened[12].x - projected_width,
        opened[12].y,
        opened[4].z,
    )
    engine.process(observation(tuple(opened), BASE))

    started = engine.process(
        observation(
            compress_hand_width(right_pinch_from_open_points(), factor=0.10),
            BASE + 100_000_000,
        ),
    )
    released = engine.process(
        observation(
            compress_hand_width(pointer_points(), factor=0.10),
            BASE + 200_000_000,
        ),
    )

    assert started == []
    assert kinds(released) == [MouseCommandType.RIGHT_CLICK]


def test_side_view_right_pinch_releases_when_projected_width_reopens() -> None:
    """侧手进入使用稳健尺度，但明显张开后不能继续锁住右键状态。"""

    engine = GestureEngine(AppConfig())
    engine.process(
        observation(side_right_width_ratio_points(1.0, opened=True), BASE),
    )
    engine.process(
        observation(side_right_width_ratio_points(0.30), BASE + 100_000_000),
    )

    release_candidate = engine.process(
        observation(side_right_width_ratio_points(0.60), BASE + 180_000_000),
    )
    released = engine.process(
        observation(side_right_width_ratio_points(0.60), BASE + 220_000_000),
    )

    assert release_candidate == []
    assert kinds(released) == [MouseCommandType.RIGHT_CLICK]


def test_side_view_right_pinch_must_reopen_before_another_click() -> None:
    """右键松开后在接触区抖动，不得连续产生多个右键。"""

    engine = GestureEngine(AppConfig())
    engine.process(
        observation(side_right_width_ratio_points(1.0, opened=True), BASE),
    )
    engine.process(
        observation(side_right_width_ratio_points(0.30), BASE + 100_000_000),
    )
    first_candidate = engine.process(
        observation(side_right_width_ratio_points(0.60), BASE + 180_000_000),
    )
    first = engine.process(
        observation(side_right_width_ratio_points(0.60), BASE + 220_000_000),
    )
    jitter_contact = engine.process(
        observation(side_right_width_ratio_points(0.30), BASE + 260_000_000),
    )
    jitter_release = engine.process(
        observation(side_right_width_ratio_points(0.60), BASE + 320_000_000),
    )

    engine.process(
        observation(side_right_width_ratio_points(1.0, opened=True), BASE + 400_000_000),
    )
    engine.process(
        observation(side_right_width_ratio_points(0.30), BASE + 480_000_000),
    )
    second_candidate = engine.process(
        observation(side_right_width_ratio_points(0.60), BASE + 560_000_000),
    )
    second = engine.process(
        observation(side_right_width_ratio_points(0.60), BASE + 600_000_000),
    )

    assert first_candidate == []
    assert kinds(first) == [MouseCommandType.RIGHT_CLICK]
    assert MouseCommandType.RIGHT_CLICK not in kinds(jitter_contact + jitter_release)
    assert second_candidate == []
    assert kinds(second) == [MouseCommandType.RIGHT_CLICK]


def test_side_view_right_contact_ignores_single_frame_palm_width_spikes() -> None:
    """掌宽估计抖动而指间实际距离不变时，不能释放或重新触发右键。"""

    engine = GestureEngine(AppConfig())
    opened = side_right_width_ratio_points(1.0, opened=True)
    contact = side_right_width_ratio_points(0.30)
    width_spike = shrink_palm_width_only(contact, 0.40)

    engine.process(observation(opened, BASE))
    engine.process(observation(contact, BASE + 40_000_000))
    first_spike = engine.process(
        observation(width_spike, BASE + 73_000_000),
    )
    first_recovery = engine.process(
        observation(contact, BASE + 106_000_000),
    )
    second_spike = engine.process(
        observation(width_spike, BASE + 139_000_000),
    )
    second_recovery = engine.process(
        observation(contact, BASE + 172_000_000),
    )

    commands = first_spike + first_recovery + second_spike + second_recovery
    assert MouseCommandType.RIGHT_CLICK not in kinds(commands)
    assert MouseCommandType.WHEEL not in kinds(commands)
    assert engine.current_gesture.value == "right_pinch"


def test_extreme_side_view_small_vertical_jitter_does_not_trigger_scroll() -> None:
    """极侧手时不能因掌宽投影过小而把约1%画面抖动放大成滚轮。"""

    start = compress_hand_width(open_palm_points(), factor=0.10)
    jitter = translate_points(start, dy=0.012)
    engine = GestureEngine(AppConfig())
    engine.process(observation(start, BASE))

    commands = engine.process(observation(jitter, BASE + 80_000_000))

    assert MouseCommandType.WHEEL not in kinds(commands)
    assert engine.current_gesture.value == "scroll"


def test_extreme_side_view_small_depth_jitter_does_not_rotate_scroll() -> None:
    """极侧手时轻微z噪声不能被归一化放大成一次翻腕滚轮。"""

    start = list(compress_hand_width(open_palm_points(), factor=0.10))
    jitter = list(start)
    point = jitter[9]
    jitter[9] = Landmark(point.x, point.y, point.z + 0.02)
    engine = GestureEngine(AppConfig())
    engine.process(observation(tuple(start), BASE))

    commands = engine.process(
        observation(tuple(jitter), BASE + 80_000_000),
    )

    assert MouseCommandType.WHEEL not in kinds(commands)
    assert engine.current_gesture.value == "scroll"


def test_medium_side_view_stable_right_contact_does_not_self_release() -> None:
    """中等侧手下稳定接触即使原始掌宽比偏大，也应保持右键捏合。"""

    engine = GestureEngine(AppConfig())
    engine.process(
        observation(
            side_right_width_ratio_points(1.0, opened=True, factor=0.40),
            BASE,
        ),
    )
    contact = side_right_width_ratio_points(0.60, factor=0.40)
    outputs = []
    for offset_ms in (40, 73, 106, 139):
        outputs.extend(
            engine.process(
                observation(contact, BASE + offset_ms * 1_000_000),
            ),
        )

    assert MouseCommandType.RIGHT_CLICK not in kinds(outputs)
    assert MouseCommandType.WHEEL not in kinds(outputs)
    assert engine.current_gesture.value == "right_pinch"


def test_medium_side_view_right_contact_ignores_consecutive_width_shrink() -> None:
    """连续掌宽收缩但指间距离不变时，不能被当成右键松开。"""

    engine = GestureEngine(AppConfig())
    engine.process(
        observation(
            side_right_width_ratio_points(1.0, opened=True, factor=0.40),
            BASE,
        ),
    )
    contact = side_right_width_ratio_points(0.60, factor=0.40)
    width_shrink = shrink_palm_width_only(contact, 0.40)
    engine.process(observation(contact, BASE + 40_000_000))

    first = engine.process(
        observation(width_shrink, BASE + 73_000_000),
    )
    second = engine.process(
        observation(width_shrink, BASE + 106_000_000),
    )

    assert MouseCommandType.RIGHT_CLICK not in kinds(first + second)
    assert engine.current_gesture.value == "right_pinch"


def test_right_contact_survives_uniform_hand_scale_growth() -> None:
    """保持相对捏合并靠近镜头时，整体放大不能被误认为松开。"""

    engine = GestureEngine(AppConfig())
    opened = side_right_width_ratio_points(1.0, opened=True, factor=0.40)
    contact = side_right_width_ratio_points(0.60, factor=0.40)
    enlarged = scale_hand_about_wrist(contact, 1.20)
    engine.process(observation(opened, BASE))
    engine.process(observation(contact, BASE + 40_000_000))

    outputs = []
    for offset_ms in (80, 120, 160):
        outputs.extend(
            engine.process(
                observation(enlarged, BASE + offset_ms * 1_000_000),
            ),
        )

    assert MouseCommandType.RIGHT_CLICK not in kinds(outputs)
    assert engine.current_gesture.value == "right_pinch"


def test_right_pinch_releases_when_hand_moves_away_and_fingers_reopen() -> None:
    """手远离镜头会让绝对距离变小，但相对手型明显张开仍必须释放。"""

    engine = GestureEngine(AppConfig())
    engine.process(
        observation(
            side_right_width_ratio_points(1.0, opened=True, factor=0.40),
            BASE,
        ),
    )
    engine.process(
        observation(
            side_right_width_ratio_points(0.60, factor=0.40),
            BASE + 40_000_000,
        ),
    )
    reopened = scale_hand_about_wrist(
        side_right_width_ratio_points(1.20, factor=0.40),
        0.50,
    )

    candidate = engine.process(
        observation(reopened, BASE + 80_000_000),
    )
    released = engine.process(
        observation(reopened, BASE + 120_000_000),
    )

    assert candidate == []
    assert kinds(released) == [MouseCommandType.RIGHT_CLICK]


def test_tightening_right_contact_does_not_lower_release_threshold() -> None:
    """先捏更紧再略微放松仍属于接触，不能提前触发右键。"""

    engine = GestureEngine(AppConfig())
    engine.process(
        observation(
            side_right_width_ratio_points(1.0, opened=True, factor=0.40),
            BASE,
        ),
    )
    engine.process(
        observation(
            side_right_width_ratio_points(0.60, factor=0.40),
            BASE + 40_000_000,
        ),
    )
    engine.process(
        observation(
            side_right_width_ratio_points(0.20, factor=0.40),
            BASE + 80_000_000,
        ),
    )

    outputs = []
    for offset_ms in (120, 160):
        outputs.extend(
            engine.process(
                observation(
                    side_right_width_ratio_points(0.35, factor=0.40),
                    BASE + offset_ms * 1_000_000,
                ),
            ),
        )

    assert MouseCommandType.RIGHT_CLICK not in kinds(outputs)
    assert engine.current_gesture.value == "right_pinch"


def test_deep_right_contact_needs_meaningful_reopen_before_release() -> None:
    """极紧接触后的微小距离噪声不能直接完成一次右键。"""

    engine = GestureEngine(AppConfig())
    engine.process(
        observation(side_right_width_ratio_points(1.0, opened=True), BASE),
    )
    engine.process(
        observation(side_right_width_ratio_points(0.0), BASE + 40_000_000),
    )

    outputs = []
    for offset_ms in (80, 120):
        outputs.extend(
            engine.process(
                observation(
                    side_right_width_ratio_points(0.20),
                    BASE + offset_ms * 1_000_000,
                ),
            ),
        )

    assert MouseCommandType.RIGHT_CLICK not in kinds(outputs)
    assert engine.current_gesture.value == "right_pinch"


def test_open_palm_to_pointer_transition_does_not_arm_false_right_click() -> None:
    engine = GestureEngine(AppConfig())
    engine.process(observation(open_palm_points(), BASE))

    commands = engine.process(
        observation(middle_tucked_pointer_points(), BASE + 80_000_000),
    )

    assert kinds(commands) == [MouseCommandType.MOVE]
    assert engine.current_gesture.value == "pointer"


def test_latched_right_pinch_is_not_stolen_by_ambiguous_index_contact() -> None:
    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))
    engine.process(observation(right_pinch_points(), BASE + 40_000_000))

    ambiguous = engine.process(
        observation(ambiguous_right_pinch_points(), BASE + 80_000_000),
    )
    released = engine.process(
        observation(pointer_points(), BASE + 140_000_000),
    )

    assert ambiguous == []
    assert kinds(released) == [MouseCommandType.RIGHT_CLICK]


def test_released_right_click_cannot_crosstalk_into_left_click() -> None:
    """右键完成后的残留双指接触，必须先张开才能开始一次左键。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))
    engine.process(observation(right_pinch_points(), BASE + 40_000_000))
    right_released = engine.process(
        observation(pointer_points(), BASE + 100_000_000),
    )

    residual = []
    residual.extend(
        engine.process(
            observation(ambiguous_right_pinch_points(), BASE + 140_000_000),
        ),
    )
    residual.extend(
        engine.process(
            observation(ambiguous_right_pinch_points(), BASE + 180_000_000),
        ),
    )
    residual.extend(
        engine.process(observation(pointer_points(), BASE + 240_000_000)),
    )

    assert kinds(right_released) == [MouseCommandType.RIGHT_CLICK]
    assert MouseCommandType.LEFT_CLICK not in kinds(residual)


def test_fist_hold_toggles_pause_and_requires_release_before_resume() -> None:
    engine = GestureEngine(AppConfig(fist_hold_ms=500))
    engine.process(observation(fist_points(), BASE))
    paused = engine.process(observation(fist_points(), BASE + 510_000_000))
    still_paused = engine.process(observation(fist_points(), BASE + 800_000_000))
    engine.process(observation(pointer_points(), BASE + 900_000_000))
    engine.process(observation(fist_points(), BASE + 1_000_000_000))
    resumed = engine.process(observation(fist_points(), BASE + 1_510_000_000))

    assert kinds(paused) == [MouseCommandType.PAUSE]
    assert paused[0].paused is True
    assert still_paused == []
    assert kinds(resumed) == [MouseCommandType.PAUSE]
    assert resumed[0].paused is False


def test_open_palm_horizontal_swipe_triggers_one_next_page() -> None:
    engine = GestureEngine(AppConfig())
    start = open_palm_points()
    engine.process(observation(start, BASE))

    page = engine.process(
        observation(translate_points(start, dx=-0.20), BASE + 180_000_000),
    )
    held = engine.process(
        observation(translate_points(start, dx=-0.24), BASE + 230_000_000),
    )

    assert kinds(page) == [MouseCommandType.PAGE_NEXT]
    assert held == []


def test_open_palm_right_swipe_triggers_previous_page() -> None:
    engine = GestureEngine(AppConfig())
    start = open_palm_points()
    engine.process(observation(start, BASE))

    page = engine.process(
        observation(translate_points(start, dx=0.20), BASE + 180_000_000),
    )

    assert kinds(page) == [MouseCommandType.PAGE_PREVIOUS]


def test_page_swipe_can_be_disabled_without_becoming_scroll() -> None:
    engine = GestureEngine(AppConfig(page_gestures_enabled=False))
    start = open_palm_points()
    engine.process(observation(start, BASE))

    commands = engine.process(
        observation(translate_points(start, dx=-0.20), BASE + 180_000_000),
    )

    assert commands == []


def test_open_palm_vertical_motion_still_scrolls_without_page_event() -> None:
    engine = GestureEngine(AppConfig())
    start = open_palm_points()
    engine.process(observation(start, BASE))

    scroll = engine.process(
        observation(translate_points(start, dy=-0.08), BASE + 120_000_000),
    )

    assert kinds(scroll) == [MouseCommandType.WHEEL]
    assert scroll[0].delta > 0


def test_open_palm_rotation_scrolls_without_translating_hand_center() -> None:
    engine = GestureEngine(AppConfig())
    engine.process(observation(open_palm_points(), BASE))

    scroll = engine.process(
        observation(rotated_scroll_points(), BASE + 100_000_000),
    )

    assert kinds(scroll) == [MouseCommandType.WHEEL]
    assert scroll[0].delta != 0
    assert engine.current_gesture.value == "scroll"


def test_pointer_recovers_immediately_after_rotation_scroll() -> None:
    """翻腕滚轮结束后不能永久锁在滚动状态而吞掉光标移动。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(open_palm_points(), BASE))
    scrolled = engine.process(
        observation(rotated_scroll_points(), BASE + 100_000_000),
    )
    recovered = engine.process(
        observation(pointer_points(), BASE + 200_000_000),
    )
    continued = engine.process(
        observation(pointer_points(), BASE + 245_000_000),
    )

    assert kinds(scrolled) == [MouseCommandType.WHEEL]
    assert kinds(recovered) == [MouseCommandType.MOVE]
    assert kinds(continued) == [MouseCommandType.MOVE]
    assert engine.current_gesture.value == "pointer"


def test_click_intent_has_priority_over_rotation_scroll() -> None:
    engine = GestureEngine(AppConfig())
    engine.process(observation(open_palm_points(), BASE))
    pinch = list(left_pinch_points())
    pinch[9] = Landmark(pinch[9].x, pinch[9].y, 0.10)

    commands = engine.process(
        observation(tuple(pinch), BASE + 100_000_000),
    )

    assert commands == []
    assert engine.current_gesture.value == "left_pinch"


def test_pointer_rotation_open_palm_projection_cannot_emit_clicks() -> None:
    """翻腕中仍呈张掌的二维指尖重叠不能被当成真实捏合。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))
    engine.process(
        observation(rotated_projected_closed_points(), BASE + 100_000_000),
    )

    projected_contact = list(open_palm_points())
    projected_contact[9] = Landmark(
        projected_contact[9].x,
        projected_contact[9].y,
        0.15,
    )
    projected_contact[4] = projected_contact[8]
    contact = engine.process(
        observation(tuple(projected_contact), BASE + 200_000_000),
    )

    projected_release = list(open_palm_points())
    projected_release[9] = Landmark(
        projected_release[9].x,
        projected_release[9].y,
        0.20,
    )
    released = engine.process(
        observation(tuple(projected_release), BASE + 300_000_000),
    )

    assert MouseCommandType.LEFT_CLICK not in kinds(contact + released)
    assert MouseCommandType.RIGHT_CLICK not in kinds(contact + released)
    assert engine.current_gesture.value == "scroll"


def test_gradual_pointer_rotation_then_open_projection_cannot_emit_clicks() -> None:
    """翻腕由多帧小变化累积时，首个张掌投影重叠也必须被识别为旋转。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))

    for offset_ms, depth in ((40, -0.02), (80, -0.04), (120, -0.05)):
        gradual = list(pointer_points())
        gradual[9] = Landmark(gradual[9].x, gradual[9].y, depth)
        engine.process(
            observation(tuple(gradual), BASE + offset_ms * 1_000_000),
        )

    projected_contact = list(open_palm_points())
    projected_contact[9] = Landmark(
        projected_contact[9].x,
        projected_contact[9].y,
        -0.075,
    )
    projected_contact[4] = projected_contact[8]
    contact = engine.process(
        observation(tuple(projected_contact), BASE + 160_000_000),
    )

    projected_release = list(open_palm_points())
    projected_release[9] = Landmark(
        projected_release[9].x,
        projected_release[9].y,
        -0.10,
    )
    released = engine.process(
        observation(tuple(projected_release), BASE + 220_000_000),
    )

    assert MouseCommandType.LEFT_CLICK not in kinds(contact + released)
    assert MouseCommandType.RIGHT_CLICK not in kinds(contact + released)
    assert engine.current_gesture.value == "scroll"


def test_gradual_rotation_crossing_on_closed_projection_cannot_start_click() -> None:
    """累计翻腕跨阈值的首帧即使被投影成捏合，也应优先保持旋转。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(pointer_points(), BASE))

    for offset_ms, depth in ((40, -0.02), (80, -0.04), (120, -0.05)):
        gradual = list(pointer_points())
        gradual[9] = Landmark(gradual[9].x, gradual[9].y, depth)
        engine.process(
            observation(tuple(gradual), BASE + offset_ms * 1_000_000),
        )

    projected_closed = list(left_pinch_points())
    projected_closed[9] = Landmark(
        projected_closed[9].x,
        projected_closed[9].y,
        -0.075,
    )
    contact = engine.process(
        observation(tuple(projected_closed), BASE + 160_000_000),
    )

    opened = list(open_palm_points())
    opened[9] = Landmark(opened[9].x, opened[9].y, -0.10)
    released = engine.process(
        observation(tuple(opened), BASE + 220_000_000),
    )

    assert MouseCommandType.LEFT_CLICK not in kinds(contact + released)
    assert MouseCommandType.RIGHT_CLICK not in kinds(contact + released)


def test_incomplete_hand_cannot_trigger_rotation_scroll() -> None:
    """翻腕滚轮和张掌平移一样，必须拥有完整21点证据。"""

    engine = GestureEngine(AppConfig())
    engine.process(observation(open_palm_points(), BASE))
    incomplete = list(rotated_scroll_points())
    point = incomplete[20]
    incomplete[20] = Landmark(1.04, point.y, point.z)

    commands = engine.process(
        observation(tuple(incomplete), BASE + 80_000_000),
    )

    assert MouseCommandType.WHEEL not in kinds(commands)


def test_horizontal_page_swipe_has_priority_over_simultaneous_depth_change() -> None:
    engine = GestureEngine(AppConfig())
    start = open_palm_points()
    engine.process(observation(start, BASE))
    moved = list(translate_points(start, dx=-0.20))
    moved[9] = Landmark(moved[9].x, moved[9].y, 0.10)

    commands = engine.process(
        observation(tuple(moved), BASE + 180_000_000),
    )

    assert kinds(commands) == [MouseCommandType.PAGE_NEXT]


def test_pointer_rotation_keeps_moving_and_cannot_start_fist_pause() -> None:
    engine = GestureEngine(AppConfig(fist_hold_ms=500))
    engine.process(observation(pointer_points(), BASE))

    rotated = engine.process(
        observation(rotated_projected_closed_points(), BASE + 100_000_000),
    )
    held = engine.process(
        observation(rotated_projected_closed_points(), BASE + 800_000_000),
    )

    assert kinds(rotated) == [MouseCommandType.MOVE]
    assert kinds(held) == [MouseCommandType.MOVE]
    assert engine.paused is False
    assert engine.current_gesture.value == "pointer"


def test_fist_pause_ignores_unstable_tip_depth_coordinates() -> None:
    """单目z噪声不能让二维明确的握拳失去暂停能力。"""

    points = list(fist_points())
    for index in (8, 12, 16, 20):
        point = points[index]
        points[index] = Landmark(point.x, point.y, 0.30)
    engine = GestureEngine(AppConfig(fist_hold_ms=500))
    engine.process(observation(tuple(points), BASE))

    held = engine.process(
        observation(tuple(points), BASE + 510_000_000),
    )

    assert MouseCommandType.PAUSE in kinds(held)
    assert engine.paused is True
    assert engine.current_gesture.value == "paused"


def test_rotation_scroll_transition_cannot_be_misjudged_as_pause() -> None:
    engine = GestureEngine(AppConfig(fist_hold_ms=500))
    engine.process(observation(open_palm_points(), BASE))

    scroll = engine.process(
        observation(rotated_projected_closed_points(), BASE + 100_000_000),
    )
    held = engine.process(
        observation(rotated_projected_closed_points(), BASE + 800_000_000),
    )

    assert kinds(scroll) == [MouseCommandType.WHEEL]
    assert held == []
    assert engine.paused is False
    assert engine.current_gesture.value == "scroll"


def test_partial_index_moves_but_partial_middle_only_reports_identity() -> None:
    engine = GestureEngine(AppConfig())
    index = HandObservation(
        landmarks=(),
        handedness="Right",
        timestamp_ns=BASE,
        inference_ms=8.0,
        partial_finger="Index",
        partial_position=Landmark(0.40, 0.30),
    )
    middle = HandObservation(
        landmarks=(),
        handedness="Right",
        timestamp_ns=BASE + 45_000_000,
        inference_ms=8.0,
        partial_finger="Middle",
        partial_position=Landmark(0.45, 0.30),
    )

    assert kinds(engine.process(index)) == [MouseCommandType.MOVE]
    assert engine.process(middle) == []
    assert engine.current_gesture.value == "partial_middle"
