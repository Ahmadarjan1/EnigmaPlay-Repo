#!/bin/bash
##setup command=wget -q "--no-check-certificate" https://raw.githubusercontent.com/ciefp/CiefpYouTube/main/installer.sh -O - | /bin/sh

######### Only This 2 lines to edit with new version ######
version='1.2'
changelog='\nAdded ffmpeg, nodejs, yt-dlp-ejs and yt-dlp config for FHD/4K support on all images'
##############################################################

# Check if we should skip restart (for batch installations)
SKIP_REBOOT="${SKIP_REBOOT:-0}"

TMPPATH=/tmp/CiefpYouTube

if [ ! -d /usr/lib64 ]; then
	PLUGINPATH=/usr/lib/enigma2/python/Plugins/Extensions/CiefpYouTube
else
	PLUGINPATH=/usr/lib64/enigma2/python/Plugins/Extensions/CiefpYouTube
fi

# Check package manager status
if [ -f /var/lib/dpkg/status ]; then
	STATUS=/var/lib/dpkg/status
	OSTYPE=DreamOs
else
	STATUS=/var/lib/opkg/status
	OSTYPE=Dream
fi

echo ""
echo "============================================================="
echo "     CiefpYouTube v$version Installer"
echo "============================================================="
echo ""

# ============ DETEKCIJA OPENATV VERZIJE ============
get_openatv_version() {
	if [ -f /etc/image-version ]; then
		grep -i "version=" /etc/image-version 2>/dev/null | cut -d'=' -f2 | cut -d'.' -f1,2
	else
		echo ""
	fi
}

# ============ INSTALACIJA ffmpeg (obavezno za spajanje video/audio) ============
install_ffmpeg() {
	echo "[CiefpYouTube] Installing ffmpeg (required for video/audio merging)..."
	
	if [ $OSTYPE = "DreamOs" ]; then
		apt-get update && apt-get install ffmpeg -y
	else
		opkg update && opkg install ffmpeg
	fi
	
	if command -v ffmpeg >/dev/null 2>&1; then
		echo "[CiefpYouTube] ffmpeg installed successfully: $(ffmpeg -version | head -1)"
	else
		echo "[CiefpYouTube] WARNING: ffmpeg installation failed - FHD/4K may not work!"
	fi
}

# ============ INSTALACIJA yt-dlp ============
install_ytdlp() {
	echo "[CiefpYouTube] Installing yt-dlp..."
	
	if [ $OSTYPE = "DreamOs" ]; then
		apt-get update
		apt-get install python3-yt-dlp -y || {
			echo "[CiefpYouTube] python3-yt-dlp not in repo, installing via pip3..."
			apt-get install python3-pip python3-codecs python3-core -y
			pip3 install yt-dlp --upgrade
		}
	else
		opkg update
		opkg install python3-yt-dlp || {
			echo "[CiefpYouTube] python3-yt-dlp not in feed, trying pip3..."
			opkg install python3-pip python3-codecs python3-core
			pip3 install yt-dlp --upgrade
		}
	fi
	
	if command -v yt-dlp >/dev/null 2>&1; then
		echo "[CiefpYouTube] yt-dlp installed successfully: $(yt-dlp --version)"
	else
		echo "[CiefpYouTube] WARNING: yt-dlp installation failed!"
	fi
}

# ============ INSTALACIJA Node.js (JavaScript runtime za yt-dlp) ============
install_nodejs() {
	echo "[CiefpYouTube] Checking for Node.js (required for YouTube JS challenges)..."
	
	if command -v node >/dev/null 2>&1; then
		echo "[CiefpYouTube] Node.js already installed: $(node --version)"
		return 0
	fi
	
	echo "[CiefpYouTube] Installing Node.js..."
	if [ $OSTYPE = "DreamOs" ]; then
		apt-get update && apt-get install nodejs -y
	else
		opkg update && opkg install nodejs
	fi
	
	if command -v node >/dev/null 2>&1; then
		echo "[CiefpYouTube] Node.js installed: $(node --version)"
	else
		echo "[CiefpYouTube] WARNING: Node.js installation failed - trying alternative..."
		# Pokušaj sa deno ako node ne radi (za ARM uređaje)
		install_deno
	fi
}

# ============ INSTALACIJA Deno (alternativa za Node.js) ============
install_deno() {
	echo "[CiefpYouTube] Installing Deno as Node.js alternative..."
	
	# Detekcija arhitekture
	ARCH=$(uname -m)
	case "$ARCH" in
		aarch64)
			DENO_URL="https://github.com/denoland/deno/releases/download/v1.40.0/deno-aarch64-unknown-linux-gnu.zip"
			;;
		armv7l)
			DENO_URL="https://github.com/denoland/deno/releases/download/v1.40.0/deno-armv7-unknown-linux-gnueabihf.zip"
			;;
		*)
			DENO_URL="https://github.com/denoland/deno/releases/download/v1.40.0/deno-x86_64-unknown-linux-gnu.zip"
			;;
	esac
	
	cd /tmp
	wget --no-check-certificate "$DENO_URL" -O deno.zip
	unzip -o deno.zip
	chmod +x deno
	cp deno /usr/bin/
	rm -f deno.zip deno
	
	if command -v deno >/dev/null 2>&1; then
		echo "[CiefpYouTube] Deno installed successfully: $(deno --version | head -1)"
		DENO_INSTALLED=true
	else
		echo "[CiefpYouTube] WARNING: Deno installation failed!"
		DENO_INSTALLED=false
	fi
}

# ============ INSTALACIJA yt-dlp-ejs (EJS challenge solver) ============
install_ytdlp_ejs() {
	echo "[CiefpYouTube] Installing yt-dlp-ejs (EJS challenge solver)..."
	
	if command -v pip3 >/dev/null 2>&1; then
		pip3 install yt-dlp-ejs --upgrade
	else
		if [ $OSTYPE = "DreamOs" ]; then
			apt-get install python3-pip -y
		else
			opkg install python3-pip
		fi
		pip3 install yt-dlp-ejs --upgrade
	fi
	
	if pip3 show yt-dlp-ejs >/dev/null 2>&1; then
		echo "[CiefpYouTube] yt-dlp-ejs installed successfully"
	else
		echo "[CiefpYouTube] WARNING: yt-dlp-ejs installation failed!"
	fi
}

# ============ KREIRANJE yt-dlp CONFIG FAJLA (KLJUČNO ZA FHD/4K) ============
create_ytdlp_config() {
	echo "[CiefpYouTube] Creating yt-dlp configuration file..."
	
	mkdir -p /home/root/.config/yt-dlp
	
	# Osnovni config
	cat > /home/root/.config/yt-dlp/config << 'EOF'
# FHD/4K format - best video + best audio merged
-f bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best

# Tihi rad
--no-warnings

# Koristi samo kompatibilne formate
--no-check-formats

# Preuzmi EJS sa GitHub-a
--remote-components ejs:github

# Spajanje streamova
--merge-output-format mp4
EOF

	# Dodaj JS runtime (node ili deno)
	if command -v node >/dev/null 2>&1; then
		echo "--js-runtimes node" >> /home/root/.config/yt-dlp/config
		echo "[CiefpYouTube] yt-dlp configured to use Node.js"
	elif command -v deno >/dev/null 2>&1; then
		echo "--js-runtimes deno" >> /home/root/.config/yt-dlp/config
		echo "[CiefpYouTube] yt-dlp configured to use Deno"
	fi
	
	# Dodaj format sort za bolji odabir
	echo "--format-sort res:1080,codec:av1:mp4" >> /home/root/.config/yt-dlp/config
	
	echo "[CiefpYouTube] yt-dlp configuration created successfully"
}

# ============ INSTALACIJA python3-requests ============
if grep -qs "Package: python3-requests" $STATUS ; then
	echo "[CiefpYouTube] python3-requests is already installed."
else
	echo "[CiefpYouTube] python3-requests is missing! Installing..."
	if [ $OSTYPE = "DreamOs" ]; then
		apt-get update && apt-get install python3-requests -y
	else
		opkg update && opkg install python3-requests
	fi
fi

# ============ INSTALACIJA python3-json ============
if [ $OSTYPE != "DreamOs" ]; then
	if ! opkg list-installed | grep -q "python3-json"; then
		echo "[CiefpYouTube] Installing python3-json..."
		opkg update && opkg install python3-json > /dev/null 2>&1
	fi
fi

echo ""

# ============ INSTALACIJA SVIH KOMPONENTI ZA FHD/4K ============
echo "============================================================="
echo "     Installing FHD/4K required components..."
echo "============================================================="
echo ""

# 1. Instaliraj ffmpeg
install_ffmpeg

# 2. Instaliraj yt-dlp
install_ytdlp

# 3. Instaliraj Node.js (ili Deno)
install_nodejs

# 4. Instaliraj yt-dlp-ejs
install_ytdlp_ejs

# 5. Kreiraj config fajl (OVO JE NAJVAŽNIJE!)
create_ytdlp_config

echo ""

# ============ INSTALACIJA PLUGINA ============
## Remove old tmp directory if exists
[ -d $TMPPATH ] && rm -rf $TMPPATH > /dev/null 2>&1

## Remove old plugin directory before upgrade
[ -d $PLUGINPATH ] && rm -rf $PLUGINPATH

# Download and install plugin
mkdir -p $TMPPATH
cd $TMPPATH
set -e

echo "[CiefpYouTube] Downloading latest package from GitHub..."
wget --no-check-certificate https://github.com/ciefp/CiefpYouTube/archive/refs/heads/main.tar.gz
tar -xzf main.tar.gz
cp -r 'CiefpYouTube-main/usr' '/'

set +e
cd
sleep 2

### Check if plugin installed correctly
if [ ! -d $PLUGINPATH ]; then
	echo "!!! SOMETHING WENT WRONG - CiefpYouTube not installed !!!"
	exit 1
fi

# Clean up installation trash
rm -rf $TMPPATH > /dev/null 2>&1
sync

echo ""
echo "#########################################################"
echo "#           CiefpYouTube v$version INSTALLED            #"
echo "#                                                       #"
echo "#  Features:                                           #"
echo "#  - FHD Video Playback                                #"
echo "#  - Playlists with Mini Skin                          #"
echo "#  - User/Live Channels                                #"
echo "#  - Broken Links Log                                  #"
echo "#                                                       #"
echo "#  Installed components:                               #"
echo "#  - ffmpeg (video/audio merging)                      #"
echo "#  - yt-dlp (stream extractor)                         #"
echo "#  - Node.js/Deno (JavaScript runtime)                 #"
echo "#  - yt-dlp-ejs (EJS challenge solver)                 #"
echo "#                                                       #"
echo "#                  developed by ciefp                   #"
echo "#                  .::CiefpSettings::.                  #"
echo "#               https://github.com/ciefp                #"
echo "#########################################################"

# Only restart if SKIP_REBOOT is not set to 1
if [ "$SKIP_REBOOT" = "0" ]; then
	echo "#            your Device will RESTART Now               #"
	echo "#########################################################"
	sleep 3
	killall -9 enigma2
else
	echo "#        Restart skipped (batch installation)           #"
	echo "#########################################################"
fi

exit 0