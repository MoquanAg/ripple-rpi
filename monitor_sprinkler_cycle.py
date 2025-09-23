#!/usr/bin/env python3
"""
Sprinkler Cycle Monitoring Script

Creates a summary of sprinkler activity for review when you wake up.
Designed to be run when you return to check what happened overnight.

Usage: python3 monitor_sprinkler_cycle.py
"""

import os
import sys
from datetime import datetime, timedelta
import re

def analyze_sprinkler_logs():
    """Analyze logs for sprinkler activity"""
    print("🔍 SPRINKLER CYCLE ANALYSIS")
    print("=" * 60)
    
    # Expected timing
    expected_start = datetime.strptime('2025-09-23 02:01:45', '%Y-%m-%d %H:%M:%S')
    expected_stop = expected_start + timedelta(minutes=15)
    expected_next = expected_stop + timedelta(hours=4)
    
    current_time = datetime.now()
    
    print(f"📅 Expected Schedule:")
    print(f"  Next start:  {expected_start.strftime('%H:%M:%S on %Y-%m-%d')}")
    print(f"  Should stop: {expected_stop.strftime('%H:%M:%S')}")
    print(f"  Next cycle:  {expected_next.strftime('%H:%M:%S')}")
    print(f"  Current:     {current_time.strftime('%H:%M:%S on %Y-%m-%d')}")
    print()
    
    # Check if logs exist
    log_files = []
    for file in os.listdir('log'):
        if file.startswith('ripple_20250923') and file.endswith('.log'):
            log_files.append(os.path.join('log', file))
    
    # Also check current day if it's still the 22nd
    for file in os.listdir('log'):
        if file.startswith('ripple_20250922') and file.endswith('.log'):
            log_files.append(os.path.join('log', file))
    
    if not log_files:
        print("❌ No log files found for monitoring period")
        return
    
    print(f"📋 Checking {len(log_files)} log file(s):")
    for log_file in log_files:
        print(f"  - {log_file}")
    print()
    
    # Look for sprinkler events
    sprinkler_events = []
    
    for log_file in log_files:
        try:
            with open(log_file, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    # Look for sprinkler-related events
                    if any(keyword in line.lower() for keyword in [
                        'sprinkler', 'simplified_sprinkler', 'static.*sprinkler',
                        'controller.*sprinkler', 'failsafe'
                    ]):
                        # Extract timestamp
                        timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                        if timestamp_match:
                            timestamp = timestamp_match.group(1)
                            sprinkler_events.append((timestamp, line.strip(), log_file, line_num))
        except Exception as e:
            print(f"⚠️  Error reading {log_file}: {e}")
    
    # Also check for relay status showing sprinkler ports
    relay_events = []
    for log_file in log_files:
        try:
            with open(log_file, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    if 'relayone statuses:' in line:
                        timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                        if timestamp_match:
                            timestamp = timestamp_match.group(1)
                            # Check if this is around expected times
                            try:
                                log_time = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                                if (abs((log_time - expected_start).total_seconds()) < 300 or  # Within 5 min of start
                                    abs((log_time - expected_stop).total_seconds()) < 300):   # Within 5 min of stop
                                    relay_events.append((timestamp, line.strip(), log_file, line_num))
                            except:
                                pass
        except Exception as e:
            print(f"⚠️  Error reading {log_file}: {e}")
    
    # Display results
    print("🚿 SPRINKLER EVENTS FOUND:")
    if sprinkler_events:
        for timestamp, event, log_file, line_num in sprinkler_events[-20:]:  # Last 20 events
            print(f"  {timestamp} - {event}")
    else:
        print("  ❌ No sprinkler events found in logs")
    
    print()
    print("🔌 RELAY STATUS AROUND EXPECTED TIMES:")
    if relay_events:
        for timestamp, event, log_file, line_num in relay_events[-10:]:  # Last 10 events
            # Extract relay status array
            status_match = re.search(r'relayone statuses: (\[.*\])', event)
            if status_match:
                status_array = eval(status_match.group(1))
                sprinkler_a = "ON" if status_array[9] == 1 else "OFF"
                sprinkler_b = "ON" if status_array[10] == 1 else "OFF"
                print(f"  {timestamp} - SprinklerA: {sprinkler_a}, SprinklerB: {sprinkler_b}")
    else:
        print("  ❌ No relay status found around expected times")
    
    print()
    print("📊 ANALYSIS SUMMARY:")
    
    # Check if we're past the expected start time
    if current_time > expected_start:
        if sprinkler_events:
            print("  ✅ Sprinkler events detected - system appears active")
        else:
            print("  ❌ No sprinkler events found - system may have failed")
    else:
        print(f"  ⏳ Still waiting for scheduled time ({expected_start.strftime('%H:%M:%S')})")
    
    # Check if we're past the expected stop time
    if current_time > expected_stop:
        # Look for recent relay status
        if relay_events:
            latest_relay = relay_events[-1]
            status_match = re.search(r'relayone statuses: (\[.*\])', latest_relay[1])
            if status_match:
                status_array = eval(status_match.group(1))
                if status_array[9] == 0 and status_array[10] == 0:
                    print("  ✅ Sprinklers appear to be OFF (as expected)")
                else:
                    print("  ⚠️  Sprinklers may still be ON (check manually)")
    
    print()
    print("🔧 NEXT STEPS:")
    print("  1. Review the events above")
    print("  2. Check current relay status manually if needed")
    print("  3. Monitor for next cycle if this one completed")
    print("  4. Report results for architectural analysis")

def check_current_status():
    """Check current system status"""
    print("\n" + "="*60)
    print("🔍 CURRENT SYSTEM STATUS")
    print("="*60)
    
    # Check if main.py is running
    try:
        import subprocess
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        if 'python main.py' in result.stdout or 'python /home/lumina/ripple-rpi/main.py' in result.stdout:
            print("✅ Main system process is running")
        else:
            print("❌ Main system process not found")
    except:
        print("⚠️  Could not check process status")
    
    # Check latest log file
    try:
        log_files = [f for f in os.listdir('log') if f.startswith('ripple_') and f.endswith('.log')]
        if log_files:
            latest_log = max(log_files)
            print(f"📄 Latest log file: {latest_log}")
            
            # Check last few lines
            with open(os.path.join('log', latest_log), 'r') as f:
                lines = f.readlines()
                print("📋 Last 3 log entries:")
                for line in lines[-3:]:
                    if line.strip():
                        print(f"  {line.strip()}")
        else:
            print("❌ No log files found")
    except Exception as e:
        print(f"⚠️  Error checking logs: {e}")

if __name__ == "__main__":
    print("🌙 OVERNIGHT SPRINKLER MONITORING REPORT")
    print("Generated at:", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    print()
    
    try:
        os.chdir('/home/lumina/ripple-rpi')
        analyze_sprinkler_logs()
        check_current_status()
        
        print("\n" + "="*60)
        print("✅ MONITORING REPORT COMPLETE")
        print("="*60)
        
    except Exception as e:
        print(f"❌ Error during analysis: {e}")
        import traceback
        traceback.print_exc()

