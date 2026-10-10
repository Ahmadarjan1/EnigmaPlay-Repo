#!/bin/bash
##setup command=wget -q "--no-check-certificate" https://raw.githubusercontent.com/ciefp/TitloviBrowser/main/installer.sh -O - | /bin/sh

######### Only This 2 lines to edit with new version ######
version='1.1'
changelog='\nFix little bugs\nUpdated Picons List'
###########################################################

# Check if we should skip restart (for batch installations)
SKIP_REBOOT="${SKIP_REBOOT:-0}"

TMPPATH=/tmp/TitloviBrowser

if [ ! -d /usr/lib64 ]; then
	PLUGINPATH=/usr/lib/enigma2/python/Plugins/Extensions/TitloviBrowser
else
	PLUGINPATH=/usr/lib64/enigma2/python/Plugins/Extensions/TitloviBrowser
fi

# OE2.0 koristi opkg status
STATUS=/var/lib/opkg/status
OSTYPE=Dream

echo ""
# Detect Python major version
if python --version 2>&1 | grep -q '^Python 3\.'; then
	echo "You have Python3 image"
	PYTHON=PY3
	Packagesix=python3-six
	Packagerequests=python3-requests
	Packagebs4=python3-beautifulsoup4
else
	echo "You have Python2 image"
	PYTHON=PY2
	Packagerequests=python-requests
	Packagebs4=python-beautifulsoup4
fi

# Install six only for Python3 images
if [ "$PYTHON" = "PY3" ]; then
	if grep -qs "Package: $Packagesix" "$STATUS" ; then
		echo "OK: $Packagesix already installed"
	else
		echo "Installing: $Packagesix"
		opkg update && opkg install "$Packagesix"
	fi
fi

echo ""
# Install requests
if grep -qs "Package: $Packagerequests" "$STATUS" ; then
	echo "OK: $Packagerequests already installed"
else
	echo "Need to install $Packagerequests"
	opkg update && opkg install "$Packagerequests"
fi

echo ""
# Install BeautifulSoup4 (bs4)
if grep -qs "Package: $Packagebs4" "$STATUS" ; then
	echo "OK: $Packagebs4 already installed"
else
	echo "Need to install $Packagebs4"
	opkg update && opkg install "$Packagebs4"
fi

echo ""

## Remove tmp directory
[ -r "$TMPPATH" ] && rm -rf "$TMPPATH" > /dev/null 2>&1

## Remove old plugin directory
[ -r "$PLUGINPATH" ] && rm -rf "$PLUGINPATH"

# Download and install plugin
mkdir -p "$TMPPATH"
cd "$TMPPATH" || exit 1
set -e

echo "# Your image is OE2.0 #"
echo ""

wget https://github.com/ciefp/TitloviBrowser/archive/refs/heads/main.tar.gz
tar -xzf main.tar.gz
cp -r 'TitloviBrowser-main/usr' '/'

set +e
cd /
sleep 2

### Check if plugin installed correctly
if [ ! -d "$PLUGINPATH" ]; then
	echo "Some thing wrong .. Plugin not installed"
	exit 1
fi

rm -rf "$TMPPATH" > /dev/null 2>&1
sync

echo ""
echo "#########################################################"
echo "#         TitloviBrowser INSTALLED SUCCESSFULLY         #"
echo "#                  developed by ciefp                   #"
echo "#                  .::CiefpSettings::.                  #"
echo "#                https://github.com/ciefp               #"
echo "#########################################################"

# Only restart if SKIP_REBOOT is not set to 1
if [ "$SKIP_REBOOT" = "0" ]; then
    echo "#           your Device will RESTART Now                #"
    echo "#########################################################"
    sleep 5
    killall -9 enigma2
else
    echo "#        Restart skipped (batch installation)           #"
    echo "#########################################################"
fi

exit 0