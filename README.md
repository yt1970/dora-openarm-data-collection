# Data collection configurations for OpenArm with dora-rs

This repository provides data collection configurations for [OpenArm](https://openarm.dev/) with [dora-rs](https://dora-rs.ai/).

日本語の再現手順(模倣学習 + MCP): [README.ja.md](README.ja.md)

## Setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git,
then run the following from the repository root after cloning:

```bash
git submodule update --init --recursive
uv sync --locked
source .venv/bin/activate
```

[`pyproject.toml`](pyproject.toml) selects Python 3.12, Dora CLI 1.0.1,
and all node dependencies, including `openarm-driver>=0.5.1`.
uv creates `.venv` in this repository and downloads a compatible Python if needed;
no `.python-version` file is required. Nodes under `nodes/` are installed editable,
so Python source edits take effect after restarting the node. The parent project
manages the shared environment and is not installed as a Python package.

Run the dataflow from the same activated shell. [`dataflow.yaml`](dataflow.yaml)
picks the leader and the robot by the `LEADER` and `ROBOT` environment variables.
For example, to use WebXR with MuJoCo (no real arms required):

```bash
./nodes/dora-openarm-webxr/example/prepare_tls.sh "$(hostname).local"
LEADER=webxr ROBOT=mujoco scripts/dora-envsubst run dataflow.yaml --uv
```

See [Configurations](#configurations) for the other leaders and robots, and the
WebXR section below for browser URLs and TLS details.
The dataflow has no package-installing `build` commands; `uv sync --locked`
installs its dependencies, so a separate `dora build` step is not needed.

[`uv.lock`](uv.lock) locks the resolved dependency versions. Editable node source
revisions are pinned by this repository's Git submodule commits; the lockfile
does not freeze uncommitted source changes. In each new terminal, run
`source .venv/bin/activate` before invoking `dora` so that it uses this project's
CLI rather than another program with the same name.

Use `uv sync --locked` after pulling updates. It refuses to change an outdated
lockfile and removes packages outside the managed dependency set. To intentionally
update a dependency, run `uv lock --upgrade-package <package>`, then
`uv sync --locked`, test, and commit the lockfile. After changing dependency
declarations or node submodule revisions, run `uv lock` and commit any resulting
lockfile changes along with the TOML or submodule changes.
See [uv's synchronization rules](https://docs.astral.sh/uv/concepts/projects/sync/).

## Configurations

[`dataflow.yaml`](dataflow.yaml) is the only dataflow. The leader and the robot
are modules next to it picked by environment variables:

| Variable | Values | Picks | Default |
|---|---|---|---|
| `LEADER` | `ker`, `vr`, `webxr`, `dummy` | `leader-$LEADER.yaml` | `dummy` |
| `ROBOT` | `cell` (real Cell), `pedestal`, `mujoco`, `dummy` | `robot-$ROBOT.yaml` | `dummy` |

dora doesn't expand environment variables in `module:` paths
([dora-rs/dora#3805](https://github.com/dora-rs/dora/issues/3805)), so run the
dataflow through [`scripts/dora-envsubst`](scripts/dora-envsubst). It expands
`$VAR`, `${VAR}` and `${VAR:-default}` in `module:` paths, writes the result to
`<name>.envsubst.yaml` and runs the given dora command on it.

Only the selected leader and robot are in the dataflow, so the others open no
device or port. `LEADER=dummy` with `ROBOT=cell` or `ROBOT=pedestal` moves the
real arms with generated motion. See [`docs/design.md`](docs/design.md) for how
the modules are structured.

The UI and the recorder use `metadata_$ROBOT.yaml`, and datasets are recorded
under `data/$LEADER-$ROBOT/`, e.g. `data/webxr-mujoco/`:

| Robot | Metadata | Recorded equipment |
|---|---|---|
| `cell` | [`metadata_cell.yaml`](metadata_cell.yaml) | Arms, lifter, five cameras |
| `pedestal` | [`metadata_pedestal.yaml`](metadata_pedestal.yaml) | Arms only |
| `mujoco` | [`metadata_mujoco.yaml`](metadata_mujoco.yaml) | Arms, five simulated cameras |
| `dummy` | [`metadata_dummy.yaml`](metadata_dummy.yaml) | Arms, five dummy cameras |

### KER leader

`LEADER=ker` uses a [KER](https://github.com/enactic/dora-openarm-ker) leader arm
connected over USB. Its joint positions are sent to the follower arms directly.

### VR leader

`LEADER=vr` receives VR controller poses over UDP by
[dora-openarm-vr](https://github.com/enactic/dora-openarm-vr), converts them to
joint positions by inverse kinematics
([dora-openarm-kinematics](https://github.com/enactic/dora-openarm-kinematics))
and sends them to the follower arms.

### WebXR leader

`LEADER=webxr` uses [dora-openarm-webxr](https://github.com/enactic/dora-openarm-webxr).
It starts a Web server and the Web browser on a VR device such as Meta Quest 3
or PICO 4 connects to it to stream controller poses. No native VR application is
needed.

WebXR requires HTTPS, so a TLS certificate is needed. A self-signed certificate is enough; see the [dora-openarm-webxr setup instructions](https://github.com/enactic/dora-openarm-webxr#setup) for how to generate one. Then run:

```bash
./nodes/dora-openarm-webxr/example/prepare_tls.sh $(hostname).local
LEADER=webxr ROBOT=mujoco scripts/dora-envsubst run dataflow.yaml --uv
```

Open http://localhost:8000/ on the local machine for the data collection UI, and open `https://<host name>:8443/` in the Web browser on your VR device (where `<host name>` is the value passed to `prepare_tls.sh`) to start teleoperation.

### Dummy leader

`LEADER=dummy` generates leader motion without any device. With `ROBOT=dummy`,
we can test the dataflow without any hardware.

### Cell robot

`ROBOT=cell` uses real OpenArm units on CAN, the Cell lifter and wrist, head and
ceiling cameras.

The Cell lifter receives the shared 250 Hz tick and records its elevation action
and observation in millimeters. It uses its built-in startup calibration and hold
behavior, and the left joystick of a VR leader moves it. A real lifter is
required on `can2` by default, and startup enables and moves it for calibration.

### Pedestal robot

`ROBOT=pedestal` uses real OpenArm units on a pedestal over CAN. It has no
lifter and no cameras. The followers use the `openarm_pedestal` configuration.

### MuJoCo robot

`ROBOT=mujoco` uses a MuJoCo simulation
([dora-openarm-mujoco](https://github.com/enactic/dora-openarm-mujoco)) instead
of real OpenArm units and cameras. We can use this for testing teleoperation and
data collection without real hardware.

### Dummy robot

`ROBOT=dummy` doesn't use any hardware. The arms echo their targets and the
cameras send test images.

## Box to tray (imitation learning demo)

This is a bimanual manipulation demo in MuJoCo: the right hand picks up a box
and puts it in the black tray, and the left hand moves out of the way. It is
collected with an iPhone and a mouse, trained with ACT
([LeRobot](https://github.com/huggingface/lerobot)) and exposed as an MCP tool.

### 1. Collect data (iPhone + mouse)

The right arm is controlled by an iPhone (ARKit app in
[`ios/PhoneTeleop/PhoneTeleopApp.swift`](ios/PhoneTeleop/PhoneTeleopApp.swift),
UDP port 5007) and the left arm by the mouse. An arm that receives iPhone poses
is controlled by the iPhone and the other arm by the mouse; if the iPhone stops
sending for about 1.5 seconds, the arm goes back to the mouse. The iPhone and
the Mac must be on the same Wi-Fi router (tethering doesn't work because the
Mac gets no IPv4 address).

```bash
dora run dataflow_box_to_tray.yaml
```

Open http://localhost:8000/ for the UI. The box position is randomized (±3 cm
and yaw) at startup and on every box reset by `--randomize-objects 0.03` in the
MuJoCo node arguments. Press Success only for episodes that put the box in the
tray.

The dataset is written to `data_box_to_tray/dataset/` and is recreated when the
dataflow is restarted. Rename it after each session, e.g.
`data_box_to_tray_bak/dataset_1`, and merge the successful episodes of all
sessions:

```bash
python merge_sessions.py data_box_to_tray_all/dataset \
  data_box_to_tray_bak/dataset_1 data_box_to_tray_bak/dataset_2
```

### 2. Convert and train

Convert to the LeRobot format with only the ceiling camera, at 10 fps, with the
idle part at the beginning and the end of each episode trimmed (run it with the
`openarm_dataset` checkout's environment):

```bash
uv run --project openarm_dataset python convert_box_to_tray_10fps.py
```

This writes `lerobot_ceiling_trim_box_to_tray_10fps/`. Train ACT in a separate
environment that has LeRobot (`lerobot[dataset]`, `lerobot[training]`) and
`mcp<2`:

```bash
lerobot-train \
  --dataset.repo_id=local/ceiling_box_to_tray_10fps \
  --dataset.root=$PWD/lerobot_ceiling_trim_box_to_tray_10fps \
  --policy.type=act --policy.device=mps --policy.push_to_hub=false \
  --policy.chunk_size=50 --policy.n_action_steps=50 \
  --batch_size=8 --steps=10000 --save_freq=2000 \
  --output_dir=outputs/train/act_box_to_tray \
  --job_name=act_box_to_tray --wandb.enable=false
```

It took about 4 hours 15 minutes for 10,000 steps with 33 episodes on an Apple
Silicon Mac.

### 3. Run the policy

To run only the policy in the simulator (no MCP), use the evaluation node. It
starts the policy 3 seconds after startup and stops it after `ACT_RUN_SEC`
seconds. `ACT_MAXSTEP` limits the change of the target per step to reduce
jerky movements:

```bash
ACT_RUN_SEC=70 ACT_REPLAN=50 ACT_MAXSTEP=0.03 dora run dataflow_act_box_to_tray.yaml
```

### 4. Run it from an LLM through MCP

```bash
dora run dataflow_act_v2.yaml
```

`openarm_act_node_v2.py` loads five ACT policies (`raise_right`, `raise_left`,
`lower_right`, `lower_left` and `box_to_tray`) and serves MCP at
`http://127.0.0.1:8765/mcp`:

| Tool | What it does |
|---|---|
| `run_task(task)` | Runs one task. `box_to_tray` needs both arms down and takes up to about 50 seconds. |
| `get_state()` | Returns the logical state (down or raised) and the joint angles of each arm. |
| `reset()` | Returns both arms to the home pose. The box is not moved. |
| `reset_box()` | Returns only the box to its initial position. The arms are not moved. |

The checkpoint paths can be changed by `ACT_CKPT_PATTERN` and `ACT_BOX_CKPT`.

### Patches for the submodules

`patches/` has changes to submodules that are not in their upstream:

- `mujoco-free-camera.patch`: the initial free camera of the MuJoCo viewer
  (field of view 15, center 1.3 0 1.3, azimuth 180, elevation -10; the distance
  can be changed by `DORA_OPENARM_MUJOCO_CAM_DISTANCE`).
- `dataset-recorder-guard.patch`: the recorder no longer crashes when it gets
  success, fail or cancel without start.

Apply them from the repository root:

```bash
git -C nodes/dora-openarm-mujoco apply ../../patches/mujoco-free-camera.patch
git -C nodes/dora-openarm-dataset-recorder apply ../../patches/dataset-recorder-guard.patch
```

## Debugging OpenArm libraries

The OpenArm-specific dependency repositories are checked out under [`lib/`](lib/README.md).
Initialize them with `git submodule update --init --recursive`.

Libraries normally come from the package index at the versions in `uv.lock`.
To use an editable library checkout, run the command for the library you need
from the repository root:

```bash
uv add --editable lib/openarm_driver
# Other optional library checkouts:
# uv add --editable lib/openarm_can/python
# uv add --editable lib/openarm_ker
# uv add --editable lib/openarm_control
# uv add --editable lib/openarm_mujoco
```

`uv add --editable` updates the parent dependency declaration, adds a local path
under `[tool.uv.sources]`, updates the lockfile, and syncs the environment.
Restart the dataflow after editing Python code. CAN bindings use
`lib/openarm_can/python`; changes to their C++ code require rebuilding.

To return to the package-index version, remove that library's entry from
`[tool.uv.sources]`, then run `uv lock` and `uv sync --locked`. Keep required
version constraints such as `openarm-driver>=0.5.1`. Avoid separate `uv pip install`
commands for managed dependencies, since they bypass the project lockfile.

## License

Licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.

Copyright 2026 Enactic, Inc.

## Code of Conduct

All participation in the OpenArm project is governed by our [Code of Conduct](CODE_OF_CONDUCT.md).
