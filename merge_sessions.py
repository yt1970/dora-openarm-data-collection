import shutil
import sys
from pathlib import Path

import yaml

SKIP = {("dataset_2", "36"),}
out = Path(sys.argv[1])
sessions = [Path(p) for p in sys.argv[2:]]
if out.exists():
    sys.exit(f"{out} already exists. Remove it or choose another name.")

base = yaml.safe_load((sessions[0] / "metadata.yaml").read_text())
(out / "episodes").mkdir(parents=True)

episodes = []
n = 0
for s in sessions:
    meta = yaml.safe_load((s / "metadata.yaml").read_text())
    for ep in meta["episodes"]:
        if not ep["success"]:
            continue
        if (s.name, str(ep["id"])) in SKIP:
            print(f"skip (excluded): {s.name}/{ep['id']}")
            continue        
        src = s / "episodes" / str(ep["id"])
        if not src.is_dir():
            print(f"skip (no folder): {src}")
            continue
        shutil.copytree(src, out / "episodes" / str(n))
        episodes.append({"id": str(n), "success": True, "task_index": ep["task_index"]})
        print(f"{src} -> {n}")
        n += 1

base["episodes"] = episodes
(out / "metadata.yaml").write_text(yaml.safe_dump(base, sort_keys=True, allow_unicode=True))
print(f"done: {n} successful episodes -> {out}")