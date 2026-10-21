"""课堂控制者关联；身份不确定时失效，不按高度或检测顺序换人。"""

from __future__ import annotations

from dataclasses import dataclass
from math import hypot, isfinite
from uuid import uuid4

from gesture_mouse.contracts import HandObservation, Landmark


def display_landmarks(points, mirror):
    """模型始终看非镜像图；只在输出时映射到预览，保留人体左右语义。"""
    return tuple(Landmark(1-p.x if mirror else p.x,p.y,p.z) for p in points)


@dataclass(frozen=True, slots=True)
class BodyObservation:
    """只包含本帧人体几何，不将模型数组下标当作身份。"""

    points: tuple[Landmark, ...]
    visibility: tuple[float, ...]

    @property
    def center(self) -> tuple[float, float]:
        return ((self.points[11].x + self.points[12].x) / 2,
                (self.points[11].y + self.points[12].y) / 2)

    @property
    def scale(self) -> float:
        a, b = self.points[11], self.points[12]
        return max(0.04, hypot(a.x - b.x, a.y - b.y))

    @property
    def box(self) -> tuple[float, float, float, float]:
        x, y = self.center
        s = self.scale
        return max(0., x-s), max(0., y-s), min(1., x+s), min(1., y+1.8*s)

    def reliable(self) -> bool:
        return (len(self.points) == 33 and len(self.visibility) == 33
                and all(self.visibility[i] >= .5 and isfinite(self.points[i].x)
                        and isfinite(self.points[i].y) and 0 <= self.points[i].x <= 1
                        and 0 <= self.points[i].y <= 1 for i in (11, 12)))


class TeacherTracker:
    """同帧肩部关联与手腕归属校验；无自动重新接管。"""

    def __init__(self, region=(0., 0., 1., 1.), hand="Right"):
        self.region = tuple(region)
        self.hand = hand
        self.body: BodyObservation | None = None
        self.lock_id = ""
        self.reason = "待锁定：请点选老师"
        self.timestamp_ns = 0

    def candidates(self, bodies):
        l, t, r, b = self.region
        return tuple(p for p in bodies if p.reliable()
                     and l <= p.center[0] <= r and t <= p.center[1] <= b)

    def invalidate(self, reason="教师跟踪丢失，请重新点选"):
        self.body = None
        self.lock_id = ""
        self.reason = reason

    def select(self, bodies, x, y, timestamp_ns):
        choices = [p for p in self.candidates(bodies)
                   if p.box[0] <= x <= p.box[2] and p.box[1] <= y <= p.box[3]]
        self.invalidate("选区内人物不唯一，请重新点选")
        if len(choices) != 1:
            return False
        self.body = choices[0]
        self.timestamp_ns = timestamp_ns
        self.lock_id = uuid4().hex
        self.reason = "教师已锁定"
        return True

    def update(self, bodies, hands, timestamp_ns) -> HandObservation | None:
        if self.body is None:
            return None
        if timestamp_ns <= self.timestamp_ns:
            return None
        if timestamp_ns - self.timestamp_ns > 500_000_000:
            self.invalidate("人体观测过期，请重新点选")
            return None
        old = self.body
        plausible = []
        for p in self.candidates(bodies):
            ratio = p.scale / old.scale
            d = hypot(p.center[0]-old.center[0], p.center[1]-old.center[1]) / old.scale
            if .65 <= ratio <= 1.55 and d <= .55:
                plausible.append((d, p))
        if len(plausible) != 1:
            self.invalidate("教师丢失或多人重叠，请重新点选")
            return None
        body = plausible[0][1]
        # 锁定对象附近出现第二个人，即使其未进入关联门限也不冒险换人。
        if any(p is not body and hypot(p.center[0]-body.center[0],
               p.center[1]-body.center[1]) < .8 * max(p.scale, body.scale)
               for p in self.candidates(bodies)):
            self.invalidate("多人交叉，控制已停止，请重新点选")
            return None
        self.body = body
        self.timestamp_ns = timestamp_ns
        wrist_index = 16 if self.hand == "Right" else 15
        elbow_index = wrist_index - 2
        if min(body.visibility[wrist_index], body.visibility[elbow_index]) < .5:
            self.reason = "控制手手腕或手肘被遮挡"
            return None
        wrist = body.points[wrist_index]
        matches = []
        for h in hands:
            if len(h.landmarks) != 21 or h.partial_finger or h.timestamp_ns != timestamp_ns:
                continue
            if not all(isfinite(p.x) and isfinite(p.y) and isfinite(p.z)
                       and 0 <= p.x <= 1 and 0 <= p.y <= 1 for p in h.landmarks):
                continue
            hw = h.landmarks[0]
            if hypot(hw.x-wrist.x, hw.y-wrist.y) > body.scale * .32:
                continue
            # 与任意另一人的手腕接近时拒绝，不用左右手分类分数猜身份。
            rival = any(other is not body and other.reliable()
                        and any(other.visibility[j] >= .5 and hypot(
                            hw.x-other.points[j].x, hw.y-other.points[j].y)
                            < other.scale * .40 for j in (15, 16)) for other in bodies)
            other_wrist = body.points[15 if wrist_index == 16 else 16]
            if rival or hypot(hw.x-other_wrist.x, hw.y-other_wrist.y) < body.scale * .25:
                continue
            matches.append(h)
        self.reason = "控制手已关联" if len(matches) == 1 else "控制手缺失或归属不明确"
        return matches[0] if len(matches) == 1 else None
