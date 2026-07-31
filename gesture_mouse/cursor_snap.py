"""Windows控件磁吸的异步探测与纯几何状态机。"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from math import hypot
from typing import Protocol

from gesture_mouse.filters import clamp


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SnapCandidate:
    """一个可点击控件及其推荐落点，坐标均为物理屏幕像素。"""

    x: int
    y: int
    left: int
    top: int
    right: int
    bottom: int
    name: str = ""
    control_type: str = ""


def _distance_to_rect(x: int, y: int, candidate: SnapCandidate) -> float:
    nearest_x = min(max(x, candidate.left), candidate.right)
    nearest_y = min(max(y, candidate.top), candidate.bottom)
    return hypot(x - nearest_x, y - nearest_y)


def _activation_distance(x: int, y: int, candidate: SnapCandidate) -> float:
    """返回磁吸激活距离；标签页只在中心锚点附近吸附。

    浏览器的TabItem矩形通常覆盖整张标签。若按矩形距离判断，光标一进入
    标签右侧就会被拉回中心，从而永远到不了独立的“关闭标签页”按钮。
    """

    if candidate.control_type == "TabItemControl":
        return hypot(x - candidate.x, y - candidate.y)
    return _distance_to_rect(x, y, candidate)


class UiTargetProbe(Protocol):
    """控件探测后端；Windows实现必须在其专用线程内初始化COM。"""

    def initialize(self) -> None: ...

    def close(self) -> None: ...

    def find_target(
        self,
        x: int,
        y: int,
        radius_px: int,
    ) -> SnapCandidate | None: ...


class MagneticSnapState:
    """带释放滞回的磁吸状态，避免光标在控件边缘反复跳动。"""

    def __init__(
        self,
        radius_px: int,
        release_multiplier: float = 1.8,
    ) -> None:
        self.radius_px = max(1, int(radius_px))
        self.release_multiplier = max(1.05, float(release_multiplier))
        self._latched: SnapCandidate | None = None

    @property
    def target_name(self) -> str | None:
        if self._latched is None:
            return None
        return self._latched.name or self._latched.control_type or "可点击控件"

    def configure(self, radius_px: int) -> None:
        self.radius_px = max(1, int(radius_px))
        self._latched = None

    def clear(self) -> None:
        self._latched = None

    def resolve(
        self,
        x: int,
        y: int,
        candidate: SnapCandidate | None,
    ) -> tuple[int, int, bool]:
        if self._latched is not None:
            release_radius = self.radius_px * self.release_multiplier
            if _activation_distance(x, y, self._latched) <= release_radius:
                return self._latched.x, self._latched.y, True
            self._latched = None

        if (
            candidate is not None
            and _activation_distance(x, y, candidate) <= self.radius_px
        ):
            self._latched = candidate
            return candidate.x, candidate.y, True
        return x, y, False


class WindowsUiAutomationProbe:
    """使用Windows UI Automation查找光标附近的可点击控件。"""

    _CONTROL_TYPES = {
        50000,  # Button
        50002,  # CheckBox
        50005,  # Hyperlink
        50011,  # MenuItem
        50013,  # RadioButton
        50031,  # SplitButton
    }

    def __init__(self) -> None:
        self._auto: object | None = None
        self._initializer: object | None = None

    def initialize(self) -> None:
        if self._auto is not None:
            return
        from uiautomation import uiautomation as auto

        self._initializer = auto.UIAutomationInitializerInThread()
        self._auto = auto

    def close(self) -> None:
        initializer = self._initializer
        self._initializer = None
        self._auto = None
        if initializer is not None:
            try:
                initializer.Uninitialize()
            except Exception:
                LOGGER.debug("释放UI Automation线程失败", exc_info=True)

    @staticmethod
    def _probe_offsets(radius_px: int) -> tuple[tuple[int, int], ...]:
        half = max(4, radius_px // 2)
        diagonal = max(4, round(radius_px * 0.70))
        return (
            (0, 0),
            (half, 0),
            (-half, 0),
            (0, half),
            (0, -half),
            (radius_px, 0),
            (-radius_px, 0),
            (0, radius_px),
            (0, -radius_px),
            (diagonal, diagonal),
            (diagonal, -diagonal),
            (-diagonal, diagonal),
            (-diagonal, -diagonal),
        )

    def _candidate_from_control(
        self,
        control: object,
    ) -> SnapCandidate | None:
        for _ in range(5):
            if control is None:
                return None
            try:
                control_type = int(control.ControlType)
            except Exception:
                return None
            if control_type in self._CONTROL_TYPES:
                break
            try:
                control = control.GetParentControl()
            except Exception:
                return None
        else:
            return None

        try:
            if not bool(control.IsEnabled) or bool(control.IsOffscreen):
                return None
            rect = control.BoundingRectangle
            left = int(rect.left)
            top = int(rect.top)
            right = int(rect.right)
            bottom = int(rect.bottom)
            if right <= left or bottom <= top:
                return None
            x, y, got_clickable = control.GetClickablePoint()
            if not got_clickable:
                x = round((left + right) / 2)
                y = round((top + bottom) / 2)
            try:
                name = str(control.Name or "")
            except Exception:
                name = ""
            try:
                type_name = str(control.ControlTypeName or "")
            except Exception:
                type_name = "ButtonControl"
            return SnapCandidate(
                x=int(x),
                y=int(y),
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                name=name,
                control_type=type_name,
            )
        except Exception:
            return None

    def find_target(
        self,
        x: int,
        y: int,
        radius_px: int,
    ) -> SnapCandidate | None:
        self.initialize()
        auto = self._auto
        if auto is None:
            return None

        candidates: dict[tuple[int, int, int, int], SnapCandidate] = {}
        for dx, dy in self._probe_offsets(radius_px):
            try:
                control = auto.ControlFromPoint(int(x + dx), int(y + dy))
                candidate = self._candidate_from_control(control)
            except Exception:
                # UI元素可能在探测期间被销毁；按Windows文档要求优雅降级。
                continue
            if candidate is None:
                continue
            key = (
                candidate.left,
                candidate.top,
                candidate.right,
                candidate.bottom,
            )
            candidates[key] = candidate

        nearby = [
            candidate
            for candidate in candidates.values()
            if _activation_distance(x, y, candidate) <= radius_px
        ]
        if not nearby:
            return None
        return min(
            nearby,
            key=lambda item: (
                _activation_distance(x, y, item),
                hypot(x - item.x, y - item.y),
            ),
        )


class CursorSnapService:
    """异步探测控件并在鼠标线程内以常数时间应用磁吸。"""

    def __init__(
        self,
        probe: UiTargetProbe,
        *,
        screen_width: int,
        screen_height: int,
        enabled: bool,
        radius_px: int,
        start_worker: bool = True,
        poll_interval_seconds: float = 0.06,
    ) -> None:
        self.probe = probe
        self.screen_width = max(2, int(screen_width))
        self.screen_height = max(2, int(screen_height))
        self.enabled = bool(enabled)
        self.radius_px = max(1, int(radius_px))
        self.poll_interval_seconds = max(0.02, float(poll_interval_seconds))
        self._state = MagneticSnapState(self.radius_px)
        self._candidate: SnapCandidate | None = None
        self._pending: tuple[int, int] | None = None
        self._lock = threading.RLock()
        self._request_event = threading.Event()
        self._stop_event = threading.Event()
        self._probe_initialized = False
        self._thread: threading.Thread | None = None
        if start_worker:
            self._thread = threading.Thread(
                target=self._run,
                name="cursor-snap-uia",
                daemon=True,
            )
            self._thread.start()

    @property
    def target_name(self) -> str | None:
        with self._lock:
            return self._state.target_name

    def configure(self, *, enabled: bool, radius_px: int) -> None:
        with self._lock:
            self.enabled = bool(enabled)
            self.radius_px = max(1, int(radius_px))
            self._candidate = None
            self._state.configure(self.radius_px)
        if self.enabled:
            self._request_event.set()

    def clear(self) -> None:
        with self._lock:
            self._candidate = None
            self._state.clear()

    def transform(self, x: float, y: float) -> tuple[float, float]:
        raw_x = clamp(x)
        raw_y = clamp(y)
        with self._lock:
            if not self.enabled:
                return raw_x, raw_y
            pixel_x = round(raw_x * (self.screen_width - 1))
            pixel_y = round(raw_y * (self.screen_height - 1))
            self._pending = (pixel_x, pixel_y)
            snapped_x, snapped_y, snapped = self._state.resolve(
                pixel_x,
                pixel_y,
                self._candidate,
            )
        self._request_event.set()
        if not snapped:
            return raw_x, raw_y
        return (
            clamp(snapped_x / (self.screen_width - 1)),
            clamp(snapped_y / (self.screen_height - 1)),
        )

    def refresh_once(self) -> None:
        with self._lock:
            if not self.enabled or self._pending is None:
                return
            x, y = self._pending
            radius_px = self.radius_px
        if not self._probe_initialized:
            self.probe.initialize()
            self._probe_initialized = True
        candidate = self.probe.find_target(x, y, radius_px)
        with self._lock:
            self._candidate = candidate

    def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                self._request_event.wait(timeout=0.10)
                self._request_event.clear()
                if self._stop_event.is_set():
                    break
                try:
                    self.refresh_once()
                except Exception:
                    LOGGER.debug("UI Automation磁吸探测失败，已临时降级", exc_info=True)
                self._stop_event.wait(self.poll_interval_seconds)
        finally:
            if self._probe_initialized:
                self.probe.close()
                self._probe_initialized = False

    def shutdown(self) -> None:
        self._stop_event.set()
        self._request_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._thread is None and self._probe_initialized:
            self.probe.close()
            self._probe_initialized = False
