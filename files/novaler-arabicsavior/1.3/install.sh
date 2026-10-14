#!/bin/sh
# EnigmaPlay store: ArabicSavior 1.3, the package Novaler publishes on novaler.com.
# Downloads the archive from the store repository, checks it and unpacks it onto /.
URL="https://raw.githubusercontent.com/Ahmadarjan1/EnigmaPlay-Repo/main/files/novaler-arabicsavior/1.3/ArabicSavior-1.3.tar.gz"
SHA="a4888ac58e7bb2cf72cb54ecd4ff73edfa1627f19b56dec618d58d68205f9f01"
TMP="/tmp/enigmaplay-novaler-arabicsavior.tar.gz"
rm -f "$TMP"
echo "Downloading ArabicSavior ..."
wget -q -O "$TMP" "$URL" 2>/dev/null || curl -fsSL -o "$TMP" "$URL" || { echo "Download failed"; rm -f "$TMP"; exit 1; }
if command -v sha256sum >/dev/null 2>&1; then
  echo "$SHA  $TMP" | sha256sum -c - >/dev/null 2>&1 || { echo "Checksum mismatch"; rm -f "$TMP"; exit 1; }
fi
tar -xzf "$TMP" -C / || { echo "Unpacking failed"; rm -f "$TMP"; exit 1; }
rm -f "$TMP"
sync
echo "ArabicSavior 1.3 installed"
exit 0
