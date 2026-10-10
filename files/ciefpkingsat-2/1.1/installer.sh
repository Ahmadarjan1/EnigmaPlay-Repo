#!/bin/bash
## setup command: wget -q "--no-check-certificate" https://raw.githubusercontent.com/ciefp/CiefpKingSat/main/installer.sh -O - | /bin/sh

version='1.1'
changelog='Python detection fix for Scarthgap/OpenPLi 9'

# Check if we should skip restart (za tvoj multiboot plugin)
SKIP_REBOOT="${SKIP_REBOOT:-0}"

TMPPATH=/tmp/CiefpKingSat
if [ ! -d /usr/lib64 ]; then
    PLUGINPATH=/usr/lib/enigma2/python/Plugins/Extensions/CiefpKingSat
else
    PLUGINPATH=/usr/lib64/enigma2/python/Plugins/Extensions/CiefpKingSat
fi

echo "Checking internet connection..."
if ! ping -c 1 8.8.8.8 >/dev/null 2>&1; then
    echo "No internet connection! Check DNS (Nameserver) settings."
    exit 1
fi

# OSIGURAJ OPKG UPDATE (Ključno za OpenPLi)
echo "Updating opkg feeds..."
opkg update >/dev/null 2>&1

# NOVA DETEKCIJA PYTHONA
echo "Checking Python version and dependencies..."
if command -v python3 >/dev/null 2>&1; then
    echo "Python 3 detected."
    PYTHON_PKGS="python3-requests python3-beautifulsoup4 python3-lxml python3-six"
elif command -v python2 >/dev/null 2>&1; then
    echo "Python 2 detected."
    PYTHON_PKGS="python-requests python-beautifulsoup4 python-xml python-six"
else
    # Ako nema ni jednog ni drugog, verovatno je problem sa PATH, ali pretpostavi Py3 za nove slike
    echo "Could not auto-detect Python, trying Python 3 defaults..."
    PYTHON_PKGS="python3-requests python3-beautifulsoup4 python3-lxml"
fi

# INSTALACIJA ZAVISNOSTI
for pkg in $PYTHON_PKGS; do
    if opkg list-installed | grep -q "^$pkg -"; then
        echo "$pkg is already installed."
    else
        echo "Installing $pkg..."
        opkg install $pkg || echo "Warning: Failed to install $pkg, plugin might fail."
    fi
done

# DOWNLOAD I INSTALACIJA PLUGINA
echo "Downloading CiefpKingSat..."
cd /tmp
rm -rf $TMPPATH >/dev/null 2>&1
mkdir -p $TMPPATH
cd $TMPPATH

wget --no-check-certificate https://github.com/ciefp/CiefpKingSat/archive/refs/heads/main.tar.gz || { echo "Download failed!"; exit 1; }
tar -xzf main.tar.gz
cp -r CiefpKingSat-main/usr /

if [ ! -d $PLUGINPATH ]; then
    echo "Something went wrong... Plugin folder not found."
    exit 1
fi

rm -rf $TMPPATH >/dev/null 2>&1
sync

echo ""
echo "#########################################################"
echo "#           CiefpKingSat INSTALLED SUCCESSFULLY         #"
echo "#                  developed by ciefp                   #"
echo "#                  .::CiefpSettings::.                  #"
echo "#               https://github.com/ciefp                #"
echo "#########################################################"

# REBOOT LOGIKA (Poštuje tvoj SKIP_REBOOT flag)
if [ "$SKIP_REBOOT" = "0" ]; then
    echo "#           Your device will RESTART Now                #"
    sleep 3
    killall -9 enigma2
else
    echo "#           Installation finished (No Reboot)           #"
fi