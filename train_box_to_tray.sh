#!/bin/bash
# box_to_tray(右手で箱を持ち上げて黒いトレーに入れる)を学習する。
# 10fps・天井カメラ1台・待機区間を切り落としたデータ(lerobot_ceiling_trim_box_to_tray_10fps)を使う。
# 33エピソード、10000ステップで、Apple Silicon Mac(MPS)で約4時間15分。
source ~/lerobot-env/bin/activate
cd "$(dirname "$0")"
caffeinate -i lerobot-train \
  --dataset.repo_id=local/ceiling_box_to_tray_10fps \
  --dataset.root=$PWD/lerobot_ceiling_trim_box_to_tray_10fps \
  --policy.type=act \
  --policy.device=mps \
  --policy.push_to_hub=false \
  --policy.chunk_size=50 \
  --policy.n_action_steps=50 \
  --batch_size=8 \
  --steps=10000 \
  --save_freq=2000 \
  --log_freq=100 \
  --output_dir=outputs/train/act_box_to_tray \
  --job_name=act_box_to_tray \
  --wandb.enable=false 2>&1 | grep -v "^objc" | tee train_box_to_tray.log
