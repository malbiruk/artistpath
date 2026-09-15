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
# 3. Last of all, once graph.ndjson has grown past COMPACT_RATIO x its live
#    size, stop the collector and rewrite the file keeping only each artist's
#    last record. Last because it is the only destructive step: by then the
#    bins are swapped and verified healthy, so a compaction failure exits into
#    the existing /fail ping without endangering a successful refresh.
#
# The collector keeps running throughout steps 1 and 2: postprocessing reads the
# append-only NDJSON and skips a partially written last line. Only compaction
# stops it, and a trap restarts it on every path out.
#
# The unit's environment comes from .env only, so to override the shrink gate
# after an intentional cleaning change add REFRESH_ALLOW_SHRINK=1 there for one
# run (or run this script by hand with it set).
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
LIVE_BYTES_FILE="$DATA_DIR/live_bytes.txt"    # what graph.ndjson would compact down to
# Compaction holds both copies of graph.ndjson at once, so it needs live_bytes
# free: a higher ratio means a bigger file and less free space at exactly the
# moment more is needed. 3/2 caps the file at ~63 GB and fires every ~2.5 days.
COMPACT_RATIO_NUM=3
COMPACT_RATIO_DEN=2

# Bins this run moved to *.old; cleared once the new build is confirmed healthy.
ROTATED=""
# Set once this run has rebuilt, which means it must also have written
# live_bytes.txt. Compaction's trigger is unreadable without that file.
REBUILT=""
# Set while the collector is stopped for compaction, so the trap can start it
# again on every path out.
COLLECTOR_STOPPED=""

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

# A bin needs restoring if this run rotated it, or if it is missing while its
# *.old exists (a signal can land between the rotation mv and the ROTATED
# bookkeeping). Stale *.old files next to a present live bin are left alone.
needs_restore() {
    [ -f "$DATA_DIR/$1.old" ] && { [[ " $ROTATED " == *" $1 "* ]] || [ ! -f "$DATA_DIR/$1" ]; }
}

swap_in_progress() {
    for b in $BINS; do
        needs_restore "$b" && return 0
    done
    return 1
}

restore_old() {
    for b in $BINS; do
        needs_restore "$b" || continue
        if [ -f "$DATA_DIR/$b" ]; then
            mv -f "$DATA_DIR/$b" "$DATA_DIR/$b.bad"
        fi
        mv -f "$DATA_DIR/$b.old" "$DATA_DIR/$b"
    done
}

on_exit() {
    local rc=$?
    set +e
    # Bins first: a live bin left missing breaks the served graph, while the
    # collector being down another minute only pauses crawling. TimeoutStopSec
    # can SIGKILL this handler, so the more urgent repair goes first.
    if [ "$rc" -ne 0 ]; then
        echo "❌ Refresh failed (exit code $rc)"
        if swap_in_progress; then
            echo "Restoring previous binaries from *.old"
            systemctl --user stop artistpath-backend.service
            restore_old
        fi
        systemctl --user start artistpath-backend.service
    fi
    # Only reachable on a failure or a signal: the success path restarts the
    # collector itself and clears the flag. Which is the point - that is
    # precisely when nothing else would.
    if [ -n "$COLLECTOR_STOPPED" ]; then
        echo "Restarting the collector"
        systemctl --user start artistpath-collector.service
        COLLECTOR_STOPPED=""
    fi
    [ "$rc" -eq 0 ] || ping_hc /fail
}
trap on_exit EXIT
# A signal (systemctl stop, reboot, Ctrl-C) must also run on_exit's rollback.
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

# Both cost tens of GB, and a run that dies holding either pushes free space
# under MIN_FREE_GB - after which every later run exits at that gate before
# reaching anything that would delete them. So they go first, unconditionally.
# Neither is ever the only copy: .new is unverified until the rename, and .old
# is a hardlink to the live file before it and a spent copy after it.
rm -f "$DATA_DIR/graph.ndjson.new" "$DATA_DIR/graph.ndjson.old"

# The collector is only ever deliberately stopped for compaction, and nothing
# restarts it if a signal killed the trap that should have. Same self-heal as
# the bins below; starting a running unit is a no-op.
systemctl --user start artistpath-collector.service

# Self-heal after a SIGKILL or power loss mid-swap (live bin missing, *.old
# present): put the previous build back before doing anything else.
if swap_in_progress; then
    echo "Live binaries missing from an interrupted swap, restoring *.old"
    restore_old
    systemctl --user start artistpath-backend.service
fi

if [ ! -f "$STATE_FILE" ]; then
    echo "No collection_state.json found, skipping"
    exit 0
fi

# Graph records appended, not artists discovered: the collector's oldest-first
# sweep refreshes edges in bulk while adding very few new artists, so gating on
# the processed count would let the served bins sit stale for days.
CURRENT_COUNT=$(cd "$COLLECTION_DIR" && "$UV" run python -c \
    "import json; s = json.load(open('$STATE_FILE')); print(s.get('crawled_total') or len(s['processed_mbids']))")
LAST_COUNT=$(cat "$LAST_COUNT_FILE" 2>/dev/null || echo 0)
DIFF=$((CURRENT_COUNT - LAST_COUNT))
echo "Current: $CURRENT_COUNT, Last refresh: $LAST_COUNT, New: $DIFF"

if [ "$DIFF" -ge "$THRESHOLD" ]; then
    echo "Refreshing: $DIFF records crawled since last refresh"
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

    # The NDJSON only grows, so a build noticeably smaller than the live one
    # means broken input or a cleaning regression. REFRESH_ALLOW_SHRINK=1
    # overrides after an intentional cleaning change.
    if [ "${REFRESH_ALLOW_SHRINK:-0}" != 1 ]; then
        for b in $BINS; do
            [ -f "$DATA_DIR/$b" ] || continue
            live_size=$(stat -c %s "$DATA_DIR/$b")
            new_size=$(stat -c %s "$STAGING_DIR/$b")
            if [ "$new_size" -lt $((live_size * 90 / 100)) ]; then
                echo "Staging $b is $new_size bytes vs $live_size live: refusing a build >10% smaller (REFRESH_ALLOW_SHRINK=1 to override)"
                exit 1
            fi
        done
    fi

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
    REBUILT=1
    echo "$CURRENT_COUNT" > "$LAST_COUNT_FILE"
    echo "Backend serving new data ($CURRENT_COUNT records crawled)"
else
    echo "Only $DIFF new records, skipping rebuild (threshold: $THRESHOLD)"
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

# Compaction, last. live_bytes.txt is written by the rebuild in step 1, so it
# lags by however long ago that was; it only has to be good enough to decide
# whether to look, and run_compaction.py measures the file exactly itself.
# No timer masking needed: this runs inside artistpath-refresh.service, so
# systemd will not start a second rebuild against the file being swapped.
LIVE_BYTES=$(cat "$LIVE_BYTES_FILE" 2>/dev/null || echo 0)
# Missing or half-written: skip, rather than let an unusable trigger value fail
# the whole refresh. The next rebuild writes it again.
[[ "$LIVE_BYTES" =~ ^[0-9]+$ ]] || LIVE_BYTES=0
# Unless this run rebuilt, in which case it wrote the file minutes ago and its
# absence means the writer moved or broke. Worth failing over: compaction
# quietly never running again only shows up as a full disk weeks later.
if [ "$LIVE_BYTES" -eq 0 ] && [ -n "$REBUILT" ]; then
    echo "Rebuilt this run but $LIVE_BYTES_FILE is missing or unreadable"
    exit 1
fi
GRAPH_BYTES=$(stat -c %s "$DATA_DIR/graph.ndjson" 2>/dev/null || echo 0)
if [ "$LIVE_BYTES" -gt 0 ] &&
    [ "$((GRAPH_BYTES * COMPACT_RATIO_DEN))" -gt "$((LIVE_BYTES * COMPACT_RATIO_NUM))" ]; then
    echo "Compacting: graph.ndjson is $GRAPH_BYTES bytes against $LIVE_BYTES live"
    ping_hc /start
    # Claimed before the stop, not after: `systemctl stop` blocks for up to the
    # collector's TimeoutStopSec=300 while it finishes its batch, and a signal
    # landing in that window would otherwise reach the trap with the flag still
    # unset and leave the crawler down. Same race the ROTATED comment describes.
    COLLECTOR_STOPPED=1
    systemctl --user stop artistpath-collector.service
    (cd "$COLLECTION_DIR" && "$UV" run python run_compaction.py --data-dir "$DATA_DIR")
    systemctl --user start artistpath-collector.service
    COLLECTOR_STOPPED=""
    # Dropped now rather than held for tomorrow's rebuild to delete. It is a
    # hardlink sharing blocks with the pre-compaction file, so it insures
    # against a compaction logic bug and nothing else, and the rewrite already
    # proved itself three ways plus a count check against the last rebuild.
    # Holding ~60 GB overnight would leave the rebuild that frees it only a few
    # GB above its own MIN_FREE_GB gate: anything else on the box taking that
    # would deadlock the two against each other permanently.
    rm -f "$DATA_DIR/graph.ndjson.old"
    echo "Compaction complete"
else
    echo "graph.ndjson is $GRAPH_BYTES bytes against $LIVE_BYTES live, skipping compaction"
fi

ping_hc ""
echo "Refresh check complete"
