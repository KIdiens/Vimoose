"""自动文档手势：无需选人和校准，张掌准备、单次翻页、回正复位。"""
from dataclasses import dataclass
from math import atan2, hypot, pi
from gesture_mouse.gestures import _is_open_palm


@dataclass(frozen=True, slots=True)
class DocumentEvent:
    session_id: str
    timestamp_ns: int
    direction: int


class DocumentGestures:
    def __init__(self, mirror=True):
        self.mirror = mirror
        self.last_sent = -1_000_000_000
        self.reset()

    def reset(self):
        self.anchor = None
        self.since = 0
        self.last = 0
        self.fired = 0
        self.return_since = None
        self.non_palm_since = None
        self.ready = False

    def process(self, hand, token, kind):
        """返回（是否占用当前动作，事件）；占用时不移动光标、不点击。"""
        if not token or hand is None or len(hand.landmarks) != 21:
            self.reset()
            return False,None
        t,p = hand.timestamp_ns,hand.landmarks
        if any(not (0<=v<=1) for point in p for v in (point.x,point.y)):
            self.reset()
            return True,None
        if t <= self.last:
            return True,None
        if self.last and t-self.last > 180_000_000:
            self.reset()
        self.last = t
        palm = _is_open_palm(p)
        if self.anchor is None and not palm:
            return False,None
        if not palm:
            if self.non_palm_since is None:
                self.non_palm_since = t
            if t-self.non_palm_since > 250_000_000:
                self.reset()
                return False,None
        else:
            self.non_palm_since = None
        scale = max(.055,hypot(p[0].x-p[9].x,p[0].y-p[9].y))
        x = sum(p[i].x for i in (0,5,9,13,17))/5
        y = sum(p[i].y for i in (0,5,9,13,17))/5
        # 使用掌面法向的连续转角，允许小幅翻腕，不要求挥动整条手臂。
        a,b = p[5],p[17]
        nx = (a.y-p[0].y)*(b.z-p[0].z)-(a.z-p[0].z)*(b.y-p[0].y)
        nz = (a.x-p[0].x)*(b.y-p[0].y)-(a.y-p[0].y)*(b.x-p[0].x)
        angle = atan2(nx,nz)
        if self.anchor is None:
            self.anchor = x,y,angle,scale
            self.since = t
            return True,None
        ax,ay,aa,ss = self.anchor
        dx,dy = (x-ax)/ss,(y-ay)/ss
        da = (angle-aa+pi)%(2*pi)-pi
        neutral = abs(dx)<.28 and abs(dy)<.28 and abs(da)<.25 and palm
        if self.fired:
            if neutral:
                if self.return_since is None:
                    self.return_since = t
                if t-self.return_since >= 300_000_000 and t-self.fired >= 600_000_000:
                    self.fired = 0
                    self.ready = True
                    self.since = t
            else:
                self.return_since = None
            return True,None
        if not self.ready:
            if not neutral:
                self.anchor = x,y,angle,scale
                self.since = t
            elif t-self.since >= 300_000_000:
                self.ready = True
            return True,None
        if abs(dx)<.18 and abs(dy)<.18 and abs(da)<.18:
            self.since = t
            return True,None
        elapsed = t-self.since
        if elapsed > 1_000_000_000:
            # 超时后必须回正，不在偏转姿势上重新建立准备基准。
            self.fired = t
            return True,None
        direction = 0
        if kind == "word" and abs(dy)>.65 and abs(dy)>abs(dx)*1.35:
            direction = 1 if dy>0 else -1
        elif abs(dx)>.65 and abs(dx)>abs(dy)*1.35:
            direction = (-1 if dx>0 else 1) * (1 if self.mirror else -1)
        elif abs(da)>.60 and abs(dx)>.12 and abs(dy)<.4:
            direction = (-1 if dx>0 else 1) * (1 if self.mirror else -1)
        if direction and elapsed >= 100_000_000 and t-self.last_sent >= 600_000_000:
            self.fired = t
            self.last_sent = t
            self.return_since = None
            return True,DocumentEvent(token,t,direction)
        return True,None
