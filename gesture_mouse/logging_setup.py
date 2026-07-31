"""不含图像数据的滚动日志配置。"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from gesture_mouse.config import app_data_dir


def setup_logging() -> None:
    directory = app_data_dir() / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        directory / "vimoose.log",
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
        ),
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)
