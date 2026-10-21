"""测试用合成手部关键点。"""

from __future__ import annotations

from gesture_mouse.contracts import HandObservation, Landmark


def pointer_points() -> tuple[Landmark, ...]:
    """食指伸出、其余手指弯曲的右手关键点。"""

    values = [
        (0.50, 0.80),  # 0 wrist
        (0.42, 0.70), (0.36, 0.62), (0.30, 0.55), (0.25, 0.48),
        (0.42, 0.60), (0.42, 0.45), (0.42, 0.33), (0.42, 0.20),
        (0.50, 0.60), (0.50, 0.48), (0.51, 0.53), (0.52, 0.58),
        (0.58, 0.61), (0.58, 0.50), (0.59, 0.55), (0.60, 0.60),
        (0.66, 0.64), (0.66, 0.54), (0.67, 0.59), (0.68, 0.64),
    ]
    return tuple(Landmark(x, y) for x, y in values)


def left_pinch_points() -> tuple[Landmark, ...]:
    points = list(pointer_points())
    points[4] = points[8]
    return tuple(points)


def collapsed_index_near_thumb_points() -> tuple[Landmark, ...]:
    """模拟食指身份瞬间跳到掌心，错误贴近拇指的预测帧。"""

    points = list(pointer_points())
    points[6] = Landmark(0.42, 0.45)
    points[7] = Landmark(0.42, 0.52)
    points[8] = Landmark(0.43, 0.56)
    points[4] = points[8]
    return tuple(points)


def fist_like_left_pinch_points() -> tuple[Landmark, ...]:
    """录像中的侧向左键捏合：其余手指收拢，二维投影近似握拳。"""

    points = list(fist_points())
    points[4] = points[8]
    return tuple(points)


def right_pinch_points() -> tuple[Landmark, ...]:
    """从食指指向过渡到中指主动伸出的右键捏合。"""

    points = list(pointer_points())
    points[12] = Landmark(0.50, 0.32)
    points[4] = points[12]
    return tuple(points)


def bent_middle_right_pinch_points(
    contact_ratio: float = 0.0,
) -> tuple[Landmark, ...]:
    """中指保持弯曲、但指尖主动前伸到拇指的真实右键姿势。"""

    points = list(pointer_points())
    points[10] = Landmark(0.50, 0.48)
    points[11] = Landmark(0.58, 0.46)
    points[12] = Landmark(0.68, 0.50)
    palm_width = (
        (points[5].x - points[17].x) ** 2
        + (points[5].y - points[17].y) ** 2
    ) ** 0.5
    palm_length = (
        (points[0].x - points[9].x) ** 2
        + (points[0].y - points[9].y) ** 2
    ) ** 0.5
    scale = max(palm_width, min(palm_length * 0.75, palm_width * 2.0))
    points[4] = Landmark(
        points[12].x - contact_ratio * scale,
        points[12].y,
    )
    return tuple(points)


def right_pinch_from_open_points() -> tuple[Landmark, ...]:
    """张掌后主动伸出中指并与拇指接触的右键捏合。"""

    points = list(open_palm_points())
    points[12] = Landmark(0.50, 0.32)
    points[4] = points[12]
    return tuple(points)


def middle_tucked_pointer_points() -> tuple[Landmark, ...]:
    """食指独立伸出时，拇指自然贴近已收拢的中指。

    这是用户录屏中最常见的移动姿势；只看拇指与中指尖距离会将它
    误判成右键捏合。
    """

    points = list(pointer_points())
    points[4] = Landmark(points[12].x + 0.01, points[12].y)
    return tuple(points)


def ambiguous_right_pinch_points() -> tuple[Landmark, ...]:
    """右键捏合过程中食指也短暂靠近拇指的过渡帧。"""

    points = list(right_pinch_points())
    points[8] = Landmark(points[4].x + 0.01, points[4].y)
    # 保留一根自然伸展的无关手指，避免合成数据退化成真正的握拳。
    points[16] = Landmark(0.58, 0.27)
    return tuple(points)


def rotated_scroll_points() -> tuple[Landmark, ...]:
    """张掌向镜头方向翻腕后的深度关键点。

    掌心中心不平移，只改变腕部到中指掌指关节的相对深度，用于验证
    原地翻腕也能产生滚轮事件。
    """

    points = list(open_palm_points())
    points[9] = Landmark(points[9].x, points[9].y, 0.10)
    return tuple(points)


def rotated_projected_closed_points() -> tuple[Landmark, ...]:
    """翻腕后二维投影近似握拳，但掌面深度已明显变化的过渡帧。"""

    points = list(fist_points())
    points[9] = Landmark(points[9].x, points[9].y, 0.10)
    return tuple(points)


def fist_points() -> tuple[Landmark, ...]:
    points = list(pointer_points())
    for tip, x, y in (
        (8, 0.43, 0.56),
        (12, 0.51, 0.58),
        (16, 0.59, 0.60),
        (20, 0.67, 0.63),
    ):
        points[tip] = Landmark(x, y)
    return tuple(points)


def open_palm_points() -> tuple[Landmark, ...]:
    """四指自然伸展的张掌关键点。"""

    points = list(pointer_points())
    for tip, x, y in (
        (12, 0.50, 0.24),
        (16, 0.58, 0.27),
        (20, 0.66, 0.31),
    ):
        points[tip] = Landmark(x, y)
    return tuple(points)


def thumb_outside_left_contact_points() -> tuple[Landmark, ...]:
    """拇指越过右边界后，模型把拇指尖预测到食指尖附近。"""

    points = list(pointer_points())
    points[6] = Landmark(0.68, 0.45)
    points[7] = Landmark(0.84, 0.32)
    points[8] = Landmark(0.99, 0.20)
    points[1] = Landmark(0.88, 0.58)
    points[2] = Landmark(0.94, 0.45)
    points[3] = Landmark(0.99, 0.31)
    points[4] = Landmark(1.02, 0.20)
    return tuple(points)


def thumb_outside_right_contact_points() -> tuple[Landmark, ...]:
    """拇指越过右边界后，模型把拇指尖预测到中指尖附近。"""

    points = list(pointer_points())
    points[4] = Landmark(1.02, 0.30)
    points[10] = Landmark(0.80, 0.46)
    points[11] = Landmark(0.91, 0.37)
    points[12] = Landmark(0.99, 0.30)
    return tuple(points)


def thumb_outside_fist_points() -> tuple[Landmark, ...]:
    """四指投影像握拳，但拇指链已经离开画面。"""

    points = list(fist_points())
    for index, y in zip((1, 2, 3, 4), (0.82, 0.76, 0.70, 0.64)):
        points[index] = Landmark(-0.04 - index * 0.01, y)
    return tuple(points)


def thumb_outside_open_palm_points() -> tuple[Landmark, ...]:
    """四指仍张开，但拇指链已经离开画面。"""

    points = list(open_palm_points())
    for index, y in zip((1, 2, 3, 4), (0.82, 0.76, 0.70, 0.64)):
        points[index] = Landmark(-0.04 - index * 0.01, y)
    return tuple(points)


def translate_points(
    points: tuple[Landmark, ...],
    dx: float = 0.0,
    dy: float = 0.0,
) -> tuple[Landmark, ...]:
    return tuple(Landmark(point.x + dx, point.y + dy, point.z) for point in points)


def observation(
    points: tuple[Landmark, ...],
    timestamp_ns: int,
) -> HandObservation:
    return HandObservation(
        landmarks=points,
        handedness="Right",
        timestamp_ns=timestamp_ns,
        inference_ms=12.0,
        handedness_score=0.98,
    )
