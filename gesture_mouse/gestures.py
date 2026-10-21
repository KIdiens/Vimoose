"""基于关键点几何关系的手势状态机。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import acos, degrees, hypot, sqrt
from time import monotonic_ns

from gesture_mouse.calibration import gesture_scale as calibrated_gesture_scale
from gesture_mouse.config import AppConfig
from gesture_mouse.contracts import (
    GestureType,
    HandObservation,
    Landmark,
    MouseCommand,
    MouseCommandType,
)
from gesture_mouse.filters import OneEuroPointerFilter, map_activity_region


class ControlState(str, Enum):
    """控制状态机内部状态。"""

    IDLE = "idle"
    MOVING = "moving"
    PINCH_PENDING = "pinch_pending"
    DRAGGING = "dragging"
    SCROLLING = "scrolling"
    PAUSED = "paused"
    LOST = "lost"


_DISCRETE_REARM_MS = 1000
_LEFT_CONTACT_CONFIRM_MS = 45
_LEFT_DEEP_CONTACT_FACTOR = 0.80
_LEFT_MAX_CONTACT_CURSOR_JUMP = 0.18
_LEFT_MIN_IDENTITY_SPAN = 0.52
_RIGHT_MIDDLE_REACH_MIN = 0.75
_RIGHT_MIDDLE_REACH_GRACE_MIN = 0.55
_RIGHT_MIDDLE_REACH_GRACE_MS = 120
_RIGHT_MIDDLE_ANGLE_MIN = 80.0
_RIGHT_MIDDLE_ANGLE_GRACE_MIN = 68.0
_RIGHT_INDEX_REACH_MIN = 1.20
_RIGHT_RELEASE_CONFIRM_MS = 25


def _distance_2d(a: Landmark, b: Landmark) -> float:
    """手势阈值使用图像平面距离，避开单目深度坐标的帧间噪声。"""

    return hypot(a.x - b.x, a.y - b.y)


def _angle(a: Landmark, vertex: Landmark, c: Landmark) -> float:
    """返回以 ``vertex`` 为顶点的图像平面夹角。

    单目模型的相对深度在侧手和弱光下更容易波动，屈伸分类只依赖二维
    骨架即可，因此不让z噪声把伸直的手指误判为弯曲。
    """

    first = (a.x - vertex.x, a.y - vertex.y)
    second = (c.x - vertex.x, c.y - vertex.y)
    first_norm = sqrt(sum(value * value for value in first))
    second_norm = sqrt(sum(value * value for value in second))
    if first_norm < 1e-8 or second_norm < 1e-8:
        return 0.0
    cosine = sum(a_value * b_value for a_value, b_value in zip(first, second))
    cosine /= first_norm * second_norm
    cosine = max(-1.0, min(1.0, cosine))
    return degrees(acos(cosine))


def _palm_width(points: tuple[Landmark, ...]) -> float:
    return max(_distance_2d(points[5], points[17]), 1e-4)


def _gesture_scale(points: tuple[Landmark, ...]) -> float:
    """返回对正手和侧手都稳定的二维手部尺度。

    只用食指与小指掌指关节之间的掌宽时，侧手会把该距离压缩到正手的
    三分之一甚至更小。这会同时造成捏合变得难触发、掌心微小抖动被
    放大成滚轮，以及翻腕/握拳阈值漂移。腕部到中指掌指关节的掌长在
    侧手下更稳定；取掌宽与0.75倍掌长的较大值，可保持正手原阈值，
    又为侧手提供可靠的归一化尺度。补偿最多限制为原掌宽的2倍，避免
    极端侧手把“自然张开”也压进捏合区，保留右键预备与双击重置空间。
    """

    return calibrated_gesture_scale(points)


def _motion_scale(points: tuple[Landmark, ...]) -> float:
    """返回平移手势尺度，避免极侧手把微小位移放大为滚轮。"""

    return max(
        _palm_width(points),
        _distance_2d(points[0], points[9]) * 0.75,
        1e-4,
    )


def _landmarks_inside_frame(
    points: tuple[Landmark, ...],
    indices: tuple[int, ...],
) -> bool:
    """确认参与离散手势判定的关键点仍完整位于摄像头画面内。

    MediaPipe会在手指刚离开画面时继续给出预测坐标，坐标甚至可能略微
    超出0~1。此类坐标可用于短时光标连续性，但不能作为点击、滚轮或
    暂停等离散指令的证据。
    """

    return all(
        0.0 <= points[index].x <= 1.0
        and 0.0 <= points[index].y <= 1.0
        for index in indices
    )


def _palm_center(points: tuple[Landmark, ...]) -> Landmark:
    indices = (0, 5, 9, 13, 17)
    return Landmark(
        x=sum(points[index].x for index in indices) / len(indices),
        y=sum(points[index].y for index in indices) / len(indices),
        z=sum(points[index].z for index in indices) / len(indices),
    )


def _palm_depth_tilt(points: tuple[Landmark, ...]) -> float:
    """返回腕部到中指掌指关节的归一化深度差。

    掌心前后翻转时，掌心在画面中的中心可以几乎不动，但9号点相对
    手腕的深度会稳定改变。以稳健手部尺度归一化后可兼容不同距离和手型。
    """

    return (points[9].z - points[0].z) / _motion_scale(points)


def _finger_extensions(points: tuple[Landmark, ...]) -> tuple[bool, bool, bool, bool]:
    fingers = ((5, 6, 8), (9, 10, 12), (13, 14, 16), (17, 18, 20))
    return tuple(_angle(points[mcp], points[pip], points[tip]) >= 135.0 for mcp, pip, tip in fingers)  # type: ignore[return-value]


def _is_pointer(points: tuple[Landmark, ...]) -> bool:
    # 张掌和捏合已在状态机中优先处理。此处只要求食指伸展，允许其余
    # 手指自然半弯，避免用户必须维持僵硬的“标准手势”。
    index, _middle, _ring, _pinky = _finger_extensions(points)
    return index


def _is_open_palm(points: tuple[Landmark, ...]) -> bool:
    index, middle, ring, pinky = _finger_extensions(points)
    return index and middle and sum((index, middle, ring, pinky)) >= 3


def _is_fist(points: tuple[Landmark, ...]) -> bool:
    if any(_finger_extensions(points)):
        return False
    center = _palm_center(points)
    scale = _gesture_scale(points)
    tips = (8, 12, 16, 20)
    mean_distance = sum(_distance_2d(points[index], center) for index in tips) / len(tips)
    return mean_distance / scale < 1.25


@dataclass(slots=True)
class GestureDebug:
    """最近一次识别的几何量，便于后续校准。"""

    left_pinch_ratio: float = 99.0
    right_pinch_ratio: float = 99.0
    palm_width: float = 0.0


class GestureEngine:
    """处理时序冲突并生成标准鼠标指令。"""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.filter = self._build_pointer_filter(config)
        self.state = ControlState.IDLE
        self.current_gesture = GestureType.NONE
        self.paused = False
        self.last_hand_ns: int | None = None
        self.debug = GestureDebug()
        self._last_pointer_input: tuple[float, float] | None = None

        self._left_active = False
        self._left_started_ns: int | None = None
        self._left_contact_samples = 0
        self._left_contact_min_ratio = 99.0
        self._left_rearm_required = False
        self._right_active = False
        self._right_started_ns: int | None = None
        self._right_ready = False
        self._right_open_ratio = 0.0
        self._right_requires_middle_reach = False
        self._right_reach_grace_started_ns: int | None = None
        self._right_contact_scale = 0.0
        self._right_contact_min_ratio = 99.0
        self._right_release_since_ns: int | None = None
        self._fist_started_ns: int | None = None
        self._fist_latched = False
        self._open_anchor_x: float | None = None
        self._scroll_anchor_y: float | None = None
        self._rotation_tilt_anchor: float | None = None
        self._rotation_scroll_active = False
        self._rotation_projection_guard_active = False
        self._rotation_last_open_ns: int | None = None
        self._pointer_tilt_anchor: float | None = None
        self._pointer_rotation_active = False
        self._page_swipe_latched = False
        self._lost_reported = False
        self._left_button_down = False
        self._discrete_rearm_required = False
        self._complete_hand_since_ns: int | None = None

    def update_config(self, config: AppConfig) -> None:
        self.config = config
        self.filter = self._build_pointer_filter(config)
        self._last_pointer_input = None

    @staticmethod
    def _build_pointer_filter(config: AppConfig) -> OneEuroPointerFilter:
        min_cutoff = 3.0 - 2.2 * config.pointer_stability
        beta = 0.35 + 1.55 * config.pointer_response
        return OneEuroPointerFilter(min_cutoff=min_cutoff, beta=beta)

    def _command(
        self,
        kind: MouseCommandType,
        timestamp_ns: int,
        **kwargs: float | int | bool | None,
    ) -> MouseCommand:
        return MouseCommand(kind=kind, timestamp_ns=timestamp_ns, **kwargs)

    def _cursor(self, point: Landmark, timestamp_ns: int) -> tuple[float, float]:
        mapped = map_activity_region(
            point.x,
            point.y,
            self.config.pointer_margin_x,
            self.config.pointer_margin_y,
        )
        self._last_pointer_input = mapped
        filtered_x, filtered_y = self.filter.update(*mapped, timestamp_ns)
        if self.config.pointer_edge_override:
            # 关键点到达安全活动区边界时直接完成最后一小段屏幕行程。
            # 这样不需要把手移出摄像头等待滤波器慢慢收敛到0或1。
            if mapped[0] <= 0.0 or mapped[0] >= 1.0:
                filtered_x = mapped[0]
            if mapped[1] <= 0.0 or mapped[1] >= 1.0:
                filtered_y = mapped[1]
        return filtered_x, filtered_y

    def _cursor_target_distance(self, point: Landmark) -> float:
        """返回食指目标相对上一光标帧的归一化屏幕位移。"""

        previous = self._last_pointer_input
        if previous is None:
            return 0.0
        current = map_activity_region(
            point.x,
            point.y,
            self.config.pointer_margin_x,
            self.config.pointer_margin_y,
        )
        return hypot(current[0] - previous[0], current[1] - previous[1])

    def _cursor_target_changed(self, point: Landmark) -> bool:
        """判断接触帧是否包含需要在锁定前提交的明显指尖位移。"""

        return self._cursor_target_distance(point) >= 0.015

    def _left_intent_threshold(self) -> float:
        """返回不侵占自然指向姿势的点击预锁定/重新武装阈值。"""

        return min(self.config.pinch_arm, self.config.pinch_release + 0.06)

    def _right_contact_threshold(self) -> float:
        """返回仅用于已确认右键意图的宽容接触阈值。"""

        return min(
            self.config.pinch_arm - 0.05,
            self.config.pinch_release + 0.05,
            self.config.pinch_engage + 0.18,
        )

    def _release_left(self, timestamp_ns: int) -> list[MouseCommand]:
        if not self._left_button_down:
            return []
        self._left_button_down = False
        return [self._command(MouseCommandType.LEFT_UP, timestamp_ns)]

    def _reset_transient(self) -> None:
        if self._left_active:
            # 未观察到可信松开就取消左捏合时，不能把同一捏合姿势在恢复后
            # 当成一次新点击。丢手、部分跟踪、暂停和异常路径都必须先看到
            # 完整手部明确张开，才能重新接受左键意图。
            self._left_rearm_required = True
        self._left_active = False
        self._left_started_ns = None
        self._left_contact_samples = 0
        self._left_contact_min_ratio = 99.0
        # 不在通用瞬态清理中解除左键重新武装要求。部分跟踪、丢手、
        # 握拳或暂停都不是一次可信的“拇指与食指已重新张开”；只有后续
        # 完整可靠帧明确越过意图区，才能允许下一次左击。
        self._right_active = False
        self._right_started_ns = None
        self._right_ready = False
        self._right_open_ratio = 0.0
        self._right_requires_middle_reach = False
        self._right_reach_grace_started_ns = None
        self._right_contact_scale = 0.0
        self._right_contact_min_ratio = 99.0
        self._right_release_since_ns = None
        self._reset_orientation_tracking()

    def _reset_orientation_tracking(self) -> None:
        self._reset_scroll_tracking()
        self._reset_pointer_rotation()

    def _reset_scroll_tracking(self) -> None:
        self._open_anchor_x = None
        self._scroll_anchor_y = None
        self._rotation_tilt_anchor = None
        self._rotation_scroll_active = False
        self._rotation_projection_guard_active = False
        self._rotation_last_open_ns = None
        self._page_swipe_latched = False

    def _reset_pointer_rotation(self) -> None:
        self._pointer_tilt_anchor = None
        self._pointer_rotation_active = False

    def _mark_discrete_unreliable(self) -> None:
        """要求完整手部稳定一段时间后才重新允许离散操作。"""

        self._discrete_rearm_required = True
        self._complete_hand_since_ns = None

    def _discrete_gestures_ready(
        self,
        complete_hand_reliable: bool,
        timestamp_ns: int,
    ) -> bool:
        """过滤出框后被模型短暂“猜回”的拇指和手掌坐标。"""

        if not complete_hand_reliable:
            self._mark_discrete_unreliable()
            return False
        if not self._discrete_rearm_required:
            return True
        if self._complete_hand_since_ns is None:
            self._complete_hand_since_ns = timestamp_ns
            return False
        stable_ms = (timestamp_ns - self._complete_hand_since_ns) / 1_000_000
        if stable_ms < _DISCRETE_REARM_MS:
            return False
        self._discrete_rearm_required = False
        self._complete_hand_since_ns = None
        return True

    def set_paused(
        self,
        paused: bool,
        timestamp_ns: int | None = None,
    ) -> list[MouseCommand]:
        """由托盘或快捷键显式设置暂停状态。"""

        now = timestamp_ns or monotonic_ns()
        commands = self._release_left(now)
        self.paused = paused
        self.state = ControlState.PAUSED if paused else ControlState.IDLE
        self.current_gesture = GestureType.PAUSED if paused else GestureType.NONE
        self._reset_transient()
        self.filter.reset()
        self._last_pointer_input = None
        commands.append(
            self._command(MouseCommandType.PAUSE, now, paused=paused),
        )
        return commands

    def emergency_stop(self, timestamp_ns: int | None = None) -> list[MouseCommand]:
        """立即停止注入并进入暂停状态。"""

        return self.set_paused(True, timestamp_ns)

    def process(self, observation: HandObservation) -> list[MouseCommand]:
        """处理一帧有效手部观测。"""

        points = observation.landmarks
        if self.config.handedness != "Any" and observation.handedness:
            if observation.handedness != self.config.handedness:
                return self.tick(observation.timestamp_ns)

        now = observation.timestamp_ns
        if observation.partial_finger and observation.partial_position is not None:
            self._mark_discrete_unreliable()
            commands = self._release_left(now)
            self._reset_transient()
            self.last_hand_ns = now
            self._lost_reported = False
            if self.paused:
                self.state = ControlState.PAUSED
                self.current_gesture = GestureType.PAUSED
                return commands
            if observation.partial_finger == "Index":
                self.current_gesture = GestureType.PARTIAL_INDEX
                self.state = ControlState.MOVING
                x, y = self._cursor(observation.partial_position, now)
                commands.append(self._command(MouseCommandType.MOVE, now, x=x, y=y))
            else:
                self.current_gesture = GestureType.PARTIAL_MIDDLE
                self.state = ControlState.IDLE
            return commands
        if len(points) != 21:
            self._mark_discrete_unreliable()
            return []

        self.last_hand_ns = now
        self._lost_reported = False
        palm_width = _palm_width(points)
        gesture_scale = _gesture_scale(points)
        palm_reliable = _landmarks_inside_frame(points, (0, 5, 9, 13, 17))
        thumb_reliable = _landmarks_inside_frame(points, (1, 2, 3, 4))
        index_reliable = _landmarks_inside_frame(points, (5, 6, 7, 8))
        middle_reliable = _landmarks_inside_frame(points, (9, 10, 11, 12))
        control_core_reliable = _landmarks_inside_frame(
            points,
            (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 17),
        )
        complete_hand_reliable = _landmarks_inside_frame(points, tuple(range(21)))
        # 左右键只需要掌心、拇指、食指和中指的可靠证据。无关的无名指
        # 或小指指尖短暂越界时，不应让所有离散操作进入一秒重启死区。
        # 张掌滚轮、翻页和握拳仍在当前帧要求完整21点，保持误触保护。
        discrete_ready = self._discrete_gestures_ready(control_core_reliable, now)
        left_geometry_reliable = (
            discrete_ready and palm_reliable and thumb_reliable and index_reliable
        )
        right_geometry_reliable = (
            discrete_ready and palm_reliable and thumb_reliable and middle_reliable
        )
        left_distance = _distance_2d(points[4], points[8])
        right_distance = _distance_2d(points[4], points[12])
        left_ratio = (
            left_distance / gesture_scale if left_geometry_reliable else 99.0
        )
        right_ratio = (
            right_distance / gesture_scale if right_geometry_reliable else 99.0
        )
        right_width_ratio = (
            right_distance / palm_width if right_geometry_reliable else 99.0
        )
        self.debug = GestureDebug(left_ratio, right_ratio, palm_width)

        # 一次左键动作结束后，必须看到手指明确张开到意图区之外，才允许
        # 下一次点击。这样不会增加首次点击延迟，也不会破坏正常双击，
        # 但能阻止关键点在 engage/release 阈值附近抖动时重复点击。
        left_intent_threshold = self._left_intent_threshold()
        if left_geometry_reliable and left_ratio >= left_intent_threshold:
            self._left_rearm_required = False

        open_palm = (
            discrete_ready and complete_hand_reliable and _is_open_palm(points)
        )
        pointer_shape = _is_pointer(points)
        palm_tilt = _palm_depth_tilt(points)
        pointer_tilt_delta = (
            palm_tilt - self._pointer_tilt_anchor
            if self._pointer_tilt_anchor is not None
            else 0.0
        )
        cumulative_pointer_rotation = (
            self._pointer_tilt_anchor is not None
            and abs(pointer_tilt_delta) >= self.config.palm_rotation_threshold
        )
        pointer_projection_rotation_started = (
            not self.paused
            and self.config.rotation_gestures_enabled
            and cumulative_pointer_rotation
            and not self._left_active
            and not self._right_active
        )
        if pointer_projection_rotation_started:
            # 首个跨阈值帧可能已经因透视压缩不再满足pointer/open形状，
            # 甚至让拇指与食指重叠。旋转证据来自此前连续指向的深度基准，
            # 因此要先锁存，再进入捏合判定。
            self._pointer_rotation_active = True
            self._rotation_projection_guard_active = True
        rotation_open_active = (
            not self.paused
            and self.config.rotation_gestures_enabled
            and open_palm
            and not self._left_active
            and not self._right_active
            and (
                self._rotation_projection_guard_active
                or (
                    abs(palm_tilt) >= self.config.palm_rotation_threshold
                    and (
                        self._pointer_rotation_active
                        or self._rotation_scroll_active
                        or cumulative_pointer_rotation
                    )
                )
            )
        )
        rotation_contact_guard_active = (
            rotation_open_active
            or (
                self._rotation_projection_guard_active
                and not self._left_active
                and not self._right_active
            )
        )
        middle_reach_ratio = (
            _distance_2d(points[9], points[12]) / gesture_scale
        )
        middle_pinch_reaches_forward = (
            middle_reach_ratio >= _RIGHT_MIDDLE_REACH_MIN
        )
        middle_pinch_angle = _angle(points[9], points[10], points[12])
        index_tip_span = _distance_2d(points[5], points[8]) / gesture_scale
        commands: list[MouseCommand] = []

        # 越界不是一次可靠的“松开”。取消可能由边缘预测误触发的捏合，
        # 但不生成点击；若已经进入拖拽，则仍立即释放左键保证安全。
        if self._left_active and not left_geometry_reliable:
            self._left_active = False
            self._left_started_ns = None
            self._left_contact_samples = 0
            self._left_contact_min_ratio = 99.0
            commands.extend(self._release_left(now))
        if self._right_active and not right_geometry_reliable:
            self._right_active = False
            self._right_started_ns = None
            self._right_contact_scale = 0.0
            self._right_contact_min_ratio = 99.0
            self._right_release_since_ns = None
        if not right_geometry_reliable:
            self._right_ready = False
            self._right_open_ratio = 0.0
            self._right_requires_middle_reach = False
            self._right_reach_grace_started_ns = None

        if rotation_contact_guard_active:
            # 翻腕过程中四指在二维图像里仍可能保持“张掌”，但拇指会
            # 依次从食指、中指投影上经过。此时的指尖重叠不是点击。
            if cumulative_pointer_rotation or self._pointer_rotation_active:
                self._pointer_rotation_active = True
                self._rotation_projection_guard_active = True
            self._right_ready = False
            self._right_open_ratio = 0.0
            self._right_requires_middle_reach = False
            self._right_reach_grace_started_ns = None
        if (
            not self.paused
            and not self._right_active
            and not rotation_contact_guard_active
        ):
            if (
                right_geometry_reliable
                and (open_palm or pointer_shape)
                and right_width_ratio >= self.config.pinch_arm
                and right_ratio >= self.config.pinch_engage
            ):
                self._right_ready = True
                self._right_open_ratio = max(self._right_open_ratio, right_ratio)
                if right_ratio >= self.config.pinch_release:
                    self._right_reach_grace_started_ns = None
                # 无论从张掌还是食指指向开始，后续接触帧都必须保留
                # 中指主动伸出。否则“已武装的指向→自然收拢中指→恢复”
                # 与右键的拇指靠近轨迹几乎相同，会在恢复时产生误右击。
                self._right_requires_middle_reach = True
        right_shape_valid = (
            not self._right_requires_middle_reach
            or (
                middle_pinch_reaches_forward
                and middle_pinch_angle >= _RIGHT_MIDDLE_ANGLE_MIN
                and index_tip_span >= _RIGHT_INDEX_REACH_MIN
            )
        )
        right_contact_threshold = self._right_contact_threshold()
        right_approach = self._right_open_ratio - right_ratio
        right_reach_grace_active = False
        if self._right_ready:
            if right_ratio > right_contact_threshold or right_shape_valid:
                self._right_reach_grace_started_ns = None
            elif (
                middle_reach_ratio >= _RIGHT_MIDDLE_REACH_GRACE_MIN
                and middle_pinch_angle >= _RIGHT_MIDDLE_ANGLE_GRACE_MIN
                and index_tip_span >= _RIGHT_INDEX_REACH_MIN
                and right_approach >= self.config.right_pinch_approach_delta
            ):
                if self._right_reach_grace_started_ns is None:
                    self._right_reach_grace_started_ns = now
                grace_ms = (
                    now - self._right_reach_grace_started_ns
                ) / 1_000_000
                right_reach_grace_active = (
                    grace_ms <= _RIGHT_MIDDLE_REACH_GRACE_MS
                )
                if not right_reach_grace_active:
                    self._right_ready = False
                    self._right_open_ratio = 0.0
                    self._right_requires_middle_reach = False
                    self._right_reach_grace_started_ns = None
            else:
                # 明显收拢的中指仍立即否定本轮预备；短等待窗只服务于
                # 已接近前伸阈值的真实接触过渡，不能复活自然收指。
                self._right_ready = False
                self._right_open_ratio = 0.0
                self._right_requires_middle_reach = False
                self._right_reach_grace_started_ns = None
        right_near_candidate = (
            right_reach_grace_active
            or self._right_active
            or (
                self._right_ready
                and right_shape_valid
                and right_ratio <= self.config.pinch_arm
                and right_approach
                >= self.config.right_pinch_approach_delta * 0.5
            )
        )
        pinch_proximity = (
            left_ratio <= self.config.pinch_arm
            or right_near_candidate
        )

        if (
            pointer_projection_rotation_started
            and not open_palm
            and index_reliable
        ):
            self.current_gesture = GestureType.POINTER
            self.state = ControlState.MOVING
            x, y = self._cursor(points[8], now)
            commands.append(self._command(MouseCommandType.MOVE, now, x=x, y=y))
            return commands

        if (
            not self.paused
            and self._left_rearm_required
            and left_geometry_reliable
            and left_ratio < left_intent_threshold
            and not right_near_candidate
        ):
            # 被拒绝的食指身份跳变可能连续存在数帧。直到拇指与食指
            # 明确重新张开前，锁住光标并禁止同一错误骨架再次进入点击。
            self.current_gesture = GestureType.PINCH_ARMED
            self.state = ControlState.PINCH_PENDING
            self._reset_orientation_tracking()
            return commands

        # 录屏中的“食指指向后向下翻腕”会让二维骨架短暂接近握拳。
        # 若前一帧明确处于光标模式，则以掌面深度变化确认这是翻腕，
        # 继续使用食指尖更新光标，而不是启动握拳暂停计时。
        if (
            not self.paused
            and self.config.rotation_gestures_enabled
            and self._pointer_tilt_anchor is not None
            and not open_palm
            and not pinch_proximity
        ):
            if (
                self._pointer_rotation_active
                or abs(pointer_tilt_delta) >= self.config.palm_rotation_threshold
            ):
                self._pointer_rotation_active = True
                self._pointer_tilt_anchor = palm_tilt
                self.current_gesture = GestureType.POINTER
                self.state = ControlState.MOVING
                x, y = self._cursor(points[8], now)
                commands.append(self._command(MouseCommandType.MOVE, now, x=x, y=y))
                return commands

        # 张掌后允许通过前后翻腕控制滚轮。该判定必须先于握拳：翻腕时
        # 四指的二维投影会缩短，旧逻辑会把平展的手误判成握拳并暂停。
        if self._rotation_scroll_active and pointer_shape and not open_palm:
            self._reset_scroll_tracking()
        if (
            not self.paused
            and self.config.rotation_gestures_enabled
            and discrete_ready
            and complete_hand_reliable
            and self._rotation_tilt_anchor is not None
            and not open_palm
            and not pinch_proximity
        ):
            tilt_delta = palm_tilt - self._rotation_tilt_anchor
            if abs(tilt_delta) >= self.config.palm_rotation_threshold:
                notches = round(
                    -tilt_delta * self.config.scroll_sensitivity * 6,
                )
                if notches == 0:
                    notches = -1 if tilt_delta > 0 else 1
                notches = max(-3, min(3, notches))
                self._rotation_tilt_anchor = palm_tilt
                self._rotation_scroll_active = True
                self.current_gesture = GestureType.SCROLL
                self.state = ControlState.SCROLLING
                commands.append(
                    self._command(
                        MouseCommandType.WHEEL,
                        now,
                        delta=notches * 120,
                    ),
                )
                return commands
            if self._rotation_scroll_active and not open_palm:
                if pointer_shape:
                    self._reset_scroll_tracking()
                else:
                    self.current_gesture = GestureType.SCROLL
                    self.state = ControlState.SCROLLING
                    return commands

        fist = discrete_ready and complete_hand_reliable and _is_fist(points)
        if fist and not pinch_proximity:
            # 从张掌进入翻腕的最初几帧可能尚未跨过滚轮阈值。给深度
            # 姿态一个短暂判定窗口，避免先启动500ms握拳暂停计时。
            if (
                not self.paused
                and self.config.rotation_gestures_enabled
                and self._rotation_last_open_ns is not None
                and (now - self._rotation_last_open_ns) / 1_000_000 <= 350
            ):
                self.current_gesture = GestureType.SCROLL
                self.state = ControlState.SCROLLING
                return commands
            commands.extend(self._release_left(now))
            self._reset_transient()
            self.current_gesture = GestureType.FIST
            if self._fist_started_ns is None:
                self._fist_started_ns = now
            held_ms = (now - self._fist_started_ns) / 1_000_000
            if held_ms >= self.config.fist_hold_ms and not self._fist_latched:
                self._fist_latched = True
                commands.extend(self.set_paused(not self.paused, now))
            return commands

        self._fist_started_ns = None
        self._fist_latched = False
        if self.paused:
            self.state = ControlState.PAUSED
            self.current_gesture = GestureType.PAUSED
            return commands

        left_now = not rotation_contact_guard_active and left_ratio <= (
            self.config.pinch_release if self._left_active else self.config.pinch_engage
        )
        right_candidate = not rotation_contact_guard_active and (
            self._right_active
            or (
                self._right_ready
                and right_shape_valid
                and right_approach >= self.config.right_pinch_approach_delta
            )
        )
        if self._right_active:
            # 进入右键时冻结归一化尺度。活动期间只比较指间实际距离相对
            # 接触最小值的增量，掌宽投影单帧变窄不会再被当成松开。
            # 很明显的张开立即释放；较小的侧手张开需稳定25ms，兼顾
            # 右键响应与关键点抖动下的准确性。
            # 整只手靠近镜头时，指间距离与手部尺度会等比例增大。冻结
            # 尺度只向上、且每帧最多跟随25%，既吸收景深变化，又不会因
            # 侧手掌宽突然缩短而误判松开。
            self._right_contact_scale = max(
                self._right_contact_scale,
                min(
                    gesture_scale,
                    max(self._right_contact_scale, 1e-4) * 1.25,
                ),
            )
            contact_scale = max(self._right_contact_scale, 1e-4)
            contact_ratio = right_distance / contact_scale
            release_delta = max(
                0.06,
                (self.config.pinch_release - self.config.pinch_engage) * 0.60,
            )
            release_threshold = min(
                self.config.pinch_release,
                max(
                    self._right_contact_min_ratio + release_delta,
                    self.config.pinch_engage * 0.65,
                ),
            )
            # 需要用相对手型兜底“手离镜头更远但手指重新张开”的场景。
            # 这里不能复用带掌宽上限的 ``right_ratio``：侧手时5–17掌宽
            # 连续变窄会压低该尺度，让指间实际距离完全不变也看起来达到
            # 松开阈值。掌长参与且不受该投影抖动影响的运动尺度可以区分
            # 这两种情况，同时仍随整手远近等比例变化。
            relative_open = (
                right_distance / _motion_scale(points)
                >= self.config.pinch_arm
            )
            if contact_ratio < release_threshold and not relative_open:
                self._right_release_since_ns = None
                right_now = True
            elif contact_ratio >= self.config.pinch_arm:
                right_now = False
            elif self._right_release_since_ns is None:
                self._right_release_since_ns = now
                right_now = True
            else:
                release_ms = (
                    now - self._right_release_since_ns
                ) / 1_000_000
                right_now = release_ms < _RIGHT_RELEASE_CONFIRM_MS
        else:
            right_now = (
                right_candidate
                and right_ratio <= right_contact_threshold
            )

        # 已锁定的右键意图优先保持到松开，防止中指向拇指靠近时食指
        # 短暂经过拇指附近，造成一次右键动作被中途窃取成左键。
        if self._right_active:
            if right_now:
                self.current_gesture = GestureType.RIGHT_PINCH
                self.state = ControlState.PINCH_PENDING
                self._reset_orientation_tracking()
                return commands
            self._right_active = False
            self._right_started_ns = None
            self._right_ready = False
            self._right_open_ratio = 0.0
            self._right_requires_middle_reach = False
            self._right_reach_grace_started_ns = None
            self._right_contact_scale = 0.0
            self._right_contact_min_ratio = 99.0
            self._right_release_since_ns = None
            # 右键完成帧已经被右键状态消费。要求后续再出现一次明确张开，
            # 防止同一接触残影在下一帧被左键状态机接管并串成左击。
            self._left_rearm_required = True
            self.current_gesture = GestureType.RIGHT_PINCH
            self.state = ControlState.IDLE
            commands.append(self._command(MouseCommandType.RIGHT_CLICK, now))
            return commands

        # 已开始的左键捏合保持原有点击/拖拽语义。
        if self._left_active:
            if not left_now:
                self._left_active = False
                self._left_rearm_required = left_ratio < left_intent_threshold
                self.current_gesture = GestureType.LEFT_PINCH
                held_ms = (
                    (now - self._left_started_ns) / 1_000_000
                    if self._left_started_ns is not None
                    else 0.0
                )
                contact_confirmed = (
                    held_ms >= _LEFT_CONTACT_CONFIRM_MS
                    and (
                        self._left_contact_samples >= 2
                        or self._left_contact_min_ratio
                        <= self.config.pinch_engage
                        * _LEFT_DEEP_CONTACT_FACTOR
                    )
                )
                left_action_completed = self._left_button_down or contact_confirmed
                if left_action_completed:
                    self._right_ready = False
                    self._right_open_ratio = 0.0
                    self._right_requires_middle_reach = False
                    self._right_reach_grace_started_ns = None
                if self._left_button_down:
                    commands.extend(self._release_left(now))
                elif contact_confirmed:
                    commands.append(self._command(MouseCommandType.LEFT_CLICK, now))
                self._left_started_ns = None
                self._left_contact_samples = 0
                self._left_contact_min_ratio = 99.0
                self.state = ControlState.IDLE
                if left_action_completed:
                    # 松开左键的当前帧本身可能已经回到清晰指向。不能因
                    # “完成左击后立即返回”吞掉这帧的右键预备，否则用户
                    # 快速从左键切到右键时必须多做一次无意义的张开。
                    if (
                        not self.paused
                        and right_geometry_reliable
                        and (open_palm or pointer_shape)
                        and right_width_ratio >= self.config.pinch_arm
                        and right_ratio >= self.config.pinch_engage
                    ):
                        self._right_ready = True
                        self._right_open_ratio = right_ratio
                        self._right_requires_middle_reach = True
                        self._right_reach_grace_started_ns = None
                    return commands
                if not right_now:
                    return commands
            else:
                self._left_contact_samples += 1
                self._left_contact_min_ratio = min(
                    self._left_contact_min_ratio,
                    left_ratio,
                )
                if (
                    self._left_contact_samples >= 2
                    or self._left_contact_min_ratio
                    <= self.config.pinch_engage * _LEFT_DEEP_CONTACT_FACTOR
                ):
                    self._right_ready = False
                    self._right_open_ratio = 0.0
                    self._right_requires_middle_reach = False
                    self._right_reach_grace_started_ns = None
                self.current_gesture = (
                    GestureType.DRAG
                    if self._left_button_down
                    else GestureType.LEFT_PINCH
                )
                self._reset_orientation_tracking()
                if self._left_started_ns is not None:
                    held_ms = (now - self._left_started_ns) / 1_000_000
                    if (
                        held_ms >= self.config.drag_hold_ms
                        and not self._left_button_down
                    ):
                        commands.append(
                            self._command(MouseCommandType.LEFT_DOWN, now),
                        )
                        self._left_button_down = True
                        self.state = ControlState.DRAGGING
                if self._left_button_down:
                    x, y = self._cursor(points[8], now)
                    commands.append(
                        self._command(MouseCommandType.MOVE, now, x=x, y=y),
                    )
                return commands

        # 新右键只有在“先张开、再明显靠近”的时序成立时才允许进入。
        # 若同一帧两指都靠近，距离明显更近的目标指获胜；接近程度相同
        # 时仍保留左键优先，避免改变高频左键操作。
        right_wins = right_now and (
            not left_now or right_ratio + 0.08 < left_ratio
        )
        if right_wins:
            # 接触时指尖的位移属于捏合形变，不是新的瞄准位置。
            self.current_gesture = GestureType.RIGHT_PINCH
            self.state = ControlState.PINCH_PENDING
            self._reset_orientation_tracking()
            self._right_active = True
            self._right_started_ns = now
            self._right_ready = False
            self._right_requires_middle_reach = False
            self._right_reach_grace_started_ns = None
            self._right_contact_scale = gesture_scale
            self._right_contact_min_ratio = right_distance / max(
                gesture_scale,
                1e-4,
            )
            self._right_release_since_ns = None
            return commands

        if left_now and not self._left_rearm_required:
            was_moving = self.state == ControlState.MOVING
            contact_cursor_jump = self._cursor_target_distance(points[8])
            if (
                was_moving
                and self.current_gesture != GestureType.PINCH_ARMED
                and contact_cursor_jump >= _LEFT_MAX_CONTACT_CURSOR_JUMP
                and index_tip_span < _LEFT_MIN_IDENTITY_SPAN
            ):
                # 正常捏合主要由拇指靠近食指，食指目标不会在一帧内跨越
                # 大片屏幕。录像中的误左击来自食指身份突然跳到掌心；
                # 拒绝本轮接触并要求重新张开，不把错误点提交给光标。
                self._left_rearm_required = True
                self._right_ready = False
                self._right_open_ratio = 0.0
                self._right_requires_middle_reach = False
                self._right_reach_grace_started_ns = None
                self._reset_orientation_tracking()
                self.current_gesture = GestureType.NONE
                self.state = ControlState.IDLE
                return commands
            # 保留屏幕上已经看到的位置，禁止接触帧重新提交 MOVE。
            self.current_gesture = GestureType.LEFT_PINCH
            self._reset_orientation_tracking()
            self._left_active = True
            self._left_started_ns = now
            self._left_contact_samples = 1
            self._left_contact_min_ratio = left_ratio
            self.state = ControlState.PINCH_PENDING
            return commands

        # 在真正接触阈值之前提前进入点击意图区，停止所有光标轨迹。
        # 这样用户将光标对准目标后，拇指靠近指尖的过程不会拖动点击位置。
        left_near = (
            not rotation_contact_guard_active
            and not self._left_rearm_required
            and left_ratio <= left_intent_threshold
        )
        right_near = (
            right_reach_grace_active
            or (
                not rotation_contact_guard_active
                and self._right_ready
                and right_shape_valid
                and right_ratio <= self.config.pinch_arm
                and right_approach
                >= self.config.right_pinch_approach_delta * 0.5
            )
        )
        if left_near or right_near:
            self.current_gesture = GestureType.PINCH_ARMED
            self.state = ControlState.PINCH_PENDING
            self._reset_orientation_tracking()
            return commands

        if open_palm:
            if self._pointer_rotation_active:
                # 从食指翻腕过渡回张掌时延续滚动模式。否则本帧重置
                # 指向旋转状态后，下一帧的透视重叠又会进入点击判定。
                self._rotation_scroll_active = True
            self._reset_pointer_rotation()
            self.current_gesture = GestureType.SCROLL
            self.state = ControlState.SCROLLING
            center = _palm_center(points)
            if self._open_anchor_x is None or self._scroll_anchor_y is None:
                self._open_anchor_x = center.x
                self._scroll_anchor_y = center.y
                self._rotation_tilt_anchor = palm_tilt
                self._rotation_last_open_ns = now
                return commands
            self._rotation_last_open_ns = now
            motion_scale = _motion_scale(points)
            movement_x = (center.x - self._open_anchor_x) / motion_scale
            movement_y = (center.y - self._scroll_anchor_y) / motion_scale
            horizontal = abs(movement_x)
            vertical = abs(movement_y)
            tilt_delta = palm_tilt - (
                self._rotation_tilt_anchor
                if self._rotation_tilt_anchor is not None
                else palm_tilt
            )
            if (
                self.config.page_gestures_enabled
                and not self._page_swipe_latched
                and horizontal >= self.config.page_swipe_threshold
                and horizontal > vertical * 1.35
            ):
                self._page_swipe_latched = True
                self.current_gesture = (
                    GestureType.PAGE_NEXT
                    if movement_x < 0
                    else GestureType.PAGE_PREVIOUS
                )
                kind = (
                    MouseCommandType.PAGE_NEXT
                    if movement_x < 0
                    else MouseCommandType.PAGE_PREVIOUS
                )
                self._rotation_tilt_anchor = palm_tilt
                commands.append(self._command(kind, now))
                return commands
            if (
                self.config.rotation_gestures_enabled
                and not pinch_proximity
                and abs(tilt_delta) >= self.config.palm_rotation_threshold
            ):
                notches = round(
                    -tilt_delta * self.config.scroll_sensitivity * 6,
                )
                if notches == 0:
                    notches = -1 if tilt_delta > 0 else 1
                notches = max(-3, min(3, notches))
                self._rotation_tilt_anchor = palm_tilt
                self._rotation_scroll_active = True
                commands.append(
                    self._command(
                        MouseCommandType.WHEEL,
                        now,
                        delta=notches * 120,
                    ),
                )
                return commands
            if (
                vertical >= self.config.scroll_threshold
                and vertical > horizontal * 1.15
            ):
                notches = max(
                    -3,
                    min(3, round(-movement_y * self.config.scroll_sensitivity * 4)),
                )
                if notches:
                    commands.append(
                        self._command(
                            MouseCommandType.WHEEL,
                            now,
                            delta=notches * 120,
                        ),
                    )
                self._open_anchor_x = center.x
                self._scroll_anchor_y = center.y
                self._rotation_tilt_anchor = palm_tilt
            return commands

        self._reset_scroll_tracking()
        if not index_reliable:
            self.current_gesture = GestureType.NONE
            self.state = ControlState.IDLE
            return commands
        # 走到这里说明MediaPipe已经给出完整的21点手部观测，并且该帧
        # 不是握拳、捏合或张掌滚动。移动模式不再额外要求食指维持
        # ≥135°的僵硬姿势；自然微弯、侧手或中指半伸时仍可控制光标。
        self.current_gesture = GestureType.POINTER
        self.state = ControlState.MOVING
        if self._pointer_tilt_anchor is None:
            # 保留本轮指向开始时的基准，累计多帧小幅翻腕。逐帧覆盖基准
            # 会让慢速旋转永远达不到阈值，首个张掌投影反而被当成捏合。
            self._pointer_tilt_anchor = palm_tilt
        self._pointer_rotation_active = False
        x, y = self._cursor(points[8], now)
        commands.append(self._command(MouseCommandType.MOVE, now, x=x, y=y))
        return commands

    def tick(self, timestamp_ns: int | None = None) -> list[MouseCommand]:
        """检查手部数据超时并执行失联保护。"""

        now = timestamp_ns or monotonic_ns()
        if self.last_hand_ns is None:
            return []
        elapsed_ms = (now - self.last_hand_ns) / 1_000_000
        if elapsed_ms < self.config.hand_lost_ms or self._lost_reported:
            return []

        commands = self._release_left(now)
        self._mark_discrete_unreliable()
        self._reset_transient()
        self.filter.reset()
        self._last_pointer_input = None
        self.state = ControlState.LOST
        self.current_gesture = GestureType.LOST
        self._lost_reported = True
        return commands

    def cancel_observation(self, timestamp_ns: int) -> list[MouseCommand]:
        """明确检出为空或被安全检查拒绝时立即撤销，不等待失联宽限。"""
        commands = self._release_left(timestamp_ns)
        self._mark_discrete_unreliable()
        self._reset_transient()
        self.filter.reset()
        self._last_pointer_input = None
        self.state = ControlState.LOST
        self.current_gesture = GestureType.LOST
        self._lost_reported = True
        return commands
