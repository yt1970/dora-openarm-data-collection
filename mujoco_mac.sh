#!/usr/bin/env bash
set -euo pipefail

LIBPYTHON_DIR="$(.venv/bin/python -c 'import sys, os; print(os.path.join(sys.base_prefix, "lib"))')"
export DYLD_FALLBACK_LIBRARY_PATH="${LIBPYTHON_DIR}${DYLD_FALLBACK_LIBRARY_PATH:+:${DYLD_FALLBACK_LIBRARY_PATH}}"
exec .venv/bin/mjpython -c 'from dora_openarm_mujoco.main import main; raise SystemExit(main())' "$@"