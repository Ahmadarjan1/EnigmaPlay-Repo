#!/bin/sh
# EnigmaPlay store: Key-Adder 5.7, the package Novaler publishes on novaler.com.
# Downloads the archive from the store repository, checks it and unpacks it onto /.
URL="https://raw.githubusercontent.com/Ahmadarjan1/EnigmaPlay-Repo/main/files/novaler-key-adder/5.7/KeyAdder.tar.gz"
SHA="1321dc22b43d1a4b6baeeefb555aa979502bc45396e6e8337cee935eb3cc3926"
TMP="/tmp/enigmaplay-novaler-key-adder.tar.gz"
rm -f "$TMP"
echo "Downloading Key-Adder ..."
wget -q -O "$TMP" "$URL" 2>/dev/null || curl -fsSL -o "$TMP" "$URL" || { echo "Download failed"; rm -f "$TMP"; exit 1; }
if command -v sha256sum >/dev/null 2>&1; then
  echo "$SHA  $TMP" | sha256sum -c - >/dev/null 2>&1 || { echo "Checksum mismatch"; rm -f "$TMP"; exit 1; }
fi
tar -xzf "$TMP" -C / || { echo "Unpacking failed"; rm -f "$TMP"; exit 1; }
rm -f "$TMP"
sync
echo "Key-Adder 5.7 installed"
exit 0
