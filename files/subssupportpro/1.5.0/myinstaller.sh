#!/bin/sh

# wget -qO - https://raw.githubusercontent.com/popking159/SubsSupportPro/refs/heads/main/myinstaller.sh | /bin/sh

# =========================================================================
# CONFIGURATION (Change these for different repositories)
# =========================================================================
PLUGIN_NAME="SubsSupportPro"
USERNAME="popking159"
REPO="SubsSupportPro"

# 1. SYSTEM DEPENDENCIES (Binary utilities installed exactly as written, e.g., unrar)
SYS_DEPENDS="unrar ffmpeg"
# =========================================================================

# Terminal Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Dynamically construct the download link DIRECTLY to the raw file to avoid Busybox wget redirect failures
PLUGIN_URL="https://raw.githubusercontent.com/${USERNAME}/${REPO}/main/main.tar.gz"

# Workspace paths
TMP_DIR="/var/volatile/tmp"
[ -d "$TMP_DIR" ] || TMP_DIR="/tmp"
TMP_FILE="$TMP_DIR/main_install.tar.gz"

PKG_MANAGER=""
PYTHON_VERSION=""
FINAL_DEPENDS=""

log() {
    # Automatically colorize based on the log tag
    case "$1" in
        *\[INFO\]*) echo -e "${CYAN}$1${NC}" ;;
        *\[OK\]*) echo -e "${GREEN}$1${NC}" ;;
        *\[WARN\]*) echo -e "${YELLOW}$1${NC}" ;;
        *\[ERROR\]*) echo -e "${RED}$1${NC}" ;;
        *) echo -e "$1" ;;
    esac
}

has_cmd() {
    command -v "$1" >/dev/null 2>&1
}

is_pkg_installed() {
    pkg="$1"
    # Check apt-get first for DreamOS
    if [ "$PKG_MANAGER" = "apt" ]; then
        dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed" && return 0
        return 1
    fi

    # Fallback to opkg for OE-Alliance
    if [ "$PKG_MANAGER" = "opkg" ]; then
        if [ -f /var/lib/opkg/status ]; then
            grep -q "^Package: $pkg$" /var/lib/opkg/status && return 0
        fi
        opkg list-installed 2>/dev/null | grep -q "^$pkg[[:space:]-]" && return 0
        return 1
    fi
    return 1
}

echo -e "${GREEN}====================================================${NC}"
echo -e "${GREEN}         $PLUGIN_NAME INSTALLER UTILITY             ${NC}"
echo -e "${GREEN}====================================================${NC}"

# 1. Detect Package Manager
# STRICT CHECK: We must check apt-get FIRST because some DreamOS 
# distributions contain dummy opkg binaries that fail when executed.
if has_cmd apt-get; then
    PKG_MANAGER="apt"
elif has_cmd opkg; then
    PKG_MANAGER="opkg"
fi
log "[INFO] Package manager detected: ${PKG_MANAGER:-None}"

# 2. Force Python Version based on OS architecture
if [ "$PKG_MANAGER" = "apt" ]; then
    # DreamOS ALWAYS uses Python 2.7 for Enigma2 plugins
    PYTHON_VERSION="2"
    PY_PREFIX="python-"
else
    # OE-Alliance (OpenATV, etc.) uses Python 3 on modern images
    if has_cmd python3; then
        PYTHON_VERSION="3"
        PY_PREFIX="python3-"
    elif has_cmd python; then
        PYTHON_VERSION="2"
        PY_PREFIX="python-"
    fi
fi
log "[INFO] Detected Python Environment: Python $PYTHON_VERSION ($PY_PREFIX)"

# 3. Build the Final Dependency List based on Package Manager & Python Version
if [ "$PKG_MANAGER" = "apt" ]; then
    TWISTED_MOD="twisted"
else
    TWISTED_MOD="twisted-web"
fi

PY3_DEPENDS="requests beautifulsoup4 codecs compression core difflib json six $TWISTED_MOD xmlrpc"
# Re-added 'requests' to ensure it installs on DreamOS
PY2_DEPENDS="requests beautifulsoup4 codecs compression core difflib json six twisted xmlrpc"

ACTIVE_PY_DEPENDS=""
if [ "$PYTHON_VERSION" = "3" ]; then
    ACTIVE_PY_DEPENDS="$PY3_DEPENDS"
elif [ "$PYTHON_VERSION" = "2" ]; then
    ACTIVE_PY_DEPENDS="$PY2_DEPENDS"
fi

for dep in $ACTIVE_PY_DEPENDS; do
    FINAL_DEPENDS="$FINAL_DEPENDS ${PY_PREFIX}${dep}"
done

for dep in $SYS_DEPENDS; do
    FINAL_DEPENDS="$FINAL_DEPENDS $dep"
done

# 4. Check and Download Dependencies
if [ -n "$FINAL_DEPENDS" ]; then
    log "[INFO] Verifying required dependencies..."
    for pkg in $FINAL_DEPENDS; do
        if is_pkg_installed "$pkg"; then
            log "[OK] Already installed: $pkg"
        else
            log "[INFO] Downloading and installing: $pkg"
            if [ "$PKG_MANAGER" = "apt" ]; then
                DEBIAN_FRONTEND=noninteractive apt-get install -y "$pkg" >/dev/null 2>&1
            elif [ "$PKG_MANAGER" = "opkg" ]; then
                opkg install "$pkg" >/dev/null 2>&1
            fi
            
            if is_pkg_installed "$pkg"; then
                log "[OK] Successfully installed: $pkg"
            else
                log "[ERROR] Required dependency '$pkg' could not be installed! Aborting setup."
                exit 1
            fi
        fi
    done
else
    log "[INFO] No dependencies specified in configuration. Skipping dependency phase."
fi

# 5. Download Plugin Archive
log "[INFO] Downloading main plugin tree archive..."
rm -f "$TMP_FILE"
wget -q --no-check-certificate "$PLUGIN_URL" -O "$TMP_FILE"

# Make sure the file actually exists and is larger than a standard HTML error page
if [ ! -s "$TMP_FILE" ] || [ $(stat -c%s "$TMP_FILE") -lt 1000 ]; then
    log "[ERROR] Download failed or file is not a valid archive!"
    rm -f "$TMP_FILE"
    exit 1
fi

# 6. Extract directly to ROOT (/)
log "[INFO] Extracting payload contents to system paths..."
# Using -xf instead of -xzf to let Busybox auto-detect compression, avoiding strict gzip errors
tar -xf "$TMP_FILE" -C /
if [ $? -ne 0 ]; then
    log "[ERROR] Extraction failed!"
    rm -f "$TMP_FILE"
    exit 1
fi

rm -f "$TMP_FILE"
sync

echo -e "${GREEN}====================================================${NC}"
echo -e "${GREEN}          $PLUGIN_NAME INSTALLATION COMPLETE        ${NC}"
echo -e "${GREEN}====================================================${NC}"

exit 0
