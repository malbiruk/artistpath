#!/bin/bash
set -euo pipefail

# The Pages project is also linked to the GitHub repo; its automatic Git
# deployments are paused (empty build config -> an empty production deployment
# that 404s on every push). Keep them paused: this direct upload is the deploy.
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPORT_HTML="$REPO_DIR/graph_analysis/graph_analysis_report.html"
PROJECT_NAME="artistpath-graph-stats"

[ -f "$REPORT_HTML" ] || {
    echo "❌ Report HTML not found at $REPORT_HTML"
    echo "   Re-render with: cd graph_analysis && quarto render graph_analysis_report.py"
    exit 1
}

# The refresh unit passes the credentials in its environment; a dev checkout
# keeps them in .env.
if [ -f "$REPO_DIR/.env" ]; then
    set -a; source "$REPO_DIR/.env"; set +a
fi
[ -n "${CLOUDFLARE_API_TOKEN:-}" ] && [ -n "${CLOUDFLARE_ACCOUNT_ID:-}" ] || {
    echo "❌ CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID must be set (environment or .env)"
    exit 1
}

STAGE_DIR="$(mktemp -d)"
trap "rm -rf '$STAGE_DIR'" EXIT

cp "$REPORT_HTML" "$STAGE_DIR/index.html"
echo "📤 Deploying $REPORT_HTML to Cloudflare Pages project '$PROJECT_NAME'"
npx --yes wrangler pages deploy "$STAGE_DIR" --project-name="$PROJECT_NAME" --branch=main
