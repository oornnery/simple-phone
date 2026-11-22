#!/usr/bin/env bash
# Start (or stop) the Asterisk used by tests/test_asterisk.py, on the host
# network so SIP and RTP need no port mapping.
#   bash scripts/asterisk.sh          start and wait until it answers
#   bash scripts/asterisk.sh stop
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME=simple-phone-asterisk
IMAGE="${ASTERISK_IMAGE:-andrius/asterisk:latest@sha256:9dd770172add68dd06eaf62396d74890b0df427906619c1cf0813afe0c5e4421}"

if [[ "${1:-start}" == stop ]]; then
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    exit 0
fi
docker rm -f "$NAME" >/dev/null 2>&1 || true
mounts=()
for file in pjsip.conf extensions.conf voicemail.conf; do
    mounts+=(-v "$ROOT/tests/asterisk/$file:/etc/asterisk/$file:ro")
done
docker run -d --name "$NAME" --network host "${mounts[@]}" "$IMAGE" >/dev/null
for _ in $(seq 60); do
    if docker exec "$NAME" asterisk -rx "pjsip show endpoints" 2>/dev/null | grep -q 1002; then
        echo "Asterisk ready on 127.0.0.1:5060"
        exit 0
    fi
    sleep 1
done
docker logs "$NAME" | tail -30
echo "Asterisk did not start" >&2
exit 1
