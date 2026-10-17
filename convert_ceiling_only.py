"""4タスクのOpenArmデータを、天井カメラのみのLeRobot v3.0に変換する。

出力: lerobot_ceiling_<task>/(dora-openarm-data-collection/ 直下)
変換条件: fps 30、smoothing なし、成功エピソードのみ、state は qpos(既定)、train-split 0.8
"""

import shutil
from pathlib import Path

import openarm_dataset

TASKS = ["raise_right", "raise_left", "lower_right", "lower_left"]
CAMERAS = ["ceiling"]

for task in TASKS:
    out = Path(f"lerobot_ceiling_{task}")
    if out.exists():
        shutil.rmtree(out)
    ds = openarm_dataset.Dataset(f"data_{task}/dataset", camera_names=CAMERAS)
    ds.write(
        str(out),
        format="lerobot_v3.0",
        valid_only=False,
        fps=30,
        smoothing_cutoff=0,
        train_split=0.8,
        success_only=True,
        arm_dynamics=False,
    )
    print("done", task)