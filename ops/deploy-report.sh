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

[ -f "$REPO_DIR/.env" ] || {
    echo "❌ .env not found (needs CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID)"
    exit 1
}
set -a; source "$REPO_DIR/.env"; set +a

TMPDIR="$(mktemp -d)"
trap "rm -rf '$TMPDIR'" EXIT

cp "$REPORT_HTML" "$TMPDIR/index.html"
echo "📤 Deploying $REPORT_HTML to Cloudflare Pages project '$PROJECT_NAME'"
npx --yes wrangler pages deploy "$TMPDIR" --project-name="$PROJECT_NAME" --branch=main
