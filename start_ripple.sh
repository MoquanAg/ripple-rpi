#!/bin/bash

# Configuration
RIPPLE_PATH="/home/lumina/ripple-rpi"
VENV_PATH="$RIPPLE_PATH/venv"

# Function to start a script in a new terminal
start_script() {
    local script_name=$1
    local script_title=$2
    lxterminal --title="$script_title" -e "bash -c '
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
sleep 2

# Start main controller script
echo "Starting main controller..."
start_script "main.py" "Ripple Controller"

# Wait to ensure controller starts before API
sleep 3

# Start API server script
echo "Starting REST API server..."
start_script "server.py" "Ripple API Server"

echo "All Ripple Fertigation System components have been launched."
echo "Main controller is running in a separate terminal."
echo "REST API server is running in a separate terminal."
echo "API is available at http://$(hostname -I | awk '{print $1}'):8000" 