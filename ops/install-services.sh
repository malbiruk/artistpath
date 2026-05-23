#!/bin/bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SYSTEMD_DIR="$HOME/.config/systemd/user"
QUADLET_DIR="$HOME/.config/containers/systemd"

mkdir -p "$SYSTEMD_DIR" "$QUADLET_DIR"

echo "Installing from $REPO_DIR/ops/"

for unit in "$REPO_DIR"/ops/*; do
    name="$(basename "$unit")"
    case "$name" in
        *.container)
            cp "$unit" "$QUADLET_DIR/$name"
            echo "  installed $name -> containers/systemd/ (quadlet)"
            ;;
        *.service|*.timer)
            cp "$unit" "$SYSTEMD_DIR/$name"
            echo "  installed $name -> systemd/user/"
            ;;
        *)
            echo "  skipped $name (not a unit file)"
            ;;
    esac
done

systemctl --user daemon-reload
echo "Daemon reloaded."

echo ""
echo "To enable services:"
echo "  systemctl --user enable --now artistpath-backend.service"
echo "  systemctl --user enable --now cloudflared.service"
echo "  systemctl --user enable --now artistpath-collector.service"
echo "  systemctl --user enable --now artistpath-refresh.timer"
echo "  systemctl --user enable --now artistpath-healthcheck.timer"
echo ""
echo "Don't forget: loginctl enable-linger $USER"
