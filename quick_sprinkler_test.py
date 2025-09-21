#!/usr/bin/env python3
"""
Quick Sprinkler Configuration Test
Validates that your device.conf sprinkler settings are correctly parsed and reasonable.
"""

import configparser
import os
import sys

def parse_time_to_seconds(time_str):
    """Convert HH:MM:SS to seconds"""
    try:
        if not time_str or time_str.strip() == "":
            return 0
        parts = time_str.strip().split(':')
        if len(parts) != 3:
            return 0
        hours, minutes, seconds = map(int, parts)
        return hours * 3600 + minutes * 60 + seconds
    except:
        return 0

def format_seconds_to_readable(seconds):
    """Convert seconds to readable format"""
    if seconds == 0:
        return "0 (DISABLED)"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")
    
    return " ".join(parts)

def main():
    config_file = 'config/device.conf'
    
    if not os.path.exists(config_file):
        print("❌ Error: config/device.conf not found")
        print("Please run this from the ripple-rpi project root directory")
        return 1
    
    print("🧪 Quick Sprinkler Configuration Test")
    print("=" * 40)
    
    try:
        # Load configuration
        config = configparser.ConfigParser()
        config.read(config_file)
        
        # Get sprinkler configuration
        on_duration_raw = config.get('Sprinkler', 'sprinkler_on_duration')
        wait_duration_raw = config.get('Sprinkler', 'sprinkler_wait_duration')
        
        print(f"📋 Raw Configuration:")
        print(f"   sprinkler_on_duration = {on_duration_raw}")
        print(f"   sprinkler_wait_duration = {wait_duration_raw}")
        print()
        
        # Parse values (system uses second value for operation)
        on_values = on_duration_raw.split(',')
        wait_values = wait_duration_raw.split(',')
        
        on_api = on_values[0].strip() if len(on_values) > 0 else "00:00:00"
        on_operational = on_values[1].strip() if len(on_values) > 1 else on_api
        
        wait_api = wait_values[0].strip() if len(wait_values) > 0 else "00:00:00"
        wait_operational = wait_values[1].strip() if len(wait_values) > 1 else wait_api
        
        # Convert to seconds
        on_seconds_api = parse_time_to_seconds(on_api)
        on_seconds_op = parse_time_to_seconds(on_operational)
        wait_seconds_api = parse_time_to_seconds(wait_api)
        wait_seconds_op = parse_time_to_seconds(wait_operational)
        
        print(f"🔍 Parsed Values:")
        print(f"   API Value (first):        ON={on_api} ({format_seconds_to_readable(on_seconds_api)})")
        print(f"   Operational (second):     ON={on_operational} ({format_seconds_to_readable(on_seconds_op)})")
        print(f"   API Value (first):        WAIT={wait_api} ({format_seconds_to_readable(wait_seconds_api)})")
        print(f"   Operational (second):     WAIT={wait_operational} ({format_seconds_to_readable(wait_seconds_op)})")
        print()
        
        # Analysis
        print("📊 Analysis:")
        
        # Check which value the system will actually use (operational = second value)
        active_on = on_seconds_op
        active_wait = wait_seconds_op
        
        if active_on == 0 or active_wait == 0:
            print("⚠️  WARNING: Sprinkler system is DISABLED (zero duration detected)")
            print(f"   Active ON duration: {format_seconds_to_readable(active_on)}")
            print(f"   Active WAIT duration: {format_seconds_to_readable(active_wait)}")
        else:
            print(f"✅ Sprinkler system is ACTIVE")
            print(f"   Sprinklers will run for: {format_seconds_to_readable(active_on)}")
            print(f"   Then wait for: {format_seconds_to_readable(active_wait)}")
            
            total_cycle = active_on + active_wait
            print(f"   Total cycle time: {format_seconds_to_readable(total_cycle)}")
            
            # Calculate daily cycles
            cycles_per_day = 86400 / total_cycle if total_cycle > 0 else 0
            daily_watering_time = (cycles_per_day * active_on) / 3600  # hours
            
            print(f"   Cycles per day: ~{cycles_per_day:.1f}")
            print(f"   Total daily watering: ~{daily_watering_time:.1f} hours")
        
        # Set total_cycle for validation checks
        total_cycle = active_on + active_wait
        
        print()
        
        # Validation checks
        print("✅ Validation Checks:")
        
        issues = []
        
        if active_on > 0 and active_wait > 0:
            print("   ✅ Both durations are non-zero")
        else:
            issues.append("Zero durations will disable sprinkler system")
        
        if active_wait >= active_on:
            print("   ✅ Wait duration is appropriate (≥ ON duration)")
        else:
            issues.append("Wait duration should typically be longer than ON duration")
        
        if 60 <= active_on <= 7200:  # 1 min to 2 hours
            print("   ✅ ON duration is reasonable (1min - 2hr)")
        elif active_on > 0:
            issues.append(f"ON duration ({format_seconds_to_readable(active_on)}) may be too short/long")
        
        if total_cycle <= 28800:  # 8 hours
            print("   ✅ Total cycle time is reasonable (≤ 8hr)")
        elif active_on > 0:
            issues.append(f"Total cycle time ({format_seconds_to_readable(total_cycle)}) is very long")
        
        if issues:
            print()
            print("⚠️  Potential Issues:")
            for issue in issues:
                print(f"   - {issue}")
        
        print()
        print("🎯 Summary:")
        if active_on == 0 or active_wait == 0:
            print("   Status: SPRINKLER SYSTEM DISABLED")
            print("   Action: Update operational values (second values) to enable")
        elif issues:
            print("   Status: ACTIVE with potential issues")
            print("   Action: Review configuration if needed")
        else:
            print("   Status: ACTIVE and well-configured")
            print("   Action: Configuration looks good!")
        
        return 0 if not issues else 1
        
    except Exception as e:
        print(f"❌ Error reading configuration: {e}")
        return 1

if __name__ == "__main__":
    exit(main())
