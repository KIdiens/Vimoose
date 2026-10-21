"""纯几何、可回放的课堂手势与校准，不产生系统输入。"""

from __future__ import annotations

from dataclasses import dataclass, fields
from math import atan2, hypot, pi, isfinite
from statistics import median

from gesture_mouse.contracts import HandObservation
from gesture_mouse.teacher_tracking import BodyObservation


@dataclass(frozen=True, slots=True)
class PresentationEvent:
    session_id: str
    timestamp_ns: int
    direction: int  # 1 下一步，-1 上一步。


@dataclass(frozen=True, slots=True)
class HandFeatures:
    timestamp_ns: int
    lateral: float
    palm_angle: float
    height: float
    open_palm: bool
    quality: bool = True


def features_for(hand: HandObservation, body: BodyObservation, mirror: bool) -> HandFeatures:
    """以身体和手腕为参照；几何坐标统一为老师自身向左为正。"""
    p = hand.landmarks
    sign = -1. if mirror else 1.
    s = max(hypot(p[0].x-p[9].x, p[0].y-p[9].y), .02)
    center_x = sum(p[i].x for i in (5, 9, 13, 17)) / 4
    lateral = sign * ((center_x-p[0].x)/s + .35*(p[0].x-body.center[0])/body.scale)
    # 手掌法向量的左右转动，避免将纯平移误作翻腕。
    a = (p[5].x-p[0].x, p[5].y-p[0].y, p[5].z-p[0].z)
    b = (p[17].x-p[0].x, p[17].y-p[0].y, p[17].z-p[0].z)
    nx, nz = a[1]*b[2]-a[2]*b[1], a[0]*b[1]-a[1]*b[0]
    angle = atan2(sign * nx, nz)
    # 指尖到手腕比中间关节更远；比固定关节角度更兼容自然张掌。
    extended = sum(hypot(p[tip].x-p[0].x, p[tip].y-p[0].y) >
                   hypot(p[pip].x-p[0].x, p[pip].y-p[0].y)*1.08
                   for pip, tip in ((6,8), (10,12), (14,16), (18,20)))
    height = (p[0].y-body.center[1])/body.scale
    quality = all(isfinite(v) for v in (lateral, angle, height)) and s >= .025
    return HandFeatures(hand.timestamp_ns, lateral, angle, height, extended >= 3, quality)


def angle_delta(a, b):
    return (a-b+pi) % (2*pi)-pi


@dataclass(slots=True)
class ClassroomCalibration:
    neutral_lateral: float = 0.
    neutral_angle: float = 0.
    neutral_height: float = 0.
    next_vector: tuple[float, float] = (1., 0.)
    previous_vector: tuple[float, float] = (-1., 0.)
    next_threshold: float = .5
    previous_threshold: float = .5

    @classmethod
    def from_mapping(cls, value):
        try:
            if not value or set(value) != {f.name for f in fields(cls)}:
                return None
            result = cls(**value)
            for v in (result.next_vector, result.previous_vector):
                if len(v) != 2 or not all(isfinite(float(x)) for x in v):
                    return None
                if not .9 <= hypot(*v) <= 1.1:
                    return None
            if not all(isfinite(float(v)) for v in (result.neutral_lateral,
                result.neutral_angle, result.neutral_height, result.next_threshold,
                result.previous_threshold)):
                return None
            if min(result.next_threshold, result.previous_threshold) < .18:
                return None
            if sum(a*b for a,b in zip(result.next_vector,result.previous_vector)) > .35:
                return None
            return result
        except (TypeError, ValueError, KeyError):
            return None

    def vector(self, f):
        return (f.lateral-self.neutral_lateral,
                angle_delta(f.palm_angle, self.neutral_angle)*.6)

    def neutral(self, f):
        # 回正主要看掌面方向；允许自然回位的少量横向偏移，不能要求回到同一像素。
        return (f.open_palm and abs(angle_delta(f.palm_angle,self.neutral_angle)) < .30
                and abs(f.lateral-self.neutral_lateral) < max(.40,min(
                    self.next_threshold,self.previous_threshold)*.6))

    def motion_started(self, f):
        v = self.vector(f)
        magnitude = hypot(*v)
        return magnitude > .01 and any(
            sum(a*b for a,b in zip(v,target)) >= threshold*.5
            and sum(a*b for a,b in zip(v,target))/magnitude >= .65
            for target,threshold in ((self.next_vector,self.next_threshold),
                                     (self.previous_vector,self.previous_threshold)))

    def classify(self, f):
        v = self.vector(f)
        magnitude = hypot(*v)
        if magnitude < .01:
            return 0
        matches = []
        for direction, target, threshold in ((1,self.next_vector,self.next_threshold),
                                             (-1,self.previous_vector,self.previous_threshold)):
            projection = sum(a*b for a,b in zip(v,target))
            if projection >= threshold and projection/magnitude >= .65:
                matches.append(direction)
        return matches[0] if len(matches) == 1 else 0


class CalibrationRecorder:
    """正掌和左右各三次动作；每次侧向到位后必须回正。"""

    def __init__(self):
        self.neutrals = []
        self.samples = {1: [], -1: []}
        self.calibration = None
        self.peak = None
        self.start_ns = None
        self.last_ns = 0
        self.message = "在舒适操作高度正对镜头张掌并保持一秒"

    def update(self, f):
        if (not f or not f.quality or f.timestamp_ns <= self.last_ns
                or (self.last_ns and f.timestamp_ns-self.last_ns > 200_000_000)):
            if f:
                self.last_ns = max(self.last_ns,f.timestamp_ns)
            self.start_ns = None
            self.peak = None
            if self.calibration is None:
                self.neutrals.clear()
            self.message = "控制手不可见，请重新张掌"
            return None
        self.last_ns = f.timestamp_ns
        if self.calibration is None:
            if not f.open_palm:
                self.neutrals.clear()
                return None
            if self.neutrals and (abs(f.lateral-self.neutrals[0].lateral) > .15
                                  or abs(angle_delta(f.palm_angle,self.neutrals[0].palm_angle)) > .25):
                self.neutrals.clear()
                self.message = "请保持正掌静止一秒，再开始左右动作"
            self.neutrals.append(f)
            if f.timestamp_ns-self.neutrals[0].timestamp_ns < 1_000_000_000:
                return None
            self.calibration = ClassroomCalibration(
                neutral_lateral=median(x.lateral for x in self.neutrals),
                neutral_angle=self.neutrals[len(self.neutrals)//2].palm_angle,
                neutral_height=median(x.height for x in self.neutrals))
        c = self.calibration
        direction = 1 if len(self.samples[1]) < 3 else -1
        self.message = (f"向{'左' if direction == 1 else '右'}摆动／翻腕后回正："
                        f"{len(self.samples[direction])}/3")
        v = c.vector(f)
        magnitude = hypot(*v)
        if magnitude > .35:
            if self.start_ns is None:
                self.start_ns = f.timestamp_ns
            if self.peak is None or magnitude > hypot(*self.peak):
                self.peak = v
        elif c.neutral(f) and self.peak is not None:
            elapsed = (f.timestamp_ns-self.start_ns)/1e6
            if 150 <= elapsed <= 4000:
                self.samples[direction].append(self.peak)
            self.start_ns, self.peak = None, None
        if len(self.samples[-1]) < 3:
            return None
        vectors = []
        for d in (1,-1):
            vals = self.samples[d]
            x, y = median(v[0] for v in vals), median(v[1] for v in vals)
            size = hypot(x,y)
            vectors.append(((x/size,y/size), max(.20, size*.6)))
        if sum(a*b for a,b in zip(vectors[0][0],vectors[1][0])) > .35:
            self.samples = {1:[], -1:[]}
            self.message = "两个方向过于相似，请向相反方向分别校准"
            return None
        c.next_vector, c.next_threshold = vectors[0]
        c.previous_vector, c.previous_threshold = vectors[1]
        self.message = "校准完成"
        return c


class ClassroomGestureEngine:
    """仅产生离散翻页事件；回正与冷却同时满足才重新准备。"""

    def __init__(self, calibration: ClassroomCalibration | None):
        self.calibration = calibration
        self.last_ns = 0
        self.state = "等待正掌"
        self.stable_ns = None
        self.motion_ns = None
        self.cooldown_until = 0
        self.recover_ns = None
        self.recovering = True
        self.motion_direction = 0

    def cancel(self):
        self.state = "等待正掌"
        self.stable_ns = self.motion_ns = self.recover_ns = None
        self.recovering = True
        self.motion_direction = 0

    def process(self, f, session_id, now_ns=None):
        if f is None or not f.quality or not session_id or self.calibration is None:
            self.cancel()
            return None
        if f.timestamp_ns <= self.last_ns:
            self.cancel()
            return None
        gap = f.timestamp_ns-self.last_ns if self.last_ns else 0
        self.last_ns = f.timestamp_ns
        if (now_ns is not None and not 0 <= now_ns-f.timestamp_ns < 200_000_000) or gap > 200_000_000:
            self.cancel()
            return None
        c = self.calibration
        if abs(f.height-c.neutral_height) > .8:
            self.cancel()
            return None
        t = f.timestamp_ns
        if self.recovering:
            if self.recover_ns is None:
                self.recover_ns = t
            if t-self.recover_ns < 500_000_000:
                self.state = "控制手恢复中"
                return None
            self.recovering = False
        neutral = c.neutral(f)
        if self.state in ("等待回正", "等待正掌", "控制手恢复中", "正掌稳定中"):
            if not neutral:
                self.stable_ns = None
                return None
            if self.stable_ns is None:
                self.stable_ns = t
            if t-self.stable_ns >= 300_000_000 and t >= self.cooldown_until:
                self.state = "可翻页"
            else:
                self.state = "正掌稳定中" if t >= self.cooldown_until else "等待回正"
            return None
        if neutral:
            self.motion_ns = None
            self.motion_direction = 0
            self.state = "可翻页"
            return None
        if self.motion_ns is None:
            if not c.motion_started(f):
                return None
            self.motion_ns = t
            self.motion_direction = 0
        duration = (t-self.motion_ns)/1e6
        self.state = "识别动作中"
        if duration > 1000:
            self.state = "等待回正"
            self.stable_ns = None
            return None
        direction = c.classify(f)
        if direction and self.motion_direction and direction != self.motion_direction:
            self.state = "等待回正"
            self.stable_ns = self.motion_ns = None
            return None
        if direction:
            self.motion_direction = direction
        if direction and duration >= 150:
            self.state = "等待回正"
            self.stable_ns = self.motion_ns = None
            self.cooldown_until = t+600_000_000
            return PresentationEvent(session_id, t, direction)
        return None
