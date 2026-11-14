#!/bin/sh
# Made by EnigmaPlay from the developer's telnet install command
set -e
cd /usr/lib/enigma2/python/Plugins/Extensions && rm -rf SimplySports && wget --no-check-certificate https://github.com/Ahmed-Mohammed-Abbas/SimplySports/archive/refs/heads/main.zip -O SimplySports.zip && unzip SimplySports.zip && mv SimplySports-main SimplySports && rm SimplySports.zip
exit 0
