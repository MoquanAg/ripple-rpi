#!/usr/bin/env python3

import os
import json
import time
import configparser
import sys
import logging
import argparse

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('api_test')

def get_relay_controls():
    """Read the RELAY_CONTROLS section from device.conf using multiple methods."""
    config_file = 'config/device.conf'
    
    # Method 1: Try using ConfigParser
    controls = {}
    config = configparser.ConfigParser()
    config.read(config_file)
    
    if 'RELAY_CONTROLS' in config:
        logger.info("Found RELAY_CONTROLS section using ConfigParser")
        # Clean up values by removing any trailing characters after the device name
        cleaned_controls = {}
        for k, v in config['RELAY_CONTROLS'].items():
            # Split by space and keep only the first part (the actual device name)
            if ',' in v:
                # For comma-separated lists (for groups)
                parts = v.split(',')
                cleaned_parts = [p.split()[0].strip() for p in parts]
                cleaned_controls[k] = ', '.join(cleaned_parts)
            else:
                # For single device names
                cleaned_controls[k] = v.split()[0].strip()
        return cleaned_controls
    
    # Method 2: Try direct file parsing
    logger.info("Trying direct file parsing for RELAY_CONTROLS")
    try:
        with open(config_file, 'r') as f:
            in_relay_controls = False
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                if line == '[RELAY_CONTROLS]':
                    in_relay_controls = True
                    continue
                elif line.startswith('[') and line.endswith(']'):
                    if in_relay_controls:  # We've moved past the section we want
                        break
                    in_relay_controls = False
                    continue
                
                if in_relay_controls and '=' in line:
                    key, value = [x.strip() for x in line.split('=', 1)]
                    # Clean up values
                    if ',' in value:
                        # For comma-separated lists (for groups)
                        parts = value.split(',')
                        cleaned_parts = [p.split()[0].strip() for p in parts]
                        controls[key] = ', '.join(cleaned_parts)
                    else:
                        # For single device names
                        controls[key] = value.split()[0].strip()
        
        if controls:
            logger.info(f"Found {len(controls)} relay controls by direct parsing")
            return controls
    except Exception as e:
        logger.error(f"Error reading config file directly: {e}")
    
    # Fallback: Hardcoded default mappings
    logger.warning("Using hardcoded default controls as fallback")
    return {
        'nutrient_pump_a': 'NutrientPumpA',
        'nutrient_pump_b': 'NutrientPumpB',
        'nutrient_pump_c': 'NutrientPumpC',
        'ph_up_pump': 'pHUpPump',
        'ph_down_pump': 'pHDownPump',
        'valve_outside_to_tank': 'ValveOutsideToTank',
        'valve_tank_to_outside': 'ValveTankToOutside',
        'mixing_pump': 'MixingPump',
        'pump_from_tank_to_gutters': 'PumpFromTankToGutters',
        'sprinkler_a': 'SprinklerA',
        'sprinkler_b': 'SprinklerB',
        'pump_from_collector_tray_to_tank': 'PumpFromCollectorTrayToTank'
    }

def send_action(action_name, state):
    """Send an action by writing to the action.json file."""
    action_file = 'config/action.json'
    
    # Create action data
    action_data = {action_name: state}
    
    # Write to action file
    try:
        with open(action_file, 'w') as f:
            json.dump(action_data, f)
        logger.info(f"Action sent: {action_name} = {state}")
        return True
    except Exception as e:
        logger.error(f"Error sending action: {e}")
        return False

def wait_for_action_processing(seconds=0.5):
    """Wait for the action to be processed."""
    time.sleep(seconds)
    
    # Check if action.json is empty (indicating it was processed)
    for attempt in range(20):  # Try up to 20 times
        try:
            with open('config/action.json', 'r') as f:
                content = f.read().strip()
                if not content or content == '{}':
                    logger.info("Action was processed\n")
                    return True
        except Exception:
            pass
        
        # Wait before trying again
        time.sleep(0.2)
    
    logger.warning("Action was not processed after multiple attempts")
    return False

def test_relay_control(action_name, on_duration=0.5, off_duration=1):
    """Test a single relay control by turning it on and then off."""
    logger.info(f"Testing {action_name}")
    
    # Turn on
    logger.info(f"Turning ON {action_name}")
    if send_action(action_name, True):
        # Wait for on duration
        processed = wait_for_action_processing(0.5)
        if not processed:
            logger.warning(f"ON command for {action_name} may not have been processed!")
        
        # Add a longer delay for the relay hardware to respond
        time.sleep(on_duration)
    else:
        logger.warning(f"Failed to turn on {action_name}")
        return False
        
    # Turn off
    logger.info(f"Turning OFF {action_name}")
    if send_action(action_name, False):
        # Wait for off duration
        processed = wait_for_action_processing(0.5)
        if not processed:
            logger.warning(f"OFF command for {action_name} may not have been processed!")
        
        # Add a longer delay for the relay hardware to respond
        time.sleep(off_duration)
    else:
        logger.warning(f"Failed to turn off {action_name}")
        return False
    
    logger.info(f"Completed test for {action_name}")
    return processed

def run_tests(specific_control=None, on_duration=1, off_duration=1, reverse_order=False):
    """Run tests for all available relay controls."""
    # Ensure the action.json file exists
    if not os.path.exists('config/action.json'):
        with open('config/action.json', 'w') as f:
            f.write('{}')
    
    # Get all available relay controls
    controls = get_relay_controls()
    
    # Track results
    results = {
        "success": [],
        "failure": []
    }
    
    if specific_control:
        if specific_control in controls:
            logger.info(f"Testing only the specified control: {specific_control}")
            success = test_relay_control(specific_control, on_duration, off_duration)
            if success:
                results["success"].append(specific_control)
            else:
                results["failure"].append(specific_control)
        else:
            logger.error(f"Specified control '{specific_control}' not found in available controls: {list(controls.keys())}")
    else:
        # Test all controls
        control_names = list(controls.keys())
        if reverse_order:
            control_names.reverse()
            
        logger.info(f"Testing {len(control_names)} controls: {control_names}")
        
        for control_name in control_names:
            try:
                success = test_relay_control(control_name, on_duration, off_duration)
                if success:
                    results["success"].append(control_name)
                else:
                    results["failure"].append(control_name)
            except Exception as e:
                logger.error(f"Error testing {control_name}: {e}")
                results["failure"].append(control_name)
    
    # Print summary
    print("\n" + "="*40)
    print("TEST RESULTS SUMMARY")
    print("="*40)
    print(f"Total controls tested: {len(results['success']) + len(results['failure'])}")
    
    print("\nSUCCESSFUL CONTROLS:")
    if results["success"]:
        for control in results["success"]:
            device = controls.get(control, "Unknown")
            print(f"  ✓ {control} -> {device}")
    else:
        print("  None")
    
    print("\nFAILED CONTROLS:")
    if results["failure"]:
        for control in results["failure"]:
            device = controls.get(control, "Unknown")
            print(f"  ✗ {control} -> {device}")
    else:
        print("  None")
    
    print("="*40 + "\n")
    
    logger.info("All tests completed")
    return results

def parse_arguments():
    parser = argparse.ArgumentParser(description='Test Ripple API relay controls')
    parser.add_argument('--control', '-c', help='Test only a specific relay control')
    parser.add_argument('--on-time', '-on', type=float, default=1, help='Duration to keep relay ON (seconds)')
    parser.add_argument('--off-time', '-off', type=float, default=1, help='Duration to keep relay OFF (seconds)')
    parser.add_argument('--reverse', '-r', action='store_true', help='Test controls in reverse order')
    parser.add_argument('--list', '-l', action='store_true', help='List available controls and exit')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose logging')
    parser.add_argument('--check-assignments', '-a', action='store_true', help='Check relay assignments')
    
    return parser.parse_args()

def check_relay_assignments():
    """Check actual assignments in the device.conf file."""
    config_file = 'config/device.conf'
    config = configparser.ConfigParser()
    config.read(config_file)
    
    relay_controls = get_relay_controls()
    
    print("\n" + "="*40)
    print("RELAY ASSIGNMENT CHECK")
    print("="*40)
    
    # Check if RELAY_ASSIGNMENTS section exists
    if 'RELAY_ASSIGNMENTS' not in config:
        print("No RELAY_ASSIGNMENTS section found in config!")
        return
    
    # Collect all assignments
    assignments = {}
    for key, value in config['RELAY_ASSIGNMENTS'].items():
        if not key.startswith('relay_'):
            continue
            
        # Parse the relay index range
        parts = key.split('_')
        if len(parts) >= 5 and parts[3] == 'to':
            relay_type = parts[1]
            start_index = int(parts[2])
            end_index = int(parts[4])
            
            # Get device names
            devices = [d.strip() for d in value.split(',')]
            
            if len(devices) != (end_index - start_index + 1):
                print(f"Warning: Number of devices {len(devices)} doesn't match range {start_index}-{end_index}")
            
            # Assign each device to its index
            for i, device in enumerate(devices):
                if i < (end_index - start_index + 1):
                    index = start_index + i
                    assignments[device] = {
                        'relay_type': relay_type,
                        'index': index,
                        'full_key': key
                    }
    
    # Check if all controls have corresponding assignments
    missing_assignments = []
    for control_name, device_name in relay_controls.items():
        devices = [d.strip() for d in device_name.split(',')]
        for device in devices:
            if device not in assignments:
                missing_assignments.append((control_name, device))
    
    # Print results
    print(f"Total relay assignments found: {len(assignments)}")
    
    print("\nASSIGNED DEVICES:")
    for device, info in sorted(assignments.items(), key=lambda x: (x[1]['relay_type'], x[1]['index'])):
        print(f"  {device} -> {info['relay_type']} index {info['index']} ({info['full_key']})")
    
    if missing_assignments:
        print("\nWARNING: The following controls are missing relay assignments:")
        for control, device in missing_assignments:
            print(f"  {control} -> {device}")
    else:
        print("\nAll controls have relay assignments.")
    
    print("="*40 + "\n")

if __name__ == "__main__":
    args = parse_arguments()
    
    # Set logging level based on verbosity
    if args.verbose:
        logging.getLogger('api_test').setLevel(logging.DEBUG)
    
    logger.info("Starting API test")
    
    if args.check_assignments:
        check_relay_assignments()
        sys.exit(0)
    
    if args.list:
        # Just list the available controls and exit
        controls = get_relay_controls()
        print("\nAvailable Relay Controls:")
        for name, device in controls.items():
            print(f"  {name} -> {device}")
        print()
        sys.exit(0)
    
    # Run the tests with the specified options
    run_tests(
        specific_control=args.control,
        on_duration=args.on_time,
        off_duration=args.off_time,
        reverse_order=args.reverse
    ) 