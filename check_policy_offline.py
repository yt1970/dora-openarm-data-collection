"""チェックポイントをオフラインで確認する。

データセットの数フレームについて、ポリシーが出す action と、記録されている action(正解)を比べる。
実行は ~/lerobot-env で:
  python check_policy_offline.py <pretrained_model のパス> <データセットのパス>
"""

import sys
from pathlib import Path

import numpy as np
import torch
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.policies.factory import make_pre_post_processors

try:
    from lerobot.datasets import LeRobotDataset
except ImportError:
    from lerobot.datasets.lerobot_dataset import LeRobotDataset

ckpt = sys.argv[1]
root = sys.argv[2]
FRAME_INDEXES = [0, 25, 50, 75, 100]  # エピソード0の中の位置(全体のフレーム番号)

policy = ACTPolicy.from_pretrained(ckpt)
policy.to(policy.config.device)
policy.eval()
pre, post = make_pre_post_processors(policy.config, pretrained_path=ckpt)
ds = LeRobotDataset("local/" + Path(root).name, root=root)

np.set_printoptions(precision=3, suppress=True, linewidth=140)
for idx in FRAME_INDEXES:
    item = ds[idx]
    policy.reset()
    batch = {
        "observation.state": item["observation.state"].unsqueeze(0),
        "observation.images.ceiling": item["observation.images.ceiling"].unsqueeze(0),
    }
    with torch.no_grad():
        action = post(policy.select_action(pre(batch)))
    pred = action.squeeze(0).cpu().numpy()
    gt = item["action"].numpy()
    err = np.abs(pred - gt)
    print(f"--- frame {idx} (episode {int(item['episode_index'])}, frame_index {int(item['frame_index'])})")
    print("  右腕 正解:", gt[:8])
    print("  右腕 予測:", pred[:8])
    print("  左腕 正解:", gt[8:])
    print("  左腕 予測:", pred[8:])
    print(f"  平均誤差 右={err[:8].mean():.3f} 左={err[8:].mean():.3f} (rad)")