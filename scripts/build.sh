#!/usr/bin/env bash
# Generate a wheel for the chosen Python; extra arguments go to uv build.
source "$(dirname "$0")/common.sh"
require_uv
ensure_native
# setuptools can retain Python modules moved by the source reorganization.
if [[ ! -x "$PYTHON" ]]; then
    PYTHON="$(command -v python3)"
fi
"$PYTHON" scripts/check_package.py --clean-build
uv build --wheel "$@"
# uv build accepts --out-dir; do not assume that all builds write to dist/.
