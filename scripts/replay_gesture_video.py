"""顺序回放录屏中的摄像头区域，对比旧掌宽归一化与当前手势算法。"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from contextlib import contextmanager
from dataclasses import fields
from math import hypot
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

import gesture_mouse.gestures as gesture_module
from gesture_mouse.config import CONFIG_VERSION, AppConfig
from gesture_mouse.contracts import HandObservation, Landmark
from gesture_mouse.gestures import GestureEngine
from gesture_mouse.vision import prepare_recognition_frame


def parse_crop(value: str | None) -> tuple[int, int, int, int] | None:
    if not value:
        return None
    parts = tuple(int(part.strip()) for part in value.split(","))
    if len(parts) != 4 or any(part < 0 for part in parts):
        raise argparse.ArgumentTypeError("裁剪格式必须为 x,y,width,height")
    if parts[2] <= 0 or parts[3] <= 0:
        raise argparse.ArgumentTypeError("裁剪宽高必须大于0")
    return parts


def crop_frame(
    frame: np.ndarray,
    crop: tuple[int, int, int, int] | None,
) -> np.ndarray:
    if crop is None:
        return frame
    x, y, width, height = crop
    frame_height, frame_width = frame.shape[:2]
    right = min(frame_width, x + width)
    bottom = min(frame_height, y + height)
    if x >= right or y >= bottom:
        raise ValueError("裁剪区域完全位于视频画面之外")
    return frame[y:bottom, x:right]


@contextmanager
def legacy_palm_width_scale(enabled: bool):
    """仅供差分回放：临时恢复0.8.0之前的单掌宽归一化。"""

    original = gesture_module._gesture_scale
    if enabled:
        gesture_module._gesture_scale = gesture_module._palm_width
    try:
        yield
    finally:
        gesture_module._gesture_scale = original


def process_engine(
    engine: GestureEngine,
    observation: HandObservation | None,
    timestamp_ns: int,
    *,
    legacy: bool,
):
    with legacy_palm_width_scale(legacy):
        if observation is None:
            return engine.tick(timestamp_ns)
        return engine.process(observation)


def command_text(commands) -> str:
    return ",".join(command.kind.value for command in commands)


def geometry(points: tuple[Landmark, ...]) -> dict[str, float]:
    if len(points) != 21:
        return {
            "palm_width": 0.0,
            "palm_length": 0.0,
            "left_ratio_width": 99.0,
            "left_ratio_robust": 99.0,
            "right_ratio_width": 99.0,
            "right_ratio_robust": 99.0,
            "index_angle": 0.0,
            "index_tip_span": 0.0,
            "middle_angle": 0.0,
            "middle_tip_span": 0.0,
            "thumb_tip_x": 0.0,
            "thumb_tip_y": 0.0,
            "index_tip_x": 0.0,
            "index_tip_y": 0.0,
            "middle_tip_x": 0.0,
            "middle_tip_y": 0.0,
            "pointer_shape": 0.0,
            "open_palm": 0.0,
            "palm_tilt": 0.0,
        }
    distance = lambda first, second: hypot(
        points[first].x - points[second].x,
        points[first].y - points[second].y,
    )
    palm_width = max(distance(5, 17), 1e-4)
    palm_length = max(distance(0, 9), 1e-4)
    robust_scale = max(
        palm_width,
        min(palm_length * 0.75, palm_width * 2.0),
        1e-4,
    )
    left_distance = distance(4, 8)
    right_distance = distance(4, 12)
    return {
        "palm_width": palm_width,
        "palm_length": palm_length,
        "left_ratio_width": left_distance / palm_width,
        "left_ratio_robust": left_distance / robust_scale,
        "right_ratio_width": right_distance / palm_width,
        "right_ratio_robust": right_distance / robust_scale,
        "index_angle": gesture_module._angle(points[5], points[6], points[8]),
        "index_tip_span": distance(5, 8) / robust_scale,
        "middle_angle": gesture_module._angle(points[9], points[10], points[12]),
        "middle_tip_span": distance(9, 12) / robust_scale,
        "thumb_tip_x": points[4].x,
        "thumb_tip_y": points[4].y,
        "index_tip_x": points[8].x,
        "index_tip_y": points[8].y,
        "middle_tip_x": points[12].x,
        "middle_tip_y": points[12].y,
        "pointer_shape": float(gesture_module._is_pointer(points)),
        "open_palm": float(gesture_module._is_open_palm(points)),
        "palm_tilt": gesture_module._palm_depth_tilt(points),
    }


def load_replay_config(path: Path | None, mode: str) -> AppConfig:
    """只读加载回放配置；raw用于复现迁移前现场参数。"""

    if path is None:
        return AppConfig()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if mode == "migrated":
        config = AppConfig.from_mapping(raw)
    else:
        allowed = {item.name for item in fields(AppConfig)}
        values = {key: value for key, value in raw.items() if key in allowed}
        values["version"] = CONFIG_VERSION
        config = AppConfig(**values)
    config.validate()
    return config


def main() -> int:
    import sys
    if "--classroom" in sys.argv:
        from replay_classroom_video import main as classroom_main
        return classroom_main([arg for arg in sys.argv[1:] if arg != "--classroom"])
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--crop", type=parse_crop)
    parser.add_argument("--start", type=float, default=0.0)
    parser.add_argument("--end", type=float)
    parser.add_argument("--sample-hz", type=float, default=10.0)
    parser.add_argument("--recognition-zoom", type=float, default=1.15)
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--config-mode",
        choices=("raw", "migrated"),
        default="migrated",
    )
    args = parser.parse_args()

    if args.sample_hz <= 0:
        parser.error("--sample-hz 必须大于0")
    if args.end is not None and args.end <= args.start:
        parser.error("--end 必须大于 --start")
    if not args.video.exists():
        parser.error(f"视频不存在：{args.video}")

    config = load_replay_config(args.config, args.config_mode)
    config.recognition_zoom = args.recognition_zoom
    old_engine = GestureEngine(config)
    new_engine = GestureEngine(config)
    model_buffer = Path("gesture_mouse/models/hand_landmarker.task").read_bytes()
    options = vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_buffer=model_buffer),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=config.min_detection_confidence,
        min_hand_presence_confidence=config.min_presence_confidence,
        min_tracking_confidence=config.min_tracking_confidence,
    )

    capture = cv2.VideoCapture(str(args.video))
    if not capture.isOpened():
        raise RuntimeError(f"无法打开视频：{args.video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    if fps <= 0:
        raise RuntimeError("视频没有有效帧率")
    sample_every = max(1, round(fps / args.sample_hz))
    start_frame = max(0, round(args.start * fps))
    end_frame = (
        round(args.end * fps)
        if args.end is not None
        else int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    )

    rows: list[dict[str, object]] = []
    state_old: Counter[str] = Counter()
    state_new: Counter[str] = Counter()
    commands_old: Counter[str] = Counter()
    commands_new: Counter[str] = Counter()
    detected = 0
    frame_index = -1
    last_timestamp_ms = -1

    try:
        with vision.HandLandmarker.create_from_options(options) as landmarker:
            while True:
                ok = capture.grab()
                if not ok:
                    break
                frame_index += 1
                if frame_index < start_frame:
                    continue
                if end_frame and frame_index >= end_frame:
                    break
                if (frame_index - start_frame) % sample_every:
                    continue
                ok, frame = capture.retrieve()
                if not ok or frame is None:
                    continue

                video_seconds = frame_index / fps
                timestamp_ms = max(last_timestamp_ms + 1, round(video_seconds * 1000))
                last_timestamp_ms = timestamp_ms
                timestamp_ns = timestamp_ms * 1_000_000
                frame = crop_frame(frame, args.crop)
                recognition_frame, transform = prepare_recognition_frame(
                    frame,
                    config.recognition_zoom,
                )
                rgb = cv2.cvtColor(recognition_frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=np.ascontiguousarray(rgb),
                )
                result = landmarker.detect_for_video(image, timestamp_ms)
                observation = None
                if result.hand_landmarks:
                    hand_points = result.hand_landmarks[0]
                    category = result.handedness[0][0] if result.handedness else None
                    points = tuple(
                        transform.restore(
                            Landmark(float(point.x), float(point.y), float(point.z)),
                        )
                        for point in hand_points
                    )
                    observation = HandObservation(
                        landmarks=points,
                        handedness=category.category_name if category else "",
                        timestamp_ns=timestamp_ns,
                        inference_ms=0.0,
                        handedness_score=float(category.score) if category else 0.0,
                    )
                    detected += 1

                old = process_engine(
                    old_engine,
                    observation,
                    timestamp_ns,
                    legacy=True,
                )
                new = process_engine(
                    new_engine,
                    observation,
                    timestamp_ns,
                    legacy=False,
                )
                old_text = command_text(old)
                new_text = command_text(new)
                state_old[old_engine.current_gesture.value] += 1
                state_new[new_engine.current_gesture.value] += 1
                if old_text:
                    commands_old[old_text] += 1
                if new_text:
                    commands_new[new_text] += 1
                metrics = geometry(observation.landmarks if observation else ())
                rows.append(
                    {
                        "video_time_s": f"{video_seconds:.3f}",
                        "detected": observation is not None,
                        **{key: f"{value:.4f}" for key, value in metrics.items()},
                        "old_state": old_engine.current_gesture.value,
                        "new_state": new_engine.current_gesture.value,
                        "right_ready": new_engine._right_ready,
                        "right_open_ratio": f"{new_engine._right_open_ratio:.4f}",
                        "right_requires_reach": (
                            new_engine._right_requires_middle_reach
                        ),
                        "right_active": new_engine._right_active,
                        "left_active": new_engine._left_active,
                        "left_rearm_required": new_engine._left_rearm_required,
                        "rotation_tilt_anchor": (
                            ""
                            if new_engine._rotation_tilt_anchor is None
                            else f"{new_engine._rotation_tilt_anchor:.4f}"
                        ),
                        "rotation_scroll_active": (
                            new_engine._rotation_scroll_active
                        ),
                        "rotation_projection_guard_active": (
                            new_engine._rotation_projection_guard_active
                        ),
                        "rotation_last_open_age_ms": (
                            ""
                            if new_engine._rotation_last_open_ns is None
                            else f"{(timestamp_ns - new_engine._rotation_last_open_ns) / 1_000_000:.1f}"
                        ),
                        "pointer_tilt_anchor": (
                            ""
                            if new_engine._pointer_tilt_anchor is None
                            else f"{new_engine._pointer_tilt_anchor:.4f}"
                        ),
                        "pointer_rotation_active": (
                            new_engine._pointer_rotation_active
                        ),
                        "old_commands": old_text,
                        "new_commands": new_text,
                    },
                )
    finally:
        capture.release()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)

    summary = {
        "video": str(args.video.resolve()),
        "crop": args.crop,
        "start_s": args.start,
        "end_s": args.end,
        "source_fps": fps,
        "sample_hz": fps / sample_every,
        "config_path": str(args.config.resolve()) if args.config else None,
        "config_mode": args.config_mode,
        "pinch_thresholds": {
            "engage": config.pinch_engage,
            "release": config.pinch_release,
            "arm": config.pinch_arm,
        },
        "samples": len(rows),
        "detected_samples": detected,
        "detection_rate_percent": round(100 * detected / max(1, len(rows)), 2),
        "old_states": dict(state_old),
        "new_states": dict(state_new),
        "old_commands": dict(commands_old),
        "new_commands": dict(commands_new),
        "changed_samples": sum(
            1
            for row in rows
            if row["old_state"] != row["new_state"]
            or row["old_commands"] != row["new_commands"]
        ),
    }
    summary_path = args.summary or args.output.with_suffix(".json")
    if summary_path.resolve() == args.output.resolve():
        summary_path = args.output.with_name(
            f"{args.output.stem}.summary.json",
        )
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
