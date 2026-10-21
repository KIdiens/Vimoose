"""版本化配置加载、迁移和持久化。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields, field
from pathlib import Path


CONFIG_VERSION = 11


def app_data_dir() -> Path:
    """返回当前用户的应用数据目录。"""

    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "Vimoose"
    return Path.home() / ".vimoose"


def legacy_app_data_dir() -> Path:
    """返回0.6及更早版本使用的目录，仅用于一次性配置迁移。"""

    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "GesturePilot"
    return Path.home() / ".gesturepilot"


@dataclass(slots=True)
class AppConfig:
    """应用可持久化配置。"""

    version: int = CONFIG_VERSION
    camera_index: int = 0
    camera_width: int = 640
    camera_height: int = 480
    camera_fps: int = 30
    mirror: bool = True
    handedness: str = "Any"
    recognition_zoom: float = 1.15
    ema_alpha: float = 0.30
    fast_alpha: float = 0.72
    pointer_stability: float = 0.58
    pointer_response: float = 0.82
    cursor_interpolation_ms: int = 42
    pointer_margin_x: float = 0.20
    pointer_margin_y: float = 0.16
    pointer_edge_override: bool = True
    pinch_engage: float = 0.42
    pinch_release: float = 0.55
    pinch_arm: float = 0.72
    right_pinch_approach_delta: float = 0.22
    drag_hold_ms: int = 2000
    fist_hold_ms: int = 500
    hand_lost_ms: int = 200
    scroll_threshold: float = 0.12
    scroll_sensitivity: float = 1.0
    rotation_gestures_enabled: bool = True
    palm_rotation_threshold: float = 0.18
    page_gestures_enabled: bool = True
    page_swipe_threshold: float = 0.70
    cursor_snap_enabled: bool = True
    cursor_snap_radius_px: int = 30
    partial_finger_tracking: bool = False
    # 即使显式开启，也只允许最近有效完整手之后的150毫秒短时续跟踪。
    partial_tracking_frames: int = 4
    min_detection_confidence: float = 0.40
    min_presence_confidence: float = 0.35
    min_tracking_confidence: float = 0.40
    preview_enabled: bool = True
    preview_fps: int = 15
    start_with_windows: bool = False
    auto_start_control: bool = False
    auto_office_enabled: bool = True
    classroom_enabled: bool = False
    classroom_hand: str = "Right"
    classroom_region: list[float] = field(default_factory=lambda: [0.,0.,1.,1.])
    classroom_calibration: dict = field(default_factory=dict)
    classroom_camera_signature: str = ""

    def classroom_signature(self) -> str:
        return f"{self.camera_index}:{self.camera_width}:{self.camera_height}:{self.mirror}:{self.classroom_hand}"

    @classmethod
    def from_mapping(cls, raw: dict[str, object]) -> "AppConfig":
        """忽略未知字段并迁移旧配置。"""

        allowed = {item.name for item in fields(cls)}
        values = {key: value for key, value in raw.items() if key in allowed}
        source_version = int(raw.get("version", 0) or 0)
        if source_version < 2:
            old_recognition_defaults = (
                raw.get("handedness", "Right") == "Right"
                and float(raw.get("min_detection_confidence", 0.55)) == 0.55
                and float(raw.get("min_presence_confidence", 0.55)) == 0.55
                and float(raw.get("min_tracking_confidence", 0.55)) == 0.55
                and float(raw.get("pinch_engage", 0.36)) == 0.36
                and float(raw.get("pinch_release", 0.48)) == 0.48
            )
            if old_recognition_defaults:
                values.update(
                    handedness="Any",
                    min_detection_confidence=0.45,
                    min_presence_confidence=0.40,
                    min_tracking_confidence=0.45,
                    pinch_engage=0.42,
                    pinch_release=0.55,
                )
        if source_version < 3:
            previous_balanced_defaults = (
                float(values.get("min_detection_confidence", 0.45)) == 0.45
                and float(values.get("min_presence_confidence", 0.40)) == 0.40
                and float(values.get("min_tracking_confidence", 0.45)) == 0.45
            )
            if previous_balanced_defaults:
                values.update(
                    min_detection_confidence=0.40,
                    min_presence_confidence=0.35,
                    min_tracking_confidence=0.40,
                )
        if source_version < 5:
            # 0.4.0的默认值8只允许约0.4秒续跟踪，无法覆盖手掌持续
            # 出框的场景。保留用户手动设置的非默认值，仅迁移旧默认值。
            if int(values.get("partial_tracking_frames", 8)) == 8:
                values["partial_tracking_frames"] = 0
        if source_version < 7:
            # 0.5.0及更早版本的300ms拖拽会把稍慢的点击直接变成拖拽；
            # 用户最新演示明确要求持续约5秒才进入拖拽。
            if int(values.get("drag_hold_ms", 300)) == 300:
                values["drag_hold_ms"] = 5000
            # 在手部仍完整位于画面内时提前覆盖全屏，避免为了够到屏幕
            # 边缘继续把手移出摄像头。仅迁移旧默认值，保留自定义校准。
            if float(values.get("pointer_margin_x", 0.12)) == 0.12:
                values["pointer_margin_x"] = 0.20
            if float(values.get("pointer_margin_y", 0.10)) == 0.10:
                values["pointer_margin_y"] = 0.16
        if source_version < 8:
            # 0.7.0把默认拖拽等待提高到5秒后，最新实测反馈认为等待过长。
            # 只迁移该版本的默认值，其他用户自定义时长保持不变。
            if int(values.get("drag_hold_ms", 5000)) == 5000:
                values["drag_hold_ms"] = 2000
        if source_version < 9:
            # 旧校准按单一掌宽生成阈值，无法直接用于0.8.1引入的稳健
            # 手部尺度。只下调超过新安全默认值的部分，保留更保守的设置。
            values["pinch_engage"] = min(
                float(values.get("pinch_engage", 0.42)),
                0.42,
            )
            values["pinch_release"] = min(
                float(values.get("pinch_release", 0.55)),
                0.55,
            )
            values["pinch_arm"] = min(
                float(values.get("pinch_arm", 0.72)),
                0.72,
            )
        if source_version < 11:
            values.update(classroom_enabled=False, partial_finger_tracking=False)
        values["classroom_enabled"] = False
        values["version"] = CONFIG_VERSION
        return cls(**values)

    def validate(self) -> None:
        """在保存或使用前进行防御性校验。"""

        self.camera_index = max(0, int(self.camera_index))
        self.camera_width = max(320, int(self.camera_width))
        self.camera_height = max(240, int(self.camera_height))
        self.camera_fps = max(5, min(60, int(self.camera_fps)))
        self.recognition_zoom = max(
            1.0,
            min(1.35, float(self.recognition_zoom)),
        )
        self.ema_alpha = max(0.05, min(0.95, float(self.ema_alpha)))
        self.fast_alpha = max(self.ema_alpha, min(0.98, float(self.fast_alpha)))
        self.pointer_stability = max(0.0, min(1.0, float(self.pointer_stability)))
        self.pointer_response = max(0.0, min(1.0, float(self.pointer_response)))
        self.cursor_interpolation_ms = max(
            12,
            min(60, int(self.cursor_interpolation_ms)),
        )
        self.pointer_margin_x = max(0.0, min(0.4, float(self.pointer_margin_x)))
        self.pointer_margin_y = max(0.0, min(0.4, float(self.pointer_margin_y)))
        self.pinch_engage = max(0.1, min(1.0, float(self.pinch_engage)))
        self.pinch_release = max(
            self.pinch_engage + 0.02,
            min(1.2, float(self.pinch_release)),
        )
        self.pinch_arm = max(
            self.pinch_release + 0.05,
            min(1.4, float(self.pinch_arm)),
        )
        self.right_pinch_approach_delta = max(
            0.10,
            min(0.60, float(self.right_pinch_approach_delta)),
        )
        self.drag_hold_ms = max(300, min(10_000, int(self.drag_hold_ms)))
        self.fist_hold_ms = max(300, min(1500, int(self.fist_hold_ms)))
        self.hand_lost_ms = max(100, min(1000, int(self.hand_lost_ms)))
        self.scroll_threshold = max(0.03, min(0.6, float(self.scroll_threshold)))
        self.scroll_sensitivity = max(0.2, min(4.0, float(self.scroll_sensitivity)))
        self.palm_rotation_threshold = max(
            0.08,
            min(0.60, float(self.palm_rotation_threshold)),
        )
        self.page_swipe_threshold = max(
            0.35,
            min(1.5, float(self.page_swipe_threshold)),
        )
        self.cursor_snap_radius_px = max(
            12,
            min(80, int(self.cursor_snap_radius_px)),
        )
        self.partial_tracking_frames = max(
            0,
            min(600, int(self.partial_tracking_frames)),
        )
        self.min_detection_confidence = max(
            0.25,
            min(0.90, float(self.min_detection_confidence)),
        )
        self.min_presence_confidence = max(
            0.25,
            min(0.90, float(self.min_presence_confidence)),
        )
        self.min_tracking_confidence = max(
            0.25,
            min(0.90, float(self.min_tracking_confidence)),
        )
        self.preview_fps = max(5, min(30, int(self.preview_fps)))
        if self.handedness not in {"Left", "Right", "Any"}:
            self.handedness = "Right"
        if self.classroom_hand not in {"Left", "Right"}:
            self.classroom_hand = "Right"
        self.classroom_enabled = False
        try:
            from math import isfinite
            r = [float(x) for x in self.classroom_region]
            if (len(r) != 4 or not all(isfinite(x) and 0 <= x <= 1 for x in r)
                    or r[2]-r[0] < .1 or r[3]-r[1] < .1):
                raise ValueError("课堂有效区无效")
            self.classroom_region = r
        except (TypeError, ValueError):
            self.classroom_region = [0.,0.,1.,1.]
        if not isinstance(self.classroom_calibration, dict):
            self.classroom_calibration = {}
        if self.classroom_camera_signature != self.classroom_signature():
            self.classroom_calibration = {}


class ConfigStore:
    """以原子替换方式管理JSON配置。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_data_dir() / "config.json"

    def load(self) -> AppConfig:
        source = self.path
        default_path = app_data_dir() / "config.json"
        if not source.exists() and source == default_path:
            legacy = legacy_app_data_dir() / "config.json"
            if legacy.exists():
                source = legacy
        if not source.exists():
            return AppConfig()
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("配置文件根节点必须是JSON对象")
            config = AppConfig.from_mapping(raw)
            config.validate()
            if source != self.path or int(raw.get("version", 0) or 0) != CONFIG_VERSION:
                self.save(config)
            return config
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return AppConfig()

    def save(self, config: AppConfig) -> None:
        config.validate()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(config), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def reset(self) -> AppConfig:
        config = AppConfig()
        self.save(config)
        return config
