#!/bin/bash
set -euo pipefail

THRESHOLD=100000
REPO_DIR="/var/home/klimasos/Services/artistpath"
DATA_DIR="$REPO_DIR/data"
COLLECTION_DIR="$REPO_DIR/data_collection"
LAST_COUNT_FILE="$DATA_DIR/last_refresh_count.txt"
STATE_FILE="$DATA_DIR/collection_state.json"

if [ ! -f "$STATE_FILE" ]; then
    echo "No collection_state.json found, skipping"
    exit 0
fi

CURRENT_COUNT=$(python3 -c "import json; print(len(json.load(open('$STATE_FILE'))['processed_mbids']))")

LAST_COUNT=0
if [ -f "$LAST_COUNT_FILE" ]; then
    LAST_COUNT=$(cat "$LAST_COUNT_FILE")
fi

DIFF=$((CURRENT_COUNT - LAST_COUNT))
echo "Current: $CURRENT_COUNT, Last refresh: $LAST_COUNT, New: $DIFF"

if [ "$DIFF" -lt "$THRESHOLD" ]; then
    echo "Only $DIFF new artists, skipping refresh (threshold: $THRESHOLD)"
    # Ping healthchecks.io success (check ran, just nothing to do)
    [ -n "${HC_REFRESH_UUID:-}" ] && curl -fsS -m 10 --retry 3 "https://hc-ping.com/$HC_REFRESH_UUID" || true
    exit 0
fi

echo "Refreshing: $DIFF new artists since last refresh"

cd "$COLLECTION_DIR"
/home/klimasos/.local/bin/uv run python run_postprocessing.py

echo "$CURRENT_COUNT" > "$LAST_COUNT_FILE"

systemctl --user restart artistpath-backend.service
echo "Backend restarted with new data"

# Ping healthchecks.io success
[ -n "${HC_REFRESH_UUID:-}" ] && curl -fsS -m 10 --retry 3 "https://hc-ping.com/$HC_REFRESH_UUID" || true

echo "Refresh complete"
