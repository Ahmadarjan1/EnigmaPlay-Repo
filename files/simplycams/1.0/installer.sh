#!/bin/sh
# ---------------------------------------------------------------------------
#  SimplyCams installer / updater for Enigma2
#  https://github.com/Ahmed-Mohammed-Abbas/SimplyCams
#
#  Install or update from telnet/SSH:
#    wget -q -O - https://raw.githubusercontent.com/Ahmed-Mohammed-Abbas/SimplyCams/main/installer.sh | sh
# ---------------------------------------------------------------------------
REPO="Ahmed-Mohammed-Abbas/SimplyCams"
BRANCH="main"
PLUGIN_DIR="/usr/lib/enigma2/python/Plugins/Extensions/SimplyCams"
TMP_DIR="/tmp/simplycams_install"
ARCHIVE_URL="https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz"
[ -n "$SIMPLYCAMS_ARCHIVE_URL" ] && ARCHIVE_URL="$SIMPLYCAMS_ARCHIVE_URL"   # used for testing
[ -n "$SIMPLYCAMS_PLUGIN_DIR" ] && PLUGIN_DIR="$SIMPLYCAMS_PLUGIN_DIR"

echo "=============================================="
echo "  SimplyCams installer"
echo "=============================================="

download() {
    wget -q -O "$2" "$1" 2>/dev/null && return 0
    wget -q --no-check-certificate -O "$2" "$1" 2>/dev/null && return 0
    command -v curl >/dev/null 2>&1 && curl -fsSL -o "$2" "$1" && return 0
    return 1
}

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR" || exit 1
cd "$TMP_DIR" || exit 1

echo "Downloading latest version ..."
if ! download "$ARCHIVE_URL" source.tar.gz; then
    echo "ERROR: download failed - check the receiver's internet connection."
    exit 1
fi
if ! tar -xzf source.tar.gz; then
    echo "ERROR: the downloaded archive is damaged."
    exit 1
fi

SRC_ROOT=$(find . -maxdepth 1 -mindepth 1 -type d | head -n 1)
if [ ! -f "$SRC_ROOT/SimplyCams/plugin.py" ]; then
    echo "ERROR: plugin files not found in the archive."
    exit 1
fi
NEW_VERSION=$(grep -v '^#' "$SRC_ROOT/version.txt" 2>/dev/null | grep -m1 '[0-9]' | tr -d ' \r\tvV')

echo "Installing SimplyCams $NEW_VERSION ..."
mkdir -p "$PLUGIN_DIR" || exit 1
rm -rf "$PLUGIN_DIR/__pycache__" "$PLUGIN_DIR"/*.pyc "$PLUGIN_DIR"/*.pyo
cp -rf "$SRC_ROOT/SimplyCams/." "$PLUGIN_DIR/" || { echo "ERROR: copy failed"; exit 1; }
cp -f "$SRC_ROOT/version.txt" "$PLUGIN_DIR/version.txt"
chmod 644 "$PLUGIN_DIR"/*.py 2>/dev/null

# GStreamer RTSP support (normally already present; failures here are harmless)
if command -v opkg >/dev/null 2>&1 && [ -z "$SIMPLYCAMS_SKIP_DEPS" ]; then
    for pkg in gstreamer1.0-plugins-good-rtsp gstreamer1.0-plugins-good-rtp \
               gstreamer1.0-plugins-good-rtpmanager gstreamer1.0-plugins-good-udp \
               gstreamer1.0-plugins-bad-videoparsersbad; do
        opkg list-installed 2>/dev/null | grep -q "^$pkg " || opkg install "$pkg" >/dev/null 2>&1
    done
fi

cd /
rm -rf "$TMP_DIR"
echo ""
echo "SimplyCams $NEW_VERSION installed successfully."

if [ "$SIMPLYCAMS_NO_RESTART" = "1" ]; then
    echo "Restart the GUI to use the new version."
else
    echo "Restarting the GUI in 3 seconds ..."
    sleep 3
    if command -v systemctl >/dev/null 2>&1 && systemctl is-active enigma2 >/dev/null 2>&1; then
        systemctl restart enigma2
    else
        killall -9 enigma2 >/dev/null 2>&1
    fi
fi
exit 0
