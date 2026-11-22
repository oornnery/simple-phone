#!/usr/bin/env bash
# Shared by the project scripts; sourced, not an application entry point.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON="$ROOT/.venv/bin/python"

require_uv() {
    command -v uv >/dev/null || { echo "Install uv >= 0.13.7 first." >&2; exit 1; }
}

require_env() {
    if [[ ! -x "$PYTHON" ]]; then
        echo "Prepare the project first: bash scripts/dev.sh" >&2
        exit 1
    fi
}

ensure_native() {
    if ! bash "$ROOT/scripts/build_pjsip.sh" --check; then
        bash "$ROOT/scripts/build_pjsip.sh"
    fi
}
