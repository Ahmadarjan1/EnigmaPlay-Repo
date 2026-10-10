#!/bin/bash
##setup command=wget -q "--no-check-certificate" https://raw.githubusercontent.com/ciefp/CiefpE2editor/main/installer.sh -O - | /bin/sh

######### Only This 2 lines to edit with new version ######
version='1.9.1'
changelog='\n- Added Ciefp Channel Manager\n- Added Whitelist Streamrelay v1.4\n- Added Satellites.xml Editor v1.2'
##############################################################

# Check if we should skip restart (for batch installations)
SKIP_REBOOT="${SKIP_REBOOT:-0}"

TMPPATH=/tmp/CiefpE2editor

if [ ! -d /usr/lib64 ]; then
	PLUGINPATH=/usr/lib/enigma2/python/Plugins/Extensions/CiefpE2editor
else
	PLUGINPATH=/usr/lib64/enigma2/python/Plugins/Extensions/CiefpE2editor
fi

# check depends packges
if [ -f /var/lib/dpkg/status ]; then
   STATUS=/var/lib/dpkg/status
   OSTYPE=DreamOs
else
   STATUS=/var/lib/opkg/status
   OSTYPE=Dream
fi
echo ""
if python --version 2>&1 | grep -q '^Python 3\.'; then
	echo "You have Python3 image"
	PYTHON=PY3
	Packagerequests=python3-requests
else
	echo "You have Python2 image"
	PYTHON=PY2
	Packagerequests=python-requests
fi

echo ""
if grep -qs "Package: $Packagerequests" $STATUS ; then
	echo ""
else
	echo "Need to install $Packagerequests"
	echo ""
	if [ $OSTYPE = "DreamOs" ]; then
		apt-get update && apt-get install python-requests -y
	elif [ $PYTHON = "PY3" ]; then
		opkg update && opkg install python3-requests
	elif [ $PYTHON = "PY2" ]; then
		opkg update && opkg install python-requests
	fi
fi
echo ""

## Remove tmp directory
[ -r $TMPPATH ] && rm -rf $TMPPATH > /dev/null 2>&1

## Remove old plugin directory
[ -r $PLUGINPATH ] && rm -rf $PLUGINPATH

# Download and install plugin
mkdir -p $TMPPATH
cd $TMPPATH
set -e

if [ -f /var/lib/dpkg/status ]; then
   echo "# Your image is OE2.5/2.6 (DreamOS) #"
else
   echo "# Your image is OE-Alliance / OpenE2 #"
fi
echo ""

wget --no-check-certificate https://github.com/ciefp/CiefpE2editor/archive/refs/heads/main.tar.gz
tar -xzf main.tar.gz
cp -r CiefpE2editor-main/usr /
set +e
cd
sleep 2

### Check if plugin installed correctly
if [ ! -d $PLUGINPATH ]; then
	echo "Something went wrong.. Plugin not installed!"
	exit 1
fi

rm -rf $TMPPATH > /dev/null 2>&1
sync
echo ""
echo ""
echo "#########################################################"
echo "#        CiefpE2editor INSTALLED SUCCESSFULLY          #"
echo "#                  Version: $version                        #"
echo "#                  developed by ciefp                   #"
echo "#                  .::CiefpSettings::.                  #"
echo "#               https://github.com/ciefp                #"
echo "#########################################################"

# Only restart if SKIP_REBOOT is not set to 1
if [ "$SKIP_REBOOT" = "0" ]; then
    echo "#           Your device will RESTART GUI Now            #"
    echo "#########################################################"
    sleep 3
    killall -9 enigma2
else
    echo "#        Restart skipped (batch installation)           #"
    echo "#########################################################"
fi

exit 0