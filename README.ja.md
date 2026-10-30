# OpenArm 模倣学習 × MCP:自然言語でロボットを動かす(日本語ガイド)

MuJoCo 上の OpenArm を、テレオペで動かしてデータを集め、模倣学習(ACT)した動作を
MCP ツールとして公開し、LLM(LM Studio など)から自然言語で操作する一式です。
講習の最終課題として作りました。評価の方が再現できるように、手順を最後までまとめています。

ベース: [enactic/dora-openarm-data-collection](https://github.com/enactic/dora-openarm-data-collection)
(ライセンスは Apache License 2.0。[LICENSE](LICENSE) を参照)

レポートは [`report.md`](report.md)、設計判断と条件・理由の記録は
[`OPENARM_MCP_PROGRESS.md`](OPENARM_MCP_PROGRESS.md) にあります。

## できること

| 動作 | 内容 | 学習データ |
| --- | --- | --- |
| `raise_right` / `raise_left` | 右手 / 左手を上げる | マウスのテレオペ(各約30本) |
| `lower_right` / `lower_left` | 右手 / 左手を下げる | マウスのテレオペ(各約30本) |
| `box_to_tray` | 両腕が下がった状態から、右手で箱を持ち上げて黒いトレーに入れる | マウス+iPhone のテレオペ(33本) |

「右は上げないで左を下げて」「右手から順番に両腕を下げて」といった指示を、LLM が解釈して、
必要なツールだけを呼びます。文の解釈は、MCP サーバーではなく LLM が行います。

## MCP のツール

| ツール | 内容 |
| --- | --- |
| `run_task(task)` | 上の5動作のどれか1つを実行する(終わってから返る。`box_to_tray` は最大約50秒) |
| `get_state()` | 各腕の論理状態(`home` / `raised`)と関節角 |
| `reset()` | 両腕を初期姿勢に戻す(箱は動かさない) |
| `reset_box()` | 箱だけを初期位置に戻す(腕は動かさない。動作中は実行できない) |

- 動かさない側の腕は、直前の目標を保持します(4動作)。
- 上がっている腕を上げる、下がっている腕を下げる、などは理由つきエラーで止めます。
- `box_to_tray` は、両腕が下がっているときだけ実行できます。

## 全体の流れ

```text
テレオペで収集(dora-rs + MuJoCo)
  → LeRobot 形式に変換(openarm_dataset)
  → 動作ごとに ACT を学習(lerobot-train。計5つ)
  → 推論ノード + MCP サーバー(openarm_act_node_v2.py)
  → LLM(LM Studio など)から自然言語で操作
```

動作ごとに別のモデルを学習します(ACT は言語入力を持たないため)。

## 必要なもの

- Apple Silicon の Mac(動作確認: MacBook Air。学習は MPS を使うので、数時間かかります)
- Python 3.12、[uv](https://docs.astral.sh/uv/getting-started/installation/)、Git
- Node.js(`npx`。LLM と MCP をつなぐ `mcp-remote` に使う)
- LM Studio(または Claude desktop)など、MCP が使える LLM クライアント
- `box_to_tray` のデータをもう一度集める場合だけ: iPhone(ARKit 対応。動作確認は iPhone 16)と、Xcode(Apple ID は無料で可)

## 0. セットアップ

### リポジトリ

```bash
git clone --recursive https://github.com/yt1970/dora-openarm-data-collection.git
cd dora-openarm-data-collection
```

### 収集・変換・起動用の環境(`.venv`)

```bash
uv venv --python 3.12
source .venv/bin/activate
uv sync                      # pyproject.toml の依存関係を入れる
uv pip install pip           # dataflow の build コマンドが pip を使うため
```

`dora` コマンドは、この環境で実行します(Python 3.12 の環境で、`pip` が `.venv` のものであることを
`which pip` で確認してください。pyenv の `pip` が使われると、`requires a different Python` で失敗します)。

### 変換用ライブラリ(`openarm_dataset`)

リポジトリ直下に、enactic の `openarm_dataset` を置きます(このリポジトリには含めていません)。

```bash
git clone https://github.com/enactic/openarm_dataset.git
```

変換のスクリプトは、`uv run --project openarm_dataset python ...` で実行します。

### 学習・推論用の環境(`~/lerobot-env`)

```bash
uv venv --python 3.12 ~/lerobot-env
source ~/lerobot-env/bin/activate
uv pip install lerobot 'lerobot[dataset]' 'lerobot[training]'
uv pip install dora-rs 'mcp<2' opencv-python pyarrow
deactivate
```

`mcp` は 2.x だと `FastMCP` が無くなるため、`mcp<2` に固定します。

### サブモジュールへのパッチ

次の2つは、サブモジュール(enactic のリポジトリ)に対する、自作の変更です。パッチとして `patches/` に入れてあります。

```bash
git -C nodes/dora-openarm-mujoco apply ../../patches/mujoco-free-camera.patch
git -C nodes/dora-openarm-dataset-recorder apply ../../patches/dataset-recorder-guard.patch
```

- `mujoco-free-camera.patch`: ビューアのフリーカメラの初期位置(視野角 15、中心 1.3 0 1.3、方位角 180、仰角 -10)。
  距離は環境変数 `DORA_OPENARM_MUJOCO_CAM_DISTANCE` で変えられます(既定 2.5)。
- `dataset-recorder-guard.patch`: Start なしで success / fail / cancel を受けても、recorder が落ちないようにする修正。

### パスの書き換え

推論用の dataflow(`dataflow_act*.yaml`)には、Python と推論ノードの場所が、作者の環境の絶対パスで書かれています。
自分の環境に合わせて、書き換えてください(リポジトリの場所と、`~/lerobot-env` の場所に置き換えます)。

```bash
sed -i '' "s|/Users/yutako/dora-openarm-data-collection|$PWD|g; s|/Users/yutako/lerobot-env|$HOME/lerobot-env|g" \
  dataflow_act.yaml dataflow_act_v2.yaml dataflow_act_box_to_tray.yaml
```

`mcp/openarm.mcp.json` の `command`(`npx` の場所)も、`which npx` の結果に合わせてください。

## 1. 学習から再現する(変換済みデータを使う)

収集と変換を省いて、学習から試せるように、変換済みの LeRobot データセットを同梱しています
(天井カメラ1台・待機区間を切り落とした版)。

| フォルダ | 内容 |
| --- | --- |
| `lerobot_ceiling_trim_raise_right` / `_raise_left` / `_lower_right` / `_lower_left` | 4動作(30 fps) |
| `lerobot_ceiling_trim_box_to_tray_10fps` | `box_to_tray`(10 fps、33エピソード、11,376 フレーム) |

```bash
bash train_trim_all.sh        # 4動作。各3000ステップ、合計で約6時間
bash train_box_to_tray.sh     # box_to_tray。10000ステップ、約4時間15分
```

出力は、`outputs/train/act_trim_<task>/checkpoints/` と `outputs/train/act_box_to_tray/checkpoints/` です。
学習済みのモデル(チェックポイント)は、容量が大きい(1つ約200 MB)ため、リポジトリには含めていません。

## 2. 起動して動かす

```bash
source .venv/bin/activate
dora run dataflow_act_v2.yaml
```

MuJoCo のシミュレーターと、推論ノード(MCP サーバー、`http://127.0.0.1:8765/mcp`)が起動します。
5つのポリシーをすべて読み込むため、1節の学習を5つとも済ませておく必要があります。

`box_to_tray` だけを試す場合は、MCP を通さない評価用のノードを使えます。
起動の3秒後からポリシーを動かし、`ACT_RUN_SEC` 秒で止めます。

```bash
ACT_RUN_SEC=70 ACT_REPLAN=50 ACT_MAXSTEP=0.03 dora run dataflow_act_box_to_tray.yaml
```

`ACT_MAXSTEP` は、1回の指令あたりの目標の最大変化(rad)で、小さいほどなめらかに(遅く)動きます。

### 簡易クライアントで確かめる

別のターミナルで、`~/lerobot-env` の Python で実行します(`mcp<2` が入っている環境です)。

```bash
~/lerobot-env/bin/python call_mcp.py get_state
~/lerobot-env/bin/python call_mcp.py run_task '{"task": "raise_right"}'
~/lerobot-env/bin/python call_mcp.py run_task '{"task": "lower_right"}'
~/lerobot-env/bin/python call_mcp.py run_task '{"task": "box_to_tray"}'
~/lerobot-env/bin/python call_mcp.py reset_box '{}'
```

呼び出しは `mcp_act_log.jsonl` に記録されます。

## 3. LLM につなぐ

`mcp/openarm.mcp.json` の内容を、LM Studio(または Claude desktop)の MCP 設定に追加します。

```json
{
  "mcpServers": {
    "openarm": {
      "command": "/opt/homebrew/bin/npx",
      "args": ["-y", "mcp-remote", "http://127.0.0.1:8765/mcp"]
    }
  }
}
```

動作確認は、LM Studio + `qwen/qwen3.8-27b` で行いました。次のような指示を試せます。

- 右手を上げて
- 右手下げないで左手上げて
- 右手から順番に両腕下げて
- (両腕が下がった状態で)箱をトレーに入れて
- 箱を元に戻して

LLM の返事ではなく、`mcp_act_log.jsonl` で、実際に呼ばれたツールを確認してください。

```bash
tail -n 10 mcp_act_log.jsonl
```

## 4. データを集めるところから再現する

ここは、ロボットのシミュレーターを操作して、データを集め直す手順です(1節で同梱のデータを使うなら不要です)。

### 4動作(マウスのテレオペ)

```bash
source .venv/bin/activate
dora run dataflow_raise_right.yaml     # 他の動作は dataflow_{raise_left,lower_right,lower_left}.yaml
```

ブラウザで http://localhost:8000/ を開いて操作します。

| 操作 | 内容 |
| --- | --- |
| パッドをドラッグ | 手先の前後左右 |
| ↑↓ キー | 手先の高さ |
| ホイール | グリッパの開閉 |
| ←→ キー | 操作する腕の切り替え |
| R キー | 箱のリセット |

- 「下げる」のデータは、先に腕を上げてから Start を押して記録します。
- 動かさない側の腕は、半分のエピソードで home、残り半分で上げた状態にします。
- 結果は `data_<task>/dataset/` に保存されます。

### `box_to_tray`(マウス + iPhone の双腕テレオペ)

右腕を iPhone(ARKit)、左腕をマウスで同時に操作します。

```text
iPhone(ARKit・Swift アプリ) → UDP 5007 → iphone-teleop ノード → 逆運動学(IK) → MuJoCo
```

#### iPhone アプリ(`ios/PhoneTeleop/PhoneTeleopApp.swift`)

1. Xcode で、SwiftUI の iOS アプリを新規に作ります(名前は `PhoneTeleop`)。
2. 生成された `PhoneTeleopApp.swift` を、このリポジトリのファイルで置き換えます。
3. Signing に、自分の Apple ID(無料で可)を設定します。
4. 情報(Info)に、カメラの利用目的(`NSCameraUsageDescription`)と、ローカルネットワークの利用目的
   (`NSLocalNetworkUsageDescription`)を追加します(ARKit がカメラを使い、UDP でパソコンに送るため)。
5. iPhone に入れて起動します。無料の署名は 7 日で切れるので、そのときは再ビルドします。

#### 収集

```bash
source .venv/bin/activate
dora run dataflow_box_to_tray.yaml
```

- パソコンと iPhone は、同じ Wi-Fi ルーターにつなぎます(iPhone のテザリングは、パソコンに IPv4 のアドレスが付かず使えません)。
  パソコンのIPアドレスは `ipconfig getifaddr en0` で調べます。
- アプリに、パソコンの IP アドレスを入れ、iPhone を前に向けて「接続」を押します(この向きがその端末の「前」になります)。
- 左右どちらの腕を担当するか(右腕)を選び、「追従」をオンにした瞬間の端末の姿勢を基準に、腕が動きます。
  窮屈になったら、オフにして持ち直し、またオンにします(ラチェット操作)。背面カメラを指でふさがないでください。
- 縦のスライダーでグリッパを開閉します(上が閉、下が開)。「腕リセット」で起動時の姿勢に戻します。
- iPhone が姿勢を送っている腕は iPhone、それ以外の腕(左腕)はマウスで操作します。送信が約 1.5 秒途切れると、その腕はマウスに戻ります。
- 箱の初期位置は、起動時と箱のリセット(R キー)のたびに、前後左右 ±3 cm と向きがランダムにずれます(`--randomize-objects 0.03`)。
- 箱をトレーに入れられたエピソードだけ、UI で Success を押します。
- 保存先は `data_box_to_tray/dataset/` です。**起動し直すと、同じ場所が空から作り直される**ので、
  終わるたびに名前を変えて退避してください(例: `data_box_to_tray_bak/dataset_1`、`dataset_2`)。

複数のセッションは、成功したエピソードだけを集めて、1つのデータセットにまとめます(番号は振り直されます)。

```bash
python merge_sessions.py data_box_to_tray_all/dataset \
  data_box_to_tray_bak/dataset_1 data_box_to_tray_bak/dataset_2
```

### 変換

```bash
# 4動作(天井カメラ1台・待機区間のトリム)
uv run --project openarm_dataset python convert_ceiling_trimmed.py

# box_to_tray(10 fps)
uv run --project openarm_dataset python convert_box_to_tray_10fps.py
```

出力は `lerobot_ceiling_trim_<task>/` と `lerobot_ceiling_trim_box_to_tray_10fps/` です。
`convert_box_to_tray_10fps.py` は、入力に `data_box_to_tray_all/dataset` を読みます。

## 結果(要点)

| 項目 | 内容 |
| --- | --- |
| 4動作の学習 | 各3000ステップ。最終 loss は 0.62〜0.70 |
| `box_to_tray` の学習 | 33エピソード、10000ステップ。最終 loss 0.186(l1 0.140) |
| LLM からの呼び出し(4動作) | 7回のうち、意図どおりが6回。否定と順番の指示も扱えた |
| `box_to_tray` のシミュレーター評価 | 9回のうち6回成功(失敗は、最初の掴み損ねから立て直せなかったもの) |

詳しくは [`report.md`](report.md) を参照してください。

## 主なファイル

| ファイル | 役割 |
| --- | --- |
| `dataflow_{raise,lower}_{right,left}.yaml` | 4動作の収集用 dataflow(マウス) |
| `dataflow_box_to_tray.yaml` | `box_to_tray` の収集用 dataflow(マウス + iPhone) |
| `dataflow_act.yaml` / `dataflow_act_v2.yaml` | 推論 + MCP の dataflow(v2 は `box_to_tray` を含む5動作) |
| `dataflow_act_box_to_tray.yaml` | `box_to_tray` だけを、MCP なしで動かす評価用 dataflow |
| `openarm_act_node.py` / `openarm_act_node_v2.py` | 推論ノード + MCP サーバー(v2 は `box_to_tray` と `reset_box` を追加) |
| `openarm_act_eval_node.py` | `box_to_tray` の評価用ノード |
| `call_mcp.py` | MCP の簡易クライアント |
| `convert_ceiling_trimmed.py` | 4動作の変換 |
| `convert_box_to_tray.py` / `convert_box_to_tray_10fps.py` | `box_to_tray` の変換(30 fps / 10 fps) |
| `merge_sessions.py` | 複数セッションの成功エピソードを結合 |
| `train_trim_all.sh` / `train_box_to_tray.sh` | 学習 |
| `check_policy_offline.py` | 学習済みポリシーの出力を、データと比べる確認用 |
| `nodes/dora-openarm-iphone-teleop/` | iPhone の姿勢を受け取るノード |
| `nodes/dora-openarm-mouse-teleop/` | マウスのテレオペ |
| `ios/PhoneTeleop/PhoneTeleopApp.swift` | iPhone アプリ |
| `mcp/openarm.mcp.json` | LLM 側の MCP 設定の例 |
| `patches/` | サブモジュールへのパッチ |
| `report.md` / `OPENARM_MCP_PROGRESS.md` | レポート / 進捗・設計判断の記録 |

## 既知の課題

- 動きがぎこちない。ACT が 5 秒分(10 fps で 50 ステップ)の動きをまとめて出し、つなぎ目で動きが不連続になる。
  `ACT_MAXSTEP` で軽減できるが、完全には消えない。
- `box_to_tray` の成功率は約 7 割で、最初の掴み損ねから立て直せない。掴み直しを含むデータの追加が必要。
- `reset` の戻り先(`HOME`)は仮の値。腕の状態は、実行した動作から数えた論理状態(実測ではない)。
- Hermes では、MCP を通した応答が遅かった(原因は調査中)。LM Studio では問題なく動作する。
- シミュレーターのみで、実機では確かめていない。iPhone 2 台での両手同時の操作も未確認。
