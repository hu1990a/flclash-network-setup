# Install ai-ipcheck on macOS, BOTH arches auto-detected.
#   arm64 (M-series): system/brew Python usually >= 3.10 -> direct pip; if too old, prefer brew, fallback python.org universal2 pkg
#   x86_64 (Intel):   Homebrew dropped Intel -> python.org 3.13 pkg route + Tsinghua mirror
# Some steps are interactive (pkg installer, sudo).
set -euo pipefail
ARCH=$(uname -m)
echo "arch: $ARCH"
PYOK=$(python3 -c 'import sys; print(sys.version_info >= (3, 10))' 2>/dev/null || echo False)
MIRROR_ARGS=""

if [ "$ARCH" = "arm64" ]; then
  if [ "$PYOK" != "True" ]; then
    if command -v brew >/dev/null 2>&1; then
      brew install python@3.13
    else
      echo "No brew and Python too old; installing python.org universal2 pkg"
      curl -L -o ~/Downloads/python313.pkg "https://www.python.org/ftp/python/3.13.2/python-3.13.2-macos11.pkg"
      echo "==> opening installer (interactive; REOPEN terminal after install, then rerun this script)"
      open ~/Downloads/python313.pkg
      exit 0
    fi
  fi
else
  # Intel: no official brew; slow networks benefit from the Tsinghua PyPI mirror
  MIRROR_ARGS="--index-url https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn"
  if [ "$PYOK" != "True" ]; then
    curl -L -o ~/Downloads/python313.pkg "https://www.python.org/ftp/python/3.13.2/python-3.13.2-macos11.pkg"
    echo "==> opening installer (interactive; REOPEN terminal after install, then rerun this script)"
    open ~/Downloads/python313.pkg
    exit 0
  fi
fi

python3 -m pip install --user --upgrade ai-ipcheck $MIRROR_ARGS
PYV=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
grep -q "Library/Python" ~/.zshrc 2>/dev/null || echo "export PATH=\"$HOME/Library/Python/$PYV/bin:$PATH\"" >> ~/.zshrc
# cert permanent fix (optional, once; harmless if framework path differs, e.g. brew python)
sudo ln -sf "$(python3 -c 'import certifi; print(certifi.where())')" "/Library/Frameworks/Python.framework/Versions/$PYV/etc/openssl/cert.pem" 2>/dev/null || echo "cert symlink skipped (ok)"
echo "reopen terminal -> run: ipcheck"
