#!/bin/bash
# Quick Sprinkler Timing Test Runner
# This script runs the sprinkler timing tests and shows a summary

echo "🧪 Ripple Sprinkler Timing Test"
echo "================================="
echo "Testing if sprinkler_on_duration and sprinkler_wait_duration"
echo "from device.conf are executed correctly."
echo ""

# Change to project directory
cd "$(dirname "$0")"

# Check if device.conf exists
if [ ! -f "config/device.conf" ]; then
    echo "❌ Error: config/device.conf not found"
    echo "Please run this script from the ripple-rpi project root"
    exit 1
fi

# Show current configuration
echo "📋 Current Configuration:"
echo "------------------------"
grep -A 2 "\[Sprinkler\]" config/device.conf
echo ""

# Run the test
echo "🚀 Running tests..."
echo ""

python3 test_sprinkler_timing.py

# Check exit code
if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Test completed successfully!"
    echo "Check the generated report file for detailed results."
else
    echo ""
    echo "⚠️  Test completed with issues."
    echo "Check the output above for details."
fi

echo ""
echo "📄 Report files:"
ls -la sprinkler_timing_test_report_*.json 2>/dev/null | tail -1 || echo "No report files found"
