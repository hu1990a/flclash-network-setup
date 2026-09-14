#!/usr/bin/env bash
# Safe beginner workflow for macOS Intel and Apple Silicon.
set -euo pipefail

MODE="${1:-audit}"
TZ_VALUE="${2:-}"
INSTALL_IPCHECK="${3:-}"
PORT="${FLCLASH_PORT:-7890}"
PROXY_TZ="${FLCLASH_PROXY_TIMEZONE:-}"

case "$MODE" in audit|apply|verify) ;; *) echo "usage: setup-mac.sh audit|apply|verify [IANA_TZ] [--install-ipcheck]"; exit 2 ;; esac

echo "FlClash macOS $MODE"
echo "arch: $(uname -m)"
command -v python3 >/dev/null 2>&1 && echo "python: PASS" || echo "python: FAIL"
[ -d /Applications/FlClash.app ] && echo "FlClash: PASS" || echo "FlClash: PENDING"

PROFILE="${FLCLASH_PROFILE:-}"
if [ -z "$PROFILE" ]; then
  for root in "$HOME/Library/Application Support/com.follow.clash/profiles" "$HOME/Library/Application Support/com.follow/clash/profiles"; do
    if [ -d "$root" ]; then
      PROFILE=$(find "$root" -maxdepth 1 -type f -name '*.yaml' -exec grep -l '^proxies:[[:space:]]*$' {} \; | head -n 1 || true)
      [ -n "$PROFILE" ] && break
    fi
  done
fi
if [ -n "$PROFILE" ]; then
  echo "profile: $(basename "$PROFILE")"
  DETECTED_PORT=$(awk '/^mixed-port:[[:space:]]*[0-9]+/{print $2; exit}' "$PROFILE" || true)
  [ -n "$DETECTED_PORT" ] && PORT="$DETECTED_PORT"
else
  echo "profile: PENDING (set FLCLASH_PROFILE to the selected YAML)"
fi
echo "proxy port: $PORT"

networksetup -listallnetworkservices || true
SERVICE="${FLCLASH_NETWORK_SERVICE:-Wi-Fi}"

if [ "$MODE" = "apply" ]; then
  if [ -z "$TZ_VALUE" ]; then
    echo "CLI timezone sets TZ for new terminals and CLI tools only."
    echo "It does not change the macOS clock, calendar, or system timezone."
    echo "1 Fixed 12 hours behind Beijing: America/Puerto_Rico (UTC-4, no DST). Easy for human time conversion, but it may conflict with the proxy exit."
    echo "2 Match the current or recommended proxy exit. Choice 2 is recommended to reduce location/timezone conflicts and follow local DST."
    read -r -p "Choose 1 or 2 [2]: " TIMEZONE_MODE
    TIMEZONE_MODE="${TIMEZONE_MODE:-2}"
    case "$TIMEZONE_MODE" in
      1) TZ_VALUE="America/Puerto_Rico" ;;
      2)
        if [ -n "$PROXY_TZ" ]; then
          TZ_VALUE="$PROXY_TZ"
        else
          read -r -p "Detected proxy IANA timezone (for example America/Los_Angeles): " TZ_VALUE
        fi
        ;;
      *) echo "timezone choice: FAIL (enter 1 or 2)"; exit 2 ;;
    esac
  fi
  [ -n "$TZ_VALUE" ] || { echo "timezone: FAIL"; exit 2; }
  if [ -n "$PROFILE" ]; then
    python3 "$(dirname "$0")/replace-config.py" "$PROFILE" --port "$PORT" --dry-run
    python3 "$(dirname "$0")/replace-config.py" "$PROFILE" --port "$PORT"
  fi
  read -r -p "Network service to disable IPv6 on [$SERVICE]: " input_service
  SERVICE="${input_service:-$SERVICE}"
  sudo networksetup -setv6off "$SERVICE"
  echo "IPv6: changed on selected service only; rollback: sudo networksetup -setv6automatic \"$SERVICE\""
  python3 - "$TZ_VALUE" "$PORT" <<'PY'
import os, re, sys
tz, port = sys.argv[1], sys.argv[2]
path = os.path.expanduser("~/.zshrc")
text = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
block = (
    "# === flclash-skill env begin ===\n"
    f"# exports proxy vars only while 127.0.0.1:{port} is listening; proxy_on/proxy_off override\n"
    f"flclash_port_listening() {{ nc -z -w 1 127.0.0.1 {port} >/dev/null 2>&1 }}\n"
    f'proxy_on()  {{ export HTTP_PROXY="http://127.0.0.1:{port}" HTTPS_PROXY="http://127.0.0.1:{port}" ALL_PROXY="socks5://127.0.0.1:{port}" http_proxy="$HTTP_PROXY" https_proxy="$HTTPS_PROXY" all_proxy="$ALL_PROXY"; echo "proxy ON -> 127.0.0.1:{port}" }}\n'
    'proxy_off() { unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy; echo "proxy OFF (direct)" }\n'
    "if flclash_port_listening; then\n"
    f'  export HTTP_PROXY="http://127.0.0.1:{port}" HTTPS_PROXY="http://127.0.0.1:{port}" ALL_PROXY="socks5://127.0.0.1:{port}"\n'
    '  export http_proxy="$HTTP_PROXY" https_proxy="$HTTPS_PROXY" all_proxy="$ALL_PROXY"\n'
    "fi\n"
    'export ANTHROPIC_BASE_URL="https://api.anthropic.com"\n'
    'export OPENAI_BASE_URL="https://api.openai.com"\n'
    f'export TZ="{tz}"\n'
    "# fail-closed: claude/codex are blocked locally when FlClash is not running\n"
    "flclash_guard() {\n"
    "  if flclash_port_listening; then command \"$@\"\n"
    "  else\n"
    "    echo \"[flclash-skill] FlClash 未运行（端口未监听），已 fail-closed 拦截: $1\"\n"
    "    echo \"  -> 先启动 FlClash 再试；确要直连测试请改用: command $1\"\n"
    "    return 1\n"
    "  fi\n"
    "}\n"
    'claude() { flclash_guard claude "$@"; }\n'
    'codex()  { flclash_guard codex "$@"; }\n'
    "# === flclash-skill env end ===\n"
)
text = re.sub(r"# === flclash-skill env begin ===.*?# === flclash-skill env end ===\n?", "", text, flags=re.S)
with open(path, "w", encoding="utf-8") as handle:
    handle.write(text.rstrip("\n") + "\n\n" + block)
print("environment: PASS")
PY
  if [ "$INSTALL_IPCHECK" = "--install-ipcheck" ]; then
    bash "$(dirname "$0")/install-ipcheck-macos.sh"
  elif command -v ipcheck >/dev/null 2>&1; then
    echo "ipcheck: PASS"
  else
    echo "ipcheck: PENDING (rerun with --install-ipcheck after approval)"
  fi
  echo "manual: enable TUN and system proxy, fully quit and reopen FlClash, then reopen Terminal"
fi

if [ "$MODE" = "verify" ]; then
  networksetup -getinfo "$SERVICE" | sed -E 's/([0-9a-fA-F]{1,4}:){2,}[0-9a-fA-F:]+/[REDACTED_IPv6]/g'
  grep -q '# === flclash-skill env begin ===' "$HOME/.zshrc" && echo "environment block: PASS" || echo "environment block: FAIL"
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 && echo "proxy port: PASS" || echo "proxy port: FAIL"
  if command -v dig >/dev/null 2>&1; then
    answer=$(dig +short @127.0.0.1 -p 1053 www.cloudflare.com A | head -n 1)
    case "$answer" in 198.18.*) echo "fake-IP DNS: PASS" ;; *) echo "fake-IP DNS: FAIL" ;; esac
  fi
  command -v ipcheck >/dev/null 2>&1 && echo "ipcheck: READY (run locally; redact public IP in reports)" || echo "ipcheck: PENDING"
fi
