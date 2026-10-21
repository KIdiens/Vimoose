"""采集、推理、解析与鼠标执行的实时流水线。"""

from __future__ import annotations

import copy
import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

import psutil

from gesture_mouse.calibration import gesture_scale
from gesture_mouse.config import AppConfig
from gesture_mouse.contracts import (
    DetectionPacket,
    FramePacket,
    GestureType,
    MouseCommand,
    MouseCommandType,
    PipelineSnapshot,
    RuntimeMetrics,
)
from gesture_mouse.filters import CursorMotionInterpolator
from gesture_mouse.gestures import GestureEngine
from gesture_mouse.latest_slot import LatestSlot
from gesture_mouse.mouse import MouseController
from gesture_mouse.vision import CameraWorker, HandLandmarkerWorker, RollingRate, default_model_path


LOGGER = logging.getLogger(__name__)
_MAX_CONTROL_PACKET_AGE_MS = 100


class ControlWorker(threading.Thread):
    """消费最新检测结果并驱动状态机。"""

    def __init__(
        self,
        detections: LatestSlot[DetectionPacket],
        engine: GestureEngine,
        mouse: MouseController,
        stop_event: threading.Event,
        on_state: Callable[[GestureType, bool], None],
        interpolation_ms: int,
        engine_lock: threading.RLock | None = None,
        office=None,
    ) -> None:
        super().__init__(name="gesture-control", daemon=True)
        self.detections = detections
        self.engine = engine
        self.mouse = mouse
        self.stop_event = stop_event
        self.on_state = on_state
        self.engine_lock = engine_lock or threading.RLock()
        self.motion = CursorMotionInterpolator(
            min_duration_ms=12,
            max_duration_ms=interpolation_ms,
        )
        self._last_packet_timestamp_ns: int | None = None
        from gesture_mouse.document_gestures import DocumentGestures
        self.office = office
        self.document_gestures = DocumentGestures(engine.config.mirror)
        self._context_token = ""

    def _execute_commands(self, commands: list[MouseCommand]) -> None:
        now = time.monotonic_ns()
        immediate: list[MouseCommand] = []
        for command in commands:
            if self.office:
                if command.kind in (MouseCommandType.PAGE_NEXT,MouseCommandType.PAGE_PREVIOUS):
                    continue
                if command.kind == MouseCommandType.WHEEL and self.office.snapshot().target:
                    continue
            if (
                command.kind == MouseCommandType.MOVE
                and command.x is not None
                and command.y is not None
            ):
                first = self.motion.set_target(command.x, command.y, now)
                if first is not None:
                    immediate.append(
                        MouseCommand(
                            MouseCommandType.MOVE,
                            now,
                            x=first[0],
                            y=first[1],
                        ),
                    )
            else:
                immediate.append(command)
                if command.kind == MouseCommandType.PAUSE:
                    self.motion.clear()
        self.mouse.execute_many(immediate)

    def _advance_motion(self, timestamp_ns: int) -> None:
        if self.engine.paused or self.engine.current_gesture == GestureType.LOST:
            self.motion.clear()
            return
        if self.engine.current_gesture not in {
            GestureType.POINTER,
            GestureType.DRAG,
            GestureType.PARTIAL_INDEX,
        }:
            self.motion.cancel()
            return
        position = self.motion.sample(timestamp_ns)
        if position is None:
            return
        self.mouse.execute(
            MouseCommand(
                MouseCommandType.MOVE,
                timestamp_ns,
                x=position[0],
                y=position[1],
            ),
        )

    def _commands_for_packet(
        self,
        packet: DetectionPacket,
        now_ns: int,
    ) -> list[MouseCommand]:
        """丢弃过期或时间倒退的异步结果，避免旧动作改变当前状态。"""

        age_ns = max(0, now_ns - packet.timestamp_ns)
        max_age_ms = min(
            self.engine.config.hand_lost_ms,
            _MAX_CONTROL_PACKET_AGE_MS,
        )
        if age_ns >= max_age_ms * 1_000_000:
            return self.engine.tick(now_ns)
        if (
            self._last_packet_timestamp_ns is not None
            and packet.timestamp_ns <= self._last_packet_timestamp_ns
        ):
            return self.engine.tick(now_ns)
        self._last_packet_timestamp_ns = packet.timestamp_ns
        if packet.observations:
            hand = packet.observations[0]
            allowed = self.engine.config.handedness
            if allowed != "Any" and hand.handedness != allowed:
                if self.office:
                    self.office.revoke()
                    self.document_gestures.reset()
                self.motion.cancel()
                return self.engine.cancel_observation(now_ns)
        if self.office:
            hand = packet.observations[0] if packet.observations else None
            if self.engine.paused or hand is None or len(hand.landmarks) != 21:
                self.office.revoke()
                self.document_gestures.reset()
            else:
                self.office.authorize("daily-control",now_ns)
            status = self.office.snapshot()
            token = status.token
            if token != self._context_token:
                self._context_token = token
                self.document_gestures.reset()
                self.motion.cancel()
                self.mouse.release_all()
                self.engine._release_left(now_ns)
                self.engine._reset_transient()
            if (token and status.target and self.engine.config.page_gestures_enabled
                    and not self.engine.paused and not self.engine._left_button_down):
                consumed,event = self.document_gestures.process(hand,token,status.target.kind)
                if consumed:
                    self.motion.cancel()
                    self.engine._reset_transient()
                    self.engine.last_hand_ns = packet.timestamp_ns
                    self.engine.current_gesture = GestureType.SCROLL
                    if event:
                        self.office.submit(event)
                        self.engine.current_gesture = (GestureType.PAGE_NEXT if event.direction>0
                                                       else GestureType.PAGE_PREVIOUS)
                    return []
        if packet.observations:
            return self.engine.process(packet.observations[0])
        self.motion.cancel()
        return self.engine.cancel_observation(now_ns)

    def run(self) -> None:
        revision = 0
        try:
            while not self.stop_event.is_set():
                packet, next_revision = self.detections.wait_next(revision, timeout=0.008)
                with self.engine_lock:
                    if packet is not None:
                        revision = next_revision
                        commands = self._commands_for_packet(
                            packet,
                            time.monotonic_ns(),
                        )
                        if self.engine.current_gesture in {
                            GestureType.PINCH_ARMED,
                            GestureType.LEFT_PINCH,
                            GestureType.RIGHT_PINCH,
                        }:
                            # 在执行点击前立即丢弃上一帧尚未完成的插值轨迹。
                            self.motion.cancel()
                        self._execute_commands(commands)
                    watchdog_commands = self.engine.tick(time.monotonic_ns())
                    self._execute_commands(watchdog_commands)
                    self._advance_motion(time.monotonic_ns())
                    self.on_state(self.engine.current_gesture, self.engine.paused)
        except Exception:
            LOGGER.exception("控制线程异常")
        finally:
            if self.office:
                self.office.revoke()
            with self.engine_lock:
                self.mouse.release_all()


class GesturePipeline:
    """管理所有工作线程，并向GUI提供快照。"""

    def __init__(
        self,
        config: AppConfig,
        mouse: MouseController,
        model_path: Path | None = None,
    ) -> None:
        self.config = config
        self.mouse = mouse
        self.model_path = model_path or default_model_path()
        self.engine = GestureEngine(config)
        self.config.classroom_enabled = False
        self.office = None

        self.frames: LatestSlot[FramePacket] = LatestSlot()
        self.detections: LatestSlot[DetectionPacket] = LatestSlot()
        self.preview: LatestSlot[FramePacket] = LatestSlot()
        self.stop_event = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock = threading.RLock()
        self._engine_lock = threading.RLock()
        self._snapshot = PipelineSnapshot()
        self._capture_rate = RollingRate()
        self._inference_rate = RollingRate()
        self._process = psutil.Process()
        self._process.cpu_percent(interval=None)
        self._captured_frames = 0
        self._inferred_frames = 0
        self._last_resource_sample_ns = 0
        self._latencies: deque[float] = deque(maxlen=600)
        self._detection_results: deque[tuple[int, bool]] = deque(maxlen=180)

    @property
    def running(self) -> bool:
        with self._lock:
            return self._snapshot.running

    def _set_error(self, message: str) -> None:
        LOGGER.error(message)
        self.stop_event.set()
        if self.office:
            self.office.stop()
        self.mouse.release_all()
        with self._lock:
            self._snapshot.camera_error = message
            self._snapshot.message = message
            self._snapshot.running = False

    def _on_frame(self, packet: FramePacket) -> None:
        self.preview.put(packet)
        self._capture_rate.mark(packet.captured_ns)
        with self._lock:
            self._captured_frames += 1
            self._snapshot.low_light = packet.brightness < 55.0
            self._snapshot.camera_signal_missing = packet.brightness < 12.0

    def _on_detection(self, packet: DetectionPacket) -> None:
        self._inference_rate.mark()
        now = time.monotonic_ns()
        with self._lock:
            self._inferred_frames += 1
            latency_ms = max(
                packet.inference_ms,
                0.0,
                (now - packet.timestamp_ns) / 1_000_000,
            )
            self._snapshot.metrics.latency_ms = latency_ms
            self._latencies.append(latency_ms)
            has_hand = bool(packet.observations)
            self._detection_results.append((now, has_hand))
            self._snapshot.metrics.handedness_score = (
                packet.observations[0].handedness_score if has_hand else 0.0
            )
            if has_hand and len(packet.observations[0].landmarks) == 21:
                points = packet.observations[0].landmarks
                self._snapshot.metrics.palm_width_percent = 100.0 * gesture_scale(points)
            else:
                self._snapshot.metrics.palm_width_percent = 0.0

    def _on_state(self, gesture: GestureType, paused: bool) -> None:
        with self._lock:
            self._snapshot.gesture = gesture
            self._snapshot.paused = paused
            if self._snapshot.camera_error:
                return
            if self._snapshot.camera_signal_missing:
                self._snapshot.message = "摄像头已打开，但没有有效视频画面"
            elif paused:
                self._snapshot.message = "控制已暂停"
            elif gesture == GestureType.LOST:
                self._snapshot.message = "未检测到有效手部"
            elif gesture == GestureType.DRAG:
                self._snapshot.message = "正在拖拽"
            elif gesture == GestureType.SCROLL:
                self._snapshot.message = "滚轮模式"
            elif gesture == GestureType.PAGE_NEXT:
                self._snapshot.message = "已翻到下一页"
            elif gesture == GestureType.PAGE_PREVIOUS:
                self._snapshot.message = "已翻到上一页"
            elif gesture == GestureType.PINCH_ARMED:
                self._snapshot.message = "点击位置已锁定"
            elif gesture == GestureType.LEFT_PINCH:
                self._snapshot.message = "左键捏合"
            elif gesture == GestureType.RIGHT_PINCH:
                self._snapshot.message = "右键捏合"
            elif gesture == GestureType.POINTER:
                self._snapshot.message = "正在控制光标"
            elif gesture == GestureType.PARTIAL_INDEX:
                self._snapshot.message = "食指局部续跟踪"
            elif gesture == GestureType.PARTIAL_MIDDLE:
                self._snapshot.message = "中指局部续跟踪"
            else:
                self._snapshot.message = "等待手势"

    def start(self) -> bool:
        with self._lock:
            if self._snapshot.running:
                return True
            if not self.model_path.exists():
                self._set_error(
                    f"缺少模型文件：{self.model_path}。请运行模型下载脚本。",
                )
                return False
            self._snapshot = PipelineSnapshot(running=True, message="正在启动摄像头")
            self._captured_frames = 0
            self._inferred_frames = 0
            self._latencies.clear()
            self._detection_results.clear()
            self.stop_event = threading.Event()
            self.frames = LatestSlot()
            self.detections = LatestSlot()
            self.preview = LatestSlot()
            self.engine = GestureEngine(self.config)

        camera = CameraWorker(
            self.config,
            self.frames,
            self.stop_event,
            self._set_error,
            self._on_frame,
        )
        from gesture_mouse.office_bridge import OfficeWorker
        from gesture_mouse.mouse import NullMouseBackend
        self.office = (OfficeWorker(isinstance(self.mouse.backend,NullMouseBackend),automatic=True)
                       if self.config.auto_office_enabled else None)
        landmarker = HandLandmarkerWorker(
            self.config,
            self.model_path,
            self.frames,
            self.detections,
            self.stop_event,
            self._set_error,
            self._on_detection,
            lambda: self.engine.paused,
        )
        control = ControlWorker(
            self.detections,
            self.engine,
            self.mouse,
            self.stop_event,
            self._on_state,
            self.config.cursor_interpolation_ms,
            self._engine_lock,
            self.office,
        )
        self._threads = ([self.office] if self.office else []) + [camera, landmarker, control]
        for thread in self._threads:
            thread.start()
        LOGGER.info("实时流水线已启动")
        return True

    def stop(self) -> None:
        if self.office:
            self.office.stop()
        with self._lock:
            had_work = self._snapshot.running or bool(self._threads)
        if not had_work:
            self.mouse.release_all()
            return
        self.stop_event.set()
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=2.0)
        self._threads.clear()
        self.mouse.release_all()
        with self._lock:
            self._snapshot.running = False
            self._snapshot.paused = False
            self._snapshot.gesture = GestureType.NONE
            if not self._snapshot.camera_error:
                self._snapshot.message = "控制已停止"
        LOGGER.info("实时流水线已停止")

    def set_paused(self, paused: bool) -> None:
        if self.office:
            self.office.revoke()
        with self._engine_lock:
            commands = self.engine.set_paused(paused)
            self.mouse.execute_many(commands)
            self._on_state(self.engine.current_gesture, paused)

    def toggle_paused(self) -> None:
        with self._engine_lock:
            self.set_paused(not self.engine.paused)

    def emergency_stop(self) -> None:
        if self.office:
            self.office.revoke()
        with self._engine_lock:
            commands = self.engine.emergency_stop()
            self.mouse.execute_many(commands)
            self.mouse.release_all()
            self._on_state(GestureType.PAUSED, True)

    def update_config(self, config: AppConfig) -> None:
        was_running = self.running
        if was_running:
            self.stop()
        self.config = config
        self.engine.update_config(config)
        self.mouse.update_config(config)
        if was_running:
            self.start()

    def get_preview(self) -> tuple[FramePacket | None, DetectionPacket | None]:
        frame, _ = self.preview.get_latest()
        detection, _ = self.detections.get_latest()
        return frame, detection

    def snapshot(self) -> PipelineSnapshot:
        now = time.monotonic_ns()
        with self._lock:
            metrics = self._snapshot.metrics
            metrics.capture_fps = self._capture_rate.value()
            metrics.inference_fps = self._inference_rate.value()
            metrics.dropped_frames = self.frames.overwrite_count
            metrics.captured_frames = self._captured_frames
            metrics.inferred_frames = self._inferred_frames
            detection_cutoff = now - 3_000_000_000
            while (
                self._detection_results
                and self._detection_results[0][0] < detection_cutoff
            ):
                self._detection_results.popleft()
            if self._detection_results:
                metrics.hand_detection_rate = 100.0 * sum(
                    1 for _timestamp, has_hand in self._detection_results if has_hand
                ) / len(self._detection_results)
            if self._latencies:
                ordered = sorted(self._latencies)
                metrics.latency_p50_ms = ordered[round((len(ordered) - 1) * 0.50)]
                metrics.latency_p95_ms = ordered[round((len(ordered) - 1) * 0.95)]
            if now - self._last_resource_sample_ns >= 1_000_000_000:
                # psutil的进程CPU百分比可按逻辑处理器数量超过100%，这里归一化
                # 为Windows任务管理器更接近的“整机CPU占比”口径。
                raw_cpu = self._process.cpu_percent(interval=None)
                metrics.cpu_percent = raw_cpu / max(1, psutil.cpu_count() or 1)
                metrics.memory_mb = self._process.memory_info().rss / (1024 * 1024)
                self._last_resource_sample_ns = now
            if self.mouse.last_error:
                self._snapshot.message = self.mouse.last_error
            snapshot = copy.deepcopy(self._snapshot)
            if self.office and snapshot.running and not snapshot.paused and not snapshot.camera_error:
                status = self.office.snapshot()
                snapshot.message = f"{status.message} · {snapshot.message}"
            snapshot.snap_target_name = self.mouse.snap_target_name
            if (
                snapshot.snap_target_name
                and snapshot.gesture
                in {
                    GestureType.POINTER,
                    GestureType.PINCH_ARMED,
                    GestureType.LEFT_PINCH,
                    GestureType.RIGHT_PINCH,
                }
            ):
                snapshot.message = f"已吸附：{snapshot.snap_target_name}"
            return snapshot
