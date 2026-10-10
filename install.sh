#!/bin/sh
# ------------------------------------------------------------------
# EnigmaPlay - one-line installer for Enigma2 boxes
#   wget -qO- https://raw.githubusercontent.com/Ahmadarjan1/EnigmaPlay-Repo/main/install.sh | sh
# POSIX sh (BusyBox ash / bash). Picks .ipk (opkg images) or .deb (apt/dpkg images).
# ------------------------------------------------------------------
REPO="https://raw.githubusercontent.com/Ahmadarjan1/EnigmaPlay-Repo/main"
PKG="enigma2-plugin-extensions-enigmaplay"
LOG="/tmp/enigmaplay_install.log"
TMP="/tmp/enigmaplay_pkg"

G='\033[0;32m'; Y='\033[1;33m'; C='\033[0;36m'; R='\033[0;31m'; N='\033[0m'
say()  { printf "%b\n" "$*"; }
fail() { say "${R}ERROR: $*${N}"; say "${C}Details: $LOG${N}"; rm -f "$TMP".*; exit 1; }
fetch() {   # fetch <url> <file>
    wget -q -O "$2" "$1" >>"$LOG" 2>&1 \
      || wget -q --no-check-certificate -O "$2" "$1" >>"$LOG" 2>&1 \
      || { command -v curl >/dev/null 2>&1 && curl -k -s -L -f -o "$2" "$1" >>"$LOG" 2>&1; }
}

: > "$LOG"
say "${C}##############################################${N}"
say "${Y}###        EnigmaPlay - Setup               ###${N}"
say "${C}##############################################${N}"

# ---- Python 3 is required ------------------------------------------------------------
PY=""
for p in python3 python; do command -v "$p" >/dev/null 2>&1 && { PY="$p"; break; }; done
[ -n "$PY" ] || fail "Python not found on this image."
PYV=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>>"$LOG")
case "$PYV" in 3.*) ;; *) fail "EnigmaPlay needs a Python 3 image (found Python $PYV)." ;; esac
say "Python: ${G}${PYV}${N}"

# ---- latest version from the store index ------------------------------------------------
fetch "$REPO/index.json" "$TMP.json" || fail "Cannot reach GitHub. Check the internet connection and the date/time of the box."
VER=$("$PY" - "$TMP.json" <<'EOF'
import json, sys
for it in json.load(open(sys.argv[1])).get("items", []):
    if it.get("id") == "enigmaplay":
        print(it.get("version", "")); break
EOF
)
[ -n "$VER" ] || fail "EnigmaPlay was not found in the store index."
say "Latest version: ${G}${VER}${N}"

# ---- package manager -----------------------------------------------------------------
if command -v opkg >/dev/null 2>&1; then
    KIND="ipk"
elif command -v dpkg >/dev/null 2>&1; then
    KIND="deb"
else
    fail "No opkg/dpkg found on this image."
fi
URL="$REPO/files/enigmaplay/$VER/${PKG}_${VER}_all.$KIND"
FILE="$TMP.$KIND"

say "Downloading: ${C}${URL}${N}"
rm -f "$FILE"
fetch "$URL" "$FILE"
[ -s "$FILE" ] || fail "Download failed."
[ "$(dd if="$FILE" bs=7 count=1 2>/dev/null)" = "!<arch>" ] || fail "The downloaded file is not a valid package."

# ---- wait while another package manager is running (image updates, other plugin installers) ----
wait_pm() {
    i=0
    while pidof opkg >/dev/null 2>&1 || pidof apt-get >/dev/null 2>&1 || pidof dpkg >/dev/null 2>&1; do
        [ $i -eq 0 ] && say "${Y}Another install/update is running on the box, waiting ...${N}"
        i=$((i + 1))
        if [ $i -gt 90 ]; then
            say "${R}The package manager is still busy after 3 minutes:${N}"
            ps 2>/dev/null | grep -E "opkg|apt|dpkg" | grep -v grep
            fail "Wait until it finishes (or restart the box) and run this command again."
        fi
        sleep 2
    done
}

# ---- Pillow (used for icons/screenshots) ----------------------------------------------
if ! "$PY" -c "import PIL" >/dev/null 2>&1; then
    wait_pm
    say "${Y}Installing Pillow ...${N}"
    if [ "$KIND" = "ipk" ]; then
        opkg update >>"$LOG" 2>&1
        opkg install python3-pillow >>"$LOG" 2>&1
    else
        apt-get update >>"$LOG" 2>&1
        apt-get install -y python3-pil >>"$LOG" 2>&1 || apt-get install -y python3-pillow >>"$LOG" 2>&1
    fi
fi

# ---- install ----------------------------------------------------------------------------
wait_pm
say "${G}Installing EnigmaPlay ${VER} ...${N}"
if [ "$KIND" = "ipk" ]; then
    for try in 1 2 3; do
        opkg install --force-reinstall --force-overwrite "$FILE" >>"$LOG" 2>&1 \
          || opkg install --nodeps --force-reinstall --force-overwrite "$FILE" >>"$LOG" 2>&1
        RC=$?
        tail -n 5 "$LOG" | grep -q "Could not lock" || break
        say "${Y}Package manager busy, retrying ...${N}"; sleep 10; wait_pm
    done
else
    export DEBIAN_FRONTEND=noninteractive
    apt-get install -y --allow-downgrades --reinstall "$FILE" >>"$LOG" 2>&1 \
      || { dpkg -i --force-overwrite "$FILE" >>"$LOG" 2>&1 && apt-get -f install -y >>"$LOG" 2>&1; }
    RC=$?
fi
rm -f "$TMP".*
# Judge success by what is really installed, not by the exit code: on some images opkg also tries to
# install unrelated packages left half-installed by other plugins (and fails), returning an error
# even though EnigmaPlay itself was installed fine.
if [ "$KIND" = "ipk" ]; then
    NEW=$(opkg status "$PKG" 2>/dev/null | sed -n 's/^Version: *//p' | head -n1)
else
    NEW=$(dpkg-query -W -f='${Version}' "$PKG" 2>/dev/null)
fi
if [ "$NEW" != "$VER" ] || [ ! -f /usr/lib/enigma2/python/Plugins/Extensions/EnigmaPlay/plugin.py ]; then
    say "${R}Installation failed (code $RC). Last messages:${N}"
    tail -n 15 "$LOG"
    exit 1
fi
[ $RC -eq 0 ] || say "${Y}Note: the package manager reported errors about other packages (see $LOG), EnigmaPlay itself is installed.${N}"

say "${G}EnigmaPlay ${VER} installed successfully.${N}"
say "${C}Restarting Enigma2 ...${N}"
sleep 2
if command -v systemctl >/dev/null 2>&1 && systemctl is-active enigma2 >/dev/null 2>&1; then
    systemctl restart enigma2
else
    killall -9 enigma2 >/dev/null 2>&1
fi
exit 0
