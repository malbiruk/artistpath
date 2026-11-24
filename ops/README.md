# Running artistpath as a service

The public instance runs the backend, the collector, a healthcheck and the nightly data refresh as systemd user units of a dedicated Unix user, `artistpath`, with the Cloudflare tunnel as a rootless Podman Quadlet ([`cloudflared.container`](cloudflared.container)). The units in this directory use `%h`, so they work for whichever user installs them.

Requirements:

- A service user with lingering enabled (`loginctl enable-linger artistpath`), and a sudoers rule that lets the admin act as it: `<admin> ALL=(artistpath) NOPASSWD: ALL`.
- In the service user's `~/.local/bin`: [uv](https://docs.astral.sh/uv/) and [Quarto](https://quarto.org/). On the host: Podman, `pasta` (package `passt`, the report render runs inside it) and Node.js (`npx wrangler` publishes the report).
- The dataset in the service user's `~/Services/artistpath/data/`, with the Last.fm cache in `data/lastfm-cache/`.

Each unit reads only its own `~/.config/artistpath/*.env` (mode 0600):

- `backend.env`: `LASTFM_API_KEY`, `METADATA_PATH`, `GRAPH_PATH`, `REVERSE_GRAPH_PATH`, `LASTFM_CACHE_PATH`
- `collector.env`: `LASTFM_COLLECTOR_API_KEY`
- `healthcheck.env`: `HC_BACKEND_UUID`, `HC_COLLECTOR_UUID`
- `refresh.env`: `HC_REFRESH_UUID`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`

The systemd sandbox drop-ins and the per-UID egress firewall the public instance runs with are host configuration and are not part of this repo: the units here alone run the services unsandboxed as the service user.

To deploy, run `ops/deploy.sh` as the admin from a checkout (`--no-build` skips `cargo build --release`). It ships the working-tree contents of tracked files, uncommitted edits included (it warns about them), plus the release binary, via `sudo -u artistpath`; runs `install-services.sh` and `uv sync --frozen` as that user; and restarts the backend. Files deleted from the repo stay in the deployed copy, and untracked files are not shipped until `git add`. The nightly refresh keeps its last run's output in `~/.local/state/log/artistpath/refresh.log`.
