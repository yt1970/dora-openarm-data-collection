"""4タスクのOpenArmデータを、天井カメラのみ・待機区間を切り落としたLeRobot v3.0に変換する。

各エピソードで、action(関節目標)が最初の値から THRESHOLD 以上動き始める LEAD 秒前から、
最後の値に落ち着く TAIL 秒後までだけを使う。
出力: lerobot_ceiling_trim_<task>/(dora-openarm-data-collection/ 直下)
"""

import shutil
from pathlib import Path

import numpy as np
import openarm_dataset
from openarm_dataset.sampler import Sampler

TASKS = ["box_to_tray"]
CAMERAS = ["ceiling"]
THRESHOLD = 0.03  # rad。動いたとみなす変化量
LEAD = 0.3  # 秒。動き出しの前に残す時間
TAIL = 0.7  # 秒。動きが止まった後に残す時間

_original = Sampler._sample_timestamps


def _trimmed(self, hz, obs, action, cameras):
    times = _original(self, hz, obs, action, cameras)
    if len(times) == 0:
        return times
    onset, last = None, None
    for df in action.values():
        if df.empty:
            continue
        arr = df.to_numpy(dtype=float)
        moving = np.where(np.abs(arr - arr[0]).max(axis=1) > THRESHOLD)[0]
        if len(moving) == 0:
            continue
        settling = np.where(np.abs(arr - arr[-1]).max(axis=1) > THRESHOLD)[0]
        t0, t1 = df.index[moving[0]], df.index[settling[-1]]
        onset = t0 if onset is None else min(onset, t0)
        last = t1 if last is None else max(last, t1)
    if onset is None:
        return times
    kept = times[(times >= onset - LEAD) & (times <= last + TAIL)]
    return kept if len(kept) >= 10 else times


Sampler._sample_timestamps = _trimmed

for task in TASKS:
    out = Path(f"lerobot_ceiling_trim_{task}_10fps")
    if out.exists():
        shutil.rmtree(out)
    ds = openarm_dataset.Dataset(f"data_{task}_all/dataset", camera_names=CAMERAS)
    ds.write(
        str(out),
        format="lerobot_v3.0",
        valid_only=False,
        fps=10,
        smoothing_cutoff=0,
        train_split=0.8,
        success_only=True,
        arm_dynamics=False,
    )
    print("done", task)