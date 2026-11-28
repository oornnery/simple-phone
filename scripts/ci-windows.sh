#!/usr/bin/env bash
# From WSL: copy this checkout to a Windows folder and run scripts/ci-windows.bat
# there (a build on \\wsl$ is very slow).
#   WIN_DIR=/mnt/c/sp/simple-phone  bash scripts/ci-windows.sh [python version]
set -euo pipefail
CMD=/mnt/c/Windows/System32/cmd.exe  # WSL's PATH may not include Windows
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${WIN_DIR:-/mnt/c/sp/simple-phone}"
mkdir -p "$DEST"
rsync -a --delete --exclude .git --exclude .venv --exclude .venv-win --exclude build \
    --exclude dist --exclude packages --exclude '*.so' "$ROOT/" "$DEST/"
# shortcut: WSL's mirrored networking makes Windows refuse UDP ports from
# 46000 up, so the copy's tests move theirs to 36000/37000; on CI they stay.
if grep -qs "networkingMode *= *mirrored" "$(wslpath "$(cd /mnt/c && "$CMD" /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r')")/.wslconfig"; then
    sed -i -E 's/\b46([0-9]{3})\b/36\1/g; s/\b47([0-9]{3})\b/37\1/g' \
        "$DEST"/tests/test_api.py "$DEST"/tests/test_media.py "$DEST"/tests/native_checks.py
fi
cd /mnt/c
"$CMD" /c "cd /d $(wslpath -w "$DEST") && scripts\\ci-windows.bat ${1:-}"
