#!/usr/bin/env bash
# Deploy reachy_foundry_agent to a Reachy Mini Wireless over SSH (no Hugging Face needed).
#
#   ./scripts/deploy-to-robot.sh                  # sync source, pip install, copy .env
#   ./scripts/deploy-to-robot.sh --no-env         # skip copying the .env file
#   ./scripts/deploy-to-robot.sh --restart        # also restart the daemon service
#
# Settings (environment variables):
#   ROBOT_HOST     default reachy-mini.local
#   ROBOT_USER     default pollen
#   ROBOT_VENV     apps venv the daemon scans (default /venvs/apps_venv; repaired if its interpreter is missing)
#   ROBOT_SERVICE  systemd unit restarted by --restart (default reachy-mini-daemon)
#
# Tip: run `ssh-copy-id $ROBOT_USER@$ROBOT_HOST` once to avoid repeated password prompts.

set -euo pipefail

ROBOT_HOST="${ROBOT_HOST:-reachy-mini.local}"
ROBOT_USER="${ROBOT_USER:-pollen}"
ROBOT_VENV="${ROBOT_VENV:-/venvs/apps_venv}"
ROBOT_SERVICE="${ROBOT_SERVICE:-reachy-mini-daemon}"

SEND_ENV=1
RESTART=0
for arg in "$@"; do
  case "$arg" in
    --no-env)  SEND_ENV=0 ;;
    --restart) RESTART=1 ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="$ROOT/reachy_foundry_agent"
ENV_FILE="$APP_DIR/.env"
REMOTE="$ROBOT_USER@$ROBOT_HOST"
REMOTE_SRC="/tmp/reachy_foundry_agent_src"

[ -f "$APP_DIR/pyproject.toml" ] || { echo "pyproject.toml not found in $APP_DIR" >&2; exit 1; }

echo "==> Checking connection to $REMOTE"
ssh -o ConnectTimeout=10 "$REMOTE" true || { echo "Cannot reach $REMOTE" >&2; exit 1; }

echo "==> Uploading source"
ssh "$REMOTE" "rm -rf '$REMOTE_SRC' && mkdir -p '$REMOTE_SRC'"
tar -C "$APP_DIR" \
    --exclude='.venv' --exclude='build' --exclude='*.egg-info' --exclude='__pycache__' \
    --exclude='.pytest_cache' --exclude='.env' --exclude='tests' \
    -cf - . | ssh "$REMOTE" "tar -C '$REMOTE_SRC' -xf -"

echo "==> Installing into the robot's apps venv"
# Passing the venv path via env var keeps quoting simple; the heredoc is expanded on the robot.
ssh "$REMOTE" "ROBOT_VENV='$ROBOT_VENV' SRC='$REMOTE_SRC' bash -s" <<'REMOTE_SCRIPT'
set -euo pipefail
export PATH="$PATH:/opt/uv"
venv="$ROBOT_VENV"
daemon_py=/venvs/mini_daemon/bin/python
py="$venv/bin/python"
echo "apps venv: $venv"

# The daemon lists apps by running $venv/bin/python; repair the interpreter if it is missing
# (existing site-packages are kept).
if [ ! -x "$py" ]; then
  echo "interpreter missing in $venv; re-creating it (packages are kept)"
  base="$(readlink -f "$daemon_py")"
  uv venv --allow-existing --python "$base" "$venv"
fi
# Same SDK version as the daemon, like the daemon's own pre-install step.
if ! "$py" -c "import reachy_mini" 2>/dev/null; then
  ver="$("$daemon_py" -c 'import importlib.metadata as m; print(m.version("reachy_mini"))')"
  uv pip install --python "$py" "reachy-mini==$ver"
fi
uv pip install --python "$py" --reinstall-package reachy_foundry_agent "$SRC"
rm -rf "$SRC"

# Earlier versions of this script installed into the daemon's own venv by mistake.
if "$daemon_py" -m pip show reachy_foundry_agent >/dev/null 2>&1; then
  echo "removing stray reachy_foundry_agent from the daemon venv"
  "$daemon_py" -m pip uninstall -y reachy_foundry_agent
fi
"$py" -c "from importlib.metadata import entry_points; print('entry points:', [e.name for e in entry_points(group='reachy_mini_apps')])"
REMOTE_SCRIPT

if [ "$SEND_ENV" -eq 1 ]; then
  if [ -f "$ENV_FILE" ]; then
    echo "==> Copying .env to ~/.reachy_foundry.env"
    scp -q "$ENV_FILE" "$REMOTE:.reachy_foundry.env"
    ssh "$REMOTE" "chmod 600 ~/.reachy_foundry.env"
  else
    echo "!! $ENV_FILE not found (run 'azd provision' or scripts/write_env.py); skipping env copy" >&2
  fi
fi

if [ "$RESTART" -eq 1 ]; then
  echo "==> Restarting $ROBOT_SERVICE"
  ssh -t "$REMOTE" "sudo systemctl restart '$ROBOT_SERVICE'"
fi

echo "Done. Open http://$ROBOT_HOST:8000 and start 'reachy_foundry_agent' from the dashboard."
