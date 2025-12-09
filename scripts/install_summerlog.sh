#!/usr/bin/env bash
set -euo pipefail

# One-shot installer for Summerlog on Debian/Ubuntu-like systems.
# It bootstraps pipx if needed, installs Summerlog from Git, and runs the CLI configurator.

REPO_REF="${SUMMERLOG_REF:-master}"
PACKAGE_URL="git+https://github.com/allisonhere/summerlog.git@${REPO_REF}"

log() { printf '\n==> %s\n' "$*"; }

ensure_python() {
  if command -v python3 >/dev/null 2>&1; then
    return
  fi
  if command -v apt-get >/dev/null 2>&1; then
    log "Installing python3 (sudo may prompt)..."
    sudo apt-get update -y
    sudo apt-get install -y python3
  else
    echo "python3 is required; please install it and rerun." >&2
    exit 1
  fi
}

ensure_pip() {
  if command -v pip >/dev/null 2>&1; then
    return
  fi
  if command -v apt-get >/dev/null 2>&1; then
    log "Installing python3-pip (sudo may prompt)..."
    sudo apt-get update -y
    sudo apt-get install -y python3-pip
  else
    echo "pip is required; please install it and rerun." >&2
    exit 1
  fi
}

ensure_pipx() {
  if command -v pipx >/dev/null 2>&1; then
    return
  fi
  ensure_pip
  log "Installing pipx locally..."
  python3 -m pip install --user pipx
  python3 -m pipx ensurepath
}

install_summerlog() {
  export PATH="$HOME/.local/bin:$PATH"
  log "Installing/refreshing Summerlog from ${REPO_REF}..."
  pipx install --force "${PACKAGE_URL}"
}

run_configure() {
  export PATH="$HOME/.local/bin:$PATH"
  # Force CLI wizard even on desktops to keep flow consistent.
  log "Launching configurator..."
  DISPLAY="" summerlog-configure
}

main() {
  ensure_python
  ensure_pipx
  install_summerlog
  run_configure
  log "Done. Verify with: which summerlog && summerlog --version"
  log "Scheduler entries (cron/systemd) were set up by the configurator."
}

main "$@"
