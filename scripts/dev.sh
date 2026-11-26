#!/usr/bin/env bash
# Bootstrap a source checkout; extra arguments are passed to uv sync.
source "$(dirname "$0")/common.sh"
require_uv
ensure_native
uv sync --locked --all-extras "$@"
# .githooks/pre-push runs scripts/ci.sh before every push
git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 && git -C "$ROOT" config core.hooksPath .githooks
"$ROOT/.venv/bin/simple-phone" --version
