import math
import threading

import dearpygui.dearpygui as dpg
import dora
import pyarrow as pa

ARMS = ("right", "left")
PAD = 300                 # パッドの一辺(px)
REACH = 0.25              # パッド端 = 基準位置から何m動かすか
Z_RANGE = 0.20            # zの可動範囲(±m)
Z_SPEED = 0.10            # 上下キー押下中のz速度(m/s)
SMOOTH = 0.2              # 1 tickあたりの目標への追従率(0〜1、小さいほど滑らか)
GRIP_STEP = 0.05          # ホイール1ノッチあたり(rad)
GRIP_RANGE = {"right": (-math.pi / 4, 0.0), "left": (0.0, math.pi / 4)}
GRIP_SIGN = {"right": -1.0, "left": 1.0}  # ホイール上回しで両腕とも0から離れる向き
# Z_WHEEL_STEP = 0.01   # ホイール1ノッチあたりのz変化(m)
# Z_MIN = -Z_RANGE           # zの下限(= home)。-Z_RANGE にすると元どおり
# WHEEL_SIGN = 1.0      # ホイールの向きが逆なら -1.0
# GRIP_SPEED = 0.40     # ↑↓キー押下中のグリッパ速度(rad/s)

def _pose_to_list(value):
    first = value.to_pylist()[0]
    return list(first["pose"]) if isinstance(first, dict) else list(value.to_pylist())


def _target(pose):
    return pa.array(
        [{"pose": [float(v) for v in pose]}],
        type=pa.struct([("pose", pa.list_(pa.float32()))]),
    )


def _new_arm():
    return {"base": None, "nx": 0.0, "ny": 0.0, "dz": 0.0, "grip": 0.0,
            "cur": [0.0, 0.0, 0.0]}


def _dora_loop(state, lock):
    node = dora.Node()
    node.send_output("status", pa.array(["ready"]))
    for event in node:
        if event["type"] == "STOP":
            break
        if event["type"] != "INPUT":
            continue
        eid = event["id"]
        if eid in ("pose_right", "pose_left"):
            side = eid.split("_")[1]
            with lock:
                arm = state["arms"][side]
                if arm["base"] is None:
                    arm["base"] = _pose_to_list(event["value"])
                    arm["grip"] = arm["base"][7]
        elif eid == "tick":
            outs = {}
            with lock:
                if any(state["arms"][s]["base"] is None for s in ARMS):
                    continue
                for side in ARMS:
                    arm = state["arms"][side]
                    goal = (-arm["ny"] * REACH, -arm["nx"] * REACH, arm["dz"])
                    for i in range(3):
                        arm["cur"][i] += (goal[i] - arm["cur"][i]) * SMOOTH
                    pose = list(arm["base"])
                    for i in range(3):
                        pose[i] += arm["cur"][i]
                    pose[7] = arm["grip"]
                    outs[side] = pose
            for side, pose in outs.items():
                node.send_output(f"target_{side}", _target(pose))

            with lock:
                req = state["reset"]
                if req:
                    state["reset"] = 2 if req == 1 else 0
            if req:
                node.send_output("button_x", pa.array([req == 1]))            


def main():
    state = {"active": "right", "reset": 0, "arms": {s: _new_arm() for s in ARMS}}
    lock = threading.Lock()

    dpg.create_context()

    def refresh():
        with lock:
            active = state["active"]
            arm = state["arms"][active]
            nx, ny, dz, grip = arm["nx"], arm["ny"], arm["dz"], arm["grip"]
        dpg.configure_item("dot", center=(PAD / 2 + nx * PAD / 2, PAD / 2 + ny * PAD / 2))
        dpg.set_value("zslider", dz)
        dpg.set_value("griptext", f"gripper: {grip:.2f}")
        dpg.set_value("activetext", f"操作中の腕: {active}  (←→で切替 / ↑↓でz)")

    def on_move(_s, _a):
        if not dpg.is_mouse_button_down(dpg.mvMouseButton_Left):
            return
        if not dpg.is_item_hovered("pad"):
            return
        mx, my = dpg.get_drawing_mouse_pos()
        nx = max(-1.0, min(1.0, (mx - PAD / 2) / (PAD / 2)))
        ny = max(-1.0, min(1.0, (my - PAD / 2) / (PAD / 2)))
        with lock:
            arm = state["arms"][state["active"]]
            arm["nx"], arm["ny"] = nx, ny
        dpg.configure_item("dot", center=(PAD / 2 + nx * PAD / 2, PAD / 2 + ny * PAD / 2))

    def on_wheel(_s, delta):
        with lock:
            side = state["active"]
            arm = state["arms"][side]
            lo, hi = GRIP_RANGE[side]
            arm["grip"] = max(lo, min(hi, arm["grip"] + delta * GRIP_STEP * GRIP_SIGN[side]))
            g = arm["grip"]
        dpg.set_value("griptext", f"gripper: {g:.2f}")

    def move_z(sign):
        dt = dpg.get_delta_time()
        with lock:
            arm = state["arms"][state["active"]]
            arm["dz"] = max(-Z_RANGE, min(Z_RANGE, arm["dz"] + sign * Z_SPEED * dt))
            dz = arm["dz"]
        dpg.set_value("zslider", dz)

    # def on_wheel(_s, delta):
    #     with lock:
    #         arm = state["arms"][state["active"]]
    #         arm["dz"] = max(Z_MIN, min(Z_RANGE, arm["dz"] + WHEEL_SIGN * delta * Z_WHEEL_STEP))
    #         dz = arm["dz"]
    #     dpg.set_value("zslider", dz)

    # def move_grip(sign):
    #     dt = dpg.get_delta_time()
    #     with lock:
    #         side = state["active"]
    #         arm = state["arms"][side]
    #         lo, hi = GRIP_RANGE[side]
    #         arm["grip"] = max(lo, min(hi, arm["grip"] + sign * GRIP_SPEED * dt * GRIP_SIGN[side]))
    #         g = arm["grip"]
    #     dpg.set_value("griptext", f"gripper: {g:.2f}")

    def on_z_slider(_s, v):
        with lock:
            state["arms"][state["active"]]["dz"] = float(v)

    def select(side):
        with lock:
            state["active"] = side
        refresh()

    def on_reset():
        with lock:
            arm = state["arms"][state["active"]]
            arm["nx"] = arm["ny"] = arm["dz"] = 0.0
        refresh()

    with dpg.handler_registry():
        dpg.add_mouse_move_handler(callback=on_move)
        dpg.add_mouse_wheel_handler(callback=on_wheel)
        dpg.add_key_down_handler(key=dpg.mvKey_Up, callback=lambda *_: move_z(+1))
        dpg.add_key_down_handler(key=dpg.mvKey_Down, callback=lambda *_: move_z(-1))
        # dpg.add_key_down_handler(key=dpg.mvKey_Up, callback=lambda *_: move_grip(+1))
        # dpg.add_key_down_handler(key=dpg.mvKey_Down, callback=lambda *_: move_grip(-1))    
        
        dpg.add_key_press_handler(key=dpg.mvKey_Left, callback=lambda *_: select("left"))
        dpg.add_key_press_handler(key=dpg.mvKey_Right, callback=lambda *_: select("right"))
        dpg.add_key_press_handler(key=dpg.mvKey_R, callback=lambda *_: state.__setitem__("reset", 1))

    with dpg.window(tag="primary", label="OpenArm mouse teleop"):
        dpg.add_text("", tag="activetext")
        dpg.add_text("パッドをドラッグ = 手先のx/y、ホイール = グリッパ")
        with dpg.drawlist(width=PAD, height=PAD, tag="pad"):
            dpg.draw_rectangle((0, 0), (PAD, PAD), color=(150, 150, 150, 255))
            dpg.draw_circle((PAD / 2, PAD / 2), 6, color=(255, 80, 80, 255),
                            fill=(255, 80, 80, 255), tag="dot")
        dpg.add_slider_float(tag="zslider", label="z", min_value=-Z_RANGE,
                             max_value=Z_RANGE, default_value=0.0, width=PAD,
                             callback=on_z_slider)
        dpg.add_text("gripper: --", tag="griptext")
        dpg.add_button(label="reset(操作中の腕)", callback=on_reset)
        dpg.add_text("R: 箱をリセット")

    dpg.create_viewport(title="OpenArm mouse teleop", width=380, height=520)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("primary", True)
    refresh()

    threading.Thread(target=_dora_loop, args=(state, lock), daemon=True).start()
    dpg.start_dearpygui()
    dpg.destroy_context()


if __name__ == "__main__":
    main()