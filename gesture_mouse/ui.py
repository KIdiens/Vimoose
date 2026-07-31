"""Vimoose 深色实时控制台、设置面板与系统托盘。"""

from __future__ import annotations

import copy
import logging
import time

import cv2
from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QCloseEvent,
    QFont,
    QIcon,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gesture_mouse.config import AppConfig, ConfigStore, app_data_dir
from gesture_mouse.calibration import (
    CalibrationError,
    calculate_calibration,
    pinch_ratio,
    pointer_position,
)
from gesture_mouse.contracts import GestureType, PipelineSnapshot
from gesture_mouse.pipeline import GesturePipeline
from gesture_mouse.startup import open_log_directory, set_start_with_windows


LOGGER = logging.getLogger(__name__)

HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
)

COLORS = {
    "background": "#07111F",
    "surface": "#0D1929",
    "surface_raised": "#122238",
    "surface_soft": "#16283E",
    "border": "#263B53",
    "border_strong": "#34516F",
    "text": "#F8FAFC",
    "subtle": "#A5B4C7",
    "muted": "#71849B",
    "accent": "#2DD4BF",
    "accent_hover": "#5EEAD4",
    "blue": "#38BDF8",
    "success": "#34D399",
    "warning": "#FBBF24",
    "danger": "#FB7185",
}


APP_STYLE = f"""
QMainWindow, QWidget {{
    background: {COLORS['background']};
    color: {COLORS['text']};
    font-family: "Microsoft YaHei UI", "Segoe UI Variable";
    font-size: 14px;
}}
QLabel {{ background: {COLORS['background']}; border: none; }}
QFrame#panel, QFrame#metricCard, QGroupBox {{
    background: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 14px;
}}
QFrame#heroCard {{
    background: {COLORS['surface_raised']};
    border: 1px solid {COLORS['border_strong']};
    border-radius: 16px;
}}
QFrame#panel QLabel, QFrame#metricCard QLabel, QGroupBox QLabel {{
    background: {COLORS['surface']};
}}
QFrame#heroCard QLabel {{ background: {COLORS['surface_raised']}; }}
QFrame#guideStrip QLabel {{ background: {COLORS['surface_soft']}; }}
QGroupBox QSlider, QGroupBox QCheckBox {{ background: {COLORS['surface']}; }}
QFrame#guideStrip {{
    background: {COLORS['surface_soft']};
    border: 1px solid {COLORS['border']};
    border-radius: 10px;
}}
QGroupBox {{
    margin-top: 16px;
    padding: 22px 16px 16px 16px;
    font-weight: 650;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 7px;
    color: {COLORS['text']};
}}
QLabel#eyebrow {{
    color: {COLORS['accent']};
    font-size: 12px;
    font-weight: 700;
}}
QLabel#muted {{ color: {COLORS['subtle']}; }}
QLabel#subtle {{ color: {COLORS['muted']}; font-size: 12px; }}
QLabel#metricValue {{
    color: {COLORS['text']};
    font-size: 20px;
    font-weight: 700;
}}
QLabel#gestureValue {{
    color: {COLORS['text']};
    font-size: 30px;
    font-weight: 750;
}}
QPushButton {{
    min-height: 44px;
    border-radius: 9px;
    border: 1px solid {COLORS['border_strong']};
    background: {COLORS['surface_raised']};
    color: {COLORS['text']};
    padding: 0 18px;
    font-weight: 650;
}}
QPushButton:hover {{
    background: {COLORS['surface_soft']};
    border-color: {COLORS['blue']};
}}
QPushButton:pressed {{ background: #0A1524; }}
QPushButton:focus {{ border: 2px solid {COLORS['accent']}; }}
QPushButton:disabled {{ color: {COLORS['muted']}; border-color: {COLORS['border']}; }}
QPushButton#primaryButton {{
    background: {COLORS['accent']};
    color: #03201D;
    border-color: {COLORS['accent']};
}}
QPushButton#primaryButton:hover {{ background: {COLORS['accent_hover']}; }}
QPushButton#dangerButton {{
    color: {COLORS['danger']};
    border-color: #7F3346;
    background: #251420;
}}
QPushButton#dangerButton:hover {{ background: #351824; border-color: {COLORS['danger']}; }}
QComboBox, QSpinBox {{
    min-height: 42px;
    border: 1px solid {COLORS['border_strong']};
    border-radius: 8px;
    background: {COLORS['surface_raised']};
    color: {COLORS['text']};
    padding: 0 10px;
}}
QComboBox:focus, QSpinBox:focus {{ border: 2px solid {COLORS['accent']}; }}
QComboBox QAbstractItemView {{
    background: {COLORS['surface_raised']};
    color: {COLORS['text']};
    selection-background-color: #164E63;
    border: 1px solid {COLORS['border_strong']};
}}
QSlider {{ min-height: 32px; }}
QSlider::groove:horizontal {{
    height: 6px;
    background: #20354A;
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{ background: {COLORS['accent']}; border-radius: 3px; }}
QSlider::handle:horizontal {{
    width: 18px;
    height: 18px;
    margin: -6px 0;
    background: {COLORS['text']};
    border: 3px solid {COLORS['accent']};
    border-radius: 9px;
}}
QProgressBar {{
    min-height: 10px;
    max-height: 10px;
    background: #20354A;
    border: none;
    border-radius: 5px;
    text-align: center;
}}
QProgressBar::chunk {{ background: {COLORS['accent']}; border-radius: 5px; }}
QTabWidget::pane {{
    border: 1px solid {COLORS['border']};
    background: {COLORS['background']};
    border-radius: 14px;
    top: -1px;
}}
QTabBar::tab {{
    min-height: 44px;
    min-width: 116px;
    padding: 0 16px;
    color: {COLORS['subtle']};
    background: transparent;
    border-bottom: 2px solid transparent;
}}
QTabBar::tab:hover {{ color: {COLORS['text']}; }}
QTabBar::tab:selected {{
    color: {COLORS['accent']};
    font-weight: 700;
    border-bottom: 2px solid {COLORS['accent']};
}}
QCheckBox {{ spacing: 12px; min-height: 38px; color: {COLORS['text']}; }}
QCheckBox::indicator {{ width: 20px; height: 20px; }}
QCheckBox::indicator:unchecked {{
    background: {COLORS['surface_raised']};
    border: 1px solid {COLORS['border_strong']};
    border-radius: 5px;
}}
QCheckBox::indicator:checked {{
    background: {COLORS['accent']};
    border: 1px solid {COLORS['accent']};
    border-radius: 5px;
}}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea#pageScroll, QScrollArea#pageScroll QWidget#qt_scrollarea_viewport,
QWidget#pageContent {{ background: {COLORS['background']}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 0; }}
QScrollBar::handle:vertical {{ background: #35516D; min-height: 32px; border-radius: 5px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QMenu {{
    background: {COLORS['surface_raised']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border_strong']};
    padding: 6px;
}}
QMenu::item {{ padding: 8px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: #164E63; }}
"""


class UiBridge(QObject):
    """将后台快捷键回调安全地转发到Qt主线程。"""

    toggle_requested = Signal()
    emergency_requested = Signal()
    quit_requested = Signal()


def build_app_icon(size: int = 64) -> QIcon:
    """生成由追踪框和指针节点构成的矢量风格图标。"""

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(COLORS["surface_raised"]))
    painter.setPen(QPen(QColor(COLORS["border_strong"]), 2))
    painter.drawRoundedRect(2, 2, size - 4, size - 4, 15, 15)
    painter.setPen(QPen(QColor(COLORS["accent"]), max(2, size // 18)))
    inset = size // 4
    painter.drawLine(inset, inset + 8, inset, inset)
    painter.drawLine(inset, inset, inset + 8, inset)
    painter.drawLine(size - inset - 8, size - inset, size - inset, size - inset)
    painter.drawLine(size - inset, size - inset, size - inset, size - inset - 8)
    painter.setBrush(QColor(COLORS["blue"]))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(size // 2 - 6, size // 2 - 6, 12, 12)
    painter.end()
    return QIcon(pixmap)


class CalibrationDialog(QDialog):
    """暂停鼠标注入后执行张开、捏合和静止指向三步校准。"""

    SAMPLE_DURATION_NS = 1_600_000_000
    STEPS = (
        (
            "张开拇指与食指",
            "将整只手放入画面，拇指与食指自然分开并保持不动。",
        ),
        (
            "轻轻捏合",
            "让拇指与食指接触或接近，按平时点击的力度保持。",
        ),
        (
            "自然指向并保持",
            "伸出食指，其余手指自然弯曲，尽量保持指尖不动。",
        ),
    )

    def __init__(
        self,
        pipeline: GesturePipeline,
        config: AppConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.pipeline = pipeline
        self.config = config
        self.result_config: AppConfig | None = None
        self._was_running = pipeline.running
        self._was_paused = pipeline.engine.paused if pipeline.running else False
        self._started_here = False
        self._step = 0
        self._sampling = False
        self._ready_to_apply = False
        self._started_ns = 0
        self._last_detection_ns = -1
        self._current_samples: list[float | tuple[float, float]] = []
        self._open_ratios: list[float] = []
        self._closed_ratios: list[float] = []
        self._pointer_points: list[tuple[float, float]] = []

        self.setWindowTitle("个性化手势校准")
        self.setWindowIcon(build_app_icon())
        self.setModal(True)
        self.setMinimumSize(560, 430)
        self.resize(620, 470)
        self._build_ui()

        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._collect_sample)
        QTimer.singleShot(0, self._prepare_pipeline)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)

        eyebrow = QLabel("PERSONAL CALIBRATION")
        eyebrow.setObjectName("eyebrow")
        title = QLabel("让识别参数适应你的手")
        title.setFont(QFont("Microsoft YaHei UI", 21, QFont.Weight.Bold))
        description = QLabel(
            "校准期间会暂停鼠标控制，但视频只在本机处理且不会保存。每一步约需2秒。",
        )
        description.setObjectName("muted")
        description.setWordWrap(True)
        layout.addWidget(eyebrow)
        layout.addWidget(title)
        layout.addWidget(description)

        stage = QFrame()
        stage.setObjectName("heroCard")
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(18, 16, 18, 16)
        stage_layout.setSpacing(8)
        self.step_label = QLabel("步骤 1 / 3")
        self.step_label.setObjectName("eyebrow")
        self.instruction_label = QLabel("")
        self.instruction_label.setObjectName("gestureValue")
        self.instruction_label.setFont(
            QFont("Microsoft YaHei UI", 20, QFont.Weight.Bold),
        )
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("muted")
        self.detail_label.setWordWrap(True)
        stage_layout.addWidget(self.step_label)
        stage_layout.addWidget(self.instruction_label)
        stage_layout.addWidget(self.detail_label)
        layout.addWidget(stage)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("当前校准步骤采样进度")
        layout.addWidget(self.progress)

        self.status_label = QLabel("正在准备摄像头和识别引擎…")
        self.status_label.setObjectName("muted")
        self.status_label.setWordWrap(True)
        self.status_label.setAccessibleName("校准状态与错误提示")
        layout.addWidget(self.status_label)

        buttons = QHBoxLayout()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        self.action_button = QPushButton("开始采样")
        self.action_button.setObjectName("primaryButton")
        self.action_button.setEnabled(False)
        self.action_button.clicked.connect(self._perform_action)
        buttons.addWidget(cancel)
        buttons.addStretch()
        buttons.addWidget(self.action_button)
        layout.addStretch()
        layout.addLayout(buttons)
        self._show_step()

    def _prepare_pipeline(self) -> None:
        if not self.pipeline.running:
            if not self.pipeline.start():
                self._set_error(self.pipeline.snapshot().message)
                return
            self._started_here = True
        self.pipeline.set_paused(True)
        self.status_label.setText("准备完成。摆好当前动作后点击“开始采样”。")
        self.action_button.setEnabled(True)

    def _show_step(self) -> None:
        title, detail = self.STEPS[self._step]
        self.step_label.setText(f"步骤 {self._step + 1} / {len(self.STEPS)}")
        self.instruction_label.setText(title)
        self.detail_label.setText(detail)
        self.progress.setValue(0)

    def _perform_action(self) -> None:
        if self._ready_to_apply:
            self.accept()
            return
        self._sampling = True
        self._started_ns = time.monotonic_ns()
        self._last_detection_ns = -1
        self._current_samples = []
        self.progress.setValue(0)
        self.status_label.setStyleSheet(f"color:{COLORS['subtle']};")
        self.status_label.setText("正在采样，请保持当前动作…")
        self.action_button.setEnabled(False)
        self.timer.start()

    def _collect_sample(self) -> None:
        if not self._sampling:
            return
        now = time.monotonic_ns()
        elapsed = now - self._started_ns
        self.progress.setValue(min(100, round(100 * elapsed / self.SAMPLE_DURATION_NS)))

        snapshot = self.pipeline.snapshot()
        if snapshot.camera_error:
            self._sampling_failed(snapshot.camera_error)
            return
        if snapshot.camera_signal_missing:
            self._sampling_failed(
                "摄像头没有有效视频画面。请启动虚拟摄像头源或切换摄像头编号。",
            )
            return

        _frame, detection = self.pipeline.get_preview()
        if (
            detection is not None
            and detection.timestamp_ns != self._last_detection_ns
            and detection.observations
        ):
            self._last_detection_ns = detection.timestamp_ns
            points = detection.observations[0].landmarks
            try:
                if self._step in {0, 1}:
                    self._current_samples.append(pinch_ratio(points))
                else:
                    self._current_samples.append(pointer_position(points))
            except CalibrationError:
                pass

        if elapsed >= self.SAMPLE_DURATION_NS:
            self.timer.stop()
            self._sampling = False
            self._finish_step()

    def _finish_step(self) -> None:
        if len(self._current_samples) < 6:
            self._sampling_failed(
                "有效样本不足。请让手腕与全部指尖进入画面，然后重新采样。",
            )
            return

        if self._step == 0:
            self._open_ratios = [float(value) for value in self._current_samples]
        elif self._step == 1:
            self._closed_ratios = [float(value) for value in self._current_samples]
        else:
            self._pointer_points = [
                value for value in self._current_samples if isinstance(value, tuple)
            ]

        if self._step < len(self.STEPS) - 1:
            self._step += 1
            self._show_step()
            self.status_label.setStyleSheet(f"color:{COLORS['success']};")
            self.status_label.setText("本步采样完成。摆好下一动作后继续。")
            self.action_button.setText("采样下一步")
            self.action_button.setEnabled(True)
            return

        try:
            result = calculate_calibration(
                self._open_ratios,
                self._closed_ratios,
                self._pointer_points,
            )
        except CalibrationError as error:
            self._set_error(str(error))
            self.action_button.setText("重新校准")
            self.action_button.setEnabled(True)
            self._step = 0
            self._show_step()
            return

        calibrated = copy.deepcopy(self.config)
        calibrated.pinch_engage = result.pinch_engage
        calibrated.pinch_release = result.pinch_release
        calibrated.pinch_arm = min(1.4, result.pinch_release + 0.17)
        calibrated.pointer_stability = result.pointer_stability
        calibrated.pointer_response = result.pointer_response
        calibrated.cursor_interpolation_ms = result.cursor_interpolation_ms
        calibrated.validate()
        self.result_config = calibrated
        self._ready_to_apply = True
        self.step_label.setText("校准完成")
        self.instruction_label.setText("参数已为你的手型优化")
        self.detail_label.setText(
            f"捏合 {result.pinch_engage:.2f} / 松开 {result.pinch_release:.2f}  ·  "
            f"稳定性 {result.pointer_stability:.0%}  ·  "
            f"丝滑过渡 {result.cursor_interpolation_ms}ms",
        )
        self.progress.setValue(100)
        self.status_label.setStyleSheet(f"color:{COLORS['success']};")
        self.status_label.setText("点击“应用校准”后保存；取消不会修改现有参数。")
        self.action_button.setText("应用校准")
        self.action_button.setEnabled(True)

    def _sampling_failed(self, message: str) -> None:
        self.timer.stop()
        self._sampling = False
        self.progress.setValue(0)
        self._set_error(message)
        self.action_button.setText("重新采样")
        self.action_button.setEnabled(True)

    def _set_error(self, message: str) -> None:
        self.status_label.setStyleSheet(f"color:{COLORS['danger']}; font-weight:650;")
        self.status_label.setText(message)

    def done(self, result: int) -> None:
        self.timer.stop()
        if self.pipeline.running:
            if self._started_here:
                self.pipeline.stop()
            elif not self._was_paused:
                self.pipeline.set_paused(False)
        super().done(result)


class MainWindow(QMainWindow):
    """产品主窗口。"""

    def __init__(
        self,
        pipeline: GesturePipeline,
        config_store: ConfigStore,
        config: AppConfig,
    ) -> None:
        super().__init__()
        self.pipeline = pipeline
        self.config_store = config_store
        self.config = config
        self._really_quit = False
        self._last_frame_sequence = -1

        self.setWindowTitle("Vimoose 视觉手势鼠标")
        self.setWindowIcon(build_app_icon())
        self.setMinimumSize(1060, 700)
        self.resize(1280, 820)
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
        self._build_tray()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self._refresh)
        self.refresh_timer.start(round(1000 / max(5, self.config.preview_fps)))

    @staticmethod
    def _panel(object_name: str = "panel") -> QFrame:
        panel = QFrame()
        panel.setObjectName(object_name)
        return panel

    @staticmethod
    def _heading(text: str, size: int = 16) -> QLabel:
        label = QLabel(text)
        label.setFont(QFont("Microsoft YaHei UI", size, QFont.Weight.DemiBold))
        return label

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 22)
        layout.setSpacing(18)
        layout.addLayout(self._build_header())

        body = QHBoxLayout()
        body.setSpacing(18)
        body.addWidget(self._build_preview_panel(), 7)

        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(390)
        self.tabs.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )
        self.tabs.addTab(self._build_control_tab(), "控制台")
        self.tabs.addTab(self._build_settings_tab(), "识别与设置")
        body.addWidget(self.tabs, 5)
        layout.addLayout(body, 1)
        self.setCentralWidget(root)

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(12)
        icon = QLabel()
        icon.setPixmap(build_app_icon(52).pixmap(52, 52))
        icon.setAccessibleName("Vimoose应用图标")
        header.addWidget(icon)

        title_box = QVBoxLayout()
        title_box.setSpacing(1)
        title = QLabel("Vimoose")
        title.setFont(QFont("Microsoft YaHei UI", 23, QFont.Weight.Bold))
        subtitle = QLabel("本地视觉识别  ·  实时无接触控制")
        subtitle.setObjectName("muted")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box)
        header.addStretch()

        self.status_pill = QLabel("已停止")
        self.status_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_pill.setMinimumSize(104, 42)
        self.status_pill.setAccessibleName("当前控制状态")
        header.addWidget(self.status_pill)

        self.pause_button = QPushButton("暂停")
        self.pause_button.setEnabled(False)
        self.pause_button.setAccessibleName("暂停或恢复手势控制")
        self.pause_button.clicked.connect(self._toggle_pause)
        header.addWidget(self.pause_button)

        self.start_button = QPushButton("启动控制")
        self.start_button.setObjectName("primaryButton")
        self.start_button.setAccessibleName("启动或停止手势控制")
        self.start_button.clicked.connect(self._toggle_running)
        header.addWidget(self.start_button)

        emergency = QPushButton("紧急停止")
        emergency.setObjectName("dangerButton")
        emergency.setAccessibleName("立即停止鼠标控制并释放按键")
        emergency.clicked.connect(self._emergency_stop)
        header.addWidget(emergency)
        return header

    def _build_preview_panel(self) -> QFrame:
        panel = self._panel()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        top = QHBoxLayout()
        title_box = QVBoxLayout()
        eyebrow = QLabel("LIVE VISION")
        eyebrow.setObjectName("eyebrow")
        title_box.addWidget(eyebrow)
        title_box.addWidget(self._heading("实时手部追踪", 17))
        top.addLayout(title_box)
        top.addStretch()
        self.light_chip = QLabel("光照正常")
        self.light_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.light_chip.setMinimumSize(92, 32)
        self.light_chip.setAccessibleName("当前光照状态")
        top.addWidget(self.light_chip)
        layout.addLayout(top)

        self.preview_label = QLabel("启动控制后，将手掌完整放入画面")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumSize(600, 430)
        self.preview_label.setStyleSheet(
            "background:#030712; color:#A5B4C7; border:1px solid #263B53;"
            "border-radius:12px; font-size:15px;",
        )
        self.preview_label.setAccessibleName("实时摄像头和手部关键点预览")
        layout.addWidget(self.preview_label, 1)

        self.frame_legend = QLabel("青色框：识别增强范围  ·  蓝色框：光标活动区域")
        self.frame_legend.setObjectName("subtle")
        self.frame_legend.setAccessibleName("预览框线说明")
        layout.addWidget(self.frame_legend)

        guide = self._panel("guideStrip")
        guide_layout = QHBoxLayout(guide)
        guide_layout.setContentsMargins(14, 10, 14, 10)
        guide_layout.setSpacing(16)
        for number, title, detail in (
            ("01", "完整入镜", "手腕和指尖都在框内"),
            ("02", "自然指向", "食指无需绷直即可移动"),
            ("03", "轻触捏合", "拇指与食指合拢后松开"),
        ):
            item = QVBoxLayout()
            tag = QLabel(f"{number}  {title}")
            tag.setStyleSheet(f"color:{COLORS['text']}; font-weight:700;")
            caption = QLabel(detail)
            caption.setObjectName("subtle")
            item.addWidget(tag)
            item.addWidget(caption)
            guide_layout.addLayout(item, 1)
        layout.addWidget(guide)

        safety = QLabel(
            "快捷保护  Ctrl+Alt+Esc 紧急停止   ·   Ctrl+Alt+G 暂停/恢复   ·   Ctrl+Alt+Q 安全退出",
        )
        safety.setObjectName("subtle")
        safety.setWordWrap(True)
        safety.setAccessibleName("安全快捷键说明")
        layout.addWidget(safety)
        return panel

    def _metric_card(self, title: str, initial: str) -> tuple[QFrame, QLabel]:
        card = self._panel("metricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(13, 11, 13, 11)
        layout.setSpacing(3)
        caption = QLabel(title)
        caption.setObjectName("subtle")
        value = QLabel(initial)
        value.setObjectName("metricValue")
        layout.addWidget(caption)
        layout.addWidget(value)
        return card, value

    def _build_control_tab(self) -> QWidget:
        content = QWidget()
        content.setObjectName("pageContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 16, 14, 16)
        layout.setSpacing(12)

        hero = self._panel("heroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(18, 16, 18, 16)
        hero_layout.setSpacing(7)
        eyebrow = QLabel("CURRENT GESTURE")
        eyebrow.setObjectName("eyebrow")
        self.gesture_value = QLabel("等待启动")
        self.gesture_value.setObjectName("gestureValue")
        self.state_message = QLabel("启动后即可在本机离线识别手势")
        self.state_message.setObjectName("muted")
        self.state_message.setWordWrap(True)
        hero_layout.addWidget(eyebrow)
        hero_layout.addWidget(self.gesture_value)
        hero_layout.addWidget(self.state_message)
        layout.addWidget(hero)

        quality = self._panel()
        quality_layout = QVBoxLayout(quality)
        quality_layout.setContentsMargins(16, 13, 16, 13)
        quality_layout.setSpacing(8)
        quality_top = QHBoxLayout()
        quality_top.addWidget(self._heading("识别稳定度", 14))
        quality_top.addStretch()
        self.quality_value = QLabel("--")
        self.quality_value.setStyleSheet(f"color:{COLORS['accent']}; font-weight:700;")
        quality_top.addWidget(self.quality_value)
        quality_layout.addLayout(quality_top)
        self.quality_progress = QProgressBar()
        self.quality_progress.setRange(0, 100)
        self.quality_progress.setTextVisible(False)
        self.quality_progress.setAccessibleName("近三秒手部检出率")
        quality_layout.addWidget(self.quality_progress)
        chips = QHBoxLayout()
        self.hand_chip = QLabel("左右手判断 --")
        self.hand_chip.setObjectName("subtle")
        self.focus_chip = QLabel(
            f"识别增强 {round(self.config.recognition_zoom * 100)}%",
        )
        self.focus_chip.setObjectName("subtle")
        self.quality_hint = QLabel("让整只手进入画面可获得更稳定的追踪")
        self.quality_hint.setObjectName("subtle")
        self.quality_hint.setWordWrap(True)
        chips.addWidget(self.hand_chip)
        chips.addWidget(self.focus_chip)
        chips.addStretch()
        quality_layout.addLayout(chips)
        quality_layout.addWidget(self.quality_hint)
        layout.addWidget(quality)

        metrics = QGridLayout()
        metrics.setSpacing(10)
        fps_card, self.fps_value = self._metric_card("采集 / 推理", "0.0 / 0.0")
        latency_card, self.latency_value = self._metric_card("延迟 / P95", "0 / 0 ms")
        resource_card, self.resource_value = self._metric_card("CPU / 内存", "0% / 0 MB")
        drops_card, self.drops_value = self._metric_card("覆盖旧帧", "0")
        metrics.addWidget(fps_card, 0, 0)
        metrics.addWidget(latency_card, 0, 1)
        metrics.addWidget(resource_card, 1, 0)
        metrics.addWidget(drops_card, 1, 1)
        layout.addLayout(metrics)

        gesture_group = QGroupBox("快捷手势")
        gesture_layout = QGridLayout(gesture_group)
        gesture_layout.setHorizontalSpacing(18)
        gesture_layout.setVerticalSpacing(8)
        gestures = (
            ("食指指向", "移动光标"),
            ("食指短捏合", "左键单击"),
            ("食指捏合约 5 秒", "按住拖拽"),
            ("中指短捏合", "右键单击"),
            ("光标靠近按钮", "自动磁吸"),
            ("张掌上下 / 翻腕", "滚轮"),
            ("张掌向左挥动", "下一页"),
            ("张掌向右挥动", "上一页"),
            ("握拳 0.5 秒", "暂停 / 恢复"),
        )
        split = (len(gestures) + 1) // 2
        for index, (gesture, action) in enumerate(gestures):
            row = index % split
            column = 0 if index < split else 2
            gesture_layout.addWidget(QLabel(gesture), row, column)
            action_label = QLabel(action)
            action_label.setObjectName("muted")
            gesture_layout.addWidget(action_label, row, column + 1)
        layout.addWidget(gesture_group)

        tools = QHBoxLayout()
        retry = QPushButton("重新连接摄像头")
        retry.clicked.connect(self._restart_control)
        logs = QPushButton("打开诊断日志")
        logs.clicked.connect(lambda: open_log_directory(app_data_dir() / "logs"))
        tools.addWidget(retry)
        tools.addWidget(logs)
        layout.addLayout(tools)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )
        scroll.setMinimumSize(0, 0)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _slider_row(
        self,
        layout: QGridLayout,
        row: int,
        label: str,
        minimum: int,
        maximum: int,
        value: int,
        suffix: str,
        hint: str = "",
    ) -> tuple[QSlider, QLabel]:
        caption = QLabel(label)
        caption.setMinimumWidth(92)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        slider.setAccessibleName(label)
        if hint:
            slider.setToolTip(hint)
            caption.setToolTip(hint)
        value_label = QLabel(f"{value}{suffix}")
        value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        value_label.setMinimumWidth(56)
        value_label.setStyleSheet(f"color:{COLORS['text']}; font-weight:650;")
        slider.valueChanged.connect(
            lambda current, target=value_label, unit=suffix: target.setText(f"{current}{unit}"),
        )
        layout.addWidget(caption, row, 0)
        layout.addWidget(slider, row, 1)
        layout.addWidget(value_label, row, 2)
        return slider, value_label

    def _build_settings_tab(self) -> QWidget:
        content = QWidget()
        content.setObjectName("pageContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(14, 16, 14, 16)
        layout.setSpacing(12)

        camera_group = QGroupBox("摄像头与识别")
        camera_layout = QGridLayout(camera_group)
        camera_layout.setVerticalSpacing(10)
        camera_layout.addWidget(QLabel("摄像头编号"), 0, 0)
        self.camera_spin = QSpinBox()
        self.camera_spin.setRange(0, 9)
        self.camera_spin.setValue(self.config.camera_index)
        self.camera_spin.setAccessibleName("摄像头编号")
        camera_layout.addWidget(self.camera_spin, 0, 1, 1, 2)
        camera_layout.addWidget(QLabel("操作手"), 1, 0)
        self.hand_combo = QComboBox()
        self.hand_combo.addItem("任意手（推荐）", "Any")
        self.hand_combo.addItem("只使用右手", "Right")
        self.hand_combo.addItem("只使用左手", "Left")
        index = self.hand_combo.findData(self.config.handedness)
        self.hand_combo.setCurrentIndex(max(0, index))
        self.hand_combo.setAccessibleName("允许控制的手")
        camera_layout.addWidget(self.hand_combo, 1, 1, 1, 2)
        confidence = round(self.config.min_detection_confidence * 100)
        self.detection_slider, _ = self._slider_row(
            camera_layout,
            2,
            "检测门槛",
            25,
            75,
            confidence,
            "%",
            "数值越低越容易检测到手；默认40%偏向灵敏，复杂背景可适当提高。",
        )
        self.recognition_zoom_slider, _ = self._slider_row(
            camera_layout,
            3,
            "识别增强",
            100,
            135,
            round(self.config.recognition_zoom * 100),
            "%",
            "温和放大中央识别区，提高远手和小手的关键点检出率。",
        )
        camera_help = QLabel(
            "默认115%兼顾灵敏度与边缘范围；经常靠近画面边缘时可调回100%。",
        )
        camera_help.setObjectName("subtle")
        camera_help.setWordWrap(True)
        camera_layout.addWidget(camera_help, 4, 0, 1, 3)
        calibration_button = QPushButton("运行三步个性化校准")
        calibration_button.setAccessibleName("启动个性化手势校准向导")
        calibration_button.clicked.connect(self._run_calibration)
        camera_layout.addWidget(calibration_button, 5, 0, 1, 3)
        layout.addWidget(camera_group)

        feel_group = QGroupBox("光标手感")
        feel_layout = QGridLayout(feel_group)
        feel_layout.setVerticalSpacing(8)
        self.stability_slider, _ = self._slider_row(
            feel_layout,
            0,
            "稳定性",
            0,
            100,
            round(self.config.pointer_stability * 100),
            "%",
            "提高后静止更稳，过高会增加轻微跟随感。",
        )
        self.response_slider, _ = self._slider_row(
            feel_layout,
            1,
            "响应速度",
            0,
            100,
            round(self.config.pointer_response * 100),
            "%",
            "提高后快速移动更跟手。",
        )
        self.interpolation_slider, _ = self._slider_row(
            feel_layout,
            2,
            "丝滑过渡",
            12,
            60,
            self.config.cursor_interpolation_ms,
            "ms",
            "在相邻识别帧之间补充过渡点，建议 32–46ms。",
        )
        self.pinch_slider, _ = self._slider_row(
            feel_layout,
            3,
            "捏合灵敏度",
            28,
            60,
            round(self.config.pinch_engage * 100),
            "%",
            "提高后拇指与指尖无需贴得过紧即可触发。",
        )
        self.scroll_slider, _ = self._slider_row(
            feel_layout,
            4,
            "滚轮速度",
            20,
            300,
            round(self.config.scroll_sensitivity * 100),
            "%",
        )
        self.edge_reach_slider, _ = self._slider_row(
            feel_layout,
            5,
            "全屏覆盖",
            8,
            28,
            round(self.config.pointer_margin_x * 100),
            "%",
            "数值越大，手在更小的摄像头安全区域内就能覆盖整个屏幕。",
        )
        self.drag_hold_slider, _ = self._slider_row(
            feel_layout,
            6,
            "拖拽长按",
            1000,
            8000,
            self.config.drag_hold_ms,
            "ms",
            "持续捏合达到该时间后才按下左键进入拖拽；默认5000ms。",
        )
        feel_help = QLabel(
            "关键点到达安全区边缘时会直接完成屏幕边缘行程，无需把手移出画面。",
        )
        feel_help.setObjectName("subtle")
        feel_help.setWordWrap(True)
        feel_layout.addWidget(feel_help, 7, 0, 1, 3)
        layout.addWidget(feel_group)

        snap_group = QGroupBox("光标磁吸")
        snap_layout = QGridLayout(snap_group)
        snap_layout.setVerticalSpacing(8)
        self.cursor_snap_check = QCheckBox(
            "靠近按钮、复选框、标签页和菜单项时吸附到可点击位置",
        )
        self.cursor_snap_check.setChecked(self.config.cursor_snap_enabled)
        self.cursor_snap_check.setAccessibleName("启用Windows控件磁吸")
        snap_layout.addWidget(self.cursor_snap_check, 0, 0, 1, 3)
        self.cursor_snap_radius_slider, _ = self._slider_row(
            snap_layout,
            1,
            "吸附半径",
            12,
            60,
            self.config.cursor_snap_radius_px,
            "px",
            "半径越大越容易吸附；离开控件后会自动解除，不会自动点击。",
        )
        snap_help = QLabel(
            "使用 Windows UI Automation 读取控件边界；目标程序不提供辅助功能信息时会自动按普通光标移动。",
        )
        snap_help.setObjectName("subtle")
        snap_help.setWordWrap(True)
        snap_layout.addWidget(snap_help, 2, 0, 1, 3)
        layout.addWidget(snap_group)

        extension_group = QGroupBox("扩展手势")
        extension_layout = QVBoxLayout(extension_group)
        self.page_gesture_check = QCheckBox(
            "张掌左右挥动翻页（向左下一页，向右上一页）",
        )
        self.page_gesture_check.setChecked(self.config.page_gestures_enabled)
        self.rotation_gesture_check = QCheckBox(
            "启用翻腕辅助（指向时移动光标，张掌时控制滚轮）",
        )
        self.rotation_gesture_check.setChecked(self.config.rotation_gestures_enabled)
        self.partial_tracking_check = QCheckBox(
            "完整手部分出框后，持续续跟踪食指或中指",
        )
        self.partial_tracking_check.setChecked(self.config.partial_finger_tracking)
        partial_help = QLabel(
            "单指身份由最近一次完整手部结果继承；指尖仍在画面内时可续跟踪，完全离开摄像头后无法继续识别。",
        )
        partial_help.setObjectName("subtle")
        partial_help.setWordWrap(True)
        extension_layout.addWidget(self.page_gesture_check)
        extension_layout.addWidget(self.rotation_gesture_check)
        extension_layout.addWidget(self.partial_tracking_check)
        extension_layout.addWidget(partial_help)
        layout.addWidget(extension_group)

        system_group = QGroupBox("启动与显示")
        system_layout = QVBoxLayout(system_group)
        self.preview_check = QCheckBox("显示实时摄像头预览")
        self.preview_check.setChecked(self.config.preview_enabled)
        self.startup_check = QCheckBox("登录 Windows 后自动启动")
        self.startup_check.setChecked(self.config.start_with_windows)
        self.auto_control_check = QCheckBox("程序启动后自动开启手势控制")
        self.auto_control_check.setChecked(self.config.auto_start_control)
        system_layout.addWidget(self.preview_check)
        system_layout.addWidget(self.startup_check)
        system_layout.addWidget(self.auto_control_check)
        layout.addWidget(system_group)

        self.save_notice = QLabel("")
        self.save_notice.setStyleSheet(f"color:{COLORS['success']}; font-weight:650;")
        self.save_notice.setAccessibleName("设置保存结果")
        layout.addWidget(self.save_notice)

        buttons = QHBoxLayout()
        reset = QPushButton("恢复默认")
        reset.clicked.connect(self._reset_settings)
        save = QPushButton("保存并立即应用")
        save.setObjectName("primaryButton")
        save.clicked.connect(self._save_settings)
        buttons.addWidget(reset)
        buttons.addWidget(save)
        layout.addLayout(buttons)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )
        scroll.setMinimumSize(0, 0)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        return scroll

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(build_app_icon(), self)
        self.tray.setToolTip("Vimoose 视觉手势鼠标")
        menu = QMenu()
        show_action = QAction("显示主窗口", self)
        show_action.triggered.connect(self._show_window)
        self.pause_action = QAction("暂停控制", self)
        self.pause_action.triggered.connect(self._toggle_pause)
        stop_action = QAction("停止控制", self)
        stop_action.triggered.connect(self._stop_control)
        quit_action = QAction("安全退出", self)
        quit_action.triggered.connect(self.request_quit)
        menu.addAction(show_action)
        menu.addAction(self.pause_action)
        menu.addAction(stop_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_window()

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _toggle_running(self) -> None:
        if self.pipeline.running:
            self._stop_control()
        elif not self.pipeline.start():
            snapshot = self.pipeline.snapshot()
            QMessageBox.warning(self, "无法启动", snapshot.message)

    def _restart_control(self) -> None:
        self.pipeline.stop()
        if not self.pipeline.start():
            QMessageBox.warning(self, "连接失败", self.pipeline.snapshot().message)

    def _stop_control(self) -> None:
        self.pipeline.stop()

    def _toggle_pause(self) -> None:
        if self.pipeline.running:
            self.pipeline.toggle_paused()

    def _emergency_stop(self) -> None:
        self.pipeline.emergency_stop()
        self.tray.showMessage(
            "Vimoose",
            "已紧急停止并释放鼠标按键。",
            QSystemTrayIcon.MessageIcon.Warning,
            3000,
        )

    def _config_from_controls(self) -> AppConfig:
        config = self.config
        config.camera_index = self.camera_spin.value()
        config.handedness = str(self.hand_combo.currentData())
        config.recognition_zoom = self.recognition_zoom_slider.value() / 100
        config.pointer_stability = self.stability_slider.value() / 100
        config.pointer_response = self.response_slider.value() / 100
        config.cursor_interpolation_ms = self.interpolation_slider.value()
        edge_margin = self.edge_reach_slider.value() / 100
        config.pointer_margin_x = edge_margin
        config.pointer_margin_y = max(0.08, edge_margin * 0.80)
        config.pinch_engage = self.pinch_slider.value() / 100
        config.pinch_release = min(1.2, config.pinch_engage + 0.13)
        config.pinch_arm = min(1.4, config.pinch_release + 0.17)
        config.scroll_sensitivity = self.scroll_slider.value() / 100
        config.drag_hold_ms = self.drag_hold_slider.value()
        config.cursor_snap_enabled = self.cursor_snap_check.isChecked()
        config.cursor_snap_radius_px = self.cursor_snap_radius_slider.value()
        config.page_gestures_enabled = self.page_gesture_check.isChecked()
        config.rotation_gestures_enabled = self.rotation_gesture_check.isChecked()
        config.partial_finger_tracking = self.partial_tracking_check.isChecked()
        detection = self.detection_slider.value() / 100
        config.min_detection_confidence = detection
        config.min_presence_confidence = max(0.25, detection - 0.05)
        config.min_tracking_confidence = detection
        config.preview_enabled = self.preview_check.isChecked()
        config.start_with_windows = self.startup_check.isChecked()
        config.auto_start_control = self.auto_control_check.isChecked()
        config.validate()
        return config

    def _save_settings(self) -> None:
        try:
            config = self._config_from_controls()
            self.config_store.save(config)
            set_start_with_windows(config.start_with_windows)
            self.pipeline.update_config(config)
            self.config = config
            self.save_notice.setText("设置已保存，识别引擎已使用新参数。")
            QTimer.singleShot(3500, lambda: self.save_notice.setText(""))
        except OSError as error:
            QMessageBox.critical(self, "保存失败", f"无法保存设置：{error}")

    def _run_calibration(self) -> None:
        dialog = CalibrationDialog(self.pipeline, self.config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.result_config is None:
            return
        try:
            self.config = dialog.result_config
            self.config_store.save(self.config)
            self.pipeline.update_config(self.config)
            self._sync_controls_from_config()
            self.save_notice.setText("个性化校准已应用并保存。")
            QTimer.singleShot(4500, lambda: self.save_notice.setText(""))
        except OSError as error:
            QMessageBox.critical(self, "校准保存失败", f"无法保存校准参数：{error}")

    def _sync_controls_from_config(self) -> None:
        self.camera_spin.setValue(self.config.camera_index)
        self.hand_combo.setCurrentIndex(self.hand_combo.findData(self.config.handedness))
        self.detection_slider.setValue(round(self.config.min_detection_confidence * 100))
        self.recognition_zoom_slider.setValue(round(self.config.recognition_zoom * 100))
        self.stability_slider.setValue(round(self.config.pointer_stability * 100))
        self.response_slider.setValue(round(self.config.pointer_response * 100))
        self.interpolation_slider.setValue(self.config.cursor_interpolation_ms)
        self.edge_reach_slider.setValue(round(self.config.pointer_margin_x * 100))
        self.pinch_slider.setValue(round(self.config.pinch_engage * 100))
        self.scroll_slider.setValue(round(self.config.scroll_sensitivity * 100))
        self.drag_hold_slider.setValue(self.config.drag_hold_ms)
        self.cursor_snap_check.setChecked(self.config.cursor_snap_enabled)
        self.cursor_snap_radius_slider.setValue(self.config.cursor_snap_radius_px)
        self.page_gesture_check.setChecked(self.config.page_gestures_enabled)
        self.rotation_gesture_check.setChecked(self.config.rotation_gestures_enabled)
        self.partial_tracking_check.setChecked(self.config.partial_finger_tracking)
        self.preview_check.setChecked(self.config.preview_enabled)
        self.startup_check.setChecked(self.config.start_with_windows)
        self.auto_control_check.setChecked(self.config.auto_start_control)

    def _reset_settings(self) -> None:
        choice = QMessageBox.question(
            self,
            "恢复默认设置",
            "确定恢复全部默认设置吗？当前自定义参数将被覆盖。",
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        self.config = self.config_store.reset()
        set_start_with_windows(False)
        self.pipeline.update_config(self.config)
        self._sync_controls_from_config()
        self.save_notice.setText("已恢复高召回率与流畅控制默认值。")

    @staticmethod
    def _gesture_text(gesture: GestureType) -> str:
        return {
            GestureType.NONE: "等待手势",
            GestureType.POINTER: "光标移动",
            GestureType.PINCH_ARMED: "点击位置锁定",
            GestureType.LEFT_PINCH: "左键捏合",
            GestureType.RIGHT_PINCH: "右键捏合",
            GestureType.DRAG: "正在拖拽",
            GestureType.SCROLL: "滚轮控制",
            GestureType.PAGE_NEXT: "下一页",
            GestureType.PAGE_PREVIOUS: "上一页",
            GestureType.PARTIAL_INDEX: "食指续跟踪",
            GestureType.PARTIAL_MIDDLE: "中指续跟踪",
            GestureType.FIST: "握拳确认",
            GestureType.PAUSED: "控制已暂停",
            GestureType.LOST: "未检测到手",
        }[gesture]

    def _update_status(self, snapshot: PipelineSnapshot) -> None:
        if snapshot.camera_error:
            color, background, title = COLORS["danger"], "#351824", "摄像头异常"
        elif snapshot.running and snapshot.camera_signal_missing:
            color, background, title = COLORS["danger"], "#351824", "无画面"
        elif not snapshot.running:
            color, background, title = COLORS["subtle"], "#16283E", "已停止"
        elif snapshot.paused:
            color, background, title = COLORS["warning"], "#332713", "已暂停"
        else:
            color, background, title = COLORS["success"], "#102C29", "控制中"
        self.status_pill.setText(title)
        self.status_pill.setStyleSheet(
            f"color:{color}; background:{background}; border:1px solid {color};"
            "border-radius:20px; font-weight:700;",
        )
        self.start_button.setText("停止控制" if snapshot.running else "启动控制")
        self.pause_button.setEnabled(snapshot.running)
        self.pause_button.setText("恢复" if snapshot.paused else "暂停")
        self.pause_action.setText("恢复控制" if snapshot.paused else "暂停控制")
        self.pause_action.setEnabled(snapshot.running)

        self.gesture_value.setText(self._gesture_text(snapshot.gesture))
        self.state_message.setText(snapshot.message)
        self.fps_value.setText(
            f"{snapshot.metrics.capture_fps:.1f} / {snapshot.metrics.inference_fps:.1f}",
        )
        self.latency_value.setText(
            f"{snapshot.metrics.latency_ms:.0f} / {snapshot.metrics.latency_p95_ms:.0f} ms",
        )
        self.resource_value.setText(
            f"{snapshot.metrics.cpu_percent:.0f}% / {snapshot.metrics.memory_mb:.0f} MB",
        )
        self.drops_value.setText(str(snapshot.metrics.dropped_frames))

        quality = round(snapshot.metrics.hand_detection_rate)
        self.quality_progress.setValue(quality)
        self.quality_value.setText(f"{quality}%" if snapshot.running else "--")
        hand_score = round(snapshot.metrics.handedness_score * 100)
        palm_size = round(snapshot.metrics.palm_width_percent)
        if palm_size:
            self.hand_chip.setText(f"手掌大小 {palm_size}%")
        else:
            self.hand_chip.setText(
                f"左右手判断 {hand_score}%" if hand_score else "手掌大小 --",
            )
        self.focus_chip.setText(
            f"识别增强 {round(self.config.recognition_zoom * 100)}%",
        )
        self.frame_legend.setVisible(self.config.recognition_zoom > 1.001)
        if not snapshot.running:
            hint = "启动控制后显示近3秒手部检出率"
        elif snapshot.camera_signal_missing:
            hint = "无有效画面：请启动虚拟摄像头视频源，或在设置中切换摄像头编号"
        elif snapshot.low_light:
            hint = "光线偏暗：请面向光源，并避免摄像头正对强背光"
        elif snapshot.metrics.inferred_frames > 8 and quality < 35:
            if 0 < snapshot.metrics.palm_width_percent < 9:
                hint = "手部在画面中过小：请靠近镜头，并让手掌位于青色识别框内"
            elif snapshot.metrics.palm_width_percent > 34:
                hint = "手部离镜头过近：请稍微后退，让手腕和全部指尖进入画面"
            else:
                hint = "识别较弱：让手掌朝向镜头，避免指尖互相遮挡"
        elif quality < 70:
            hint = "识别波动：保持手掌正对镜头，动作幅度稍大一些"
        else:
            hint = "追踪稳定，可以开始移动、捏合或滚动"
        self.quality_hint.setText(hint)

        if snapshot.camera_signal_missing:
            light_color, light_bg, light_text = COLORS["danger"], "#351824", "无画面信号"
        elif snapshot.low_light:
            light_color, light_bg, light_text = COLORS["warning"], "#332713", "光线偏暗"
        else:
            light_color, light_bg, light_text = COLORS["success"], "#102C29", "光照正常"
        self.light_chip.setText(light_text)
        self.light_chip.setStyleSheet(
            f"color:{light_color}; background:{light_bg}; border:1px solid {light_color};"
            "border-radius:16px; font-weight:650;",
        )

    def _render_preview(self, snapshot: PipelineSnapshot) -> None:
        if not self.config.preview_enabled:
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("实时预览已关闭，识别仍在本地继续运行")
            return
        frame_packet, detection = self.pipeline.get_preview()
        if frame_packet is None or frame_packet.sequence == self._last_frame_sequence:
            return
        self._last_frame_sequence = frame_packet.sequence
        frame = frame_packet.frame.copy()
        height, width = frame.shape[:2]

        if self.config.recognition_zoom > 1.001:
            focus_width = round(width / self.config.recognition_zoom)
            focus_height = round(height / self.config.recognition_zoom)
            focus_left = (width - focus_width) // 2
            focus_top = (height - focus_height) // 2
            cv2.rectangle(
                frame,
                (focus_left, focus_top),
                (focus_left + focus_width, focus_top + focus_height),
                (210, 203, 45),
                1,
                cv2.LINE_AA,
            )
        margin_x = round(self.config.pointer_margin_x * width)
        margin_y = round(self.config.pointer_margin_y * height)
        cv2.rectangle(
            frame,
            (margin_x, margin_y),
            (width - margin_x, height - margin_y),
            (248, 189, 56),
            1,
            cv2.LINE_AA,
        )
        if detection and detection.observations:
            observation = detection.observations[0]
            points = observation.landmarks
            if len(points) == 21:
                for start, end in HAND_CONNECTIONS:
                    first = (round(points[start].x * width), round(points[start].y * height))
                    second = (round(points[end].x * width), round(points[end].y * height))
                    cv2.line(frame, first, second, (191, 212, 45), 2, cv2.LINE_AA)
                for index, point in enumerate(points):
                    center = (round(point.x * width), round(point.y * height))
                    radius = 6 if index in {4, 8, 12} else 4
                    color = (153, 246, 52) if index in {4, 8, 12} else (248, 250, 252)
                    cv2.circle(frame, center, radius, (15, 25, 41), -1, cv2.LINE_AA)
                    cv2.circle(frame, center, max(2, radius - 2), color, -1, cv2.LINE_AA)
            elif observation.partial_position is not None:
                point = observation.partial_position
                center = (round(point.x * width), round(point.y * height))
                color = (
                    (45, 212, 191)
                    if observation.partial_finger == "Index"
                    else (56, 189, 248)
                )
                cv2.circle(frame, center, 13, (15, 25, 41), -1, cv2.LINE_AA)
                cv2.circle(frame, center, 9, color, 2, cv2.LINE_AA)
                cv2.line(
                    frame,
                    (center[0] - 5, center[1]),
                    (center[0] + 5, center[1]),
                    color,
                    2,
                    cv2.LINE_AA,
                )
                cv2.line(
                    frame,
                    (center[0], center[1] - 5),
                    (center[0], center[1] + 5),
                    color,
                    2,
                    cv2.LINE_AA,
                )
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = QImage(
            rgb.data,
            width,
            height,
            rgb.strides[0],
            QImage.Format.Format_RGB888,
        ).copy()
        pixmap = QPixmap.fromImage(image).scaled(
            self.preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setText("")
        self.preview_label.setPixmap(pixmap)

    def _refresh(self) -> None:
        snapshot = self.pipeline.snapshot()
        self._update_status(snapshot)
        if snapshot.running:
            self._render_preview(snapshot)
        elif snapshot.camera_error:
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText(snapshot.camera_error)

    def request_quit(self) -> None:
        self._really_quit = True
        self.pipeline.stop()
        self.tray.hide()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._really_quit or not self.tray.isVisible():
            self.pipeline.stop()
            event.accept()
            return
        self.hide()
        self.tray.showMessage(
            "Vimoose仍在运行",
            "程序已最小化到系统托盘。使用“安全退出”可完全关闭。",
            QSystemTrayIcon.MessageIcon.Information,
            2500,
        )
        event.ignore()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and self.isMinimized():
            QTimer.singleShot(0, self.hide)
