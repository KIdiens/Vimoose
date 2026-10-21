import json

from gesture_mouse.config import AppConfig, ConfigStore, CONFIG_VERSION


def test_unknown_fields_are_ignored_and_values_are_clamped(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "version": 0,
                "camera_fps": 999,
                "recognition_zoom": 9,
                "ema_alpha": -1,
                "pinch_engage": 0.4,
                "pinch_release": 0.3,
                "pinch_arm": 0.1,
                "right_pinch_approach_delta": 9,
                "palm_rotation_threshold": 0,
                "unknown": "ignored",
            },
        ),
        encoding="utf-8",
    )

    config = ConfigStore(path).load()

    assert config.version == CONFIG_VERSION
    assert config.camera_fps == 60
    assert config.recognition_zoom == 1.35
    assert config.ema_alpha == 0.05
    assert config.pinch_release >= config.pinch_engage + 0.02
    assert config.pinch_arm >= config.pinch_release + 0.05
    assert config.right_pinch_approach_delta == 0.60
    assert config.palm_rotation_threshold == 0.08


def test_version_one_defaults_migrate_to_more_forgiving_recognition(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "handedness": "Right",
                "min_detection_confidence": 0.55,
                "min_presence_confidence": 0.55,
                "min_tracking_confidence": 0.55,
                "pinch_engage": 0.36,
                "pinch_release": 0.48,
            },
        ),
        encoding="utf-8",
    )

    config = ConfigStore(path).load()

    assert config.version == CONFIG_VERSION
    assert config.handedness == "Any"
    assert config.min_detection_confidence == 0.40
    assert config.min_presence_confidence == 0.35
    assert config.min_tracking_confidence == 0.40
    assert config.pinch_engage == 0.42
    assert config.pinch_release == 0.55
    assert config.recognition_zoom == 1.15


def test_save_and_reload_round_trip(tmp_path) -> None:
    path = tmp_path / "config.json"
    store = ConfigStore(path)
    config = AppConfig(camera_index=2, handedness="Left")
    store.save(config)

    loaded = store.load()

    assert loaded.camera_index == 2
    assert loaded.handedness == "Left"


def test_non_object_json_config_falls_back_to_defaults(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text("[]", encoding="utf-8")

    loaded = ConfigStore(path).load()

    assert loaded == AppConfig()


def test_default_store_migrates_legacy_gesturepilot_config(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    legacy = tmp_path / "GesturePilot" / "config.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps({"version": 7, "camera_index": 3, "handedness": "Left"}),
        encoding="utf-8",
    )

    loaded = ConfigStore().load()

    migrated = tmp_path / "Vimoose" / "config.json"
    assert loaded.camera_index == 3
    assert loaded.handedness == "Left"
    assert migrated.exists()


def test_version_four_default_partial_tracking_limit_migrates_to_quality_based() -> None:
    config = AppConfig.from_mapping(
        {
            "version": 4,
            "partial_tracking_frames": 8,
        },
    )

    assert config.version == CONFIG_VERSION
    assert config.partial_tracking_frames == 0


def test_custom_partial_tracking_limit_is_preserved_during_migration() -> None:
    config = AppConfig.from_mapping(
        {
            "version": 4,
            "partial_tracking_frames": 120,
        },
    )

    assert config.partial_tracking_frames == 120


def test_version_five_receives_safe_right_pinch_and_rotation_defaults() -> None:
    config = AppConfig.from_mapping(
        {
            "version": 5,
            "pinch_engage": 0.42,
        },
    )

    assert config.version == CONFIG_VERSION
    assert config.right_pinch_approach_delta == 0.22
    assert config.rotation_gestures_enabled is True
    assert config.palm_rotation_threshold == 0.18


def test_version_six_receives_video_feedback_defaults() -> None:
    config = AppConfig.from_mapping(
        {
            "version": 6,
            "drag_hold_ms": 300,
            "pointer_margin_x": 0.12,
            "pointer_margin_y": 0.10,
        },
    )

    assert config.version == CONFIG_VERSION
    assert config.drag_hold_ms == 2000
    assert config.pointer_margin_x == 0.20
    assert config.pointer_margin_y == 0.16
    assert config.cursor_snap_enabled is True
    assert config.cursor_snap_radius_px == 30


def test_version_seven_default_drag_wait_migrates_to_two_seconds() -> None:
    config = AppConfig.from_mapping(
        {
            "version": 7,
            "drag_hold_ms": 5000,
        },
    )

    assert config.version == CONFIG_VERSION
    assert config.drag_hold_ms == 2000


def test_loading_old_config_persists_migrated_version_and_drag_wait(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"version": 7, "drag_hold_ms": 5000}),
        encoding="utf-8",
    )

    loaded = ConfigStore(path).load()
    persisted = json.loads(path.read_text(encoding="utf-8"))

    assert loaded.version == CONFIG_VERSION
    assert loaded.drag_hold_ms == 2000
    assert persisted["version"] == CONFIG_VERSION
    assert persisted["drag_hold_ms"] == 2000


def test_version_eight_caps_old_palm_width_calibration_thresholds() -> None:
    """0.8.1前的高阈值来自旧掌宽尺度，不能直接用于稳健尺度。"""

    config = AppConfig.from_mapping(
        {
            "version": 8,
            "pinch_engage": 0.68,
            "pinch_release": 0.90,
            "pinch_arm": 1.07,
            "pointer_stability": 0.70,
        },
    )

    assert config.version == CONFIG_VERSION
    assert config.pinch_engage == 0.42
    assert config.pinch_release == 0.55
    assert config.pinch_arm == 0.72
    assert config.pointer_stability == 0.70


def test_version_nine_preserves_new_scale_custom_thresholds() -> None:
    config = AppConfig.from_mapping(
        {
            "version": 9,
            "pinch_engage": 0.50,
            "pinch_release": 0.66,
            "pinch_arm": 0.84,
        },
    )

    assert config.version == CONFIG_VERSION
    assert config.pinch_engage == 0.50
    assert config.pinch_release == 0.66
    assert config.pinch_arm == 0.84
