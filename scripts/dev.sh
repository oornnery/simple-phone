#!/usr/bin/env bash
# Bootstrap a source checkout; extra arguments are passed to uv sync.
source "$(dirname "$0")/common.sh"
require_uv
ensure_native
uv sync --locked --all-extras "$@"
"$ROOT/.venv/bin/simple-phone" --version
