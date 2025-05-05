#!/bin/bash

# Configuration
RIPPLE_PATH="/home/lumina/ripple-rpi"
VENV_PATH="$RIPPLE_PATH/venv"

# Function to start a script in a new terminal
start_script() {
    local script_name=$1
    local script_title=$2
    lxterminal --title="$script_title" -e "bash -c '
        cd $RIPPLE_PATH
        source $VENV_PATH/bin/activate
        echo Starting $script_name...
        python $RIPPLE_PATH/$script_name
        echo \"$script_title exited. Press Enter to close this window.\"
        read
    '" &
}

# Display startup message
echo "Starting Ripple Fertigation System..."

# Kill existing Ripple processes if running
echo "Stopping any existing Ripple processes..."
pkill -f "$RIPPLE_PATH/main.py"
pkill -f "$RIPPLE_PATH/server.py"

# Give processes time to terminate
sleep 1

# Ensure config directory exists
echo "Checking configuration directory..."
mkdir -p "$RIPPLE_PATH/config"
mkdir -p "$RIPPLE_PATH/data"

# Copy template config if needed
if [ ! -f "$RIPPLE_PATH/config/device.conf" ]; then
    echo "Creating default device.conf from template..."
    cp "$RIPPLE_PATH/config/template_device.conf" "$RIPPLE_PATH/config/device.conf"
fi

# Ensure action.json exists
if [ ! -f "$RIPPLE_PATH/config/action.json" ]; then
    echo "Creating empty action.json..."
    echo "{}" > "$RIPPLE_PATH/config/action.json"
fi

# Start main controller script
echo "Starting main controller..."
start_script "main.py" "Ripple Controller"

# Wait to ensure controller starts before API
sleep 1

# Start API server script
echo "Starting REST API server..."
start_script "server.py" "Ripple API Server"

echo "All Ripple Fertigation System components have been launched."
echo "Main controller is running in a separate terminal."
echo "REST API server is running in a separate terminal."
echo "API is available at http://$(hostname -I | awk '{print $1}'):8000"