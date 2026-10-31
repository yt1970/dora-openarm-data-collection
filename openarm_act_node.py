"""OpenArm ACT 推論ノード + MCP サーバー(dora-rs)。

置き場所: /Users/yutako/dora-openarm-data-collection/openarm_act_node.py
実行環境: ~/lerobot-env (lerobot, dora-rs, mcp, opencv-python, pyarrow が必要)

役割:
  - 4つのACT(raise_right / raise_left / lower_right / lower_left)を読み込む
  - MCPツール run_task / get_state / reset を公開する
  - tick(約30Hz)ごとに、実行中のタスクのポリシーで推論し、
    move_position_right / move_position_left(float32 x 8)を出力する
  - 指示された腕の出力だけを使い、もう一方の腕は直前の目標を保持する
"""

import asyncio
import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
import pyarrow as pa
import torch
import os as _os


ROOT = Path(__file__).resolve().parent
N_ACT = int(_os.environ.get("ACT_REPLAN", "50"))  # 何ステップごとに再計画するか
MAX_STEP = float(_os.environ.get("ACT_MAXSTEP", "0.02"))  # 1ステップで動ける最大量(rad)
SMOOTH = float(_os.environ.get("ACT_SMOOTH", "1.0"))  # 1.0=そのまま、小さいほどなめらか
TASKS = ("raise_right", "raise_left", "lower_right", "lower_left")


# 各タスクで推論を回すフレーム数(30fps)。トリム済みデータの平均長(約95 / 約190フレーム)に余裕を足した値。
TASK_FRAMES = {"raise_right": 120, "raise_left": 120, "lower_right": 220, "lower_left": 200}
# タスク -> (動かす腕, 開始時に必要な論理状態, 終了後の論理状態)
TASK_SPEC = {
    "raise_right": ("right", "home", "raised"),
    "raise_left": ("left", "home", "raised"),
    "lower_right": ("right", "raised", "home"),
    "lower_left": ("left", "raised", "home"),
}
CKPT_PATTERN = os.environ.get(
    "ACT_CKPT_PATTERN", "outputs/train/act_trim_{task}/checkpoints/last/pretrained_model"
)
DEVICE = os.environ.get("ACT_DEVICE", "mps")
PORT = int(os.environ.get("MCP_PORT", "8765"))
LOG_FILE = os.environ.get("MCP_LOG_FILE", str(ROOT / "mcp_act_log.jsonl"))
IMG_H, IMG_W = 600, 960  # 学習時の天井カメラの大きさ
RESET_FRAMES = 60
# home姿勢(右も左も J1..J7, grip)。keyframe home の値。違っていたら直す。
HOME = np.array([0, 0, 0, math.pi / 2, 0, 0, 0, 0], dtype=np.float32)


def qpos_from(value: pa.Array) -> np.ndarray:
    """dora の入力(struct{qpos} または 数値配列)から先頭8要素を取り出す。"""
    if isinstance(value, pa.StructArray) or pa.types.is_struct(value.type):
        q = value.to_pylist()[0]["qpos"]
    else:
        q = value.to_pylist()
    return np.asarray(q[:8], dtype=np.float32)


class Controller:
    """MCPスレッドとdoraのメインループの橋渡し。"""

    def __init__(self, policies: dict):
        self.policies = policies  # task -> (policy, preprocessor, postprocessor)
        self.lock = threading.Lock()
        self.q = {"right": None, "left": None}  # 最新の実測関節角
        self.jpeg: np.ndarray | None = None
        self.target = {"right": None, "left": None}  # 送り続ける目標
        self.logical = {"right": "home", "left": "home"}  # 論理状態(実測ではない)
        self.job: dict | None = None
        self.last_error = ""

    # ---- MCP側 ----
    def ready(self) -> bool:
        return self.jpeg is not None and all(v is not None for v in self.q.values())

    def start_task(self, task: str):
        arm, need, after = TASK_SPEC[task]
        with self.lock:
            if not self.ready():
                return None, "まだセンサ(関節角・カメラ)を受信していません。MuJoCoが起動しているか確認してください"
            if self.job is not None:
                return None, f"別の動作({self.job['name']})を実行中です。終わってから呼んでください"
            if self.logical[arm] != need:
                ja = {"right": "右手", "left": "左手"}[arm]
                state = {"home": "下がっている", "raised": "上がっている"}[self.logical[arm]]
                verb = "上げる" if task.startswith("raise") else "下げる"
                return None, f"{ja}は既に{state}ので、{verb}動作はできません"
            self.policies[task][0].reset()
            job = {
                "name": task, "kind": "task", "arm": arm, "after": after,
                "frames": TASK_FRAMES[task], "done": threading.Event(), "status": "running",
            }
            self.job = job
            return job, ""

    def start_reset(self):
        with self.lock:
            if self.job is not None:
                return None, f"別の動作({self.job['name']})を実行中です"
            if not self.ready():
                return None, "まだセンサを受信していません"
            job = {
                "name": "reset", "kind": "reset", "frames": RESET_FRAMES,
                "start": {s: self.target[s].copy() for s in ("right", "left")},
                "done": threading.Event(), "status": "running", "i": 0,
            }
            self.job = job
            return job, ""

    def snapshot(self) -> dict:
        with self.lock:
            def r(x):
                return None if x is None else [round(float(v), 3) for v in x]
            return {
                "right": {"pose": self.logical["right"], "qpos": r(self.q["right"])},
                "left": {"pose": self.logical["left"], "qpos": r(self.q["left"])},
                "busy": None if self.job is None else self.job["name"],
                "note": "pose は実行した動作から数えた論理状態(実測ではない)",
            }

    # ---- dora側(メインループから tick ごとに呼ぶ) ----
    def step(self) -> tuple[np.ndarray, np.ndarray] | None:
        with self.lock:
            if not self.ready():
                return None
            if self.target["right"] is None:  # 最初に受け取った実測値を保持の初期値にする
                self.target["right"] = self.q["right"].copy()
                self.target["left"] = self.q["left"].copy()
            job = self.job
        if job is not None:
            try:
                if job["kind"] == "task":
                    self._step_task(job)
                else:
                    self._step_reset(job)
            except Exception as e:  # 推論失敗でも落とさず、目標を保持して終了
                self.last_error = repr(e)
                print("inference error:", repr(e), flush=True)
                self._finish(job, "error:" + repr(e))
        return self.target["right"].copy(), self.target["left"].copy()

    def _step_task(self, job: dict) -> None:
        policy, pre, post = self.policies[job["name"]]
        img = cv2.imdecode(self.jpeg, cv2.IMREAD_COLOR)  # BGR
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        if img.shape[:2] != (IMG_H, IMG_W):
            img = cv2.resize(img, (IMG_W, IMG_H))
        state = np.concatenate([self.q["right"], self.q["left"]]).astype(np.float32)
        obs = {
            "observation.state": torch.from_numpy(state).unsqueeze(0),
            "observation.images.ceiling": (
                torch.from_numpy(img).float().div(255).permute(2, 0, 1).unsqueeze(0)
            ),
        }
        policy.config.n_action_steps = N_ACT
        with torch.inference_mode():
            action = post(policy.select_action(pre(obs)))
        a = action.squeeze(0).cpu().numpy().astype(np.float32)
        arm = job["arm"]
        prev = getattr(self, "_prev", {}).get(arm)
        if prev is not None:
            a = prev + SMOOTH * (a - prev)
            a = prev + np.clip(a - prev, -MAX_STEP, MAX_STEP)
        if not hasattr(self, "_prev"):
            self._prev = {}
        self._prev[arm] = a
        self.target[arm] = a[:8].copy() if arm == "right" else a[8:16].copy()
        job["frames"] -= 1
        if job["frames"] <= 0:
            with self.lock:
                self.logical[arm] = job["after"]
            self._finish(job, "done")

    def _step_reset(self, job: dict) -> None:
        job["i"] += 1
        a = min(1.0, job["i"] / job["frames"])
        for s in ("right", "left"):
            self.target[s] = (job["start"][s] + (HOME - job["start"][s]) * a).astype(np.float32)
        if a >= 1.0:
            with self.lock:
                self.logical = {"right": "home", "left": "home"}
            self._finish(job, "done")

    def _finish(self, job: dict, status: str) -> None:
        with self.lock:
            job["status"] = status
            self.job = None
        job["done"].set()


def load_policies() -> dict:
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors

    out = {}
    for task in TASKS:
        ckpt = str(ROOT / CKPT_PATTERN.format(task=task))
        print(f"loading {task}: {ckpt}", flush=True)
        policy = ACTPolicy.from_pretrained(ckpt)
        policy.to(DEVICE)
        policy.eval()
        pre, post = make_pre_post_processors(policy.config, pretrained_path=ckpt)
        out[task] = (policy, pre, post)
    return out


def build_server(ctrl: Controller):
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("openarm-act", host="127.0.0.1", port=PORT)
    log_lock = threading.Lock()

    def log(tool: str, args: dict, result: str) -> None:
        rec = {"ts_ns": time.time_ns(), "tool": tool, "args": args, "result": result}
        with log_lock, open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    async def wait(job: dict, label: str) -> str:
        await asyncio.to_thread(job["done"].wait, 60.0)
        return f"{label}: {job['status']}"

    @mcp.tool()
    async def run_task(
        task: Literal["raise_right", "raise_left", "lower_right", "lower_left"],
        instruction: str = "",
    ) -> str:
        """片腕を上げる/下げる動作を1つ実行する。終わってから返る。

        指示されていない腕は動かさない。「右は上げないで左を下げて」なら
        lower_left を1回だけ呼ぶ。両腕を動かすときは1つずつ順に呼ぶ。

        Args:
            task: raise_right=右手を上げる / raise_left=左手を上げる /
                  lower_right=右手を下げる / lower_left=左手を下げる
            instruction: ユーザーの元の指示文
        """
        job, err = ctrl.start_task(task)
        result = err if job is None else await wait(job, task)
        log("run_task", {"task": task, "instruction": instruction}, result)
        return result

    @mcp.tool()
    async def get_state() -> str:
        """各腕の論理状態(home=下がっている / raised=上がっている)と関節角を返す。"""
        return json.dumps(ctrl.snapshot(), ensure_ascii=False)

    @mcp.tool()
    async def reset(instruction: str = "") -> str:
        """両腕を home(下がった初期姿勢)に戻す。"""
        job, err = ctrl.start_reset()
        result = err if job is None else await wait(job, "reset")
        log("reset", {"instruction": instruction}, result)
        return result

    return mcp


def main() -> None:
    import dora

    ctrl = Controller(load_policies())
    server = build_server(ctrl)
    threading.Thread(target=lambda: server.run(transport="streamable-http"), daemon=True).start()
    print(f"MCP: http://127.0.0.1:{PORT}/mcp", flush=True)

    node = dora.Node()
    for event in node:
        if event["type"] == "STOP":
            break
        if event["type"] != "INPUT":
            continue
        eid, value = event["id"], event["value"]
        if eid == "state_right":
            ctrl.q["right"] = qpos_from(value)
        elif eid == "state_left":
            ctrl.q["left"] = qpos_from(value)
        elif eid == "camera_ceiling":
            ctrl.jpeg = value.to_numpy(zero_copy_only=False).astype(np.uint8)
        elif eid == "tick":
            out = ctrl.step()
            if out is not None:
                right, left = out
                node.send_output("move_position_right", pa.array(right, type=pa.float32()))
                node.send_output("move_position_left", pa.array(left, type=pa.float32()))


if __name__ == "__main__":
    main()
