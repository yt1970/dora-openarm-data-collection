# OpenArm MCP 進捗管理

最終更新: 2026-10-17(Step 7 完了: LM Studio + qwen/qwen3.8-27b から、自然言語で否定・組み合わせを含む指示が動いた)

## このファイルの使い方(新しい会話の Claude へ)

- 作業の最初にこのファイルを全部読む。作業が進むたびに「現在地」「チェックリスト」「進捗ログ」を更新する。
- 設計の全体像は Claude Docs の「LLM×模倣学習でロボットを誰でも動かす:OpenArm MCP 構想」(ドキュメントID `0df495fb-9019-4943-ad1d-6894297ff50f`。Claude Docs のツールで読む。WebFetch では読めない)。
- ユーザーは日本語で、長文を嫌う。短く、単純に伝える。
- ファイル書き込みは原則ユーザーが行う(MCP はコンテキストを食うため)。このmdは、ユーザーが許可したときだけ Claude が直接更新してよい(2026-10-14 に許可あり)。コードや設定ファイルは、案を提示してユーザーが書く。読み取りはユーザーが許可した範囲で行う。

## ゴール

既存のLLMから、誰でも簡単にロボットを動かせるようにする。そのために、MuJoCo上のOpenArmの動作を模倣学習し、MCPツールとして公開して、Hermes上のQwen3.5 9Bから自然言語で動かす。

最初のデモは4動作:右手を上げる、左手を上げる、右手を下げる、左手を下げる。「右は上げないで左を下げて」のような否定や組み合わせはLLMが解釈し、該当ツールだけを呼ぶ。

## 現在地(2026-10-16)

- 収集: 4動作とも完了。
- 変換(Step 3): 4タスクとも完了(下記「変換結果」)。
- 学習(Step 4): 完了。待機区間を切り落としたデータ(`lerobot_ceiling_trim_<task>`)で、4タスクとも3000ステップを学習した(下記「学習結果」)。チェックポイントは `outputs/train/act_trim_<task>/checkpoints/{001000,002000,003000,last}`。
- 推論(Step 5)と MCP(Step 6): 2026-10-16 に動作を確認した。`dora run dataflow_act.yaml` でシミュレーターと推論ノードを起動し、`call_mcp.py` から `run_task` を呼ぶと、4動作とも完了した(実際の動きも目で確認済み)。次は Hermes(Qwen3.5 9B)との接続(Step 7)。

## 設計判断(確定)

| 動作 | ツール名 | 開始状態 | 終了状態 |
| --- | --- | --- | --- |
| 右手を上げる | `raise_right` | home | 右手が上がっている |
| 左手を上げる | `raise_left` | home | 左手が上がっている |
| 右手を下げる | `lower_right` | 右手が上がっている | home |
| 左手を下げる | `lower_left` | 左手が上がっている | home |

1. 動作ごとに別のACTポリシーを学習する(計4つ)。ACTは言語入力を持たず、1つだと「上げる途中」と「下げる途中」が状態から区別できない。
2. 「上げる」は手先のzを最大(+0.2m)まで上げる。「下げる」はhome位置(z≈0、目視)まで戻す。zは他の用途(テーブル上の物を取る)のためにマイナスも許可する(クランプしない)。
3. 「下げる」のデータは、先に腕を上げてからStartを押し、そこから下げて記録した。
4. 動かさない側の腕は、収集時に半分のエピソードで home、残り半分で上げた状態にした。推論時は、指示された腕の出力だけを使い、もう一方の腕は直前の目標を保持する。
5. カメラは収集時に全5台(ceiling / head_left / head_right / wrist_left / wrist_right)を記録した。**学習には天井カメラ1台を使う**(2026-10-14 確定)。理由: ACTは画像か環境状態が必須で、天井カメラなら両腕が映る。高さは画像が見えにくい可能性があるが、腕の高さは observation.state(関節角)で正確に分かる。学習で高さを区別できない場合は、頭カメラや手首カメラを足す。
6. MCPサーバーは文を解釈しない。ツールは `run_task(task)`(4動作のenum)、`get_state()`、`reset()`。腕が上がっていない状態で「下げる」を呼ばれたら、理由つきのエラーを返す。

## リポジトリの事実

場所: `/Users/yutako/dora-openarm-data-collection/`(enactic/dora-openarm-data-collection をベースに改変)

- **収集用dataflow:** `dataflow_{raise,lower}_{right,left}.yaml`(元は `dataflow_mouse_teleop_data_collection.yaml`)。メタデータは `metadata_{raise,lower}_{right,left}.yaml`。
    - ノード: `mouse-teleop` → `ik` → `mujoco-collect`、`fk`、`ui`(Web UI localhost:8000)、`recorder`。
    - `mujoco-collect` は `path: ./mujoco_mac.sh`(Macでmjpython経由)、`args: "--scene demo --keyframe home --enable-collision --ctrl --viewer --render"`。
    - 保存先: `data_<task>/dataset/`(OpenArm Dataset v0.4.0)。
- **mouse-teleop の操作:** パッドをドラッグで手先のx/y、↑↓キーでz(±0.20m、0.10m/s)、ホイールでグリッパ、←→で操作する腕を切替、Rキーで箱リセット。(一度入れ替えたが元に戻した。ドラッグしながらホイールは難しい。)
- **mujoco-collect の入出力:** 入力 `move_position_right/left`(float32[8] か struct{qpos})、`request_position`、`request_state`、`button_x`。出力 `position_*`、`state_*`、`camera_*`(JPEG)。
- **recorder(`nodes/dora-openarm-dataset-recorder`):** エピソード番号はUIが送る `episode_number`。例外処理が無く、1回の例外でノードごと落ちる。**修正済み(2026-10-13):** Start なしの success/fail/cancel で落ちないようにガードを追加。同番号の Start も無視。
- **変換ツール:** `./openarm_dataset`(最新、`git pull` 済み)。`openarm-dataset-convert` は `--format lerobot_v3.0`、`--success-only`、`--state {qpos,pose,rot6d}` などに対応。
- **記録周期(実測):** obs 約10Hz、action 約80Hz、camera 約20Hz。変換で 30fps に補間される。

## 収集結果(2026-10-13〜14)

| タスク | 保存数 | 失敗/除外 | 容量(元) |
| --- | --- | --- | --- |
| raise_right | 32(metadata) | ID 24(データ空)・ID 7(極端に短い)を除外 → 30 | 727MB |
| raise_left | 33 | 失敗1(変換時に除外) → 約32 | 893MB |
| lower_right | 32 | 失敗1(変換時に除外) → 約31 | 1.1GB |
| lower_left | 32 | 失敗4(変換時に除外) → 約28 | 853MB |

収集で起きた問題: ①ディスク満杯 → ollama のモデルを削除して解消。②recorder が「Start なしの success」で落ちて1エピソードしか保存されなかった → recorder にガード追加、`data_raise_right` を消して再収集。③`raise_right` に空エピソード(ID 24)と極端に短いエピソード(ID 7)が混入 → metadata から除外(バックアップ `metadata.yaml.bak`)。

## Step 3: LeRobot 変換

### 変換コマンド(`raise_right` で成功を確認)

```bash
openarm-dataset-convert data_raise_right/dataset lerobot_raise_right \
  --format lerobot_v3.0 --success-only --fps 30 --smoothing-cutoff 0
```

### 条件と理由

- `--format lerobot_v3.0`: lerobot-train(ACT)で使う現行形式。
- `--success-only`: 失敗エピソードを学習に混ぜない。
- `--fps 30`: 既定値。記録周期がバラバラなので 30fps に揃える。
- `--smoothing-cutoff 0`: スムージング無効。既定の 1Hz は VR 操作のノイズ除去向けで、今回のデータはIK出力で元から滑らか。1Hz だと速い動きがなまり、遅れも出る。
- `--state qpos`(既定): state/action とも 16次元(右8+左8: 7関節+グリッパ)の関節角。推論時に mujoco から取る状態と、mujoco に送る関節目標が同じ表現で揃うため。
- `--train-split` は既定(0.8): info.json の splits に train/val が記録されるだけ。
- カメラは全5台のまま。

### 結果(`raise_right`)

30エピソード、5389フレーム(1エピソード平均約180フレーム=約6秒)、27MB(動画は圧縮されて元の727MBから大幅縮小)。splits は train 0:24 / val 24:30。features は action(16)、observation.state(16)、カメラ映像、success。

### 残りの変換コマンド

```bash
for t in raise_left lower_right lower_left; do
  rm -rf lerobot_$t
  openarm-dataset-convert data_$t/dataset lerobot_$t \
    --format lerobot_v3.0 --success-only --fps 30 --smoothing-cutoff 0
done
for t in raise_right raise_left lower_right lower_left; do
  echo $t; grep -E "total_episodes|total_frames" lerobot_$t/meta/info.json
done
```

## 進捗チェックリスト

- [x] 0. 設計ドキュメント作成、設計判断の確定、リポジトリ構造の確認
- [x] 1. 収集設定を整える(4つのdataflowとメタデータ)
- [x] 2. テレオペで収集する(4動作とも完了)
- [x] 3. LeRobot形式に変換する(`lerobot_v3.0`、動作ごとに1データセット)(2026-10-14、件数は `info.json` で確認済み。LeRobotでの読み込み確認は Step 4 の学習開始時に行う)
- [x] 4. 動作ごとに模倣学習する(ACT、天井カメラ1台)(2026-10-16、4タスクとも3000ステップ完了)
    - 残る確認: 各ポリシーがシミュレーター内で動作を完了できるか(Step 5 で確認。使うチェックポイントも、そこで決める)
- [x] 5. 推論ノードを作る(2026-10-16 完了。`dora run` で起動し、4動作を手動で呼び出して実行できた)(現在の関節角と画像からポリシーで推論し、`move_position_*` へ直接出力。IKノードは通らない)
    - 済み(2026-10-15): `openarm_act_node.py` を書いた(未実行・構文チェックのみ)。`dataflow_act.yaml` を用意済み。学習環境に `dora-rs mcp opencv-python pyarrow` を追加済み。
    - 済み(2026-10-16): 動かして確認。エラーは `mcp` 2.x で `FastMCP` が無いだけ → `uv pip install 'mcp<2'` で解決。`dora` コマンドは `lerobot-env` ではなく、収集用の `(dora-openarm-data-collection)` 環境で実行する(推論ノード自体は `dataflow_act.yaml` の path で `lerobot-env` の python を指定)。
    - 完了条件: dataflow上で4動作を手動で呼び出して実行できる
- [x] 6. MCPサーバーで公開する(`run_task`、`get_state`、`reset`)(2026-10-16 完了。`call_mcp.py`(リポジトリ直下、`python call_mcp.py run_task '{"task": "raise_right"}'`)から4動作を呼び出せた。`get_state` も確認。不正なタスク名は入力検証エラーで弾かれる。前提エラーと `reset` は 2026-10-17 に確認済み)
    - 完了条件: MCPクライアントから4動作を呼び出せる
- [x] 7. LLMにつなぐ(2026-10-17、LM Studio + `qwen/qwen3.8-27b` で確認。Hermes は回答が遅く、未解決)
    - 済み(2026-10-17): Claude desktop をクライアントにして予行。`claude_desktop_config.json` に `openarm`(`npx -y mcp-remote http://127.0.0.1:8765/mcp`)を追加し、自然言語で確認。「右手上げて」→ `raise_right` のみ、「右手上げないで左手上げて」→ `raise_left` のみ、「左手下げないで右手下げて」→ `lower_right` のみ。どれも期待どおりに動き、動かさない側の腕は保持された(目視で「完璧」)。
    - 済み(2026-10-17): `reset` も確認(両腕が初期姿勢に戻った)。Hermes の MCP 設定にも `openarm`(`npx -y mcp-remote http://127.0.0.1:8765/mcp`)を追加し、接続を確認(ログで initialize → tools/list が通る)。
    - 済み(2026-10-17): LM Studio(MCP 設定は Claude desktop と同じ形式)+ `qwen/qwen3.8-27b` で確認。`mcp_act_log.jsonl` で判定し、7つの呼び出しのうち意図どおりは6つ。「右手下げないで左手上げて」→ `raise_left` のみ、「右手から順番に両腕下げて」→ `lower_right` → `lower_left`、「右手を上げて、その後下げて」→ `raise_right` → `lower_right`。「両手を上げて」は左が既に上がっていて、`raise_left` が理由つきエラーで止まった(モデルが状態を確認せずに呼んだが、MCP 側が防いだ)。
    - 課題: 「両手下げて」で `lower_*` を 2 回ではなく `reset` を選んだ(結果は同じだが、`reset` は学習した動作ではない補間)。`reset` の説明文に「非常時の初期化用」と足す案。
    - 課題: Hermes は、Qwen3.5 9B も Gemma4 2B も同じくらい遅かった(モデルを小さくしても変わらないので、Hermes 側の準備が重いと考えている。`npx mcp-remote` の起動やシステムプロンプトの長さが候補)。LM Studio では問題なく動いた。
    - 案: `tev1`(Together AI の4B/0.8Bの分類用モデル、Ollama 0.35以降)。専用API `/v1/systemone` で、「右手を上げる指示か」等を4つのはい/いいえ質問(`noul`)として投げ、確率が高いツールだけ MCP で呼ぶ。Hermes のエージェント用モデルとしては使えない。日本語と否定は未確認(英語中心。テストが必要)。
    - 完了条件: 4動作に加え、否定や組み合わせの指示でも期待どおりのツールだけが呼ばれる

## 天井カメラ1台のデータセット(2026-10-14)

- スクリプト: `convert_ceiling_only.py`(リポジトリ直下。`openarm_dataset.Dataset(..., camera_names=["ceiling"]).write(...)`。条件は上の変換条件と同じ)。
- 出力: `lerobot_ceiling_<task>/`(4タスク。エピソード数・フレーム数は下表と同じ、`observation.images.ceiling` のみ、各 5〜7MB)。
- **学習に使うのはこちら。** 全5台版(`lerobot_<task>`)は予備として残す。

## 待機区間を切り落としたデータセット(2026-10-15)

- スクリプト: `convert_ceiling_trimmed.py`(リポジトリ直下。`convert_ceiling_only.py` と同じ条件に、切り出しを追加)。
- 切り出し: 各エピソードで、action が最初の値から 0.03 rad 以上動き始める 0.3 秒前から、最後の値に落ち着く 0.7 秒後までだけを使う。`openarm_dataset.sampler.Sampler._sample_timestamps` を差し替えて実現。
- 出力: `lerobot_ceiling_trim_<task>/`。天井カメラ1台。
- 結果: raise_right 30ep・2836フレーム(元 5389)、raise_left 32ep・3048(元 6003)、lower_right 31ep・5950(元 9095)、lower_left 28ep・4589(元 6691)。エピソード数は変わらず、フレームが3〜5割減った。
- **学習にはこちらを使う。** 待機区間ありの版(`lerobot_ceiling_<task>`)は比較用に残す。

## 変換結果(2026-10-14)

| タスク | エピソード | フレーム | 1エピソード平均 |
| --- | --- | --- | --- |
| raise_right | 30 | 5389 | 約180フレーム(約6秒) |
| raise_left | 32 | 6003 | 約188フレーム(約6秒) |
| lower_right | 31 | 9095 | 約293フレーム(約10秒) |
| lower_left | 28 | 6691 | 約239フレーム(約8秒) |

出力先: `lerobot_raise_right` / `lerobot_raise_left` / `lerobot_lower_right` / `lerobot_lower_left`(`dora-openarm-data-collection/` 直下)。

## Step 4: ACT 学習(2026-10-15)

### 環境

- 学習専用の環境 `~/lerobot-env`(uv、Python 3.12)。収集・変換用の `(openarm-dataset)` 環境とは分ける(依存関係の衝突を避けるため)。
- 入れたもの: `uv pip install lerobot`(0.6.1)に加え、`uv pip install 'lerobot[dataset]'` と `uv pip install 'lerobot[training]'`(これを入れないと `datasets` と `accelerate` が無いというエラーで止まる)。
- 有効化: `source ~/lerobot-env/bin/activate`。ffmpeg は Homebrew のものを使用。
- 起動時の `objc[...] Class AVF... is implemented in both ...` の警告は、opencv / av / ffmpeg の重複で、これまでのところ無害。出力から消すには `2>&1 | grep -v "^objc"`。
- 注意: 学習ログをターミナルに貼り付けない(引用符が閉じず入力待ちになる)。

### 試し学習(300ステップ、2026-10-15)

- 結果: 動作確認OK。30エピソード・5389フレームを読み込み、ACT(ResNet18 + Transformer、約5,200万パラメータ)が学習ループに入り、300ステップで8分、1ステップ約1.6秒(mps)。
- 200ステップ時点: loss 6.509(l1_loss 0.362、kld_loss 0.615。loss は kld に kl_weight=10 を掛けた分を含む)。まだ学習初期の値で、品質は見ていない。
- 成果物: `outputs/train/act_raise_right_test/checkpoints/last/pretrained_model/`(config.json、model.safetensors、前処理・後処理の safetensors と json)。

### 本学習のコマンド(raise_right)

```bash
cd /Users/yutako/dora-openarm-data-collection
caffeinate -i lerobot-train \
  --dataset.repo_id=local/ceiling_raise_right \
  --dataset.root=$PWD/lerobot_ceiling_raise_right \
  --policy.type=act \
  --policy.device=mps \
  --policy.push_to_hub=false \
  --policy.chunk_size=50 \
  --policy.n_action_steps=50 \
  --batch_size=8 \
  --steps=3000 \
  --save_freq=500 \
  --log_freq=100 \
  --output_dir=outputs/train/act_raise_right \
  --job_name=act_raise_right \
  --wandb.enable=false 2>&1 | grep -v "^objc" | tee train_raise_right.log
```

他のタスクは、`raise_right` の部分(データセットのパス、`--dataset.repo_id`、`--output_dir`、`--job_name`、ログ名)を `raise_left` / `lower_right` / `lower_left` に置き換える。

### 条件と理由

- `--policy.type=act`: 動作ごとに別のACTを学習する設計(設計判断1)。
- `--policy.device=mps`: Mac(Apple Silicon)のGPU。
- `--policy.chunk_size=50`、`--policy.n_action_steps=50`: 動きが約6秒(約180フレーム)と短いので、既定の100より短くした。下げる動作は約8〜10秒なので、結果次第で見直す。
- `--batch_size=8`: 試し学習で問題なく動いた値(メモリ・速度とも)。
- `--steps=3000`: 安全側の見積もり(約4.5周、約80分)。単純な動きなので、1000〜2000ステップで足りる可能性もある。`--save_freq=500` で途中のチェックポイントを残し、後でシミュレーターで動かして比べる。loss が横ばいになったら止めてよい。
- `caffeinate -i`: 学習中にMacがスリープしないようにする。
- `--log_freq=100`: 100ステップごとに loss を表示。`| tee` でログをファイルにも残す。
- 速度の目安: 1ステップ約1.6秒。3000ステップ=約80分。4タスクを3000ステップずつだと約5時間。重い場合は、天井カメラの画像(600x960)を縮小して変換し直す案(数倍速くなる見込み。推論側も同じサイズに揃える必要あり)。
- 学習中は MuJoCo など GPU を使う重い処理を動かさない。

### 学習結果(ここに追記する)

- raise_right 本学習(待機区間あり、`outputs/train/act_raise_right`、3000ステップ、約1時間25分): 終了。2700ステップ時点で loss 0.785(l1_loss 0.131、kld_loss 0.065)。チェックポイントは 500 ステップごと(500〜3000)。
- オフライン確認(`check_policy_offline.py`、エピソード0の5フレーム): 動き出した後(frame 100)の右腕は、関節1が増え関節4が減る向き(腕を上げる向き)に予測できていた。左腕(動かさない側)は誤差 0.007〜0.014 rad で保てていた。一方、frame 0〜50 の正解は同じホーム姿勢のまま(約2秒の待機)で、入力も同一のため予測も同一。ポリシーは「いつ動き出すか」を区別できない。シミュレーターでの動作確認は未実施(推論ノードがまだ無い)。

### トリム済みデータでの本学習(2026-10-15夜〜10-16朝)

- 条件: `train_trim_all.sh` と同じ(ACT、chunk_size 50、n_action_steps 50、batch 8、3000ステップ、save_freq 1000、mps)。データは `lerobot_ceiling_trim_<task>`。
- 結果(3000ステップ時点):

| タスク | loss | l1_loss | kld_loss | 所要時間 |
| --- | --- | --- | --- | --- |
| raise_right | 0.656 | 0.110 | 0.055 | 1時間29分 |
| lower_right | 0.621 | 0.102 | 0.052 | 1時間33分 |
| raise_left | 0.701 | 0.122 | 0.058 | 1時間40分 |
| lower_left | 0.686 | 0.112 | 0.057 | 1時間32分 |

- 速度: 序盤は約1.1秒/ステップ、その後は約1.9〜2.0秒/ステップに遅くなった(ファンのない MacBook Air の熱による低下の可能性)。4タスクで約6時間かかった(見込みの約4〜5時間より長い)。
- トラブル: `lower_left` が最初の1回、1000ステップ付近で止まった。原因は、ストレージ不足の可能性が高い(空きが無くなり、Gemma4 26B を削除して解消。その後の空きは約17GB で、使用率99%)。出力フォルダは作られていなかったので、同じコマンドで最初から回し直して完了した。
- 注意: ストレージの空きが少ない。モデルやデータの整理が必要。
- lossの値は、動作の出来を直接は表さない。シミュレーターでの確認は未実施。

## Step 5 の準備メモ(2026-10-15、推論ノードを作るときの事実)

### ポリシーの入出力(`pretrained_model/config.json` より)

- 入力: `observation.state` = 16次元(右 joint1-7 + gripper、左 joint1-7 + gripper の関節角)、`observation.images.ceiling` = 3x600x960。
- 出力: `action` = 16次元(同じ並びの関節目標)。`chunk_size=50`、`n_action_steps=50`、`n_obs_steps=1`。
- 正規化は MEAN_STD(state / action / 画像)。前処理・後処理の定義は `policy_preprocessor.json` / `policy_postprocessor.json` と safetensors に保存済み。推論でもこれを使う。

### MuJoCo ノードの入出力(`nodes/dora-openarm-mujoco/src/dora_openarm_mujoco/main.py` を読んで確認)

- 入力 `move_position_right` / `move_position_left`: float32[8](joint1-7 + グリッパ)。struct{qpos} も可。`--ctrl` では data.ctrl に書き込み物理を進める。
- 入力 `request_position`（任意のペイロードでよい）を受けると、`position_right` / `position_left`(struct{qpos: float32[8]})を返す。`request_state` では `state_right` / `state_left`(qpos, qvel, qtorque などを含む struct)。学習データの observation.state は state_* の qpos。
- 出力 `camera_ceiling`: uint8 配列の JPEG、30Hz、metadata `{"encoding": "jpeg"}`。JPEG は BGR からエンコードされている(デコード後に RGB へ変換する)。`--render` が必要。
- 収集時のタイマー: `request_position` 20ms、`request_state` 4ms。推論ノードでは、このタイマーを `tick`(約30Hz)に合わせて使う予定。

### 推論ノードの設計案

- 1つの dora ノードに、　(a) 4つのポリシーの読み込み、(b) MCP サーバー(別スレッド)をまとめる。試作(`dora-openarm-mcp-teleop`)の補間部分を、ACT 推論に置き換える形。
- 入力: `tick`(約30Hz)、`position_right` / `position_left` または `state_*`、`camera_ceiling`。出力: `move_position_right` / `move_position_left`。IK ノードは通らない(学習の action は関節目標そのもの)。
- 指示された腕の出力だけを送り、もう一方の腕は直前の目標を保持する(設計判断4)。
- ACT には「終わり」の信号がないので、一定時間(例: エピソードの長さと同じ約8〜10秒)だけ推論して停止する方針。終了後は目標を保持。
- 前提チェック(「上げていないのに下げる」等)は get_state でして、理由つきエラーを返す(設計判断6)。
- LeRobot をノードから使うときは、学習環境(`~/lerobot-env`)と dora の環境が同じである必要がある。推論ノードだけ `~/lerobot-env` で起動する構成を検討。
- 先にオフラインで、チェックポイントがデータセットの1フレームから妥当な action(正解に近い値)を出すか確認する。

## 推論ノード(`openarm_act_node.py`)(2026-10-15)

- 場所: リポジトリ直下。実行は学習環境(`~/lerobot-env`)の python。dataflow は `dataflow_act.yaml`(`mouse-teleop` / `ik` / `ui` / `recorder` / `fk` を外し、`mujoco-collect` の inputs を `act-infer` の出力と `request_state` タイマーにし、`act-infer` ノードを追加)。
- 構成: 起動時に4つのACT(`outputs/train/act_trim_<task>/checkpoints/last/pretrained_model`)を読み込み、MCPサーバー(127.0.0.1:8765、streamable-http)をスレッドで起動。tick(33ms)ごとに、実行中のタスクだけ推論して `move_position_right/left` を出力する。
- MCPツール: `run_task(task, instruction)`、`get_state()`、`reset()`。動作は終わってから返る。実行中の別呼び出しは「実行中」エラー。
- 指示された腕の出力だけを使い、もう一方の腕は直前の目標を保持する。保持の初期値は、最初に受け取った実測の関節角。
- 前提チェック: 腕の状態は、実行した動作から数えた論理状態(実測ではない)。上がっている腕を上げる、下がっている腕を下げる、は理由つきエラー。
- 推論フレーム数: raise 120、lower_right 220、lower_left 200(30fps。トリム済みの平均長に余裕を足した値)。
- 環境変数: `ACT_CKPT_PATTERN`、`ACT_DEVICE`(既定 mps)、`MCP_PORT`、`MCP_LOG_FILE`(既定 `mcp_act_log.jsonl`)。
- 未確認の点: ①`request_state` を33msで出して問題ないか(収集時は4ms)。②`HOME`(J4=π/2)は試作から持ってきた仮の値で、`reset` の戻り先。③画像の色順(BGR→RGB)。④state の qpos が先頭8要素(7関節+グリッパ)か。⑤推論が33msに間に合うか(チャンクの再計算時)。

## 次にやること

1. 前提エラー(上がっている腕を上げる、下がっている腕を下げる)と `reset` を `call_mcp.py` で確認する。両腕を続けて動かしたときに、もう一方の腕が保持されるかも見る。
2. Step 7: Hermes(Qwen3.5 9B)から MCP(http://127.0.0.1:8765/mcp)を呼ぶ。否定・組み合わせの指示(「右は上げないで左を下げて」)で、期待どおりのツールだけが呼ばれるか見る。
3. 途中のチェックポイントで、シミュレーター上の動きを比べ、使うステップ数を決める。
4. 学習結果を「学習結果」に追記する。

## 未決事項

- 【将来案】4つのACTを、言語条件付きの1モデル(SmolVLA / π0 を LeRobot で微調整)に置き換える。MCPのツール(`raise_right` など)の形は変えず、中身だけ差し替える。
    - 今は、動作が4つだけ、Macで数時間のうちに学習できる、言語理解はQwenが担当する、という理由でタスクごとのACTにしている(「LLMが計画し、技ごとのポリシーが実行する」SayCan型に近い構成)。
    - まず今の構成で、全体(学習 → 推論ノード → MCP → Hermes)が動くことを確かめる。VLAへの置き換えはその後に試す。
- 先頭の待機フレーム(Start 直後に動かない区間)の切り落としが必要か(本学習の動きを見て判断)
- 学習ステップ数(3000が必要か。途中のチェックポイントで比べて決める)
- chunk_size=50 が下げる動作(約8〜10秒)で足りるか
- 学習の速度(4タスクで約5時間)。重ければ画像の縮小を検討
- obs が約10Hz と粗い。動きがぎこちなければ原因候補
- 各ポリシーの成功率の基準(例:終了時の手先高さ)
- Qwen3.5 9Bが複数ツールの組み合わせを安定して呼べるか(ツール説明文は短く保つ)

## 参考:クラウド側で作った試作(使うときはユーザーが手元に取り込む)

先の会話で、MCPサーバー + 関節角の補間によるdoraノードの試作(`dora-openarm-mcp-teleop`)を作った。FastMCP(streamable-http、127.0.0.1:8765)をdoraノード内のスレッドで動かし、指令ごとに補間して `position_left` / `position_right` を20msごとに出す構成。ステップ5〜6では、補間部分をACT推論に置き換える。

## 進捗ログ(新しい順)

- 2026-10-17: LM Studio + `qwen/qwen3.8-27b` で、自然言語からロボットを動かせた。ログで 7 回のうち 6 回が意図どおり(否定・順番・状態エラーを含む)、「両手下げて」だけ `reset` を選んだ。Hermes はモデルを変えても遅く、LM Studio を使うことにした。`tev1`(分類用モデル)は Hermes 用としては不適と判断。
- 2026-10-17: Claude desktop をクライアントにして Step 7 を予行。「右手上げて」「右手上げないで左手上げて」「左手下げないで右手下げて」で、必要なツールだけが呼ばれ、動かさない腕は保持された。前提エラー(下がっている腕を下げる)も、「右手は既に下がっているので、下げる動作はできません」と理由つきで返った。
- 2026-10-16: 推論ノードと MCP サーバーをシミュレーターで初めて動かし、`call_mcp.py` から raise/lower の4動作とも完了。Step 5・6 完了。`mcp<2` の固定が必要だった。
- 2026-10-16: トリム済みデータでの4タスクの学習(各3000ステップ)が完了。最終lossは 0.62〜0.70 程度。ストレージ不足で `lower_left` が1回止まり、回し直した。次は推論ノードの動作確認。
- 2026-10-15: 推論ノード + MCPサーバー `openarm_act_node.py` を作成(未実行)。`dataflow_act.yaml` と学習環境の追加パッケージを用意。トリム済みデータの4タスク学習は、帰宅後の夜に `train_trim_all.sh` で実行する予定。将来案(言語条件付きVLAへの置き換え)を未決事項に追記。
- 2026-10-15: 待機区間を切り落とした `lerobot_ceiling_trim_<task>` を4タスク分作成。raise_right の本学習(待機区間あり、3000ステップ)が完了し、オフライン確認で待機区間の問題を確認。
- 2026-10-15: 学習環境 `~/lerobot-env`(lerobot 0.6.1)を構築。raise_right の試し学習(300ステップ、8分)が成功。本学習(3000ステップ、save_freq 500)のコマンドと理由を記録。
- 2026-10-14: 学習用に天井カメラ1台のデータセット `lerobot_ceiling_<task>` を作成(4タスクともエピソード数は同じ、画像は ceiling のみを確認)。
- 2026-10-14: 残り3タスクの変換が完了(raise_left 32 / lower_right 31 / lower_left 28 エピソード)。Step 3 完了。
- 2026-10-14: `raise_right` の変換に成功(30エピソード、5389フレーム)。変換条件と理由を記録。空・極端に短いエピソード(ID 24, 7)を除外。このmdを再構成。
- 2026-10-13: 4動作すべての収集が完了。recorder の落ちる問題を修正。
- 2026-10-13: 収集用dataflow・メタデータを生成(Step 1)。カメラは全5台のまま記録すると決定。
- 2026-10-13: mouse-teleop の操作入れ替えを試したが、元に戻した。zの下限はマイナスを許可。
- 2026-10-13: 設計ドキュメントを作成。「下げる」の定義(home に戻す)を確定。このmdを作成。
