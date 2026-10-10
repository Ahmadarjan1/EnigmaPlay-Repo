#!/bin/bash
##setup command=wget -q "--no-check-certificate" https://raw.githubusercontent.com/ciefp/CiefpEasySetup/main/installer.sh -O - | /bin/sh

######### Verzija 1.0 - PY3 Multi-Image ##########
version='1.0'
##################################################

SKIP_REBOOT="${SKIP_REBOOT:-0}"
TMPPATH=/tmp/CiefpEasySetup

if [ ! -d /usr/lib64 ]; then
    PLUGINPATH=/usr/lib/enigma2/python/Plugins/Extensions/CiefpEasySetup
else
    PLUGINPATH=/usr/lib64/enigma2/python/Plugins/Extensions/CiefpEasySetup
fi

# Detekcija sistema (DreamOS vs standardni OpenAlliance)
if [ -f /var/lib/dpkg/status ]; then
   STATUS=/var/lib/dpkg/status
   OSTYPE=DreamOs
else
   STATUS=/var/lib/opkg/status
   OSTYPE=Dream
fi

# Provera Python verzije
if python --version 2>&1 | grep -q '^Python 3\.'; then
    PYTHON=PY3
    Packagesix=python3-six
    Packagerequests=python3-requests
else
    PYTHON=PY2
    Packagesix=python-six
    Packagerequests=python-requests
fi

# Instalacija zavisnosti (Dependencies)
install_dep() {
    if ! grep -qs "Package: $1" "$STATUS"; then
        echo "Instaliram $1..."
        if [ "$OSTYPE" = "DreamOs" ]; then
            apt-get update && apt-get install "$1" -y
        else
            opkg update && opkg install "$1"
        fi
    fi
}

install_dep "wget"
install_dep "$Packagesix"
install_dep "$Packagerequests"

## Čišćenje pre instalacije
rm -rf $TMPPATH > /dev/null 2>&1
rm -rf $PLUGINPATH > /dev/null 2>&1

## Preuzimanje i instalacija
mkdir -p $TMPPATH
cd $TMPPATH
set -e

wget --no-check-certificate https://github.com/ciefp/CiefpEasySetup/archive/refs/heads/main.tar.gz
tar -xzf main.tar.gz
cp -r 'CiefpEasySetup-main/usr' '/'

set +e
cd /
sleep 2

### Provera uspešnosti
if [ ! -d $PLUGINPATH ]; then
    echo "Greška: Plugin nije uspešno instaliran!"
    exit 1
fi

rm -rf $TMPPATH > /dev/null 2>&1
sync
echo ""
echo ""
echo "#########################################################"
echo "#          CiefpPlugins INSTALLED SUCCESSFULLY          #"
echo "#                  developed by ciefp                   #"
echo "#                  .::CiefpSettings::.                  #"
echo "#               https://github.com/ciefp                #"
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