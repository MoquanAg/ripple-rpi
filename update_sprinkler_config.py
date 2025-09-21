#!/usr/bin/env python3
"""
Sprinkler Configuration Update Script
Updates device.conf with optimal settings for pea shoots and tomato/pepper plants
"""

import configparser
import os
import shutil
from datetime import datetime

def backup_config(config_file):
    """Create a timestamped backup of the config file"""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_file = f"{config_file}.backup_{timestamp}"
    shutil.copy2(config_file, backup_file)
    print(f"✅ Created backup: {backup_file}")
    return backup_file

def update_sprinkler_config(stage="balanced"):
    """Update sprinkler configuration for different growth stages"""
    config_file = 'config/device.conf'
    
    if not os.path.exists(config_file):
        print("❌ Error: config/device.conf not found")
        return False
    
    # Configuration options for different growth stages
    configs = {
        "germination": {
            "on_duration": "00:02:00",    # 2 minutes - gentle for pea shoots
            "wait_duration": "02:00:00",  # 2 hours - frequent for germination
            "description": "Optimized for pea shoot germination (frequent, gentle watering)"
        },
        "balanced": {
            "on_duration": "00:03:00",    # 3 minutes - good for both plant types
            "wait_duration": "03:00:00",  # 3 hours - balanced frequency
            "description": "Balanced for pea shoots + young tomatoes/peppers"
        },
        "mature": {
            "on_duration": "00:04:00",    # 4 minutes - more for mature plants
            "wait_duration": "04:00:00",  # 4 hours - less frequent but longer
            "description": "Optimized for mature tomatoes/peppers"
        },
        "test": {
            "on_duration": "00:00:30",    # 30 seconds - for testing
            "wait_duration": "00:02:00",  # 2 minutes - quick testing
            "description": "Short durations for testing system functionality"
        }
    }
    
    if stage not in configs:
        print(f"❌ Error: Unknown stage '{stage}'. Available: {list(configs.keys())}")
        return False
    
    config_data = configs[stage]
    
    print(f"🌱 Updating sprinkler configuration for: {stage.upper()}")
    print(f"   Description: {config_data['description']}")
    print(f"   ON duration: {config_data['on_duration']}")
    print(f"   WAIT duration: {config_data['wait_duration']}")
    
    # Create backup
    backup_file = backup_config(config_file)
    
    try:
        # Load and update configuration
        config = configparser.ConfigParser()
        config.read(config_file)
        
        # Update sprinkler settings (keep first value unchanged, update second value)
        current_on = config.get('Sprinkler', 'sprinkler_on_duration').split(',')[0].strip()
        current_wait = config.get('Sprinkler', 'sprinkler_wait_duration').split(',')[0].strip()
        
        new_on = f"{current_on}, {config_data['on_duration']}"
        new_wait = f"{current_wait}, {config_data['wait_duration']}"
        
        config.set('Sprinkler', 'sprinkler_on_duration', new_on)
        config.set('Sprinkler', 'sprinkler_wait_duration', new_wait)
        
        # Write updated configuration
        with open(config_file, 'w') as f:
            config.write(f)
        
        print("✅ Configuration updated successfully!")
        print(f"   sprinkler_on_duration = {new_on}")
        print(f"   sprinkler_wait_duration = {new_wait}")
        
        # Calculate daily watering info
        on_seconds = sum(int(x) * 60**(2-i) for i, x in enumerate(config_data['on_duration'].split(':')))
        wait_seconds = sum(int(x) * 60**(2-i) for i, x in enumerate(config_data['wait_duration'].split(':')))
        
        cycle_seconds = on_seconds + wait_seconds
        cycles_per_day = 86400 / cycle_seconds if cycle_seconds > 0 else 0
        daily_watering_minutes = (cycles_per_day * on_seconds) / 60
        
        print(f"\n📊 Watering Schedule:")
        print(f"   Cycle frequency: Every {wait_seconds//3600}h {(wait_seconds%3600)//60}m")
        print(f"   Cycles per day: ~{cycles_per_day:.1f}")
        print(f"   Daily watering time: ~{daily_watering_minutes:.1f} minutes")
        
        return True
        
    except Exception as e:
        print(f"❌ Error updating configuration: {e}")
        # Restore backup
        try:
            shutil.copy2(backup_file, config_file)
            print(f"🔄 Restored original configuration from backup")
        except:
            pass
        return False

def show_current_config():
    """Show current sprinkler configuration"""
    config_file = 'config/device.conf'
    
    if not os.path.exists(config_file):
        print("❌ Error: config/device.conf not found")
        return
    
    config = configparser.ConfigParser()
    config.read(config_file)
    
    on_duration = config.get('Sprinkler', 'sprinkler_on_duration')
    wait_duration = config.get('Sprinkler', 'sprinkler_wait_duration')
    
    print("📋 Current Sprinkler Configuration:")
    print(f"   sprinkler_on_duration = {on_duration}")
    print(f"   sprinkler_wait_duration = {wait_duration}")

def main():
    """Main script execution"""
    import sys
    
    print("🌱 Ripple Sprinkler Configuration Updater")
    print("=" * 45)
    
    # Show current config
    show_current_config()
    print()
    
    if len(sys.argv) < 2:
        print("📖 Available growth stages:")
        print("   germination  - For pea shoots (frequent, gentle)")
        print("   balanced     - For mixed plants (recommended)")
        print("   mature       - For large tomatoes/peppers")
        print("   test         - Short durations for testing")
        print()
        print("Usage: python3 update_sprinkler_config.py <stage>")
        print("Example: python3 update_sprinkler_config.py balanced")
        return 1
    
    stage = sys.argv[1].lower()
    
    if update_sprinkler_config(stage):
        print("\n🎯 Next Steps:")
        print("1. Test configuration: python3 quick_sprinkler_test.py")
        print("2. Run full test: ./run_sprinkler_test.sh")
        print("3. Monitor plants for 24-48 hours")
        print("4. Adjust if needed based on plant response")
        return 0
    else:
        return 1

if __name__ == "__main__":
    exit(main())
