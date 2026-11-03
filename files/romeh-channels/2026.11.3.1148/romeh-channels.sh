#!/bin/sh
# Channel list by rome7 (Online 4 Tech / Romeh) for Enigma2 - installer used by the EnigmaPlay store.
# Takes the latest list from the developer's GitHub, keeps a backup of the current list, installs,
# and reloads the channel list without a GUI restart.
# Bouquets for pirated streams (icam / streamrelay) are not installed.
REPO_TGZ="https://github.com/online4tech/Enigma2-Chanal-List-BYRomeh/archive/refs/heads/main.tar.gz"
TMP=/tmp/ep_romeh_list
DEST=/etc/enigma2

echo "Downloading the channel list (rome7)..."
rm -rf "$TMP"; mkdir -p "$TMP"
if command -v wget >/dev/null 2>&1; then
    wget -q --no-check-certificate -O "$TMP/list.tgz" "$REPO_TGZ"
else
    curl -skL -o "$TMP/list.tgz" "$REPO_TGZ"
fi
if [ ! -s "$TMP/list.tgz" ] || ! tar -xzf "$TMP/list.tgz" -C "$TMP" 2>/dev/null; then
    echo "Download failed, nothing was changed."; rm -rf "$TMP"; exit 1
fi
SRC=$(find "$TMP" -maxdepth 1 -type d -name "Enigma2-Chanal-List-BYRomeh*" | head -n 1)
if [ -z "$SRC" ] || [ ! -s "$SRC/lamedb" ] || [ ! -s "$SRC/bouquets.tv" ]; then
    echo "The list is incomplete, nothing was changed."; rm -rf "$TMP"; exit 1
fi

# drop bouquets of pirated streams (icam / streamrelay)
for f in "$SRC"/userbouquet.*; do
    [ -f "$f" ] || continue
    if echo "$f" | grep -qi "icam" || head -n 1 "$f" | grep -qi "icam\|streamrelay"; then
        b=$(basename "$f"); rm -f "$f"
        grep -v "\"$b\"" "$SRC/bouquets.tv" > "$SRC/bouquets.tv.new" && mv "$SRC/bouquets.tv.new" "$SRC/bouquets.tv"
    fi
done

# backup of the current list
BK="$DEST/channels_backup_$(date +%Y%m%d_%H%M%S).tar.gz"
( cd "$DEST" && tar -czf "$BK" lamedb lamedb5 bouquets.tv bouquets.radio userbouquet.* blacklist whitelist 2>/dev/null )
echo "Backup of your old list: $BK"

# install
rm -f "$DEST"/userbouquet.*.tv "$DEST"/userbouquet.*.radio "$DEST"/userbouquet.*.del "$DEST"/lamedb5
cp -f "$SRC/lamedb" "$SRC/bouquets.tv" "$DEST/"
[ -f "$SRC/bouquets.radio" ] && cp -f "$SRC/bouquets.radio" "$DEST/"
cp -f "$SRC"/userbouquet.* "$DEST/" 2>/dev/null
[ -f "$SRC/blacklist" ] && cp -f "$SRC/blacklist" "$DEST/"
if [ -s "$SRC/satellites.xml" ]; then
    [ -f /etc/tuxbox/satellites.xml ] && cp -f /etc/tuxbox/satellites.xml /etc/tuxbox/satellites.xml.bak
    cp -f "$SRC/satellites.xml" /etc/tuxbox/satellites.xml 2>/dev/null
fi
rm -rf "$TMP"

# reload the list in the running GUI
wget -qO /dev/null "http://127.0.0.1/web/servicelistreload?mode=0" 2>/dev/null || true
echo "Channel list installed."
exit 0
