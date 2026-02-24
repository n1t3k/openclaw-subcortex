#!/usr/bin/env bash
# install.sh — Install Subcortex as a systemd user service
# Usage: bash install.sh [--workspace /path/to/workspace]

set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
WORKSPACE="${SUBCORTEX_WORKSPACE:-$HOME/.agent-subcortex}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$SCRIPT_DIR/subcortex.py"
SERVICE_NAME="agent-subcortex"
SERVICE_DIR="$HOME/.config/systemd/user"
SERVICE_FILE="$SERVICE_DIR/$SERVICE_NAME.service"

# Optional: override agent name
AGENT_NAME="${AGENT_NAME:-the AI assistant}"

echo "━━━ Subcortex Installer ━━━"
echo "  Workspace:  $WORKSPACE"
echo "  Agent name: $AGENT_NAME"
echo "  Service:    $SERVICE_NAME"
echo

# ── Pre-flight checks ─────────────────────────────────────────────────────────

if ! command -v python3 &>/dev/null; then
  echo "ERROR: python3 not found" >&2
  exit 1
fi

# Check Python version >= 3.10
PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"; then
  echo "✓ Python $PYTHON_VERSION"
else
  echo "ERROR: Python 3.10+ required (found $PYTHON_VERSION)" >&2
  exit 1
fi

if ! python3 -c "import requests" &>/dev/null; then
  echo "ERROR: 'requests' library not installed. Run: pip install requests" >&2
  exit 1
fi
echo "✓ requests library found"

# Check Ollama (warn only — may be down transiently)
if curl -sf http://localhost:11434/api/tags &>/dev/null; then
  echo "✓ Ollama responding at localhost:11434"
else
  echo "WARNING: Ollama not responding at localhost:11434 (will retry at runtime)"
fi

# ── Setup workspace ───────────────────────────────────────────────────────────

mkdir -p "$WORKSPACE/memory/subconscious"
echo "✓ Workspace ready: $WORKSPACE/memory/subconscious/"

# ── Write systemd service ─────────────────────────────────────────────────────

mkdir -p "$SERVICE_DIR"

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Agent Subcortex — Background Mind
Documentation=file://$SCRIPT_DIR/README.md
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $SCRIPT
WorkingDirectory=$WORKSPACE
Environment=SUBCORTEX_WORKSPACE=$WORKSPACE
Environment=AGENT_NAME=$AGENT_NAME
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal
SyslogIdentifier=agent-subcortex

[Install]
WantedBy=default.target
EOF

echo "✓ Wrote service file: $SERVICE_FILE"

# ── Enable and start ──────────────────────────────────────────────────────────

systemctl --user daemon-reload
echo "✓ systemd daemon reloaded"

systemctl --user enable "$SERVICE_NAME"
echo "✓ Service enabled (will start on login)"

systemctl --user start "$SERVICE_NAME"
echo "✓ Service started"

sleep 2

# ── Status ────────────────────────────────────────────────────────────────────

echo
echo "━━━ Service Status ━━━"
systemctl --user status "$SERVICE_NAME" --no-pager -l || true

echo
echo "━━━ Useful Commands ━━━"
echo "  Status:   systemctl --user status $SERVICE_NAME"
echo "  Logs:     journalctl --user -u $SERVICE_NAME -f"
echo "  Stop:     systemctl --user stop $SERVICE_NAME"
echo "  Restart:  systemctl --user restart $SERVICE_NAME"
echo "  Latest:   cat $WORKSPACE/memory/subconscious/latest.md"
echo "  Impulses: tail -f $WORKSPACE/memory/subconscious/impulses.jsonl"
echo
echo "✓ Subcortex installed and running"
