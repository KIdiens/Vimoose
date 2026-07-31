from gesture_mouse.cursor_snap import (
    CursorSnapService,
    MagneticSnapState,
    SnapCandidate,
    WindowsUiAutomationProbe,
)


class FakeProbe:
    def __init__(self, candidate: SnapCandidate | None) -> None:
        self.candidate = candidate
        self.requests: list[tuple[int, int, int]] = []

    def initialize(self) -> None:
        pass

    def close(self) -> None:
        pass

    def find_target(
        self,
        x: int,
        y: int,
        radius_px: int,
    ) -> SnapCandidate | None:
        self.requests.append((x, y, radius_px))
        return self.candidate


class FakeRectangle:
    def __init__(self, left: int, top: int, right: int, bottom: int) -> None:
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


class FakeControl:
    def __init__(
        self,
        control_type: int,
        name: str,
        rect: tuple[int, int, int, int],
        clickable: tuple[int, int],
        control_type_name: str,
    ) -> None:
        self.ControlType = control_type
        self.Name = name
        self.BoundingRectangle = FakeRectangle(*rect)
        self.IsEnabled = True
        self.IsOffscreen = False
        self.ControlTypeName = control_type_name
        self._clickable = clickable

    def GetClickablePoint(self) -> tuple[int, int, bool]:
        return (*self._clickable, True)

    def GetParentControl(self) -> None:
        return None


class FakeAutomation:
    def __init__(self, tab: FakeControl, close_button: FakeControl) -> None:
        self.tab = tab
        self.close_button = close_button

    def ControlFromPoint(self, x: int, _y: int) -> FakeControl:
        return self.close_button if x >= 733 else self.tab


def button_candidate() -> SnapCandidate:
    return SnapCandidate(
        x=950,
        y=20,
        left=930,
        top=0,
        right=970,
        bottom=40,
        name="关闭",
        control_type="ButtonControl",
    )


def tab_candidate() -> SnapCandidate:
    return SnapCandidate(
        x=665,
        y=26,
        left=560,
        top=0,
        right=773,
        bottom=52,
        name="浏览器标签页",
        control_type="TabItemControl",
    )


def test_magnetic_state_latches_to_clickable_point_near_button_edge() -> None:
    state = MagneticSnapState(radius_px=30)

    x, y, snapped = state.resolve(920, 20, button_candidate())

    assert (x, y, snapped) == (950, 20, True)
    assert state.target_name == "关闭"


def test_magnetic_state_releases_after_pointer_leaves_release_zone() -> None:
    state = MagneticSnapState(radius_px=30, release_multiplier=1.8)
    state.resolve(920, 20, button_candidate())

    x, y, snapped = state.resolve(800, 200, None)

    assert (x, y, snapped) == (800, 200, False)
    assert state.target_name is None


def test_tab_item_does_not_capture_pointer_near_its_close_button() -> None:
    state = MagneticSnapState(radius_px=30)

    x, y, snapped = state.resolve(750, 20, tab_candidate())

    assert (x, y, snapped) == (750, 20, False)
    assert state.target_name is None


def test_pointer_can_leave_tab_center_and_snap_to_close_button() -> None:
    state = MagneticSnapState(radius_px=30, release_multiplier=1.8)
    close_button = SnapCandidate(
        x=743,
        y=25,
        left=733,
        top=15,
        right=753,
        bottom=35,
        name="关闭标签页",
        control_type="ButtonControl",
    )
    assert state.resolve(665, 26, tab_candidate()) == (665, 26, True)

    x, y, snapped = state.resolve(750, 20, close_button)

    assert (x, y, snapped) == (743, 25, True)
    assert state.target_name == "关闭标签页"


def test_windows_probe_ignores_tab_background_and_finds_close_child() -> None:
    tab = FakeControl(
        50019,
        "浏览器标签页",
        (560, 0, 773, 52),
        (665, 26),
        "TabItemControl",
    )
    close_button = FakeControl(
        50000,
        "关闭标签页",
        (733, 15, 753, 35),
        (743, 25),
        "ButtonControl",
    )
    probe = WindowsUiAutomationProbe()
    probe._auto = FakeAutomation(tab, close_button)

    candidate = probe.find_target(720, 20, 30)

    assert candidate is not None
    assert candidate.name == "关闭标签页"
    assert candidate.control_type == "ButtonControl"
    assert (candidate.x, candidate.y) == (743, 25)


def test_snap_service_converts_between_normalized_and_physical_coordinates() -> None:
    probe = FakeProbe(button_candidate())
    service = CursorSnapService(
        probe,
        screen_width=1000,
        screen_height=500,
        enabled=True,
        radius_px=30,
        start_worker=False,
    )
    try:
        raw = service.transform(0.92, 0.04)
        service.refresh_once()
        snapped = service.transform(0.92, 0.04)
    finally:
        service.shutdown()

    assert raw == (0.92, 0.04)
    assert abs(snapped[0] - 950 / 999) < 1e-9
    assert abs(snapped[1] - 20 / 499) < 1e-9
    assert service.target_name == "关闭"
    assert probe.requests[-1] == (919, 20, 30)


def test_disabled_snap_service_never_calls_probe() -> None:
    probe = FakeProbe(button_candidate())
    service = CursorSnapService(
        probe,
        screen_width=1000,
        screen_height=500,
        enabled=False,
        radius_px=30,
        start_worker=False,
    )
    try:
        assert service.transform(0.5, 0.5) == (0.5, 0.5)
        service.refresh_once()
    finally:
        service.shutdown()

    assert probe.requests == []
