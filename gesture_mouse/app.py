"""应用入口和生命周期管理。"""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import sys
from ctypes import wintypes

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from gesture_mouse import __version__
from gesture_mouse.config import ConfigStore
from gesture_mouse.hotkeys import HotkeyMonitor
from gesture_mouse.logging_setup import setup_logging
from gesture_mouse.mouse import MouseController, NullMouseBackend, Win32MouseBackend
from gesture_mouse.pipeline import GesturePipeline
from gesture_mouse.ui import MainWindow, UiBridge, build_app_icon


LOGGER = logging.getLogger(__name__)


def _enable_dpi_awareness() -> None:
    """开发模式下的DPI兜底；打包程序主要依赖应用清单。"""

    if os.name != "nt":
        return
    try:
        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        LOGGER.warning("无法设置Per-Monitor V2 DPI awareness", exc_info=True)


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Vimoose 视觉手势鼠标")
    parser.add_argument("--minimized", action="store_true", help="启动后只显示托盘")
    parser.add_argument(
        "--safe-mode",
        action="store_true",
        help="不注入鼠标事件，用于界面和摄像头诊断",
    )
    parser.add_argument(
        "--diagnostic-seconds",
        type=float,
        default=0.0,
        help="使用空鼠标后端运行指定秒数后安全退出",
    )
    parser.add_argument(
        "--verify-cursor-snap",
        action="store_true",
        help="打开测试窗口并验证Windows标题栏按钮磁吸，随后自动退出",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    _enable_dpi_awareness()
    setup_logging()

    QCoreApplication.setOrganizationName("Vimoose")
    QCoreApplication.setApplicationName("Vimoose")
    QCoreApplication.setApplicationVersion(__version__)
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(build_app_icon())

    store = ConfigStore()
    config = store.load()
    try:
        backend = (
            NullMouseBackend()
            if (
                args.safe_mode or args.diagnostic_seconds > 0
            ) and not args.verify_cursor_snap
            else Win32MouseBackend(config)
        )
    except RuntimeError as error:
        QMessageBox.critical(None, "平台不受支持", str(error))
        return 2

    mouse = MouseController(backend)
    pipeline = GesturePipeline(config, mouse)
    window = MainWindow(pipeline, store, config)
    bridge = UiBridge()
    bridge.toggle_requested.connect(
        lambda: pipeline.toggle_paused() if pipeline.running else pipeline.start(),
    )
    bridge.emergency_requested.connect(window._emergency_stop)
    bridge.quit_requested.connect(window.request_quit)

    hotkeys = HotkeyMonitor(
        bridge.toggle_requested.emit,
        bridge.emergency_requested.emit,
        bridge.quit_requested.emit,
    )
    hotkeys.start()

    def handle_exception(
        exception_type: type[BaseException],
        exception: BaseException,
        traceback: object,
    ) -> None:
        LOGGER.critical(
            "主线程未处理异常",
            exc_info=(exception_type, exception, traceback),
        )
        pipeline.emergency_stop()
        QMessageBox.critical(
            window,
            "Vimoose发生错误",
            "程序已停止控制并释放鼠标。详细信息已写入诊断日志。",
        )

    sys.excepthook = handle_exception

    if not args.minimized or args.verify_cursor_snap:
        window.show()
    if config.auto_start_control or args.diagnostic_seconds > 0:
        pipeline.start()
    if args.diagnostic_seconds > 0:
        def finish_diagnostic() -> None:
            snapshot = pipeline.snapshot()
            LOGGER.info(
                "诊断完成 capture_fps=%.1f inference_fps=%.1f "
                "latency_ms=%.1f latency_p50_ms=%.1f latency_p95_ms=%.1f "
                "hand_detection_rate=%.1f dropped_frames=%d "
                "cpu_percent=%.1f memory_mb=%.1f error=%s",
                snapshot.metrics.capture_fps,
                snapshot.metrics.inference_fps,
                snapshot.metrics.latency_ms,
                snapshot.metrics.latency_p50_ms,
                snapshot.metrics.latency_p95_ms,
                snapshot.metrics.hand_detection_rate,
                snapshot.metrics.dropped_frames,
                snapshot.metrics.cpu_percent,
                snapshot.metrics.memory_mb,
                snapshot.camera_error or "none",
            )
            window.request_quit()

        QTimer.singleShot(
            max(1000, round(args.diagnostic_seconds * 1000)),
            finish_diagnostic,
        )
    if args.verify_cursor_snap:
        if not isinstance(backend, Win32MouseBackend):
            LOGGER.error("磁吸诊断需要Windows原生鼠标后端")
            QTimer.singleShot(0, lambda: app.exit(4))
        else:
            original = wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(original))
            target_position: dict[str, float] = {}
            diagnostic_state = {"attempts": 0, "finished": False}
            window_handle = int(window.winId())
            # 后台安装测试启动的窗口不一定获得前台层级；诊断期间临时置顶，
            # 确保UI Automation命中的是本测试窗口而非其后方应用。
            window.raise_()
            window.activateWindow()
            set_window_pos = ctypes.windll.user32.SetWindowPos
            set_window_pos.argtypes = (
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            )
            set_window_pos.restype = wintypes.BOOL
            def ensure_diagnostic_front() -> bool:
                window.raise_()
                window.activateWindow()
                positioned_now = bool(set_window_pos(
                wintypes.HWND(window_handle),
                wintypes.HWND(-1),  # HWND_TOPMOST
                0,
                0,
                0,
                0,
                0x0001 | 0x0002 | 0x0040,  # NOSIZE | NOMOVE | SHOWWINDOW
                ))
                ctypes.windll.user32.SetForegroundWindow(
                    wintypes.HWND(window_handle),
                )
                return positioned_now

            positioned = ensure_diagnostic_front()
            if not positioned:
                LOGGER.warning("磁吸诊断窗口置顶失败")

            def restore_diagnostic_state() -> None:
                set_window_pos(
                    wintypes.HWND(window_handle),
                    wintypes.HWND(-2),  # HWND_NOTOPMOST
                    0,
                    0,
                    0,
                    0,
                    0x0001 | 0x0002,
                )
                ctypes.windll.user32.SetCursorPos(original.x, original.y)

            def verify_result() -> None:
                if diagnostic_state["finished"]:
                    return
                diagnostic_state["finished"] = True
                current = wintypes.POINT()
                ctypes.windll.user32.GetCursorPos(ctypes.byref(current))
                rect = wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(
                    int(window.winId()),
                    ctypes.byref(rect),
                )
                target_name = backend.snap_target_name
                passed = bool(
                    target_name
                    and rect.right - 80 <= current.x <= rect.right
                    and rect.top <= current.y <= rect.top + 60
                )
                LOGGER.info(
                    "磁吸诊断 passed=%s target=%s cursor=%d,%d "
                    "window=%d,%d,%d,%d",
                    passed,
                    target_name or "none",
                    current.x,
                    current.y,
                    rect.left,
                    rect.top,
                    rect.right,
                    rect.bottom,
                )
                restore_diagnostic_state()
                app.exit(0 if passed else 4)

            def poll_snap_move() -> None:
                """等待首次COM/UI Automation初始化后反复取回异步探测结果。"""

                diagnostic_state["attempts"] += 1
                backend.move(target_position["x"], target_position["y"])
                if backend.snap_target_name:
                    QTimer.singleShot(120, verify_result)
                    return
                if diagnostic_state["attempts"] >= 50:
                    verify_result()
                    return
                QTimer.singleShot(200, poll_snap_move)

            def first_snap_move() -> None:
                # window.show()的延迟事件可能重置初始Z序；进入事件循环后
                # 再置顶一次，避免后台安装测试误命中后方应用控件。
                ensure_diagnostic_front()
                rect = wintypes.RECT()
                ctypes.windll.user32.GetWindowRect(
                    int(window.winId()),
                    ctypes.byref(rect),
                )
                screen_width = ctypes.windll.user32.GetSystemMetrics(0)
                screen_height = ctypes.windll.user32.GetSystemMetrics(1)
                target_position["x"] = (rect.right - 38) / max(
                    1,
                    screen_width - 1,
                )
                # 从窗口客户区内、关闭按钮下方靠近，避免测试点落在窗口
                # 外部时被后方应用的真实按钮抢占（那本身是合法磁吸）。
                target_position["y"] = (rect.top + 48) / max(
                    1,
                    screen_height - 1,
                )
                backend.move(target_position["x"], target_position["y"])
                QTimer.singleShot(200, poll_snap_move)

            QTimer.singleShot(700, first_snap_move)

            def diagnostic_timeout() -> None:
                if diagnostic_state["finished"]:
                    return
                diagnostic_state["finished"] = True
                restore_diagnostic_state()
                LOGGER.error("磁吸诊断超时")
                app.exit(5)

            QTimer.singleShot(15000, diagnostic_timeout)

    exit_code = app.exec()
    pipeline.stop()
    hotkeys.stop()
    mouse.shutdown()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
