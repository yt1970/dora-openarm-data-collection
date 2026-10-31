# OpenArm MCP:自然言語でロボットを動かす

MuJoCo 上の OpenArm をテレオペで動かしてデータを集め、模倣学習(ACT)した動作を
MCP ツールとして公開し、LLM(LM Studio など)から自然言語で操作するための一式です。

**最新で完全な再現手順は [`README.ja.md`](README.ja.md) にあります**(`box_to_tray`、`reset_box`、iPhone テレオペを含む)。

ベース: [enactic/dora-openarm-data-collection](https://github.com/enactic/dora-openarm-data-collection)
(ライセンスはベースのリポジトリに従います。公開前に確認してください)

## できること

「右手を上げて」「右は上げないで左を下げて」「右手から順番に両腕を下げて」のような指示を、
LLM が解釈して、必要なツールだけを呼びます。

| ツール | 動作 |
| --- | --- |
| `run_task(task)` | `raise_right` / `raise_left` / `lower_right` / `lower_left` / `box_to_tray` のどれか1つを実行(終わってから返る) |
| `get_state()` | 各腕の論理状態(`home` / `raised`)と関節角を返す |
| `reset()` | 両腕を初期姿勢に戻す(学習した動作ではなく、補間。箱は動かさない) |
| `reset_box()` | 箱だけを初期位置に戻す(腕は動かさない) |

- 動かさない側の腕は、直前の目標を保持します。
- 上がっている腕を上げる、下がっている腕を下げる、は理由つきエラーを返します(モデルが誤って呼んでも止まります)。
- 文の解釈(否定・組み合わせ)は、MCP サーバーではなく LLM が行います。

## 全体の流れ

```text
マウスのテレオペで収集(dora-rs + MuJoCo)
  → LeRobot 形式に変換(openarm-dataset-convert)
  → 動作ごとに ACT を学習(lerobot-train、4つ)
  → 推論ノード + MCP サーバー(openarm_act_node.py)
  → LLM(LM Studio など)から自然言語で操作
```

動作ごとに別のモデルを学習しています(ACT は言語入力を持たないため)。

## 環境

Python 環境を 2 つに分けています。

| 環境 | 用途 |
| --- | --- |
| `.venv`(収集用) | `dora` コマンド、収集、変換 |
| `~/lerobot-env`(学習・推論用) | `lerobot`、推論ノード。`dora-rs` `mcp<2` `opencv-python` `pyarrow` が必要 |

```bash
source ~/lerobot-env/bin/activate
uv pip install lerobot 'lerobot[dataset]' 'lerobot[training]'
uv pip install dora-rs 'mcp<2' opencv-python pyarrow
```

`mcp` は 2.x だと `FastMCP` が無くなるため、`mcp<2` に固定します。

## 手順

### 1. 収集(マウスのテレオペ)

動作ごとに dataflow を用意しています(`dataflow_{raise,lower}_{right,left}.yaml`)。

```bash
source .venv/bin/activate
dora run dataflow_raise_right.yaml     # 他の3動作も同様
```

ブラウザで http://localhost:8000 を開いて操作します。マウスのドラッグで手先の x/y、
↑↓キーで z、ホイールでグリッパ、←→で操作する腕を切り替えます。
「下げる」のデータは、先に腕を上げてから Start を押して記録します。

### 2. 変換

```bash
python convert_ceiling_trimmed.py
```

天井カメラ1台のみ、動き出す前後の待機区間を切り落として、`lerobot_ceiling_trim_<task>/` に出力します。

### 3. 学習

```bash
caffeinate -i bash train_trim_all.sh
```

4動作を順に、各 3000 ステップ学習します(MacBook Air の MPS で、合計約6時間)。
出力は `outputs/train/act_trim_<task>/checkpoints/` です。

### 4. 起動

```bash
source .venv/bin/activate
dora run dataflow_act.yaml
```

MuJoCo のシミュレーターと、推論ノード(MCP サーバー、`http://127.0.0.1:8765/mcp`)が起動します。

### 5. LLM につなぐ

`mcp/openarm.mcp.json` の内容を、LM Studio や Claude desktop の MCP 設定に追加します。
HTTP の MCP を橋渡しするため `mcp-remote`(`npx`)を使います。`command` は `which npx` のパスに合わせてください。

動作確認用の簡易クライアントもあります。

```bash
source ~/lerobot-env/bin/activate
python call_mcp.py get_state
python call_mcp.py run_task '{"task": "raise_right"}'
```

MCP の呼び出しは `mcp_act_log.jsonl` に記録されます。LLM の返事ではなく、この記録で、
実際に呼ばれたツールを確認してください。

## 主なファイル

| ファイル | 役割 |
| --- | --- |
| `dataflow_*.yaml` | 収集用 / 推論用の dora dataflow(`dataflow_act.yaml` が推論用) |
| `openarm_act_node.py` | 推論ノード + MCP サーバー |
| `call_mcp.py` | MCP の簡易クライアント |
| `convert_ceiling_trimmed.py` | 変換(天井カメラ、待機区間のトリム) |
| `train_trim_all.sh` | 4動作の学習 |
| `check_policy_offline.py` | 学習済みポリシーの出力を、データと比べる確認用 |
| `mcp/openarm.mcp.json` | LLM 側の MCP 設定の例 |
| `OPENARM_MCP_PROGRESS.md` | 進捗・設計判断・条件と理由の記録 |

## 既知の課題

- 動きがぎこちない(ACT を、チャンクごとにまとめて出力する方式で動かしているため。改善案は進捗mdを参照)。
- `reset` の戻り先(`HOME`)は仮の値。グリッパ値が実際の初期状態と少し違う。
- 腕の状態は、実行した動作から数えた論理状態(実測ではない)。
- Hermes では、MCP を通した応答が遅かった(原因は調査中)。LM Studio では問題なく動作。
- 成功率の評価は未実施(目視での確認のみ)。
