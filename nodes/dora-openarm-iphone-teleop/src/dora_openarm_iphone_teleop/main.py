import json
import math
import os
import socket
import threading
import time

import dora
import numpy as np
import pyarrow as pa
from scipy.spatial.transform import Rotation as R
from scipy.spatial.transform import Slerp

SIDES = ("right", "left")
PORT = int(os.environ.get("IPHONE_PORT", "5007"))
POS_SCALE = float(os.environ.get("IPHONE_POS_SCALE", "1.0"))  # iPhone 1m = ロボット何m
SMOOTH = float(os.environ.get("IPHONE_SMOOTH", "0.3"))        # 1 tickあたりの追従率
HOME_SMOOTH = 0.1                                             # リセット時の戻る速さ
GRIP_SMOOTH = 0.2
FRESH = 0.5     # この秒数以内のパケットなら制御に使う(超えたら保持)
OWNER = 1.5     # この秒数以内にパケットが来ている腕は、スマホが担当
GRIP_END = {"right": -math.pi / 4, "left": math.pi / 4}       # g=1(閉)のときのグリッパ角

# ARKitワールド(x右, y上, z後ろ) -> ロボット(x前, y左, z上)
C = np.array([[0, 0, -1], [-1, 0, 0], [0, 1, 0]], dtype=float)


def _target(pose):
    return pa.array(
        [{"pose": [float(v) for v in pose]}],
        type=pa.struct([("pose", pa.list_(pa.float32()))]),
    )


def _pose_to_list(value):
    first = value.to_pylist()[0]
    return list(first["pose"]) if isinstance(first, dict) else list(value.to_pylist())


def _quat(p):
    return R.from_quat([p[4], p[5], p[6], p[3]])  # [qw,qx,qy,qz] -> xyzw


def _slerp(r0, r1, t):
    return Slerp([0, 1], R.concatenate([r0, r1]))([t])[0]


class Arm:
    def __init__(self):
        self.pose = None      # 最新のfk姿勢 [px,py,pz,qw,qx,qy,qz,grip]
        self.home = None      # 起動時の姿勢
        self.mouse = None     # 最新のマウス目標
        self.pos = self.rot = None
        self.grip = 0.0
        self.owned = False
        self.engaged = False
        self.homing = False
        self.rc = None
        self.p0 = self.q0 = self.t0_pos = self.t0_rot = None

    def load(self, pose):
        self.pos = np.array(pose[:3], dtype=float)
        self.rot = _quat(pose)
        self.grip = pose[7]


def _udp_loop(latest, lock):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", PORT))
    while True:
        data, addr = sock.recvfrom(2048)
        try:
            pkt = json.loads(data)
            side = pkt["side"]
        except (ValueError, TypeError, KeyError):
            continue
        if side not in SIDES:
            continue
        now = time.monotonic()
        with lock:
            cur = latest[side]
            # 同じ腕を別の端末が使用中なら無視(先着優先)
            if cur is not None and cur["addr"] != addr[0] and now - cur["rt"] < OWNER:
                continue
            latest[side] = {"pkt": pkt, "rt": now, "addr": addr[0]}


def main():
    latest = {s: None for s in SIDES}
    lock = threading.Lock()
    threading.Thread(target=_udp_loop, args=(latest, lock), daemon=True).start()

    arms = {s: Arm() for s in SIDES}

    node = dora.Node()
    node.send_output("status", pa.array(["ready"]))

    for event in node:
        if event["type"] == "STOP":
            break
        if event["type"] != "INPUT":
            continue
        eid = event["id"]

        if eid in ("pose_right", "pose_left"):
            a = arms[eid.split("_")[1]]
            a.pose = _pose_to_list(event["value"])
            if a.home is None:
                a.home = list(a.pose)
                a.load(a.pose)
            continue

        if eid in ("mouse_target_right", "mouse_target_left"):
            arms[eid.split("_")[-1]].mouse = _pose_to_list(event["value"])
            continue

        if eid != "tick":
            continue

        now = time.monotonic()
        with lock:
            snap = {s: latest[s] for s in SIDES}

        owned_sides = []
        outs = {}
        for side in SIDES:
            a = arms[side]
            if a.pose is None:
                continue
            entry = snap[side]
            active = entry is not None and now - entry["rt"] < OWNER

            if active and not a.owned:          # スマホがこの腕を担当し始めた
                a.owned = True
                a.load(a.pose)                  # 現在姿勢から再スタート(目標が飛ばない)
                a.engaged = False
                a.homing = False
                a.rc = None
            elif not active and a.owned:        # スマホが離れた -> マウスへ
                a.owned = False
                a.mouse = None
                a.engaged = False

            if not a.owned:
                outs[side] = a.mouse if a.mouse is not None else a.pose
                continue

            owned_sides.append(side)
            pkt = entry["pkt"]
            fresh = now - entry["rt"] < FRESH and pkt.get("ok") == 1

            rc = pkt.get("rc")
            if a.rc is None:
                a.rc = rc
            elif rc != a.rc:                    # リセットボタン
                a.rc = rc
                a.homing = True
                a.engaged = False

            if a.homing:
                hp = np.array(a.home[:3], dtype=float)
                hr = _quat(a.home)
                a.pos = a.pos + (hp - a.pos) * HOME_SMOOTH
                a.rot = _slerp(a.rot, hr, HOME_SMOOTH)
                if np.linalg.norm(hp - a.pos) < 1e-3 and (a.rot.inv() * hr).magnitude() < 0.01:
                    a.homing = False
            elif fresh and pkt.get("c") == 1:
                p = np.array(pkt["p"], dtype=float)
                q = R.from_quat(pkt["q"])       # [x,y,z,w]
                if not a.engaged:
                    a.engaged = True
                    a.pos = np.array(a.pose[:3], dtype=float)   # 実際の腕の位置から開始
                    a.rot = _quat(a.pose)
                    a.p0, a.q0 = p, q
                    a.t0_pos, a.t0_rot = a.pos.copy(), a.rot
                goal_pos = a.t0_pos + POS_SCALE * (C @ (p - a.p0))
                d_ar = (q * a.q0.inv()).as_matrix()
                goal_rot = R.from_matrix(C @ d_ar @ C.T) * a.t0_rot
                a.pos = a.pos + (goal_pos - a.pos) * SMOOTH
                a.rot = _slerp(a.rot, goal_rot, SMOOTH)
            else:
                a.engaged = False

            if fresh:
                goal_grip = float(pkt.get("g", 0.0)) * GRIP_END[side]
                a.grip += (goal_grip - a.grip) * GRIP_SMOOTH

            x, y, z, w = a.rot.as_quat()
            outs[side] = [a.pos[0], a.pos[1], a.pos[2], w, x, y, z, a.grip]

        for side, pose in outs.items():
            node.send_output(f"target_{side}", _target(pose))
        node.send_output("phone_sides", pa.array([",".join(owned_sides)]))


if __name__ == "__main__":
    main()