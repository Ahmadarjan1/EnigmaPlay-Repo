#!/bin/bash
#
# Command: wget -q --no-check-certificate -O - https://raw.githubusercontent.com/islam-2412/FuryBiss/main/fury/installer.sh | /bin/sh
#

# ==============================================================================
# تعريف الألوان
# ==============================================================================
RED='\033[1;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
CYAN='\033[1;36m'
MAGENTA='\033[1;35m'
NC='\033[0m' # بدون لون

# ==============================================================================
# روابط ومسارات البلاجين
# ==============================================================================
REPO_BASE_URL="https://raw.githubusercontent.com/islam-2412/FuryBiss/main/fury"
REMOTE_VERSION_URL="${REPO_BASE_URL}/version.txt"
LOCAL_VERSION_FILE="/usr/lib/enigma2/python/Plugins/Extensions/FuryBiss/version.txt"
PLUGIN_DIR="/usr/lib/enigma2/python/Plugins/Extensions/FuryBiss"

# ==============================================================================
# دوال الطباعة الجمالية (Functions)
# ==============================================================================
print_info() { echo -e "${BLUE}[ INFO ]${NC} $1"; }
print_success() { echo -e "${GREEN}[ SUCCESS ]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[ WARNING ]${NC} $1"; }
print_error() { echo -e "${RED}[ ERROR ]${NC} $1"; }
print_divider() { echo -e "${CYAN}========================================================================${NC}"; }

# دالة تحميل ذكية تدعم Open Source و DreamOS
download_file() {
    URL="$1"
    OUT_FILE="$2"
    rm -f "$OUT_FILE"

    if command -v curl >/dev/null 2>&1; then
        curl -s -k -L "$URL" -o "$OUT_FILE"
        return $?
    fi

    if command -v wget >/dev/null 2>&1; then
        wget -q --no-check-certificate -O "$OUT_FILE" "$URL"
        return $?
    fi

    print_warning "curl/wget not found. Trying to install..."
    if [ "$IS_DREAMOS" = true ]; then
        apt-get update >/dev/null 2>&1
        apt-get install -y wget curl >/dev/null 2>&1
    else
        opkg update >/dev/null 2>&1
        opkg install wget curl >/dev/null 2>&1
    fi

    if command -v wget >/dev/null 2>&1; then
        wget -q --no-check-certificate -O "$OUT_FILE" "$URL"
        return $?
    fi

    if command -v curl >/dev/null 2>&1; then
        curl -s -k -L "$URL" -o "$OUT_FILE"
        return $?
    fi

    return 1
}

# ==============================================================================
# بداية التثبيت
# ==============================================================================
clear
print_divider
echo -e "${GREEN}                 Installing FuryBiss Plugin (Smart Install)         ${NC}"
echo -e "${MAGENTA}                 Maintainer: Islam Salama (Abou Yassin)               ${NC}"
print_divider
echo ""

# 1. التعرف على نوع الصورة (DreamOS vs Open Source)
print_info "Detecting Image Type..."
IS_DREAMOS=false
if grep -qi "opendreambox" /etc/issue /etc/os-release /etc/image-version 2>/dev/null; then
    IS_DREAMOS=true
    print_success "Detected Image Type: ${YELLOW}DreamOS (opendreambox)${NC}"
else
    if [ -f /etc/issue ]; then
        IMAGE_NAME=$(sed -n '1p' /etc/issue | sed -e 's/[Ww]elcome to //g' -e 's/\\n//g' -e 's/\\l//g' | awk '{print $1}')
    else
        IMAGE_NAME="Open Source / Others"
    fi
    print_success "Detected Image Type: ${YELLOW}${IMAGE_NAME}${NC}"
fi
echo ""

# 2. التعرف على معمارية النظام
print_info "Checking system architecture..."
SYS_ARCH=$(uname -m)
case $SYS_ARCH in
    armv*|aarch32)
        ARCH="arm"
        ;;
    aarch64)
        ARCH="aarch64"
        ;;
    mips*)
        ARCH="mipsel"
        ;;
    *)
        print_error "Unsupported architecture ($SYS_ARCH) for this plugin."
        exit 1
        ;;
esac
print_success "Detected Architecture: ${YELLOW}$ARCH${NC}"
echo ""

# 3. التعرف على إصدار البايثون
print_info "Checking Python version..."
PY_BIN=""
PY_VER=$(python -c 'import sys; print(str(sys.version_info[0])+"."+str(sys.version_info[1]))' 2>/dev/null)
if [ -n "$PY_VER" ]; then
    PY_BIN="python"
else
    PY_VER=$(python3 -c 'import sys; print(str(sys.version_info[0])+"."+str(sys.version_info[1]))' 2>/dev/null)
    if [ -n "$PY_VER" ]; then
        PY_BIN="python3"
    fi
fi

if [ -z "$PY_VER" ] || [ -z "$PY_BIN" ]; then
    print_error "Python is not installed or detected on this device!"
    exit 1
fi

case $PY_VER in
   2.7|3.9|3.10|3.11|3.12|3.13|3.14|3.15)
        print_success "Detected Python Version: ${YELLOW}$PY_VER${NC}"
        ;;
    *)
        print_error "Python $PY_VER is not supported by this plugin version."
        exit 1
        ;;
esac
echo ""

# 4. مقارنة إصدار البلاجين (Local vs Remote)
print_info "Checking for updates..."

normalize_version() {
    echo "$1" | tr -cd '0-9.\n' | head -n 1 | sed 's/^\.*//; s/\.*$//'
}

version_newer_than() {
    "$PY_BIN" - "$1" "$2" <<'PY'
import sys, re
def parse(value):
    parts = re.findall(r'\d+', value or '')
    return tuple(int(p) for p in parts) if parts else (0,)
left = parse(sys.argv[1])
right = parse(sys.argv[2])
sys.exit(0 if left > right else 1)
PY
}

LOCAL_VERSION=""
if [ -f "$LOCAL_VERSION_FILE" ]; then
    LOCAL_VERSION=$(normalize_version "$(cat "$LOCAL_VERSION_FILE" 2>/dev/null)")
fi

REMOTE_VERSION_TMP="/tmp/furybiss_version.txt"
download_file "$REMOTE_VERSION_URL" "$REMOTE_VERSION_TMP"
REMOTE_VERSION=$(normalize_version "$(cat "$REMOTE_VERSION_TMP" 2>/dev/null)")
rm -f "$REMOTE_VERSION_TMP"

if [ -n "$REMOTE_VERSION" ] && [ -n "$LOCAL_VERSION" ]; then
    echo -e "   - Installed version: ${YELLOW}$LOCAL_VERSION${NC}"
    echo -e "   - Server version   : ${YELLOW}$REMOTE_VERSION${NC}"
    if ! version_newer_than "$REMOTE_VERSION" "$LOCAL_VERSION"; then
        print_warning "FuryBiss is the same or newer version, forcing reinstallation anyway..."
    else
        print_success "New version detected. Updating now..."
    fi
else
    print_warning "Version check info is incomplete. Continuing with installation..."
fi
echo ""

# 5. تنظيف الإصدارات القديمة
print_info "Removing old versions of FuryBiss..."
rm -f /tmp/furybiss_*

if [ "$IS_DREAMOS" = true ]; then
    apt-get remove -y enigma2-plugin-extensions-furybiss > /dev/null 2>&1
    apt-get remove -y enigma2-plugin-extensions-furybis > /dev/null 2>&1
else
    opkg remove enigma2-plugin-extensions-furybiss --force-depends > /dev/null 2>&1
    opkg remove enigma2-plugin-extensions-furybis --force-depends > /dev/null 2>&1
fi

if [ -d "$PLUGIN_DIR" ] ; then
    rm -rf "$PLUGIN_DIR"
    print_success "Old folder /FuryBiss deleted permanently."
else
    print_info "No old folder found. System is clean."
fi
echo ""

# 6. تحميل الحزمة
cd /tmp || exit 1

# تحديد اسم الملف بناءً على نوع الصورة
if [ "$IS_DREAMOS" = true ]; then
    FILE_NAME="furybiss_${PY_VER}_${ARCH}_dreamos.deb"
else
    FILE_NAME="furybiss_${PY_VER}_${ARCH}.ipk"
fi

DOWNLOAD_URL="${REPO_BASE_URL}/${FILE_NAME}"

print_info "Downloading FuryBiss package: ${YELLOW}${FILE_NAME}${NC} ..."
download_file "${DOWNLOAD_URL}" "/tmp/${FILE_NAME}"

if [ ! -s "/tmp/${FILE_NAME}" ] || [ $(stat -c%s "/tmp/${FILE_NAME}") -lt 1000 ]; then
    print_error "Failed to download ${FILE_NAME} or file is corrupted."
    rm -f "/tmp/${FILE_NAME}"
    exit 1
fi
print_success "Download completed."
echo ""

# 7. تثبيت التحديث
print_info "Installing new version..."
INSTALL_LOG="/tmp/furybiss_install.log"

if [ "$IS_DREAMOS" = true ]; then
    dpkg -i "/tmp/${FILE_NAME}" > "$INSTALL_LOG" 2>&1
    apt-get install -f -y >> "$INSTALL_LOG" 2>&1
    INSTALL_RESULT=$?
else
    opkg install --force-reinstall --force-overwrite "/tmp/${FILE_NAME}" > "$INSTALL_LOG" 2>&1
    INSTALL_RESULT=$?
fi

if [ $INSTALL_RESULT -ne 0 ]; then
    print_error "Installation of FuryBiss failed."
    cat "$INSTALL_LOG"
    rm -f "/tmp/${FILE_NAME}"
    rm -f "$INSTALL_LOG"
    exit 1
fi

rm -f "/tmp/${FILE_NAME}"
rm -f "$INSTALL_LOG"
print_success "Temporary files cleaned."
echo ""

# ==============================================================================
# نهاية التثبيت
# ==============================================================================
print_divider
echo -e "${GREEN}             FuryBiss Installed Successfully!               ${NC}"
echo -e "${YELLOW}                        Long live Egypt.               ${NC}"
echo -e "${CYAN}             Please wait... Restarting Enigma2 GUI...             ${NC}"
print_divider

sleep 3
if command -v systemctl >/dev/null 2>&1; then
    systemctl restart enigma2
else
    killall -9 enigma2
fi

exit 0
