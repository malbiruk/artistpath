#!/bin/bash
# Ship this checkout to the artistpath service user and restart the backend.
# Run as the admin user from a checkout; relies on
#   /etc/sudoers.d/artistpath:  <admin> ALL=(artistpath) NOPASSWD: ALL
#
# Usage: ops/deploy.sh [--no-build]
#
# Ships the working-tree contents of tracked files (uncommitted edits included;
# git ls-files minus data/) plus the release binary cargo built, so never .env,
# data/, venvs or target/. Files deleted from the repo stay in the service copy,
# and untracked files are not shipped until `git add`.
set -euo pipefail

usage() {
    echo "usage: ops/deploy.sh [--no-build]" >&2
    exit 2
}
BUILD=1
case $# in
0) ;;
1) [ "$1" = --no-build ] || usage; BUILD="" ;;
*) usage ;;
esac

SVC_USER="artistpath"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SVC_HOME="$(getent passwd "$SVC_USER" | cut -d: -f6)" || { echo "❌ no user $SVC_USER"; exit 1; }
SVC_DIR="$SVC_HOME/Services/artistpath"
BINARY="web/backend/target/release/artistpath-web" # its path in the service copy
HEALTH_URL="http://127.0.0.1:3050/health"

# sudo keeps the cwd, which the service user cannot read, and systemctl/podman
# need the service user's runtime dir.
as_svc() {
    (cd / && sudo -u "$SVC_USER" env XDG_RUNTIME_DIR="/run/user/$(id -u "$SVC_USER")" "$@")
}

cd "$REPO_DIR"
if [ -n "$(git ls-files -- .env '*/.env')" ]; then
    echo "❌ a .env file is tracked by git: refusing to ship it"
    exit 1
fi
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "⚠️  Uncommitted changes to tracked files will be shipped as they are:"
    git status --short --untracked-files=no
fi

# Ask cargo where it builds, so CARGO_TARGET_DIR, CARGO_BUILD_TARGET_DIR or a
# build.target-dir setting cannot make this ship a stale binary.
command -v cargo >/dev/null || { echo "❌ cargo is needed to locate the binary" >&2; exit 1; }
TARGET_DIR=$(cd web/backend && cargo metadata --format-version 1 --no-deps |
    python3 -c 'import json, sys; print(json.load(sys.stdin)["target_directory"])')
BUILT="$TARGET_DIR/release/artistpath-web"
if [ -n "$BUILD" ]; then
    echo "🔨 cargo build --release"
    (cd web/backend && cargo build --release)
fi
[ -x "$BUILT" ] || { echo "❌ $BUILT missing: build it or drop --no-build"; exit 1; }
if ldd "$BUILT" | grep 'not found'; then
    echo "❌ $BUILT has unresolved libraries (above)"
    exit 1
fi

FILES=()
while IFS= read -r -d '' f; do
    [[ "$f" == data/* ]] && continue
    [ -e "$f" ] || continue # deleted in the working tree
    FILES+=("$f")
done < <(git ls-files -z --cached)

echo "📦 Shipping ${#FILES[@]} tracked files plus $BINARY (from $BUILT) to $SVC_DIR"
# Unpack into a scratch dir first, so a failed transfer leaves the service copy
# as it was. --remove-destination writes new inodes: the running backend keeps
# its binary until the restart.
SCRATCH=$(as_svc mktemp -d "$SVC_HOME/.deploy.XXXXXX")
trap 'as_svc rm -rf "$SCRATCH"' EXIT
as_svc chmod 0755 "$SCRATCH" # mktemp's 0700 would reach $SVC_DIR through cp -a
printf '%s\0' "${FILES[@]}" | tar --null -T - -cf - | as_svc tar -xf - -C "$SCRATCH"
# shellcheck disable=SC2016 # expanded by the inner shell
as_svc sh -c 'mkdir -p "${1%/*}" && cat >"$1" && chmod 755 "$1"' sh "$SCRATCH/$BINARY" <"$BUILT"
as_svc mkdir -p "$SVC_DIR"
as_svc cp -a --remove-destination "$SCRATCH/." "$SVC_DIR/"

for d in data_collection graph_analysis; do
    echo "🐍 uv sync --frozen in $d"
    as_svc env -C "$SVC_DIR/$d" "$SVC_HOME/.local/bin/uv" sync --frozen
done

as_svc "$SVC_DIR/ops/install-services.sh"
echo "🔄 Restarting artistpath-backend.service"
as_svc systemctl --user restart artistpath-backend.service
deadline=$((SECONDS + 120))
until curl -fsS -m 5 -o /dev/null "$HEALTH_URL" 2>/dev/null; do
    [ "$SECONDS" -lt "$deadline" ] || { echo "❌ Backend not healthy 2 minutes after the restart"; exit 1; }
    sleep 2
done
echo "✅ Backend healthy"

echo "The collector was not restarted (it finishes its batch and saves state on stop). To pick up collector changes:"
echo "   cd / && sudo -u $SVC_USER env XDG_RUNTIME_DIR=/run/user/$(id -u "$SVC_USER") systemctl --user restart artistpath-collector.service"
