#!/bin/sh
#
echo "DOWNLOAD AND INSTALL multi-stalkerpro"

#
plugin="multi_stalkerpro"
git_url="https://raw.githubusercontent.com/emilnabil/multi-stalkerpro/main"
version="1.2"
PLUGIN_PATH="/usr/lib/enigma2/python/Plugins/Extensions/MultiStalkerPro"
SETTINGS='/etc/enigma2/settings'
temp_dir="/tmp"
PYTHON_VERSION=$(python --version 2>&1 | awk '{print $2}')

#
if [ -z "$PYTHON_VERSION" ]; then
  echo "Python is not installed or could not detect Python version."
  exit 1
fi

#
if command -v apt-get > /dev/null 2>&1; then
  INSTALL="apt-get install -y"
  OPKGREMOV="apt-get purge --auto-remove -y"
  OS='DreamOS'
elif command -v opkg > /dev/null 2>&1; then
  INSTALL="opkg install --force-reinstall --force-depends"
  OPKGREMOV="opkg remove --force-depends"
  OS='Opensource'
else
  echo "Unsupported OS"
  exit 1
fi

# 
[ -e /etc/enigma2/MultiStalkerPro.json ] && cp -f /etc/enigma2/MultiStalkerPro.json "$temp_dir"

# 
$OPKGREMOV enigma2-plugin-extensions-multi-stalkerpro
OLD_PACKAGE=(
  "$PLUGIN_PATH"
  "/usr/lib/enigma2/python/Components/Converter/MultiStalkerAudioInfo*"
  "/usr/lib/enigma2/python/Components/Converter/MultiStalkerProServicePosition*"
  "/usr/lib/enigma2/python/Components/Converter/MultiStalkerProServiceResolution*"
  "/usr/lib/enigma2/python/Components/Renderer/MultiStalkerAudioIcon*"
  "/usr/lib/enigma2/python/Components/Renderer/MultiStalkerProRunningText*"
  "/usr/lib/enigma2/python/Components/Renderer/MultiStalkerProStars*"
)
for path in "${OLD_PACKAGE[@]}"; do
  [ -e "$path" ] && rm -rf "$path"
done
echo "Old Package removed"

#
case $PYTHON_VERSION in
  3.9.*) PY_VERSION='3.9' ;;
  3.10.*) PY_VERSION='3.10' ;;
  3.11.*) PY_VERSION='3.11' ;;
  3.12.*) PY_VERSION='3.12' ;;
  2.7.*) PY_VERSION='2.7' ;;
  *)
    echo "Unsupported Python version."
    exit 1
    ;;
esac

#
arch=$(uname -m)
case $arch in
  "mips")
    package_url="$git_url/multi-stalkerpro_mips32el_py${PY_VERSION}.tar.gz"
    if grep -qiE "openvix|openbh" /etc/image-version; then
      dependencies=("python3-rarfile_4.1-r0_mips32el.ipk")
      package_url="$git_url/multi-stalkerpro_mips32el_openvix-openbh_py3.12.tar.gz"
    elif grep -qi openpli /etc/issue; then
      dependencies=("python3.9-rarfile_4.1-r0_mips32el.ipk" "python3.9-levenshtein_0.12.0-r0_mips32el.ipk" "python3.9-fuzzywuzzy_0.18.0-r0_mips32el.ipk")
    fi
    ;;
  "armv7l")
    package_url="$git_url/multi-stalkerpro_armv7ahf_py${PY_VERSION}.tar.gz"
    if grep -qiE "openvix|openbh" /etc/image-version; then
      dependencies=("python3-rarfile_4.1-r0_cortexa15hf-neon-vfpv4.ipk")
      package_url="$git_url/multi-stalkerpro_armv7ahf_openvix-openbh_py3.12.tar.gz"
    elif grep -qi openpli /etc/issue; then
      dependencies=("python3-rarfile_4.1-r0_armv7ahf-neon.ipk" "python3-levenshtein_0.12.0-r0_armv7ahf-neon.ipk" "python3-fuzzywuzzy_0.18.0-r0_armv7ahf-neon.ipk")
    fi
    ;;
  "aarch64")
    package_url="$git_url/multi-stalkerpro_aarch64_py${PY_VERSION}.tar.gz"
    if grep -qiE "openvix|openbh" /etc/image-version; then
      dependencies=("python3-rarfile_4.1-r0_aarch64.ipk")
      package_url="$git_url/multi-stalkerpro_aarch64_openvix-openbh_py3.12.tar.gz"
    fi
    ;;
  *)
    echo "Unsupported architecture."
    exit 1
    ;;
esac

#
for dep in "${dependencies[@]}"; do
  curl -k -L "$git_url/$dep" -o "/tmp/$dep"
  $INSTALL "/tmp/$dep" && rm -f "/tmp/$dep"
done

# 
cd "$temp_dir" || exit 1
if ! wget "$package_url" -O multi-stalkerpro.tar.gz; then
  echo "Failed to download the package."
  exit 1
fi

if ! tar -xzf multi-stalkerpro.tar.gz -C /; then
  echo "Failed to extract the package."
  exit 1
fi
rm -f multi-stalkerpro.tar.gz

#
wget -q --no-check-certificate "$git_url/icon.png" -O "$PLUGIN_PATH/icon.png"

# 
[ -e /tmp/MultiStalkerPro.json ] && cp -f /tmp/MultiStalkerPro.json /etc/enigma2/MultiStalkerPro.json && rm -f /tmp/MultiStalkerPro.json

#
echo "###############################################################"
echo "#             multi-stalkerpro installed                      #"
echo "#              Uploaded By Emil_Nabil                         #"
echo "###############################################################"
sleep 3
echo "          Your Device Will RESTART Now  "
sleep 2

# 
if grep -q "DreamOS" /etc/issue && command -v systemctl > /dev/null 2>&1; then
  systemctl restart enigma2
else
  killall -9 enigma2
fi

exit 0






