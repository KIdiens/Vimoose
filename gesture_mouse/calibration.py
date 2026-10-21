"""基于用户真实手型样本计算个性化识别参数。"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from statistics import median
from typing import Sequence

from gesture_mouse.contracts import Landmark
from gesture_mouse.filters import clamp


class CalibrationError(ValueError):
    """校准样本不足或动作区分度不够。"""


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    """可直接写入应用配置的校准结果。"""

    pinch_engage: float
    pinch_release: float
    pointer_stability: float
    pointer_response: float
    cursor_interpolation_ms: int
    open_ratio: float
    closed_ratio: float
    pointer_jitter: float


def pinch_ratio(points: Sequence[Landmark]) -> float:
    """返回按稳健手部尺度归一化的拇指—食指二维距离。"""

    if len(points) != 21:
        raise CalibrationError("手部关键点数量不完整")
    return hypot(
        points[4].x - points[8].x,
        points[4].y - points[8].y,
    ) / gesture_scale(points)


def gesture_scale(points: Sequence[Landmark]) -> float:
    """返回校准和运行时共用的二维手部尺度。"""

    if len(points) != 21:
        raise CalibrationError("手部关键点数量不完整")
    palm_width = hypot(
        points[5].x - points[17].x,
        points[5].y - points[17].y,
    )
    palm_length = hypot(
        points[0].x - points[9].x,
        points[0].y - points[9].y,
    )
    length_scale = min(palm_length * 0.75, palm_width * 2.0)
    return max(palm_width, length_scale, 1e-4)


def pointer_position(points: Sequence[Landmark]) -> tuple[float, float]:
    """返回用于静止抖动评估的食指指尖位置。"""

    if len(points) != 21:
        raise CalibrationError("手部关键点数量不完整")
    return points[8].x, points[8].y


def calculate_calibration(
    open_ratios: Sequence[float],
    closed_ratios: Sequence[float],
    pointer_points: Sequence[tuple[float, float]],
) -> CalibrationResult:
    """从张开、捏合与静止指向样本计算阈值、滤波和插值参数。"""

    if min(len(open_ratios), len(closed_ratios), len(pointer_points)) < 6:
        raise CalibrationError("有效样本不足，请保持动作并重新采样")

    open_ratio = float(median(open_ratios))
    closed_ratio = float(median(closed_ratios))
    separation = open_ratio - closed_ratio
    if separation < 0.10:
        raise CalibrationError("张开与捏合动作区分不明显，请放大动作后重试")

    # 两个阈值均落在用户自己的开合区间中，形成稳定滞回。
    engage = clamp(closed_ratio + separation * 0.32, 0.22, 0.68)
    release = clamp(closed_ratio + separation * 0.56, engage + 0.06, 0.90)
    release = min(release, max(engage + 0.06, open_ratio - 0.03))

    center_x = float(median(point[0] for point in pointer_points))
    center_y = float(median(point[1] for point in pointer_points))
    jitter = float(
        median(hypot(x - center_x, y - center_y) for x, y in pointer_points),
    )
    stability = clamp(0.44 + jitter * 28.0, 0.44, 0.84)
    response = clamp(0.86 - jitter * 4.0, 0.72, 0.86)
    interpolation_ms = round(clamp(32.0 + jitter * 800.0, 32.0, 52.0))

    return CalibrationResult(
        pinch_engage=engage,
        pinch_release=release,
        pointer_stability=stability,
        pointer_response=response,
        cursor_interpolation_ms=interpolation_ms,
        open_ratio=open_ratio,
        closed_ratio=closed_ratio,
        pointer_jitter=jitter,
    )
