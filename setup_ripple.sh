#!/bin/bash
echo "Setting up Ripple Fertigation System."

# Configuration
RIPPLE_HOME="/home/lumina"
RIPPLE_PATH="$RIPPLE_HOME/ripple-rpi"
VENV_PATH="$RIPPLE_PATH/venv"

echo "Setting up Python virtual environment."

# Set up Python virtual environment
python -m venv "$VENV_PATH"

# Configure pip to use Aliyun mirror
"$VENV_PATH/bin/pip" config set global.index-url https://mirrors.aliyun.com/pypi/simple/
"$VENV_PATH/bin/pip" config set global.trusted-host mirrors.aliyun.com

source "$VENV_PATH/bin/activate"

"$VENV_PATH/bin/pip" install --upgrade pip
"$VENV_PATH/bin/pip" install -r "$RIPPLE_PATH/requirements.txt"



# Create autostart entry
AUTOSTART_DIR="$RIPPLE_HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"

# Ensure start script is executable
chmod +x "$RIPPLE_PATH/start_ripple.sh"

# Create config directory if it doesn't exist
mkdir -p "$RIPPLE_PATH/config"

# Create device.conf from template if it doesn't exist
if [ ! -f "$RIPPLE_PATH/config/device.conf" ]; then
    echo "Creating device configuration."
    # If there's a template, use it, otherwise create a minimal one
    if [ -f "$RIPPLE_PATH/config/template_device.conf" ]; then
        cp "$RIPPLE_PATH/config/template_device.conf" "$RIPPLE_PATH/config/device.conf"
    fi
else
    echo "Device configuration already exists."
fi

# Create autostart desktop entry
cat << EOF > "$AUTOSTART_DIR/ripple-fertigation.desktop"
[Desktop Entry]
Type=Application
Name=Ripple Fertigation System
Comment=Starts the Ripple Fertigation System at boot
Exec=lxterminal -e "bash -c '$RIPPLE_PATH/start_ripple.sh; exec bash'"
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

echo "Added autostart entry for Ripple Fertigation System."

# Create data and log directories if they don't exist
mkdir -p "$RIPPLE_PATH/data"
mkdir -p "$RIPPLE_PATH/log"

# Set appropriate permissions
echo "Setting file permissions."
chmod -R 755 "$RIPPLE_PATH"
chmod 644 "$RIPPLE_PATH/config/device.conf"

echo "Setup complete. The Ripple Fertigation System will start automatically at boot."
echo "You can also start it manually by running: $RIPPLE_PATH/start_ripple.sh" 