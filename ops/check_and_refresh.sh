#!/bin/bash
# Daily data refresh (run by artistpath-refresh.timer).
#
# 1. Once at least THRESHOLD artists have been crawled since the last refresh,
#    rebuild graph.bin / rev-graph.bin / metadata.bin into data/staging (the
#    live backend mmaps data/*.bin, so they are never written in place), then
#    stop the backend, rotate the live bins to *.old, move the staging bins in,
#    start the backend and wait for /health. Any failure after the rotation
#    restores *.old (the rejected build is kept as *.bad).
# 2. Whenever the served data is newer than the analytics report, recompute the
#    graph metrics, re-render the report and deploy it to Cloudflare Pages.
#
# The collector keeps running throughout: postprocessing reads the append-only
# NDJSON and skips a partially written last line.
set -euo pipefail

THRESHOLD=100000
REPO_DIR="/var/home/klimasos/Services/artistpath"
DATA_DIR="$REPO_DIR/data"
STAGING_DIR="$DATA_DIR/staging"
COLLECTION_DIR="$REPO_DIR/data_collection"
ANALYSIS_DIR="$REPO_DIR/graph_analysis"
STATE_FILE="$DATA_DIR/collection_state.json"
LAST_COUNT_FILE="$DATA_DIR/last_refresh_count.txt"  # artists crawled when the served bins were built
REPORT_COUNT_FILE="$DATA_DIR/last_report_count.txt" # ... when the report was last deployed
UV="/home/klimasos/.local/bin/uv"
QUARTO="/home/klimasos/.local/bin/quarto"
HEALTH_URL="http://localhost:3050/health"
BINS="graph.bin rev-graph.bin metadata.bin"
MIN_FREE_GB=40

# Bins this run moved to *.old; cleared once the new build is confirmed healthy.
ROTATED=""

ping_hc() {
    [ -n "${HC_REFRESH_UUID:-}" ] || return 0
    curl -fsS -m 10 --retry 3 "https://hc-ping.com/$HC_REFRESH_UUID$1" >/dev/null || true
}

wait_healthy() {
    for _ in $(seq 60); do
        curl -fsS -m 5 "$HEALTH_URL" >/dev/null 2>&1 && return 0
        sleep 10
    done
    return 1
}

restore_old() {
    for b in $ROTATED; do
        if [ -f "$DATA_DIR/$b" ]; then
            mv -f "$DATA_DIR/$b" "$DATA_DIR/$b.bad"
        fi
        mv -f "$DATA_DIR/$b.old" "$DATA_DIR/$b"
    done
}

on_exit() {
    local rc=$?
    set +e
    if [ "$rc" -eq 0 ]; then
        return 0
    fi
    echo "❌ Refresh failed (exit code $rc)"
    if [ -n "$ROTATED" ]; then
        echo "Restoring previous binaries from *.old"
        systemctl --user stop artistpath-backend.service
        restore_old
    fi
    systemctl --user start artistpath-backend.service
    ping_hc /fail
}
trap on_exit EXIT

if [ ! -f "$STATE_FILE" ]; then
    echo "No collection_state.json found, skipping"
    exit 0
fi

CURRENT_COUNT=$(cd "$COLLECTION_DIR" && "$UV" run python -c \
    "import json; print(len(json.load(open('$STATE_FILE'))['processed_mbids']))")
LAST_COUNT=$(cat "$LAST_COUNT_FILE" 2>/dev/null || echo 0)
DIFF=$((CURRENT_COUNT - LAST_COUNT))
echo "Current: $CURRENT_COUNT, Last refresh: $LAST_COUNT, New: $DIFF"

if [ "$DIFF" -ge "$THRESHOLD" ]; then
    echo "Refreshing: $DIFF new artists since last refresh"
    ping_hc /start

    rm -rf "$STAGING_DIR"
    FREE_GB=$(df --output=avail -BG "$DATA_DIR" | tail -1 | tr -dc '0-9')
    if [ "$FREE_GB" -lt "$MIN_FREE_GB" ]; then
        echo "Only ${FREE_GB}G free on $DATA_DIR, need ${MIN_FREE_GB}G for a staging build"
        exit 1
    fi

    mkdir -p "$STAGING_DIR"
    (cd "$COLLECTION_DIR" && "$UV" run python run_postprocessing.py --out-dir "$STAGING_DIR")
    for b in $BINS; do
        if [ ! -s "$STAGING_DIR/$b" ]; then
            echo "Staging build missing $b"
            exit 1
        fi
    done

    systemctl --user stop artistpath-backend.service
    for b in $BINS; do
        if [ -f "$DATA_DIR/$b" ]; then
            mv -f "$DATA_DIR/$b" "$DATA_DIR/$b.old"
            ROTATED="$ROTATED $b"
        fi
    done
    for b in $BINS; do
        mv -f "$STAGING_DIR/$b" "$DATA_DIR/$b"
    done
    rm -rf "$STAGING_DIR"
    systemctl --user start artistpath-backend.service

    if ! wait_healthy; then
        echo "❌ Backend unhealthy with new data, rolling back"
        exit 1
    fi
    ROTATED=""
    echo "$CURRENT_COUNT" > "$LAST_COUNT_FILE"
    echo "Backend serving new data ($CURRENT_COUNT artists crawled)"
else
    echo "Only $DIFF new artists, skipping rebuild (threshold: $THRESHOLD)"
fi

if [ -f "$LAST_COUNT_FILE" ] && [ "$(cat "$REPORT_COUNT_FILE" 2>/dev/null)" != "$(cat "$LAST_COUNT_FILE")" ]; then
    echo "Updating analytics report"
    cd "$ANALYSIS_DIR"
    "$UV" run python calculate_graph_metrics.py
    QUARTO_PYTHON="$ANALYSIS_DIR/.venv/bin/python" "$QUARTO" render graph_analysis_report.py
    "$REPO_DIR/ops/deploy-report.sh"
    cp "$LAST_COUNT_FILE" "$REPORT_COUNT_FILE"
    echo "Report deployed"
fi

ping_hc ""
echo "Refresh check complete"
