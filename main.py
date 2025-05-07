#!/usr/bin/env python3

import os
import sys
import time
import logging
import json
from typing import Dict, List, Optional, Union, Any
import configparser
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from datetime import datetime, timedelta

# Add the src directory to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, 'src')
sys.path.append(src_dir)

import globals
from src.sensors.water_level import WaterLevel
from src.sensors.Relay import Relay
from src.sensors.DO import DO
from src.sensors.pH import pH
from src.sensors.ec import EC
from src.lumina_logger import GlobalLogger
from src.scheduler import RippleScheduler

logger = GlobalLogger("RippleController", log_prefix="ripple_").logger

class ConfigFileHandler(FileSystemEventHandler):
    def __init__(self, controller):
        self.controller = controller
        self.last_action_state = {}
        self.last_config_state = {}  # Store the last known state of the config file
        self.last_event_time = {}    # Track last event time for each file to prevent duplicates
        self.event_debounce_seconds = 1.0  # Minimum seconds between same-file events
        # Load initial config state
        self._load_current_config()
        
    def _load_current_config(self):
        """Load the current state of the config file for comparison"""
        try:
            if os.path.exists(self.controller.config_file):
                config = configparser.ConfigParser(empty_lines_in_values=False, interpolation=None)
                config.read(self.controller.config_file)
                
                # Store a copy of the current config state
                self.last_config_state = {}
                for section in config.sections():
                    self.last_config_state[section] = {}
                    for key, value in config[section].items():
                        self.last_config_state[section][key] = value
                        
                logger.debug(f"Loaded current config state with {len(self.last_config_state)} sections")
        except Exception as e:
            logger.error(f"Error loading current config state: {e}")
        
    def on_modified(self, event):
        try:
            # Normalize paths for comparison
            config_file_path = os.path.abspath(self.controller.config_file)
            action_file_path = os.path.abspath(os.path.join(self.controller.config_dir, 'action.json'))
            event_path = os.path.abspath(event.src_path)
            
            # Implement debouncing to prevent duplicate events
            current_time = time.time()
            if event_path in self.last_event_time:
                # If we've seen this event recently, check if enough time has passed
                time_since_last = current_time - self.last_event_time[event_path]
                if time_since_last < self.event_debounce_seconds:
                    logger.info(f"Ignoring duplicate event for {event_path} - only {time_since_last:.2f}s since last event")
                    return
            
            # Update the last event time for this path
            self.last_event_time[event_path] = current_time
            
            logger.info(f"File modified: {event_path}")
            
            # Check if device.conf was modified
            if os.path.basename(event_path) == 'device.conf' or event_path == config_file_path:
                logger.info("Configuration file (device.conf) modified, detecting changes")
                
                # Identify which sections were changed
                changed_sections = self._identify_changed_sections()
                
                if changed_sections:
                    logger.info(f"Changed sections detected: {changed_sections}")
                    # Reload specific sections and trigger relevant checks
                    self.controller.reload_specific_sections(changed_sections)
                else:
                    logger.info("No significant changes detected in config file")
                
                # Update our stored config state for next comparison
                self._load_current_config()
                
            elif event_path == action_file_path:
                logger.info("Action file modified, processing new actions")
                # Add a small delay to ensure file writing is complete
                time.sleep(0.1)
                self.process_actions()
        except Exception as e:
            logger.error(f"Error in on_modified handler: {e}")
            logger.exception("Full exception details:")
    
    def _identify_changed_sections(self):
        """Identify which sections in the config file have changed"""
        changed_sections = set()
        
        try:
            # Load the current config state
            current_config = configparser.ConfigParser(empty_lines_in_values=False, interpolation=None)
            current_config.read(self.controller.config_file)
            
            # Check for new or modified sections
            for section in current_config.sections():
                # If this is a new section
                if section not in self.last_config_state:
                    changed_sections.add(section)
                    continue
                
                # Check for modified keys in existing sections
                for key, value in current_config[section].items():
                    if key not in self.last_config_state[section] or self.last_config_state[section][key] != value:
                        changed_sections.add(section)
                        break
            
            # Check for deleted sections
            for section in self.last_config_state:
                if section not in current_config.sections():
                    changed_sections.add(section)
            
            return changed_sections
            
        except Exception as e:
            logger.error(f"Error identifying changed sections: {e}")
            return set()  # Return empty set if there's an error
    
    def process_actions(self):
        try:
            # Check if file exists and is not empty before trying to read it
            if not os.path.exists('config/action.json') or os.path.getsize('config/action.json') == 0:
                logger.warning("Action file does not exist or is empty")
                return
                
            # Read the action file
            try:
                with open('config/action.json', 'r') as f:
                    file_content = f.read().strip()
                    if not file_content:
                        logger.warning("Action file is empty")
                        return
                    new_actions = json.loads(file_content)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in action file: {e}")
                # Try to reset the file to empty JSON object
                with open('config/action.json', 'w') as f:
                    json.dump({}, f)
                return
                
            # Check if actions are different from last state
            if new_actions != self.last_action_state:
                logger.info(f"New actions detected: {new_actions}")
                
                # Get relay instance first
                relay_instance = Relay()
                if not relay_instance:
                    logger.warning("Failed to get relay instance, cannot process actions")
                    return
                
                # First, clear the action file to acknowledge receipt
                # This helps prevent race conditions
                with open('config/action.json', 'w') as f:
                    json.dump({}, f)
                logger.info("Action file cleared before processing to prevent race conditions")
                
                # Read dynamic mappings from config file
                # Make sure config is up-to-date
                self.controller.config.read(self.controller.config_file)
                config = self.controller.config
                
                # Log available sections for debugging
                logger.info(f"Available config sections: {config.sections()}")
                
                action_mapping = {}
                
                # Create mapping function for a relay device
                def create_relay_action(device_name):
                    # Check if it's a single relay device or a group
                    if ',' in device_name:
                        # Handle group of devices using set_multiple_relays where possible
                        devices = [d.strip() for d in device_name.split(',')]
                        
                        # For special group cases where we know relay indices
                        if all(d in ["SprinklerA", "SprinklerB"] for d in devices) and len(devices) == 2:
                            # Sprinklers are on adjacent indices (typically 9 and 10)
                            logger.info(f"Using optimized set_multiple_relays for sprinklers")
                            # Get the first relay key
                            relay_key = list(relay_instance.relay_addresses.keys())[0]
                            # Get indices from relay_assignments
                            indices = []
                            for device in devices:
                                if device in relay_instance.relay_assignments:
                                    indices.append(relay_instance.relay_assignments[device]['index'])
                            if len(indices) == 2 and abs(indices[0] - indices[1]) == 1:
                                # They're adjacent, use set_multiple_relays
                                start_index = min(indices)
                                return lambda status: relay_instance.set_multiple_relays(relay_key, start_index, [status, status])
                        
                        elif all(d.startswith("NutrientPump") for d in devices) and len(devices) == 3:
                            # Nutrient pumps are on adjacent indices (typically 0, 1, 2)
                            logger.info(f"Using optimized set_multiple_relays for nutrient pumps")
                            # Get the first relay key
                            relay_key = list(relay_instance.relay_addresses.keys())[0]
                            # Get indices from relay_assignments
                            indices = []
                            for device in devices:
                                if device in relay_instance.relay_assignments:
                                    indices.append(relay_instance.relay_assignments[device]['index'])
                            if len(indices) == 3 and max(indices) - min(indices) == 2:
                                # They're adjacent, use set_multiple_relays
                                start_index = min(indices)
                                return lambda status: relay_instance.set_multiple_relays(relay_key, start_index, [status, status, status])
                        
                        # Fallback to individual relay control if optimization not possible
                        logger.info(f"Using individual relay control for group: {devices}")
                        return lambda status: [relay_instance.set_relay(device, status) for device in devices]
                    else:
                        # IMPORTANT: All controls should use set_relay directly
                        # This ensures we correctly use case-insensitive relay lookup
                        logger.info(f"Creating direct relay action for: {device_name}")
                        return lambda status: relay_instance.set_relay(device_name, status)
                
                # First check if RELAY_CONTROLS is in config (standard way)
                if 'RELAY_CONTROLS' in config:
                    logger.info("Using RELAY_CONTROLS section from config")
                    for api_name, device_name in config['RELAY_CONTROLS'].items():
                        action_mapping[api_name] = create_relay_action(device_name)
                        logger.info(f"Loaded action mapping: {api_name} -> {device_name}")
                # If not found, try direct file reading
                else:
                    logger.info("Trying to read RELAY_CONTROLS directly from config file")
                    try:
                        # Direct parsing to maintain case sensitivity
                        with open(self.controller.config_file, 'r') as f:
                            in_relay_controls = False
                            relay_controls = {}
                            
                            for line in f:
                                line = line.strip()
                                if not line or line.startswith('#'):
                                    continue
                                    
                                if line == '[RELAY_CONTROLS]':
                                    in_relay_controls = True
                                    continue
                                elif line.startswith('[') and line.endswith(']'):
                                    in_relay_controls = False
                                    continue
                                    
                                if in_relay_controls and '=' in line:
                                    key, value = [x.strip() for x in line.split('=', 1)]
                                    relay_controls[key] = value
                                    
                            if relay_controls:
                                logger.info(f"Found {len(relay_controls)} relay controls by direct reading")
                                for api_name, device_name in relay_controls.items():
                                    action_mapping[api_name] = create_relay_action(device_name)
                                    logger.info(f"Loaded action mapping: {api_name} -> {device_name}")
                            else:
                                raise ValueError("No relay controls found in file")
                    except Exception as e:
                        logger.error(f"Error reading config file directly: {e}")
                        # Fall back to hardcoded mappings
                        logger.warning("Falling back to hardcoded mappings")
                        default_mappings = {
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
                        for api_name, device_name in default_mappings.items():
                            action_mapping[api_name] = create_relay_action(device_name)
                            logger.info(f"Using default mapping: {api_name} -> {device_name}")
                
                # Process each action
                for action, state in new_actions.items():
                    action_handler = action_mapping.get(action)
                    if action_handler:
                        logger.info(f"Processing action {action} with state {state}")
                        try:
                            # Debug the action handler
                            logger.info(f"Action handler type: {type(action_handler).__name__}")
                            logger.info(f"Action handler object: {action_handler}")
                            
                            # Get device name from the mapping we loaded earlier
                            device_name = "unknown"
                            for key, value in config.items():
                                if key == 'RELAY_CONTROLS':
                                    device_name = value.get(action, "unknown")
                                    logger.info(f"Found device mapping in config: {action} -> {device_name}")
                            
                            logger.info(f"Executing action handler for {action} -> {device_name}")
                            
                            # Call the appropriate action handler function - with detailed error trapping
                            try:
                                result = action_handler(state)
                                logger.info(f"Action handler result: {result}")
                            except TypeError as te:
                                logger.error(f"TypeError in action handler: {te}")
                                logger.error(f"Action handler arguments might be incorrect: {action_handler}, state={state}")
                            except AttributeError as ae:
                                logger.error(f"AttributeError in action handler: {ae}")
                                logger.error(f"Object might be missing expected method: {action_handler}")
                            
                            # Add a delay after each action to ensure hardware responds
                            time.sleep(0.2)
                            
                            # Log success
                            logger.info(f"Action {action} successfully executed")
                        except Exception as e:
                            logger.error(f"Error applying action {action}: {e}")
                            logger.exception("Full exception details:")
                    else:
                        logger.warning(f"Unknown action: {action}")
                
                # Update last state
                self.last_action_state = new_actions.copy()
                
                # Only clear the action file if we've finished processing all actions
                logger.info("All actions processed")
            else:
                logger.info("No new actions detected")
                
        except Exception as e:
            logger.error(f"Error processing actions: {e}")
            logger.exception("Full exception details:")

class RippleController:
    def __init__(self):
        """Initialize the Ripple controller."""
        self.water_level_sensors = {}  # Dict to store water level sensor instances
        self.relays = {}  # Dict to store relay instances
        self.sensor_targets = {}  # Dict to store sensor target values
        self.scheduler = RippleScheduler()
        
        # Use absolute paths for config files
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_dir = os.path.join(self.base_dir, 'config')
        self.data_dir = os.path.join(self.base_dir, 'data')
        
        # Ensure config and data directories exist
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)
        
        self.config_file = os.path.join(self.config_dir, 'device.conf')
        # Create config parser with case sensitivity
        self.config = configparser.ConfigParser(empty_lines_in_values=False, interpolation=None)
        self.sensor_data_file = os.path.join(self.data_dir, 'saved_sensor_data.json')
        
        self.initialize_sensors()
        self.load_sensor_targets()
        
        # Make sure config file exists before attempting to watch it
        if not os.path.exists(self.config_file):
            logger.warning(f"Config file {self.config_file} does not exist. Creating an empty file.")
            with open(self.config_file, 'w') as f:
                pass
        
        # Make sure action.json exists before attempting to watch it
        action_file = os.path.join(self.config_dir, 'action.json')
        if not os.path.exists(action_file):
            logger.warning(f"Action file {action_file} does not exist. Creating an empty JSON file.")
            with open(action_file, 'w') as f:
                json.dump({}, f)
        else:
            # Ensure action file has valid JSON format
            try:
                with open(action_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        json.loads(content)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Action file has invalid JSON format: {e}. Resetting to empty object.")
                with open(action_file, 'w') as f:
                    json.dump({}, f)
        
        # Initialize watchdog observer
        self.event_handler = ConfigFileHandler(self)
        self.observer = Observer()
        self.observer.schedule(self.event_handler, self.config_dir, recursive=False)
        self.observer.start()
        logger.info(f"Configuration and action file monitoring started for directory: {self.config_dir}")

    def _time_to_seconds(self, time_str):
        """Convert HH:MM:SS format to seconds"""
        hours, minutes, seconds = map(int, time_str.split(':'))
        return hours * 3600 + minutes * 60 + seconds

    def initialize_sensors(self):
        """Initialize all sensors from configuration."""
        try:
            # Initialize water level sensors
            WaterLevel.load_all_sensors()
            
            # Initialize relays - create a single instance which will load addresses
            Relay()
            
            # Initialize pH sensors
            pH.load_all_sensors()
            
            # Initialize EC sensors
            EC.load_all_sensors()
            
            # Initialize DO sensors
            # DO.load_all_sensors()
            
            logger.info("All sensors initialized successfully")
        except Exception as e:
            logger.error(f"Error initializing sensors: {e}")
            logger.exception("Full exception details:")

    def load_sensor_targets(self):
        """Load sensor target values from device.conf."""
        try:
            self.config.read(self.config_file)
            
            # Load pH targets
            ph_target = self.config.get('pH', 'ph_target').split(',')[1].strip()
            ph_deadband = self.config.get('pH', 'ph_deadband').split(',')[1].strip()
            ph_min = self.config.get('pH', 'ph_min').split(',')[1].strip()
            ph_max = self.config.get('pH', 'ph_max').split(',')[1].strip()
            
            # Load EC targets
            ec_target = self.config.get('EC', 'ec_target').split(',')[1].strip()
            ec_deadband = self.config.get('EC', 'ec_deadband').split(',')[1].strip()
            ec_min = self.config.get('EC', 'ec_min').split(',')[1].strip()
            ec_max = self.config.get('EC', 'ec_max').split(',')[1].strip()
            
            # Load Water Level targets
            water_level_target = self.config.get('WaterLevel', 'water_level_target').split(',')[1].strip()
            water_level_deadband = self.config.get('WaterLevel', 'water_level_deadband').split(',')[1].strip()
            water_level_min = self.config.get('WaterLevel', 'water_level_min').split(',')[1].strip()
            water_level_max = self.config.get('WaterLevel', 'water_level_max').split(',')[1].strip()
            
            # Store the values
            self.sensor_targets = {
                'pH': {
                    'target': float(ph_target),
                    'deadband': float(ph_deadband),
                    'min': float(ph_min),
                    'max': float(ph_max)
                },
                'EC': {
                    'target': float(ec_target),
                    'deadband': float(ec_deadband),
                    'min': float(ec_min),
                    'max': float(ec_max)
                },
                'WaterLevel': {
                    'target': float(water_level_target),
                    'deadband': float(water_level_deadband),
                    'min': float(water_level_min),
                    'max': float(water_level_max)
                }
            }
            
            logger.info(f"Loaded sensor targets: {self.sensor_targets}")
            
        except Exception as e:
            logger.error(f"Error loading sensor targets from device.conf: {e}")
            # Set default values if config file can't be read
            self.sensor_targets = {
                'pH': {'target': 7.0, 'deadband': 0.1, 'min': 6.5, 'max': 7.5},
                'EC': {'target': 1.0, 'deadband': 0.1, 'min': 0.5, 'max': 1.5},
                'WaterLevel': {'target': 80.0, 'deadband': 10.0, 'min': 50.0, 'max': 100.0}
            }

    def reload_specific_sections(self, changed_sections):
        """Reload only the specific sections that have changed"""
        try:
            # Reload the config file
            self.config.read(self.config_file)
            
            # Track if we've made any changes that require a full reload of sensor targets
            need_reload_targets = False
            
            # Process each changed section
            for section in changed_sections:
                logger.info(f"Reloading configuration for section: {section}")
                
                if section == 'Mixing':
                    self.scheduler.update_configuration('Mixing', 'mixing_interval', 
                        self.config.get('Mixing', 'mixing_interval').split(',')[0])
                    self.scheduler.update_configuration('Mixing', 'mixing_duration', 
                        self.config.get('Mixing', 'mixing_duration').split(',')[0])
                    self.scheduler.update_configuration('Mixing', 'trigger_mixing_duration', 
                        self.config.get('Mixing', 'trigger_mixing_duration').split(',')[0])
                    
                    # Check if mixing_duration is set to zero
                    mixing_duration = self.config.get('Mixing', 'mixing_duration').split(',')[0]
                    mixing_seconds = self._time_to_seconds(mixing_duration)
                    
                    if mixing_seconds == 0:
                        # Turn off mixing pump if duration is set to zero
                        from src.sensors.Relay import Relay
                        relay = Relay()
                        if relay:
                            relay.set_mixing_pump(False)
                            logger.info("Mixing pump turned off due to zero duration configuration")
                            
                            # Make sure scheduler knows the pump is off
                            if hasattr(self.scheduler, 'mixing_pump_running'):
                                self.scheduler.mixing_pump_running = False
                                self.scheduler.mixing_pump_end_time = None
                                
                            # Remove any scheduled mixing pump stop jobs
                            try:
                                if hasattr(self.scheduler, 'scheduler'):
                                    self.scheduler.scheduler.remove_job('mixing_stop_job')
                                    logger.info("Removed scheduled mixing pump stop job")
                            except Exception as e:
                                # Job might not exist, which is fine
                                logger.debug(f"No mixing stop job to remove: {e}")
                                pass
                        else:
                            logger.warning("Failed to turn off mixing pump: relay not available")
                            
                    logger.info("Mixing configuration updated")
                
                elif section == 'NutrientPump':
                    self.scheduler.update_configuration('NutrientPump', 'nutrient_pump_on_duration', 
                        self.config.get('NutrientPump', 'nutrient_pump_on_duration').split(',')[0])
                    self.scheduler.update_configuration('NutrientPump', 'nutrient_pump_wait_duration', 
                        self.config.get('NutrientPump', 'nutrient_pump_wait_duration').split(',')[0])
                    self.scheduler.update_configuration('NutrientPump', 'ph_pump_on_duration', 
                        self.config.get('NutrientPump', 'ph_pump_on_duration').split(',')[0])
                    self.scheduler.update_configuration('NutrientPump', 'ph_pump_wait_duration', 
                        self.config.get('NutrientPump', 'ph_pump_wait_duration').split(',')[0])
                    
                    # Initialize Relay connection
                    from src.sensors.Relay import Relay
                    relay = Relay()
                    
                    # Check nutrient pump duration
                    nutrient_duration = self.config.get('NutrientPump', 'nutrient_pump_on_duration').split(',')[0]
                    nutrient_seconds = self._time_to_seconds(nutrient_duration)
                    
                    if nutrient_seconds == 0:
                        # Turn off nutrient pumps if duration is set to zero
                        if relay:
                            relay.set_nutrient_pumps(False)
                            logger.info("Nutrient pumps turned off due to zero duration configuration")
                            
                            # Remove any scheduled nutrient pump stop jobs
                            try:
                                if hasattr(self.scheduler, 'scheduler'):
                                    for job_id in ['scheduled_nutrient_stop', 'scheduled_nutrient_a_stop', 
                                                'scheduled_nutrient_b_stop', 'scheduled_nutrient_c_stop', 
                                                'nutrient_stop_job']:
                                        try:
                                            self.scheduler.scheduler.remove_job(job_id)
                                        except Exception:
                                            # Individual job might not exist
                                            pass
                                    logger.info("Removed scheduled nutrient pump stop jobs")
                            except Exception as e:
                                logger.debug(f"Error removing nutrient stop jobs: {e}")
                                pass
                        else:
                            logger.warning("Failed to turn off nutrient pumps: relay not available")
                    
                    # Check pH pump duration
                    ph_duration = self.config.get('NutrientPump', 'ph_pump_on_duration').split(',')[0]
                    ph_seconds = self._time_to_seconds(ph_duration)
                    
                    if ph_seconds == 0:
                        # Turn off pH pumps if duration is set to zero
                        if relay:
                            relay.set_ph_plus_pump(False)
                            relay.set_ph_minus_pump(False)
                            logger.info("pH pumps turned off due to zero duration configuration")
                            
                            # Remove any scheduled pH pump stop jobs
                            try:
                                if hasattr(self.scheduler, 'scheduler'):
                                    for job_id in ['scheduled_ph_stop', 'ph_stop_job']:
                                        try:
                                            self.scheduler.scheduler.remove_job(job_id)
                                        except Exception:
                                            # Individual job might not exist
                                            pass
                                    logger.info("Removed scheduled pH pump stop jobs")
                            except Exception as e:
                                logger.debug(f"Error removing pH stop jobs: {e}")
                                pass
                        else:
                            logger.warning("Failed to turn off pH pumps: relay not available")
                    
                    # Only trigger nutrient cycle check if we're not turning things off
                    if nutrient_seconds > 0:
                        # Trigger immediate EC check for nutrient adjustments
                        logger.info("Triggering immediate nutrient cycle check due to NutrientPump config change")
                        self.scheduler._run_nutrient_cycle()
                    
                    logger.info("NutrientPump configuration updated")
                
                elif section == 'Sprinkler':
                    # First, ensure sprinklers are turned off before doing anything else
                    # This guarantees that changing any sprinkler setting will always reset the sprinkler state
                    try:
                        from src.sensors.Relay import Relay
                        relay = Relay()
                        if relay:
                            relay.set_sprinklers(False)
                            logger.info("Sprinklers turned off as part of configuration change procedure")
                    except Exception as e:
                        logger.error(f"Error turning off sprinklers: {e}")
                        
                    # Now update the configuration values
                    self.scheduler.update_configuration('Sprinkler', 'sprinkler_on_duration', 
                        self.config.get('Sprinkler', 'sprinkler_on_duration').split(',')[0])
                    self.scheduler.update_configuration('Sprinkler', 'sprinkler_wait_duration', 
                        self.config.get('Sprinkler', 'sprinkler_wait_duration').split(',')[0])
                    
                    # Only proceed to potentially turning them back on if not in an error state
                    try:
                        # IMPORTANT: Clean up ALL possible sprinkler-related jobs first
                        try:
                            if hasattr(self.scheduler, 'scheduler'):
                                # Stop any sprinkler stop jobs regardless of their ID
                                for job_id in ['immediate_sprinkler_stop', 'startup_sprinkler_stop', 
                                              'scheduled_sprinkler_stop', 'config_sprinkler_stop',
                                              'sprinkler_cycle']:
                                    try:
                                        self.scheduler.scheduler.remove_job(job_id)
                                        logger.info(f"[Startup] Removed existing sprinkler job with ID: {job_id}")
                                    except Exception:
                                        # Job might not exist
                                        pass
                        except Exception as e:
                            logger.warning(f"[Startup] Error cleaning up sprinkler jobs: {e}")
                            
                        # Get sprinkler on_duration from config - USING THE SECOND VALUE (operational value)
                        sprinkler_on_duration_raw = self.config.get('Sprinkler', 'sprinkler_on_duration')
                        logger.info(f"Raw sprinkler_on_duration from config: '{sprinkler_on_duration_raw}'")
                        
                        # Properly parse the value to get the second element (operational value)
                        sprinkler_on_duration = ""
                        if ',' in sprinkler_on_duration_raw:
                            sprinkler_on_duration_parts = sprinkler_on_duration_raw.split(',')
                            if len(sprinkler_on_duration_parts) >= 2:
                                sprinkler_on_duration = sprinkler_on_duration_parts[1].strip()
                                logger.info(f"[Startup] Using OPERATIONAL value from config: '{sprinkler_on_duration}'")
                            else:
                                sprinkler_on_duration = sprinkler_on_duration_parts[0].strip()
                                logger.info(f"[Startup] Using first value (no second value found): '{sprinkler_on_duration}'")
                        else:
                            sprinkler_on_duration = sprinkler_on_duration_raw.strip()
                            logger.info(f"[Startup] Using single value (no comma): '{sprinkler_on_duration}'")
                        
                        # Strip any quotes
                        sprinkler_on_duration = sprinkler_on_duration.strip('"\'')
                        
                        sprinkler_on_seconds = self._time_to_seconds(sprinkler_on_duration)
                        logger.info(f"[Startup] Parsed sprinkler duration: {sprinkler_on_duration} = {sprinkler_on_seconds} seconds")
                        
                        # Only activate the sprinkler if duration is positive
                        if sprinkler_on_seconds > 0:
                            from src.sensors.Relay import Relay
                            relay = Relay()
                            if relay:
                                logger.info(f"[Startup] Sprinkler duration > 0 ({sprinkler_on_duration}), activating sprinklers")
                                # Turn on sprinklers directly
                                relay.set_sprinklers(True)
                                
                                # Schedule to stop after the configured duration
                                try:
                                    # First try to use the scheduler (preferred method)
                                    if hasattr(self.scheduler, 'scheduler') and hasattr(self.scheduler.scheduler, 'add_job'):
                                        # Create a copy of the duration for the lambda to avoid variable capture issues
                                        duration_copy = sprinkler_on_seconds
                                        stop_time = datetime.now() + timedelta(seconds=duration_copy)
                                        
                                        # Add a job that directly calls set_sprinklers(False)
                                        job = self.scheduler.scheduler.add_job(
                                            lambda: self._direct_stop_sprinklers(),
                                            'date',
                                            run_date=stop_time,
                                            id='config_sprinkler_stop',  # CONSISTENT JOB ID
                                            replace_existing=True
                                        )
                                        logger.info(f"Scheduled sprinkler stop via scheduler for: {stop_time.strftime('%H:%M:%S')} - job ID: config_sprinkler_stop")
                                        # Log all scheduled jobs to verify
                                        self._log_all_scheduler_jobs()
                                    else:
                                        # Fallback to a thread-based timer if scheduler is unavailable
                                        logger.warning("[Startup] Scheduler unavailable, using thread-based timer as fallback")
                                        self._create_backup_sprinkler_timer(sprinkler_on_seconds)
                                except Exception as e:
                                    logger.error(f"[Startup] Error scheduling sprinkler stop via scheduler: {e}")
                                    logger.exception("Full exception details:")
                                    # Try the backup method if scheduler failed
                                    logger.info("[Startup] Attempting to use thread-based timer as fallback after scheduler failure")
                                    self._create_backup_sprinkler_timer(sprinkler_on_seconds)
                            else:
                                logger.warning("[Startup] Failed to activate sprinklers: relay not available")
                        else:
                            logger.info("[Startup] Sprinkler duration set to zero, keeping sprinklers off")
                    except Exception as e:
                        logger.error(f"Error in sprinkler control: {e}")
                        logger.exception("Full exception details:")
                        
                    logger.info("Sprinkler configuration updated")
                
                elif section == 'EC':
                    if 'EC' in self.config:
                        self.scheduler.update_configuration('EC', 'ec_target', 
                            self.config.get('EC', 'ec_target').split(',')[0])
                        self.scheduler.update_configuration('EC', 'ec_deadband', 
                            self.config.get('EC', 'ec_deadband').split(',')[0])
                        self.scheduler.update_configuration('EC', 'ec_max', 
                            self.config.get('EC', 'ec_max').split(',')[0])
                        
                        # Update sensor targets
                        need_reload_targets = True
                        
                        # Trigger immediate EC check
                        logger.info("Triggering immediate EC check due to EC config change")
                        self.scheduler._run_nutrient_cycle()
                        logger.info("EC configuration updated")
                
                elif section == 'pH':
                    if 'pH' in self.config:
                        self.scheduler.update_configuration('pH', 'ph_target', 
                            self.config.get('pH', 'ph_target').split(',')[0])
                        self.scheduler.update_configuration('pH', 'ph_deadband', 
                            self.config.get('pH', 'ph_deadband').split(',')[0])
                        self.scheduler.update_configuration('pH', 'ph_min', 
                            self.config.get('pH', 'ph_min').split(',')[0])
                        self.scheduler.update_configuration('pH', 'ph_max', 
                            self.config.get('pH', 'ph_max').split(',')[0])
                        
                        # Update sensor targets
                        need_reload_targets = True
                        
                        # Trigger immediate pH check
                        logger.info("Triggering immediate pH check due to pH config change")
                        self.scheduler._run_ph_cycle()
                        logger.info("pH configuration updated")
                
                elif section == 'WaterLevel':
                    # Water level targets affect valve control
                    need_reload_targets = True
                    
                    # Trigger immediate water level check
                    logger.info("Triggering immediate water level check due to WaterLevel config change")
                    self.scheduler._check_water_level()
                    logger.info("WaterLevel configuration updated")
            
            # Reload sensor targets if needed
            if need_reload_targets:
                self.load_sensor_targets()
                logger.info("Sensor targets reloaded")
            
            logger.info("Specific configuration sections reloaded successfully")
            
        except Exception as e:
            logger.error(f"Error reloading specific sections: {e}")
            # Fall back to full reload if specific reload fails
            logger.info("Falling back to full configuration reload")
            self.reload_configuration()
    
    def reload_configuration(self):
        """Reload complete configuration from device.conf (fallback method)"""
        try:
            # Reload the config file
            self.config.read(self.config_file)
            
            # Reload sensor targets
            self.load_sensor_targets()
            
            # Update scheduler configuration
            self.scheduler.update_configuration('Mixing', 'mixing_interval', 
                self.config.get('Mixing', 'mixing_interval').split(',')[0])
            self.scheduler.update_configuration('Mixing', 'mixing_duration', 
                self.config.get('Mixing', 'mixing_duration').split(',')[0])
            self.scheduler.update_configuration('Mixing', 'trigger_mixing_duration', 
                self.config.get('Mixing', 'trigger_mixing_duration').split(',')[0])
                
            self.scheduler.update_configuration('NutrientPump', 'nutrient_pump_on_duration', 
                self.config.get('NutrientPump', 'nutrient_pump_on_duration').split(',')[0])
            self.scheduler.update_configuration('NutrientPump', 'nutrient_pump_wait_duration', 
                self.config.get('NutrientPump', 'nutrient_pump_wait_duration').split(',')[0])
            self.scheduler.update_configuration('NutrientPump', 'ph_pump_on_duration', 
                self.config.get('NutrientPump', 'ph_pump_on_duration').split(',')[0])
            self.scheduler.update_configuration('NutrientPump', 'ph_pump_wait_duration', 
                self.config.get('NutrientPump', 'ph_pump_wait_duration').split(',')[0])
                
            self.scheduler.update_configuration('Sprinkler', 'sprinkler_on_duration', 
                self.config.get('Sprinkler', 'sprinkler_on_duration').split(',')[0])
            self.scheduler.update_configuration('Sprinkler', 'sprinkler_wait_duration', 
                self.config.get('Sprinkler', 'sprinkler_wait_duration').split(',')[0])

            # Update EC targets
            if 'EC' in self.config:
                self.scheduler.update_configuration('EC', 'ec_target', 
                    self.config.get('EC', 'ec_target').split(',')[0])
                self.scheduler.update_configuration('EC', 'ec_deadband', 
                    self.config.get('EC', 'ec_deadband').split(',')[0])
                self.scheduler.update_configuration('EC', 'ec_max', 
                    self.config.get('EC', 'ec_max').split(',')[0])

            # Update pH targets
            if 'pH' in self.config:
                self.scheduler.update_configuration('pH', 'ph_target', 
                    self.config.get('pH', 'ph_target').split(',')[0])
                self.scheduler.update_configuration('pH', 'ph_deadband', 
                    self.config.get('pH', 'ph_deadband').split(',')[0])
                self.scheduler.update_configuration('pH', 'ph_min', 
                    self.config.get('pH', 'ph_min').split(',')[0])
                self.scheduler.update_configuration('pH', 'ph_max', 
                    self.config.get('pH', 'ph_max').split(',')[0])
                
            logger.info("Full configuration reloaded successfully")
            
            # Immediately run scheduler checks when configuration changes
            logger.info("Running immediate scheduler checks due to configuration change...")
            
            # Trigger immediate pH check
            self.scheduler._run_ph_cycle()
            
            # Trigger immediate EC check
            self.scheduler._run_nutrient_cycle()
            
            # Trigger immediate water level check
            self.scheduler._check_water_level()
            
            # Trigger immediate sprinkler check
            # Check if it's time to run the sprinkler based on the current configuration
            try:
                # Get sprinkler on_duration from config
                sprinkler_on_duration = self.config.get('Sprinkler', 'sprinkler_on_duration').split(',')[0]
                sprinkler_on_seconds = self._time_to_seconds(sprinkler_on_duration)
                
                # Only run the sprinkler if the duration is not zero
                if sprinkler_on_seconds > 0:
                    logger.info("Running immediate sprinkler check due to configuration change")
                    self.scheduler._run_sprinkler_cycle()
                else:
                    logger.info("Sprinkler cycle skipped: zero duration configured")
            except Exception as e:
                logger.error(f"Error in immediate sprinkler check: {e}")
            
            logger.info("Immediate scheduler checks completed")
            
        except Exception as e:
            logger.error(f"Error reloading configuration: {e}")

    def start(self):
        """Start the Ripple controller"""
        try:
            logger.info("Starting Ripple controller")
            self.scheduler.start()
            
            # Run immediate checks for all systems at startup
            self._run_startup_checks()
            
            self.run_main_loop()
        except Exception as e:
            logger.error(f"Error starting Ripple controller: {e}")
            self.shutdown()
            
    def _run_startup_checks(self):
        """Run all system checks and activations at startup"""
        try:
            logger.info("==== RUNNING STARTUP CHECKS AND ACTIVATIONS ====")
            
            # Make sure we have the latest config
            self.config.read(self.config_file)
            
            # 1. Check and activate water level monitoring
            try:
                logger.info("[Startup] Running initial water level check")
                self.scheduler._check_water_level()
            except Exception as e:
                logger.error(f"[Startup] Error during water level check: {e}")
                
            # 2. Run an initial pH check
            try:
                logger.info("[Startup] Running initial pH check")
                self.scheduler._run_ph_cycle()
            except Exception as e:
                logger.error(f"[Startup] Error during pH check: {e}")
                
            # 3. Run an initial nutrient (EC) check
            try:
                logger.info("[Startup] Running initial nutrient cycle check")
                self.scheduler._run_nutrient_cycle()
            except Exception as e:
                logger.error(f"[Startup] Error during nutrient cycle check: {e}")
                
            # 4. Check and activate mixing pump if needed
            try:
                logger.info("[Startup] Running initial mixing pump check")
                # Read mixing duration from config
                mixing_duration_raw = self.config.get('Mixing', 'mixing_duration')
                
                # Handle comma-separated values - use second value if available
                if ',' in mixing_duration_raw:
                    mixing_duration_parts = mixing_duration_raw.split(',')
                    if len(mixing_duration_parts) >= 2:
                        mixing_duration = mixing_duration_parts[1].strip()
                    else:
                        mixing_duration = mixing_duration_parts[0].strip()
                else:
                    mixing_duration = mixing_duration_raw.strip()
                
                # Strip any quotes
                mixing_duration = mixing_duration.strip('"\'')
                
                # Convert to seconds
                mixing_seconds = self._time_to_seconds(mixing_duration)
                
                if mixing_seconds > 0:
                    logger.info(f"[Startup] Running mixing pump cycle with duration: {mixing_duration}")
                    self.scheduler._run_mixing_cycle()
                else:
                    logger.info("[Startup] Mixing pump duration is zero, not activating")
            except Exception as e:
                logger.error(f"[Startup] Error during mixing pump check: {e}")
                
            # 5. Check and activate sprinklers if needed
            try:
                self._activate_sprinklers_on_startup()
            except Exception as e:
                logger.error(f"[Startup] Error during sprinkler activation: {e}")
                
            logger.info("==== STARTUP CHECKS AND ACTIVATIONS COMPLETE ====")
            
        except Exception as e:
            logger.error(f"Error running startup checks: {e}")
            logger.exception("Full exception details:")

    def _activate_sprinklers_on_startup(self):
        """Check and activate sprinklers on system startup if configured"""
        try:
            logger.info("Checking if sprinklers should be activated on startup")
            
            # Make sure we have the latest config
            self.config.read(self.config_file)
            
            # IMPORTANT: Clean up ALL possible sprinkler-related jobs first
            try:
                if hasattr(self.scheduler, 'scheduler'):
                    # Stop any sprinkler stop jobs regardless of their ID
                    for job_id in ['immediate_sprinkler_stop', 'startup_sprinkler_stop', 
                                  'scheduled_sprinkler_stop', 'config_sprinkler_stop',
                                  'sprinkler_cycle']:
                        try:
                            self.scheduler.scheduler.remove_job(job_id)
                            logger.info(f"[Startup] Removed existing sprinkler job with ID: {job_id}")
                        except Exception:
                            # Job might not exist
                            pass
            except Exception as e:
                logger.warning(f"[Startup] Error cleaning up sprinkler jobs: {e}")
            
            # Get sprinkler on_duration from config - USING THE SECOND VALUE (operational value)
            sprinkler_on_duration_raw = self.config.get('Sprinkler', 'sprinkler_on_duration')
            logger.info(f"Raw sprinkler_on_duration from config: '{sprinkler_on_duration_raw}'")
            
            # Properly parse the value to get the second element (operational value)
            sprinkler_on_duration = ""
            if ',' in sprinkler_on_duration_raw:
                sprinkler_on_duration_parts = sprinkler_on_duration_raw.split(',')
                if len(sprinkler_on_duration_parts) >= 2:
                    sprinkler_on_duration = sprinkler_on_duration_parts[1].strip()
                    logger.info(f"[Startup] Using OPERATIONAL value from config: '{sprinkler_on_duration}'")
                else:
                    sprinkler_on_duration = sprinkler_on_duration_parts[0].strip()
                    logger.info(f"[Startup] Using first value (no second value found): '{sprinkler_on_duration}'")
            else:
                sprinkler_on_duration = sprinkler_on_duration_raw.strip()
                logger.info(f"[Startup] Using single value (no comma): '{sprinkler_on_duration}'")
            
            # Strip any quotes
            sprinkler_on_duration = sprinkler_on_duration.strip('"\'')
            
            sprinkler_on_seconds = self._time_to_seconds(sprinkler_on_duration)
            logger.info(f"[Startup] Parsed sprinkler duration: {sprinkler_on_duration} = {sprinkler_on_seconds} seconds")
            
            # Only activate the sprinkler if duration is positive
            if sprinkler_on_seconds > 0:
                from src.sensors.Relay import Relay
                relay = Relay()
                if relay:
                    logger.info(f"[Startup] Sprinkler duration > 0 ({sprinkler_on_duration}), activating sprinklers")
                    # Turn on sprinklers directly
                    relay.set_sprinklers(True)
                    
                    # Schedule to stop after the configured duration
                    try:
                        # First try to use the scheduler (preferred method)
                        if hasattr(self.scheduler, 'scheduler') and hasattr(self.scheduler.scheduler, 'add_job'):
                            # Create a copy of the duration for the lambda to avoid variable capture issues
                            duration_copy = sprinkler_on_seconds
                            stop_time = datetime.now() + timedelta(seconds=duration_copy)
                            
                            # Add a job that directly calls set_sprinklers(False)
                            self.scheduler.scheduler.add_job(
                                lambda: self._direct_stop_sprinklers(),
                                'date',
                                run_date=stop_time,
                                id='startup_sprinkler_stop',
                                replace_existing=True
                            )
                            logger.info(f"[Startup] Scheduled sprinkler stop via scheduler for: {stop_time.strftime('%H:%M:%S')} - job ID: startup_sprinkler_stop")
                            # Log all scheduled jobs to verify
                            self._log_all_scheduler_jobs()
                        else:
                            # Fallback to a thread-based timer if scheduler is unavailable
                            logger.warning("[Startup] Scheduler unavailable, using thread-based timer as fallback")
                            self._create_backup_sprinkler_timer(sprinkler_on_seconds)
                    except Exception as e:
                        logger.error(f"[Startup] Error scheduling sprinkler stop via scheduler: {e}")
                        logger.exception("Full exception details:")
                        # Try the backup method if scheduler failed
                        logger.info("[Startup] Attempting to use thread-based timer as fallback after scheduler failure")
                        self._create_backup_sprinkler_timer(sprinkler_on_seconds)
                else:
                    logger.warning("[Startup] Failed to activate sprinklers: relay not available")
            else:
                logger.info("[Startup] Sprinkler duration set to zero, keeping sprinklers off")
        except Exception as e:
            logger.error(f"Error activating sprinklers on startup: {e}")
            logger.exception("Full exception details:")

    def shutdown(self):
        """Shutdown the Ripple controller"""
        try:
            logger.info("Shutting down Ripple controller")
            self.scheduler.shutdown()
            self.observer.stop()
            self.observer.join()
            logger.info("Configuration and action file monitoring stopped")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            
    def run_main_loop(self):
        """Main loop for the Ripple controller"""
        logger.info("Starting main control loop")
        try:
            while True:
                # Get data from all sensors
                self.update_sensor_data()
                
                # Save sensor data
                self.save_sensor_data()
                
                # Process any pending commands or events
                self.process_events()
                
                # Wait for next cycle
                time.sleep(10)  # 10 second interval between sensor readings
                
        except KeyboardInterrupt:
            logger.info("Main loop interrupted by user")
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            logger.exception("Full exception details:")
            
    def update_sensor_data(self):
        """Update data from all connected sensors"""
        try:
            # Initialize sensor readings
            water_levels = {}
            ph_statuses = {}
            ec_statuses = {}
            
            # Update water level sensor readings
            water_levels = WaterLevel.get_statuses_async()
            if water_levels:
                logger.debug(f"Water levels: {water_levels}")
            else:
                logger.warning("No water level readings received")
            
            # Update relay states
            relay_instance = Relay()
            if relay_instance:
                relay_instance.get_status()
                if relay_instance.relay_statuses:
                    logger.debug(f"Relay states: {relay_instance.relay_statuses}")
            
            # Update pH sensor readings
            ph_statuses = pH.get_statuses_async()
            if ph_statuses:
                logger.debug(f"pH sensor readings: {ph_statuses}")
            else:
                logger.warning("No pH readings received")
            
            # Update EC sensor readings
            ec_statuses = EC.get_statuses_async()
            if ec_statuses:
                logger.debug(f"EC sensor readings: {ec_statuses}")
            else:
                logger.warning("No EC readings received")
            
            # Check if sensor values are within configured ranges
            try:
                self.check_sensor_ranges(ph_statuses, ec_statuses, water_levels)
            except Exception as e:
                logger.error(f"Error in check_sensor_ranges: {e}")
                logger.exception("Full exception details:")
                    
        except Exception as e:
            logger.error(f"Error updating sensor data: {e}")
            logger.exception("Full exception details:")
            
    def check_sensor_ranges(self, ph_statuses: Dict[str, float], ec_statuses: Dict[str, float], water_levels: Dict[str, float]):
        """Check if sensor values are within configured ranges from device.conf."""
        try:
            # Track if we need automatic pH correction
            needs_ph_correction = False
            ph_value = None
            
            # Check pH values
            if ph_statuses:
                ph_targets = self.sensor_targets['pH']
                for sensor_name, ph_value in ph_statuses.items():
                    if ph_value < ph_targets['min'] or ph_value > ph_targets['max']:
                        logger.warning(f"pH sensor {sensor_name} value {ph_value} is outside safe range ({ph_targets['min']}-{ph_targets['max']})")
                        needs_ph_correction = True
                    elif abs(ph_value - ph_targets['target']) > ph_targets['deadband']:
                        logger.info(f"pH sensor {sensor_name} value {ph_value} is outside target range ({ph_targets['target']}±{ph_targets['deadband']})")
                        needs_ph_correction = True
            
            # Check EC values
            if ec_statuses:
                ec_targets = self.sensor_targets['EC']
                for sensor_name, ec_value in ec_statuses.items():
                    if ec_value < ec_targets['min'] or ec_value > ec_targets['max']:
                        logger.warning(f"EC sensor {sensor_name} value {ec_value} is outside safe range ({ec_targets['min']}-{ec_targets['max']})")
                    elif abs(ec_value - ec_targets['target']) > ec_targets['deadband']:
                        logger.info(f"EC sensor {sensor_name} value {ec_value} is outside target range ({ec_targets['target']}±{ec_targets['deadband']})")
            
            # Check Water Level values
            if water_levels:
                water_level_targets = self.sensor_targets['WaterLevel']
                for sensor_name, water_level in water_levels.items():
                    if water_level < water_level_targets['min'] or water_level > water_level_targets['max']:
                        logger.warning(f"Water level sensor {sensor_name} value {water_level} is outside safe range ({water_level_targets['min']}-{water_level_targets['max']})")
                    elif abs(water_level - water_level_targets['target']) > water_level_targets['deadband']:
                        logger.info(f"Water level sensor {sensor_name} value {water_level} is outside target range ({water_level_targets['target']}±{water_level_targets['deadband']})")
            
            # Trigger automatic pH correction if needed
            if needs_ph_correction and ph_value is not None:
                self._trigger_ph_correction(ph_value)
                
        except Exception as e:
            logger.error(f"Error checking sensor ranges: {e}")
            
    def _trigger_ph_correction(self, current_ph):
        """Trigger automatic pH correction if not already running"""
        try:
            # Use the scheduler to run pH correction
            if hasattr(self, 'scheduler') and self.scheduler:
                # Check if the scheduler has a method to check if pH correction is already running
                if hasattr(self.scheduler, '_run_ph_cycle'):
                    logger.info(f"Triggering automatic pH correction, current pH: {current_ph}")
                    self.scheduler._run_ph_cycle()
                else:
                    logger.warning("Cannot trigger pH correction: Scheduler missing _run_ph_cycle method")
            else:
                logger.warning("Cannot trigger pH correction: Scheduler not available")
        except Exception as e:
            logger.error(f"Error triggering pH correction: {e}")
            logger.exception("Full exception details:")

    def process_events(self):
        """Process any pending events or commands."""
        # This method can be expanded to handle scheduled tasks,
        # respond to sensor thresholds, etc.
        pass

    def save_sensor_data(self):
        """Save current sensor data to JSON file"""
        try:
            data = {
                "data": {
                    "water_metrics": {
                        "water_level": {
                            "measurements": {
                                "name": "water_metrics",
                                "points": []
                            }
                        },
                        "ph": {
                            "measurements": {
                                "name": "water_metrics",
                                "points": []
                            }
                        },
                        "ec": {
                            "measurements": {
                                "name": "water_metrics",
                                "points": []
                            }
                        }
                    },
                    "relay_metrics": {
                        "measurements": {
                            "name": "relay_metrics",
                            "points": []
                        },
                        "configuration": {
                            "relay_configuration": {
                                "relayone": {
                                    "total_ports": 16,
                                    "assigned_ports": [],
                                    "unassigned_ports": list(range(16))
                                }
                            }
                        }
                    }
                },
                "relays": {
                    "last_updated": datetime.now().isoformat(),
                    "relayone": {
                        "RELAYONE": {
                            "RELAYONE": [0] * 16
                        }
                    }
                },
                "devices": {
                    "last_updated": datetime.now().isoformat()
                }
            }

            # Get water level data
            wl_data = WaterLevel.get_statuses_async()
            if wl_data:
                for sensor_name, value in wl_data.items():
                    data["data"]["water_metrics"]["water_level"]["measurements"]["points"].append({
                        "tags": {
                            "sensor": "water_level",
                            "measurement": "level",
                            "location": sensor_name
                        },
                        "fields": {
                            "value": value,
                            "temperature": None,
                            "pressure_unit": None,
                            "decimal_places": None,
                            "range_min": 0,
                            "range_max": 200,
                            "zero_offset": None
                        },
                        "timestamp": datetime.now().isoformat()
                    })

            # Get pH data
            ph_data = pH.get_statuses_async()
            if ph_data:
                for sensor_name, value in ph_data.items():
                    data["data"]["water_metrics"]["ph"]["measurements"]["points"].append({
                        "tags": {
                            "sensor": "ph",
                            "measurement": "ph",
                            "location": sensor_name
                        },
                        "fields": {
                            "value": value,
                            "temperature": 25.0,
                            "offset": None
                        },
                        "timestamp": datetime.now().isoformat()
                    })

            # Get EC data
            ec_data = EC.get_statuses_async()
            if ec_data:
                for sensor_name, value in ec_data.items():
                    data["data"]["water_metrics"]["ec"]["measurements"]["points"].append({
                        "tags": {
                            "sensor": "ec",
                            "measurement": "ec",
                            "location": sensor_name
                        },
                        "fields": {
                            "value": value,
                            "tds": value * 0.5,
                            "salinity": value * 0.55,
                            "temperature": 25.0,
                            "resistance": 1000.0,
                            "ec_constant": 1.0,
                            "compensation_coef": 0.02,
                            "manual_temp": 25.0,
                            "temp_offset": None,
                            "electrode_sensitivity": None,
                            "compensation_mode": None,
                            "sensor_type": None
                        },
                        "timestamp": datetime.now().isoformat()
                    })

            # Get relay data and map according to device.conf assignments
            relay_instance = Relay()
            if relay_instance:
                relay_instance.get_status()
                if relay_instance.relay_statuses:
                    # Map relay statuses according to device.conf assignments
                    relay_mapping = {
                        0: "NutrientPumpA",
                        1: "NutrientPumpB",
                        2: "NutrientPumpC",
                        3: "pHUpPump",
                        4: "pHDownPump",
                        5: "ValveOutsideToTank",
                        6: "ValveTankToOutside",
                        7: "MixingPump",
                        8: "PumpFromTankToGutters",
                        9: "SprinklerA",
                        10: "SprinklerB",
                        11: "PumpFromCollectorTrayToTank"
                    }
                    
                    # Update relay status array
                    data["relays"]["relayone"]["RELAYONE"]["RELAYONE"] = relay_instance.relay_statuses
                    
                    # Update relay metrics points
                    for port, status in enumerate(relay_instance.relay_statuses):
                        device_name = relay_mapping.get(port, "none")
                        data["data"]["relay_metrics"]["measurements"]["points"].append({
                            "tags": {
                                "relay_board": "relayone",
                                "port_index": port,
                                "port_type": "assigned" if device_name != "none" else "unassigned",
                                "device": device_name
                            },
                            "fields": {
                                "status": status,
                                "is_assigned": device_name != "none",
                                "raw_status": status
                            },
                            "timestamp": datetime.now().isoformat()
                        })

            # Save to file
            with open(self.sensor_data_file, 'w') as f:
                json.dump(data, f, indent=2)
                
            logger.debug("Sensor data saved successfully")
        except Exception as e:
            logger.error(f"Error saving sensor data: {e}")

    def _direct_stop_sprinklers(self):
        """Direct method to stop sprinklers - called by the scheduler job"""
        try:
            logger.info("Scheduler job triggered to stop sprinklers")
            from src.sensors.Relay import Relay
            relay = Relay()
            if relay:
                # First check if sprinklers are actually on
                logger.info("Checking sprinkler state before turning off")
                # Then, forcefully turn them off
                relay.set_sprinklers(False)
                logger.info("Sprinklers turned off by scheduler job")
                
                # Double check: Clean up any other sprinkler jobs to avoid conflicts
                try:
                    if hasattr(self.scheduler, 'scheduler'):
                        for job_id in ['immediate_sprinkler_stop', 'startup_sprinkler_stop', 
                                      'scheduled_sprinkler_stop', 'config_sprinkler_stop']:
                            if job_id != 'config_sprinkler_stop':  # Don't remove the current job
                                try:
                                    self.scheduler.scheduler.remove_job(job_id)
                                    logger.info(f"Removed additional sprinkler job with ID: {job_id}")
                                except Exception:
                                    # Job might not exist
                                    pass
                except Exception as e:
                    logger.warning(f"Error cleaning up additional sprinkler jobs: {e}")
            else:
                logger.error("Failed to get relay instance in scheduler job")
        except Exception as e:
            logger.error(f"Error in _direct_stop_sprinklers: {e}")
            logger.exception("Full exception details:")
            
    def _log_all_scheduler_jobs(self):
        """Log all currently scheduled jobs for debugging"""
        try:
            if hasattr(self.scheduler, 'scheduler'):
                jobs = self.scheduler.scheduler.get_jobs()
                logger.info(f"==== CURRENT SCHEDULER JOBS ({len(jobs)}) ====")
                for job in jobs:
                    run_time = job.next_run_time.strftime('%H:%M:%S') if job.next_run_time else "None"
                    logger.info(f"Job ID: {job.id}, Next run: {run_time}, Function: {job.func}")
                logger.info("=======================================")
            else:
                logger.warning("Could not access scheduler to list jobs")
        except Exception as e:
            logger.error(f"Error listing scheduler jobs: {e}")

    def _create_backup_sprinkler_timer(self, duration_seconds):
        """Create a backup thread-based timer to stop sprinklers"""
        try:
            logger.info(f"Setting up backup thread to stop sprinklers in {duration_seconds} seconds")
            import threading
            
            def stop_sprinklers_thread():
                logger.info(f"Backup thread-based sprinkler timer started - will stop in {duration_seconds} seconds")
                time.sleep(duration_seconds)
                try:
                    logger.info("Backup thread timer elapsed - turning off sprinklers now")
                    # Create a new relay instance within this thread to ensure a fresh connection
                    from src.sensors.Relay import Relay
                    relay = Relay()
                    if relay:
                        relay.set_sprinklers(False)
                        logger.info("Sprinklers turned off by backup thread timer")
                    else:
                        logger.error("Failed to get relay instance in backup timer thread")
                except Exception as e:
                    logger.error(f"Error turning off sprinklers in backup timer thread: {e}")
                    logger.exception("Full thread exception details:")
            
            # Start the timer thread
            stop_thread = threading.Thread(target=stop_sprinklers_thread)
            stop_thread.daemon = True
            stop_thread.start()
            logger.info(f"Backup sprinkler stop thread started with ID: {stop_thread.ident}")
            return True
        except Exception as e:
            logger.error(f"Error creating backup sprinkler timer: {e}")
            logger.exception("Full exception details:")
            return False

if __name__ == "__main__":
    try:
        controller = RippleController()
        # Start the main control loop
        controller.start()
    except Exception as e:
        logger.error(f"Error starting Ripple controller: {e}")
        logger.exception("Full exception details:") 