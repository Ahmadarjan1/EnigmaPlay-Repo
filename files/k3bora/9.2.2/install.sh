#!/bin/sh
# Ultra Stalker Final V9.2.2 - Public Online Installer
# Enigma2 / Python 3.12, 3.13, 3.14, 3.15

set -u

PLUGIN_PKG="enigma2-plugin-extensions-ultrastalker"
TARGET_VERSION="9.2.2"
IPK_NAME="UltraStalker_V7_UPDATE.ipk"
IPK_URL="https://github.com/K3bOra/-UltraStalker/releases/download/v10.0.60/${IPK_NAME}"
EXPECTED_SHA256="b9a62e2d1ba2c5ff1805322fd73a19bf251a6a82c347407a52913651d4531ddd"
TMP_IPK="/tmp/${IPK_NAME}"
TMP_PART="${TMP_IPK}.part"
OPKG_LOG="/tmp/ultrastalker-opkg-update.log"

say() { printf '%s\n' "$*"; }
cleanup() { rm -f "$TMP_IPK" "$TMP_PART" "$OPKG_LOG" 2>/dev/null || true; }
fail() { say ""; say "[ERROR] $*"; cleanup; exit 1; }
trap cleanup EXIT INT TERM

calc_sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    elif command -v busybox >/dev/null 2>&1 && busybox sha256sum "$1" >/dev/null 2>&1; then
        busybox sha256sum "$1" | awk '{print $1}'
    elif command -v openssl >/dev/null 2>&1; then
        openssl dgst -sha256 "$1" | awk '{print $NF}'
    else
        return 1
    fi
}

fetch_package() {
    rm -f "$TMP_PART" 2>/dev/null || true
    if command -v wget >/dev/null 2>&1; then
        wget -O "$TMP_PART" "$IPK_URL" || return 1
    elif command -v curl >/dev/null 2>&1; then
        curl -fL "$IPK_URL" -o "$TMP_PART" || return 1
    else
        return 1
    fi
    [ -s "$TMP_PART" ] || return 1
    mv -f "$TMP_PART" "$TMP_IPK"
    return 0
}

say "=============================================="
say "       Ultra Stalker Final V9.2.2"
say "              Online Installer"
say "=============================================="

[ "$(id -u 2>/dev/null || echo 1)" = "0" ] || fail "Run this installer as root."
command -v opkg >/dev/null 2>&1 || fail "opkg was not found on this receiver."

if command -v python3 >/dev/null 2>&1; then
    PYBIN=python3
elif command -v python >/dev/null 2>&1 && python -c 'import sys; raise SystemExit(0 if sys.version_info.major == 3 else 1)' >/dev/null 2>&1; then
    PYBIN=python
else
    fail "Python 3 was not found."
fi

PYVER="$($PYBIN -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
case "$PYVER" in
    3.12|3.13|3.14|3.15) say "[OK] Python $PYVER" ;;
    *) fail "Unsupported Python version: ${PYVER:-unknown}. Required: 3.12 / 3.13 / 3.14 / 3.15." ;;
esac

FREE_KB="$(df -Pk /tmp 2>/dev/null | awk 'NR==2 {print $4}')"
case "$FREE_KB" in
    ''|*[!0-9]*) ;;
    *) [ "$FREE_KB" -ge 30000 ] || fail "At least 30 MB free space in /tmp is required." ;;
esac

say "[1/5] Checking required libraries..."
MISSING=""
if ! "$PYBIN" -c 'import sqlite3' >/dev/null 2>&1; then MISSING="$MISSING python3-sqlite3"; fi
if ! "$PYBIN" -c 'from PIL import Image' >/dev/null 2>&1; then MISSING="$MISSING python3-pillow"; fi
if ! "$PYBIN" -c 'import twisted; from twisted.web.client import Agent' >/dev/null 2>&1; then MISSING="$MISSING python3-twisted"; fi
if [ -n "$MISSING" ]; then
    say "      Missing:$MISSING"
    say "      Refreshing package feeds..."
    opkg update >"$OPKG_LOG" 2>&1 || say "[WARN] Package feed refresh reported an error; trying available lists."
    for dep in $MISSING; do
        say "      Installing $dep..."
        opkg install "$dep" || fail "Could not install required dependency: $dep"
    done
else
    say "[OK] Required libraries are already installed."
fi

"$PYBIN" -c 'import sqlite3' >/dev/null 2>&1 || fail "Python sqlite3 is unavailable."
"$PYBIN" -c 'from PIL import Image' >/dev/null 2>&1 || fail "Python Pillow is unavailable."
"$PYBIN" -c 'import twisted; from twisted.web.client import Agent' >/dev/null 2>&1 || fail "Python Twisted is unavailable."

say "[2/5] Downloading Ultra Stalker V9.2.2..."
fetch_package || fail "Download failed."

SIZE="$(wc -c < "$TMP_IPK" 2>/dev/null || echo 0)"
case "$SIZE" in
    ''|*[!0-9]*) fail "Could not validate downloaded package size." ;;
    *) [ "$SIZE" -gt 1000000 ] || fail "Downloaded file is too small to be a valid Ultra Stalker package." ;;
esac

say "[3/5] Verifying SHA256..."
ACTUAL_SHA256="$(calc_sha256 "$TMP_IPK" 2>/dev/null || true)"
[ -n "$ACTUAL_SHA256" ] || fail "No SHA256 verification tool is available."
[ "$ACTUAL_SHA256" = "$EXPECTED_SHA256" ] || fail "SHA256 mismatch. Package was not installed."
say "[OK] Package integrity verified."

say "[4/5] Installing / updating Ultra Stalker..."
if ! opkg install --force-reinstall "$TMP_IPK"; then
    say "[WARN] --force-reinstall failed; retrying normal opkg install..."
    opkg install "$TMP_IPK" || fail "Package installation failed."
fi

STATUS="$(opkg status "$PLUGIN_PKG" 2>/dev/null || true)"
printf '%s\n' "$STATUS" | grep -q '^Status:.* installed' || fail "Ultra Stalker is not registered as installed."
INSTALLED_VERSION="$(printf '%s\n' "$STATUS" | awk -F': ' '/^Version:/ {print $2; exit}')"
[ "$INSTALLED_VERSION" = "$TARGET_VERSION" ] || fail "Unexpected installed version: ${INSTALLED_VERSION:-unknown}; expected $TARGET_VERSION."

say "[5/5] Installation verified."
say ""
say "=============================================="
say " Ultra Stalker Final V9.2.2 installed correctly."
say " Enigma2 restart is handled by the package."
say "=============================================="
sync 2>/dev/null || true
exit 0
