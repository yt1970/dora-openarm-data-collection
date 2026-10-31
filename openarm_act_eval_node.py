"""box_to_tray 用のACT評価ノード(MCPなし)。起動3秒後から45秒間、ポリシーを10Hzで実行する。"""
import os
import time
from pathlib import Path

import cv2
import numpy as np
import pyarrow as pa
import torch

ROOT = Path(__file__).resolve().parent
CKPT = os.environ.get(
    "ACT_CKPT", "outputs/train/act_box_to_tray/checkpoints/010000/pretrained_model"
)
DEVICE = os.environ.get("ACT_DEVICE", "mps")
START_SEC = float(os.environ.get("ACT_START_SEC", "3"))
RUN_SEC = float(os.environ.get("ACT_RUN_SEC", "45"))
MAX_STEP = float(os.environ.get("ACT_MAXSTEP", "0.3"))  # 1tickの最大変化(rad)
IMG_H, IMG_W = 600, 960


def qpos_from(value):
    if pa.types.is_struct(value.type):
        q = value.to_pylist()[0]["qpos"]
    else:
        q = value.to_pylist()
    return np.asarray(q[:8], dtype=np.float32)


def main():
    import dora
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors

    ckpt = str(ROOT / CKPT)
    print("loading", ckpt, flush=True)
    policy = ACTPolicy.from_pretrained(ckpt)
    policy.to(DEVICE)
    policy.eval()
    policy.config.n_action_steps = int(os.environ.get("ACT_REPLAN", "50"))
    policy.reset()
    pre, post = make_pre_post_processors(policy.config, pretrained_path=ckpt)

    q = {"right": None, "left": None}
    jpeg = None
    target = None
    t0 = None
    finished = False

    node = dora.Node()
    for event in node:
        if event["type"] == "STOP":
            break
        if event["type"] != "INPUT":
            continue
        eid, value = event["id"], event["value"]
        if eid == "state_right":
            q["right"] = qpos_from(value)
        elif eid == "state_left":
            q["left"] = qpos_from(value)
        elif eid == "camera_ceiling":
            jpeg = value.to_numpy(zero_copy_only=False).astype(np.uint8)
        elif eid == "tick":
            if jpeg is None or q["right"] is None or q["left"] is None:
                continue
            if target is None:
                target = np.concatenate([q["right"], q["left"]])
                t0 = time.time()
            elapsed = time.time() - t0
            if START_SEC <= elapsed < START_SEC + RUN_SEC:
                try:
                    img = cv2.cvtColor(cv2.imdecode(jpeg, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
                    if img.shape[:2] != (IMG_H, IMG_W):
                        img = cv2.resize(img, (IMG_W, IMG_H))
                    state = np.concatenate([q["right"], q["left"]]).astype(np.float32)
                    obs = {
                        "observation.state": torch.from_numpy(state).unsqueeze(0),
                        "observation.images.ceiling": torch.from_numpy(img)
                        .float().div(255).permute(2, 0, 1).unsqueeze(0),
                    }
                    with torch.inference_mode():
                        a = post(policy.select_action(pre(obs)))
                    a = a.squeeze(0).cpu().numpy().astype(np.float32)
                    target = target + np.clip(a - target, -MAX_STEP, MAX_STEP)
                except Exception as e:
                    print("inference error:", repr(e), flush=True)
            elif elapsed >= START_SEC + RUN_SEC and not finished:
                print("done: holding the last target", flush=True)
                finished = True
            node.send_output("move_position_right", pa.array(target[:8], type=pa.float32()))
            node.send_output("move_position_left", pa.array(target[8:16], type=pa.float32()))


if __name__ == "__main__":
    main()