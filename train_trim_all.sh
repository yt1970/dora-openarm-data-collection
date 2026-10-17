#!/bin/bash
# 4タスクを順に学習する(天井カメラ1台・待機区間を切り落とした版)。
# 順番は raise_right → lower_right → raise_left → lower_left。
# 先に「上げる」と「下げる」の両方を片腕で試せるようにするため。
source ~/lerobot-env/bin/activate
cd /Users/yutako/dora-openarm-data-collection
for t in raise_right lower_right raise_left lower_left; do
  lerobot-train \
    --dataset.repo_id=local/ceiling_trim_$t \
    --dataset.root=$PWD/lerobot_ceiling_trim_$t \
    --policy.type=act \
    --policy.device=mps \
    --policy.push_to_hub=false \
    --policy.chunk_size=50 \
    --policy.n_action_steps=50 \
    --batch_size=8 \
    --steps=3000 \
    --save_freq=1000 \
    --log_freq=100 \
    --output_dir=outputs/train/act_trim_$t \
    --job_name=act_trim_$t \
    --wandb.enable=false 2>&1 | tee train_trim_$t.log
done