#!/bin/bash
# Quick wake-up check for sprinkler system
# Run this when you wake up to see what happened overnight

echo "🌅 WAKE UP SPRINKLER CHECK"
echo "========================="
echo "Current time: $(date)"
echo ""

cd /home/lumina/ripple-rpi

echo "🔍 Quick System Status:"
echo "-----------------------"

# Check if system is running
if pgrep -f "python.*main.py" > /dev/null; then
    echo "✅ System is running (PID: $(pgrep -f 'python.*main.py'))"
else
    echo "❌ System is NOT running"
fi

echo ""
echo "📊 Current Relay Status:"
echo "------------------------"

# Get the latest relay status from logs
LATEST_LOG=$(ls -t log/ripple_*.log 2>/dev/null | head -1)
if [ -n "$LATEST_LOG" ]; then
    echo "📄 From: $LATEST_LOG"
    LATEST_RELAY=$(grep "relayone statuses:" "$LATEST_LOG" | tail -1)
    if [ -n "$LATEST_RELAY" ]; then
        echo "$LATEST_RELAY"
        
        # Extract the status array and check sprinkler ports (9, 10)
        STATUS_ARRAY=$(echo "$LATEST_RELAY" | grep -o '\[.*\]')
        if [ -n "$STATUS_ARRAY" ]; then
            echo ""
            echo "🚿 Sprinkler Status Decoded:"
            python3 -c "
import sys
try:
    status = $STATUS_ARRAY
    print(f'  SprinklerA (port 9):  {\"ON\" if status[9] == 1 else \"OFF\"}')
    print(f'  SprinklerB (port 10): {\"ON\" if status[10] == 1 else \"OFF\"}')
except:
    print('  ❌ Could not decode status')
"
        fi
    else
        echo "❌ No relay status found in logs"
    fi
else
    echo "❌ No log files found"
fi

echo ""
echo "⏰ Expected Timing:"
echo "------------------"
echo "Next cycle should start: 02:01:45"
echo "Should run for: 15 minutes"
echo "Next cycle after that: 06:01:45"

echo ""
echo "📋 For detailed analysis, run:"
echo "python3 monitor_sprinkler_cycle.py"
echo ""

