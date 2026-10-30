import math
import os
import threading

import dearpygui.dearpygui as dpg
import dora
import pyarrow as pa

ALL_ARMS = ("right", "left")
PAD = 300                 # パッドの一辺(px)
REACH = 0.25              # パッド端 = 基準位置から何m動かすか
Z_RANGE = 0.20            # zの可動範囲(±m)
Z_SPEED = 0.10            # 上下キー押下中のz速度(m/s)
Z_WHEEL_STEP = 0.01       # 右クリック+ホイール1ノッチあたりのz変化(m)
Z_WHEEL_SIGN = 1.0        # ホイールの向きが逆なら -1.0
SMOOTH = 0.2              # 1 tickあたりの目標への追従率(0〜1、小さいほど滑らか)
GRIP_STEP = 0.05          # ホイール1ノッチあたり(rad)
GRIP_RANGE = {"right": (-math.pi / 4, 0.0), "left": (0.0, math.pi / 4)}
GRIP_SIGN = {"right": -1.0, "left": 1.0}  # ホイール上回しで両腕とも0から離れる向き


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _pose_to_list(value):
    first = value.to_pylist()[0]
    return list(first["pose"]) if isinstance(first, dict) else list(value.to_pylist())


def _target(pose):
    return pa.array(
        [{"pose": [float(v) for v in pose]}],
        type=pa.struct([("pose", pa.list_(pa.float32()))]),
    )


def _new_arm():
    return {"base": None, "home": None, "nx": 0.0, "ny": 0.0, "dz": 0.0,
            "grip": 0.0, "cur": [0.0, 0.0, 0.0]}


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
            pose = _pose_to_list(event["value"])
            with lock:
                state["poses"][side] = pose
                arm = state["arms"][side]
                if arm["home"] is None:
                    arm["home"] = list(pose)
                if arm["base"] is None:
                    arm["base"] = list(pose)
                    arm["grip"] = pose[7]

        elif eid == "phone_sides":
            txt = event["value"].to_pylist()[0] or ""
            phone = {s for s in txt.split(",") if s}
            new = tuple(s for s in ALL_ARMS if s not in phone)
            with lock:
                old = state["marms"]
                if new != old:
                    for s in new:
                        if s in old:
                            continue
                        # スマホから戻ってきた腕: 現在姿勢から再スタート
                        arm = state["arms"][s]
                        pose = state["poses"].get(s)
                        arm["nx"] = arm["ny"] = arm["dz"] = 0.0
                        arm["cur"] = [0.0, 0.0, 0.0]
                        if pose is not None:
                            arm["base"] = list(pose)
                            arm["grip"] = pose[7]
                    state["marms"] = new
                    if state["active"] not in new:
                        state["active"] = new[0] if new else None
                    state["dirty"] = True

        elif eid == "tick":
            outs = {}
            with lock:
                marms = state["marms"]
                if marms and all(state["arms"][s]["base"] is not None for s in marms):
                    for side in marms:
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
    marms = tuple(s for s in os.environ.get("MOUSE_ARMS", "right,left").split(",")
                  if s in ALL_ARMS)
    state = {
        "active": marms[0] if marms else None,
        "marms": marms,
        "reset": 0,
        "dirty": False,
        "poses": {},
        "arms": {s: _new_arm() for s in ALL_ARMS},
    }
    lock = threading.Lock()

    dpg.create_context()

    def refresh():
        with lock:
            active = state["active"]
            marms = state["marms"]
            arm = state["arms"][active] if active else None
            nx, ny, dz, grip = ((arm["nx"], arm["ny"], arm["dz"], arm["grip"])
                                if arm else (0.0, 0.0, 0.0, 0.0))
        dpg.configure_item("dot", center=(PAD / 2 + nx * PAD / 2, PAD / 2 + ny * PAD / 2))
        dpg.set_value("zslider", dz)
        dpg.set_value("griptext", f"gripper: {grip:.2f}")
        if active:
            tail = "  (←→で切替)" if len(marms) > 1 else ""
            dpg.set_value("activetext", f"マウスの腕: {active}{tail}")
        else:
            dpg.set_value("activetext", "マウスの腕: なし(両腕スマホ担当)")

    def on_move(_s, _a):
        if not dpg.is_mouse_button_down(dpg.mvMouseButton_Left):
            return
        if not dpg.is_item_hovered("pad"):
            return
        mx, my = dpg.get_drawing_mouse_pos()
        nx = _clamp((mx - PAD / 2) / (PAD / 2), -1.0, 1.0)
        ny = _clamp((my - PAD / 2) / (PAD / 2), -1.0, 1.0)
        with lock:
            side = state["active"]
            if side is None:
                return
            arm = state["arms"][side]
            arm["nx"], arm["ny"] = nx, ny
        dpg.configure_item("dot", center=(PAD / 2 + nx * PAD / 2, PAD / 2 + ny * PAD / 2))

    def on_wheel(_s, delta):
        z_mode = dpg.is_mouse_button_down(dpg.mvMouseButton_Left)
        with lock:
            side = state["active"]
            if side is None:
                return
            arm = state["arms"][side]
            if z_mode:   # 右クリック+ホイール = z
                arm["dz"] = _clamp(arm["dz"] + Z_WHEEL_SIGN * delta * Z_WHEEL_STEP,
                                   -Z_RANGE, Z_RANGE)
            else:        # ホイールのみ = グリッパ
                lo, hi = GRIP_RANGE[side]
                arm["grip"] = _clamp(arm["grip"] + delta * GRIP_STEP * GRIP_SIGN[side], lo, hi)
            dz, g = arm["dz"], arm["grip"]
        dpg.set_value("zslider", dz)
        dpg.set_value("griptext", f"gripper: {g:.2f}")

    def move_z(sign):
        dt = dpg.get_delta_time()
        with lock:
            side = state["active"]
            if side is None:
                return
            arm = state["arms"][side]
            arm["dz"] = _clamp(arm["dz"] + sign * Z_SPEED * dt, -Z_RANGE, Z_RANGE)
            dz = arm["dz"]
        dpg.set_value("zslider", dz)

    def on_z_slider(_s, v):
        with lock:
            side = state["active"]
            if side is not None:
                state["arms"][side]["dz"] = float(v)

    def select(side):
        with lock:
            if side not in state["marms"]:
                return
            state["active"] = side
        refresh()

    def on_reset():
        # 起動時の位置・向きへ戻す(今の目標からなめらかに)
        with lock:
            side = state["active"]
            if side is None:
                return
            arm = state["arms"][side]
            if arm["home"] is not None and arm["base"] is not None:
                for i in range(3):
                    arm["cur"][i] += arm["base"][i] - arm["home"][i]
                arm["base"] = list(arm["home"])
            arm["nx"] = arm["ny"] = arm["dz"] = 0.0
        refresh()

    with dpg.handler_registry():
        dpg.add_mouse_move_handler(callback=on_move)
        dpg.add_mouse_wheel_handler(callback=on_wheel)
        dpg.add_key_down_handler(key=dpg.mvKey_Up, callback=lambda *_: move_z(+1))
        dpg.add_key_down_handler(key=dpg.mvKey_Down, callback=lambda *_: move_z(-1))
        dpg.add_key_press_handler(key=dpg.mvKey_Left, callback=lambda *_: select("left"))
        dpg.add_key_press_handler(key=dpg.mvKey_Right, callback=lambda *_: select("right"))
        dpg.add_key_press_handler(key=dpg.mvKey_R, callback=lambda *_: state.__setitem__("reset", 1))

    with dpg.window(tag="primary", label="OpenArm mouse teleop"):
        dpg.add_text("", tag="activetext")
        dpg.add_text("ドラッグ=x/y  ホイール=グリッパ  左クリック+ホイール=z")
        with dpg.drawlist(width=PAD, height=PAD, tag="pad"):
            dpg.draw_rectangle((0, 0), (PAD, PAD), color=(150, 150, 150, 255))
            dpg.draw_circle((PAD / 2, PAD / 2), 6, color=(255, 80, 80, 255),
                            fill=(255, 80, 80, 255), tag="dot")
        dpg.add_slider_float(tag="zslider", label="z", min_value=-Z_RANGE,
                             max_value=Z_RANGE, default_value=0.0, width=PAD,
                             callback=on_z_slider)
        dpg.add_text("gripper: --", tag="griptext")
        dpg.add_button(label="reset(操作中の腕)", callback=on_reset)
        dpg.add_text("R: 箱をリセット  ↑↓: z")

    dpg.create_viewport(title="OpenArm mouse teleop", width=380, height=520)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("primary", True)
    refresh()

    threading.Thread(target=_dora_loop, args=(state, lock), daemon=True).start()

    while dpg.is_dearpygui_running():
        with lock:
            dirty = state["dirty"]
            state["dirty"] = False
        if dirty:
            refresh()
        dpg.render_dearpygui_frame()
    dpg.destroy_context()


if __name__ == "__main__":
    main()