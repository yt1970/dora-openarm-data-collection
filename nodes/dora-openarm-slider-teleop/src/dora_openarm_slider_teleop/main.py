import math
import threading
from dataclasses import dataclass

import dearpygui.dearpygui as dpg
import dora
import numpy as np
import pyarrow as pa


@dataclass(frozen=True)
class JointSpec:
    name: str
    lo: float
    hi: float
    home: float


# Ranges match openarm_v20_bimanual.xml ctrlrange; home values match the
# "home" keyframe in cell.xml (used by the demo scene).
# Note left/right asymmetry on J1, J2, and gripper.
HALF_PI = math.pi / 2
QUARTER_PI = math.pi / 4
JOINT_SPECS: dict[str, list[JointSpec]] = {
    "right": [
        JointSpec("J1",   -1.39626,    3.49066,   0.0),
        JointSpec("J2",   -0.174533,   3.31613,   0.0),
        JointSpec("J3",   -1.5708,     1.5708,    0.0),
        JointSpec("J4",    0.0,        2.44346,   HALF_PI),
        JointSpec("J5",   -1.5708,     1.5708,    0.0),
        JointSpec("J6",   -0.785398,   0.785398,  0.0),
        JointSpec("J7",   -1.5708,     1.5708,    0.0),
        JointSpec("grip", -QUARTER_PI, 0.0,       0.0),
    ],
    "left": [
        JointSpec("J1",   -3.49066,    1.39626,   0.0),
        JointSpec("J2",   -3.31613,    0.174533,  0.0),
        JointSpec("J3",   -1.5708,     1.5708,    0.0),
        JointSpec("J4",    0.0,        2.44346,   HALF_PI),
        JointSpec("J5",   -1.5708,     1.5708,    0.0),
        JointSpec("J6",   -0.785398,   0.785398,  0.0),
        JointSpec("J7",   -1.5708,     1.5708,    0.0),
        JointSpec("grip",  0.0,        QUARTER_PI, 0.0),
    ],
}


def _initial_state() -> dict[str, list[float]]:
    return {side: [s.home for s in specs] for side, specs in JOINT_SPECS.items()}


def _build_ui(state: dict, lock: threading.Lock) -> None:
    dpg.create_context()

    def make_callback(side: str, idx: int):
        def _cb(_sender, app_data, _user_data):
            with lock:
                state[side][idx] = float(app_data)
        return _cb

    with dpg.window(tag="primary", label="OpenArm keyboard slider teleop"):
        with dpg.group(horizontal=True):
            for side in ("left", "right"):
                with dpg.child_window(width=340, height=440):
                    dpg.add_text(f"{side} arm")
                    dpg.add_separator()
                    for i, spec in enumerate(JOINT_SPECS[side]):
                        dpg.add_slider_float(
                            label=spec.name,
                            min_value=spec.lo,
                            max_value=spec.hi,
                            default_value=spec.home,
                            width=240,
                            callback=make_callback(side, i),
                        )

    dpg.create_viewport(title="OpenArm slider teleop", width=720, height=500)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("primary", True)

def _dora_loop(state: dict, lock: threading.Lock) -> None:
    node = dora.Node()
    node.send_output("status", pa.array(["ready"]))

    for event in node:
        if event["type"] == "STOP":
            break
        if event["type"] != "INPUT" or event["id"] != "tick":
            continue

        with lock:
            right = np.array(state["right"], dtype=np.float32)
            left = np.array(state["left"], dtype=np.float32)

        node.send_output("position_right", pa.array(right, type=pa.float32()))
        node.send_output("position_left", pa.array(left, type=pa.float32()))


def main() -> None:
    """Run Dear PyGui on the main thread and dora in a worker thread."""
    state = _initial_state()
    lock = threading.Lock()

    _build_ui(state, lock)

    worker = threading.Thread(target=_dora_loop, args=(state, lock), daemon=True)
    worker.start()

    dpg.start_dearpygui()
    dpg.destroy_context()


if __name__ == "__main__":
    main()