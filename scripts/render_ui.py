"""离屏渲染桌面界面，用于视觉回归检查。"""

from __future__ import annotations

import argparse
from pathlib import Path

from PySide6.QtTest import QTest
from PySide6.QtCore import QEventLoop, QPoint, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from gesture_mouse.config import AppConfig, ConfigStore
from gesture_mouse.mouse import MouseController, NullMouseBackend
from gesture_mouse.pipeline import GesturePipeline
from gesture_mouse.ui import CalibrationDialog, MainWindow


def capture_window(window: QWidget, path: Path) -> None:
    """由Qt完整渲染控件树，避免合成器窗口抓图只返回最新脏区域。"""

    pixmap = QPixmap(window.size())
    pixmap.fill(window.palette().window().color())
    window.render(pixmap, QPoint(0, 0))
    pixmap.save(str(path))


def event_loop_wait(milliseconds: int) -> None:
    """进入原生Qt事件循环等待，避免QTest.qWait长期占用Python GIL。"""

    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts"))
    parser.add_argument(
        "--exercise-pipeline",
        action="store_true",
        help="使用空鼠标后端运行摄像头与模型后再截图",
    )
    parser.add_argument("--preview-fps", type=int, default=15)
    parser.add_argument("--no-preview", action="store_true")
    parser.add_argument(
        "--calibration",
        action="store_true",
        help="渲染个性化校准对话框并验证安全暂停流程",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    app = QApplication([])
    config = AppConfig(
        preview_fps=args.preview_fps,
        preview_enabled=not args.no_preview,
    )
    pipeline = GesturePipeline(config, MouseController(NullMouseBackend()))
    window = MainWindow(
        pipeline,
        ConfigStore(args.output_dir / "visual-test-config.json"),
        config,
    )
    window.show()
    if args.calibration:
        dialog = CalibrationDialog(pipeline, config, window)
        dialog.show()
        event_loop_wait(1800)
        capture_window(dialog, args.output_dir / "ui-calibration.png")
        dialog.reject()
        window._really_quit = True
        window.close()
        app.quit()
        return 0
    if args.exercise_pipeline:
        pipeline.start()
        event_loop_wait(5000)
        snapshot = pipeline.snapshot()
        print(
            "FPS="
            f"{snapshot.metrics.capture_fps:.1f}/{snapshot.metrics.inference_fps:.1f} "
            f"延迟={snapshot.metrics.latency_ms:.1f}ms "
            f"检出率={snapshot.metrics.hand_detection_rate:.1f}% "
            f"CPU={snapshot.metrics.cpu_percent:.1f}% "
            f"内存={snapshot.metrics.memory_mb:.1f}MB",
        )
    else:
        QTest.qWait(250)
    app.processEvents()
    QTest.qWait(120)
    print(
        f"CONTROL_GEOMETRY={window.x()},{window.y()} "
        f"{window.width()}x{window.height()}",
    )
    capture_window(window, args.output_dir / "ui-main.png")

    window.hide()
    app.processEvents()
    window.tabs.setCurrentIndex(1)
    window.show()
    app.processEvents()
    event_loop_wait(250)
    print(
        f"SETTINGS_GEOMETRY={window.x()},{window.y()} "
        f"{window.width()}x{window.height()}",
    )
    capture_window(window, args.output_dir / "ui-settings.png")
    settings_page = window.tabs.widget(1)
    if settings_page is not None and hasattr(settings_page, "verticalScrollBar"):
        scrollbar = settings_page.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum() // 2)
        event_loop_wait(180)
        capture_window(window, args.output_dir / "ui-settings-middle.png")
        scrollbar.setValue(scrollbar.maximum())
        event_loop_wait(180)
        capture_window(window, args.output_dir / "ui-settings-extensions.png")

    window._really_quit = True
    pipeline.stop()
    window.close()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
