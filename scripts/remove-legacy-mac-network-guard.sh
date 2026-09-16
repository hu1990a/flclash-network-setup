#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="$HOME/Library/Application Support/flclash-network-setup/network-guard"
PLIST="$HOME/Library/LaunchAgents/com.marvx.flclash-network-guard.plist"
LABEL="com.marvx.flclash-network-guard"
UID_VALUE="$(id -u)"
CORE_TARGET="$INSTALL_ROOT/network-guard.py"

launchctl bootout "gui/$UID_VALUE/$LABEL" 2>/dev/null || true
pkill -f "$CORE_TARGET" 2>/dev/null || true
rm -f "$PLIST"

case "$INSTALL_ROOT" in
  "$HOME/Library/Application Support/flclash-network-setup/network-guard") rm -rf "$INSTALL_ROOT" ;;
  *) echo "Refusing unexpected install path." >&2; exit 3 ;;
esac

printf 'removed_launch_agent=%s\nremoved_install_directory=%s\n' \
  "$([[ ! -e "$PLIST" ]] && echo yes || echo no)" \
  "$([[ ! -e "$INSTALL_ROOT" ]] && echo yes || echo no)"
