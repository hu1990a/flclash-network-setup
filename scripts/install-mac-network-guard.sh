#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-status}"
CONSENT="${FLCLASH_GUARD_EXTERNAL_CONSENT:-0}"
if [[ "${2:-}" == "--allow-external-ip-check" ]]; then CONSENT=1; fi

INSTALL_ROOT="$HOME/Library/Application Support/flclash-network-setup/network-guard"
CORE_SOURCE="$(cd "$(dirname "$0")" && pwd)/network-guard.py"
CORE_TARGET="$INSTALL_ROOT/network-guard.py"
CONFIG="$INSTALL_ROOT/config.json"
STATE="$INSTALL_ROOT/state.json"
PAUSED="$INSTALL_ROOT/paused.flag"
PLIST="$HOME/Library/LaunchAgents/com.marvx.flclash-network-guard.plist"
LABEL="com.marvx.flclash-network-guard"
UID_VALUE="$(id -u)"

write_config() {
  mkdir -p "$INSTALL_ROOT"
  python3 - "$CONFIG" "$STATE" "$PAUSED" "$CONSENT" <<'PY'
import json, sys
path, state, paused, consent = sys.argv[1:]
with open(path, "w", encoding="utf-8") as handle:
    json.dump({
        "default_port": 7890,
        "external_check_consent": consent == "1",
        "external_endpoint": "https://ifconfig.co/json",
        "local_interval_seconds": 20,
        "external_interval_seconds": 3600,
        "confirmations_required": 2,
        "state_path": state,
        "paused_path": paused,
    }, handle, ensure_ascii=False, indent=2)
PY
}

write_plist() {
  mkdir -p "$(dirname "$PLIST")"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string><string>$CORE_TARGET</string><string>run</string><string>--config</string><string>$CONFIG</string>
  </array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
</dict></plist>
EOF
}

case "$ACTION" in
  install)
    command -v python3 >/dev/null || { echo "Python 3 is required." >&2; exit 2; }
    mkdir -p "$INSTALL_ROOT"
    cp "$CORE_SOURCE" "$CORE_TARGET"
    chmod 700 "$CORE_TARGET"
    write_config
    write_plist
    launchctl bootout "gui/$UID_VALUE/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$UID_VALUE" "$PLIST"
    launchctl kickstart -k "gui/$UID_VALUE/$LABEL"
    echo "Installed and started. External IP checks: $([[ "$CONSENT" == 1 ]] && echo CONSENTED || echo DISABLED)"
    ;;
  pause)
    mkdir -p "$INSTALL_ROOT" && printf 'paused\n' > "$PAUSED"
    echo "Paused."
    ;;
  resume)
    rm -f "$PAUSED"
    launchctl kickstart -k "gui/$UID_VALUE/$LABEL" 2>/dev/null || true
    echo "Resumed."
    ;;
  check-now)
    [[ -f "$CONFIG" ]] || { echo "Network guard is not installed." >&2; exit 2; }
    /usr/bin/python3 "$CORE_TARGET" check --config "$CONFIG" --notify
    ;;
  status)
    printf 'installed=%s\npaused=%s\n' "$([[ -f "$PLIST" ]] && echo yes || echo no)" "$([[ -f "$PAUSED" ]] && echo yes || echo no)"
    [[ -f "$STATE" ]] && /usr/bin/python3 "$CORE_TARGET" status --config "$CONFIG" || true
    ;;
  uninstall)
    launchctl bootout "gui/$UID_VALUE/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    case "$INSTALL_ROOT" in
      "$HOME/Library/Application Support/flclash-network-setup/network-guard") rm -rf "$INSTALL_ROOT" ;;
      *) echo "Refusing unexpected install path." >&2; exit 3 ;;
    esac
    echo "Uninstalled."
    ;;
  *)
    echo "Usage: $0 {install|pause|resume|check-now|status|uninstall} [--allow-external-ip-check]" >&2
    exit 2
    ;;
esac

# macOS notifications are delivered by network-guard.py through osascript.
