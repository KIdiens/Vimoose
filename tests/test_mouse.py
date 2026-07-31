from gesture_mouse.contracts import MouseCommand, MouseCommandType
from gesture_mouse.mouse import MouseController, NullMouseBackend


def test_controller_dispatches_without_system_injection() -> None:
    backend = NullMouseBackend()
    controller = MouseController(backend)
    controller.execute_many(
        [
            MouseCommand(MouseCommandType.MOVE, 1, x=0.25, y=0.75),
            MouseCommand(MouseCommandType.LEFT_DOWN, 2),
            MouseCommand(MouseCommandType.LEFT_UP, 3),
            MouseCommand(MouseCommandType.WHEEL, 4, delta=120),
            MouseCommand(MouseCommandType.PAGE_NEXT, 5),
            MouseCommand(MouseCommandType.PAGE_PREVIOUS, 6),
        ],
    )

    assert [name for name, _ in backend.commands] == [
        "move",
        "left_down",
        "left_up",
        "wheel",
        "page_next",
        "page_previous",
    ]
