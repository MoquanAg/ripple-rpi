#!/usr/bin/env python3

import os
import sys
import time
import threading
import logging
import json
from typing import Dict, List, Optional, Union, Any
import configparser
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from datetime import datetime, timedelta

# MOQ-98: Process-wide singleton debounce state for ConfigFileHandler.
# The module may be imported from multiple paths (e.g. 'main' vs 'src.main'),
# creating separate module-level namespaces. Using sys.modules ensures a single
# debounce gate across all instances in the process.
import sys
if not hasattr(sys, '_config_debounce_lock'):
    sys._config_debounce_lock = threading.Lock()
    sys._config_last_event_time = {}
    sys._CONFIG_DEBOUNCE_SECONDS = 1.0

# Add the src directory to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, 'src')
sys.path.append(src_dir)

import src.globals as globals
globals.start_scheduler()
import src.helpers as helpers
from src.sensors.water_level import WaterLevel
from src.sensors.Relay import Relay
from src.sensors.DO import DO
from src.sensors.pH import pH
from src.sensors.ec import EC
from src.lumina_logger import GlobalLogger
# Removed old RippleScheduler - now using simplified controllers

logger = GlobalLogger("RippleController", log_prefix="ripple_").logger

class ConfigFileHandler(FileSystemEventHandler):
    """
    File system event handler for monitoring configuration file changes.

    Monitors the device configuration file (device.conf) and action file (action.json)
    for modifications and triggers appropriate reloading and processing operations.
    Implements debouncing to prevent duplicate event processing and change detection
    to identify specific configuration sections that were modified.
    """
    def __init__(self, controller):
        self.controller = controller
        self.last_action_state = {}
        self.last_config_state = {}  # Store the last known state of the config file
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
                        
                logger.debug(f"[WATCHDOG] Loaded current config state with {len(self.last_config_state)} sections")
                # Debug: Log sprinkler section for monitoring
                if 'Sprinkler' in self.last_config_state:
                    logger.debug(f"[WATCHDOG] Sprinkler section loaded: {dict(self.last_config_state['Sprinkler'])}")
        except Exception as e:
            logger.error(f"Error loading current config state: {e}")
            logger.exception("Full exception details:")
        
    def on_modified(self, event):
        """
        Handle file modification events from the file system monitor.
        
        Processes file modification events for device.conf and action.json files,
        implementing debouncing and change detection to trigger appropriate
        reloading and processing operations.
        
        Args:
            event: FileSystemEvent object containing event details
            
        Note:
            - Docstring created by Claude 3.5 Sonnet on 2024-09-22
            - Implements debouncing to prevent duplicate event processing
            - Detects changes in device.conf configuration sections
            - Processes action.json for manual command execution
            - Triggers selective configuration reloading based on changes
            - Updates internal state tracking for future comparisons
        """
        try:
            # Normalize paths for comparison
            config_file_path = os.path.abspath(self.controller.config_file)
            action_file_path = os.path.abspath(os.path.join(self.controller.config_dir, 'action.json'))
            event_path = os.path.abspath(event.src_path)

            # MOQ-98: Use a single debounce key for config-dir events.
            # sed -i fires bursts of events (temp file, directory, rename) at the same
            # millisecond. Using one key ensures only the first event in a burst is
            # processed, and a threading lock makes the check-and-update atomic.
            if event_path == action_file_path:
                debounce_key = 'action.json'
            else:
                debounce_key = 'device.conf'

            with sys._config_debounce_lock:
                current_time = time.time()
                if debounce_key in sys._config_last_event_time:
                    time_since_last = current_time - sys._config_last_event_time[debounce_key]
                    if time_since_last < sys._CONFIG_DEBOUNCE_SECONDS:
                        logger.debug(f"Ignoring duplicate event for {debounce_key} ({event_path}) - {time_since_last:.4f}s since last")
                        return
                sys._config_last_event_time[debounce_key] = current_time

            logger.info(f"File modified: {event_path} (debounce key: {debounce_key})")

            # Check if device.conf was modified (direct event or any config-dir event
            # from sed -i which uses temp+rename instead of in-place write)
            if debounce_key == 'device.conf':
                # Wait for sed -i rename to complete before reading the file
                time.sleep(0.2)

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

            elif debounce_key == 'action.json':
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
            
            logger.debug(f"[WATCHDOG] Checking {len(current_config.sections())} sections against {len(self.last_config_state)} stored sections")
            
            # Check for new or modified sections
            for section in current_config.sections():
                # If this is a new section
                if section not in self.last_config_state:
                    logger.info(f"[WATCHDOG] New section detected: {section}")
                    changed_sections.add(section)
                    continue
                
                # Check for modified keys in existing sections
                for key, value in current_config[section].items():
                    if key not in self.last_config_state[section]:
                        logger.info(f"[WATCHDOG] New key detected in {section}: {key} = {value}")
                        changed_sections.add(section)
                        break
                    elif self.last_config_state[section][key] != value:
                        logger.info(f"[WATCHDOG] Changed value in {section}.{key}: '{self.last_config_state[section][key]}' -> '{value}'")
                        changed_sections.add(section)
                        break
            
            # Check for deleted sections
            for section in self.last_config_state:
                if section not in current_config.sections():
                    logger.info(f"[WATCHDOG] Deleted section detected: {section}")
                    changed_sections.add(section)
            
            if changed_sections:
                logger.info(f"[WATCHDOG] Total changed sections: {changed_sections}")
            else:
                logger.debug(f"[WATCHDOG] No changes detected between stored and current config")
            
            return changed_sections
            
        except Exception as e:
            logger.error(f"Error identifying changed sections: {e}")
            logger.exception("Full exception details:")
            return set()  # Return empty set if there's an error
    
    def process_actions(self):
        try:
            # Check if file exists and is not empty before trying to read it
            if not os.path.exists('config/action.json') or os.path.getsize('config/action.json') == 0:
                logger.debug("Action file does not exist or is empty")
                return

            # Read the action file
            try:
                with open('config/action.json', 'r') as f:
                    file_content = f.read().strip()
                    if not file_content:
                        logger.debug("Action file is empty")
                        return
                    new_actions = json.loads(file_content)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in action file: {e}")
                # Try to reset the file to empty JSON object
                with open('config/action.json', 'w') as f:
                    json.dump({}, f)
                return

            # Skip processing if actions is empty dict (file was cleared)
            # This prevents spurious events from file clearing
            if not new_actions:
                logger.debug("Action file contains empty dict, nothing to process")
                return

            # Check if actions are different from last state
            if new_actions != self.last_action_state:
                logger.info(f"New actions detected: {new_actions}")

                # Get relay instance first
                relay_instance = Relay()
                if not relay_instance:
                    logger.warning("Failed to get relay instance, cannot process actions")
                    return

                # NOTE: File clearing moved to AFTER processing to prevent action loss on crash
                
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

                # Re-check file before clearing to handle concurrent requests
                try:
                    with open('config/action.json', 'r') as f:
                        current_content = json.load(f)
                    # Only clear if no new actions arrived during processing
                    if current_content == new_actions or not current_content:
                        with open('config/action.json', 'w') as f:
                            json.dump({}, f)
                        logger.info("Action file cleared after successful processing")
                    else:
                        logger.info("New actions detected during processing, will process next cycle")
                except Exception as e:
                    logger.error(f"Error checking/clearing action file: {e}")

                logger.info("All actions processed")
            else:
                logger.debug("No new actions detected")
                
        except Exception as e:
            logger.error(f"Error processing actions: {e}")
            logger.exception("Full exception details:")

class RippleController:
    """
    Main controller class for the Ripple fertigation system.
    
    Orchestrates the entire fertigation control system including sensor management,
    relay control, scheduling, configuration handling, and system monitoring. Acts
    as the central coordinator for all system components and provides unified
    control interfaces for automated and manual operations.
    
    Features:
    - Multi-sensor management (pH, EC, DO, Water Level)
    - Relay control system for pumps, valves, and sprinklers
    - Automated scheduling for nutrient dosing and irrigation
    - Configuration file monitoring and hot-reloading
    - Action file processing for manual commands
    - System health monitoring and logging
    - Data persistence and sensor data management
    
    System Components:
    - Sensor Management: pH, EC, DO, Water Level sensors with Modbus communication
    - Relay Control: Nutrient pumps, pH pumps, valves, sprinklers, mixing pumps
    - Scheduling: Automated nutrient dosing, pH adjustment, mixing cycles
    - Configuration: Device configuration monitoring and reloading
    - Actions: Manual command processing and relay control
    
    Data Flow:
    1. Configuration monitoring detects changes in device.conf and action.json
    2. Sensor data collection through Modbus communication
    3. Target value comparison and control decisions
    4. Relay activation based on control logic
    5. Scheduling system manages automated operations
    6. Data persistence and logging for system monitoring
    
    Args:
        None
        
    Note:
        - Docstring created by Claude 3.5 Sonnet on 2024-09-22
        - Implements comprehensive fertigation control system
        - Uses file system monitoring for configuration changes
        - Coordinates multiple sensor and actuator subsystems
        - Provides both automated and manual control interfaces
        - Includes extensive error handling and logging
    """
    # Maps PLUMBING config keys to relay device names for startup configuration.
    PLUMBING_STARTUP_DEVICES = {
        'ValveOutsideToTank_on_at_startup': 'ValveOutsideToTank',
        'ValveTankToOutside_on_at_startup': 'ValveTankToOutside',
        'PumpFromTankToGutters_on_at_startup': 'PumpFromTankToGutters',
        'MixingPump_on_at_startup': 'MixingPump',
        'PumpFromCollectorTrayToTank_on_at_startup': 'PumpFromCollectorTrayToTank',
        'LiquidCoolingPumpAndFan_on_at_startup': 'LiquidCoolingPumpAndFan',
        'ValveCO2_on_at_startup': 'ValveCO2',
    }

    def __init__(self, enable_file_watcher=True):
        """Initialize the Ripple controller.

        Args:
            enable_file_watcher: If True, start watchdog observer for config/action files.
                Set to False when only hardware access is needed (e.g. from server.py).
        """
        self._enable_file_watcher = enable_file_watcher
        self.water_level_sensors = {}  # Dict to store water level sensor instances
        self.relays = {}  # Dict to store relay instances
        self.sensor_targets = {}  # Dict to store sensor target values
        # Removed old RippleScheduler - now using simplified controllers
        
        # Initialize simplified sprinkler controller
        from src.simplified_sprinkler_controller import get_sprinkler_controller
        from src.simplified_nutrient_controller import get_nutrient_controller
        from src.simplified_mixing_controller import get_mixing_controller
        from src.simplified_ph_controller import get_ph_controller
        from src.simplified_water_level_controller import get_water_level_controller
        self.sprinkler_controller = get_sprinkler_controller()
        self.nutrient_controller = get_nutrient_controller()
        self.mixing_controller = get_mixing_controller()
        self.ph_controller = get_ph_controller()
        self.water_level_controller = get_water_level_controller()
        
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
        self.apply_plumbing_startup_configuration()
        self.apply_sprinkler_startup_configuration()

        # MOQ-96: Initialize recurring sprinkler schedule
        # apply_sprinkler_startup_configuration only toggles the relay;
        # we must also start the scheduling chain so cycles continue.
        self.initialize_sprinkler_scheduling()

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
        
        # Initialize watchdog observer (only when enabled and only once per process)
        if self._enable_file_watcher and not getattr(sys, '_config_observer_started', False):
            self.event_handler = ConfigFileHandler(self)
            self.observer = Observer()
            self.observer.schedule(self.event_handler, self.config_dir, recursive=False)
            self.observer.start()
            sys._config_observer_started = True
            logger.info(f"Configuration and action file monitoring started for directory: {self.config_dir}")
        else:
            self.event_handler = None
            self.observer = None
            if not self._enable_file_watcher:
                logger.info("File watcher disabled for this controller instance")
            else:
                logger.info(f"Config file monitoring already active — skipping duplicate observer")

    def _time_to_seconds(self, time_str):
        """Convert HH:MM:SS format to seconds"""
        hours, minutes, seconds = map(int, time_str.split(':'))
        return hours * 3600 + minutes * 60 + seconds

    def initialize_sensors(self):
        """Initialize all sensors from configuration with proper sequencing."""
        try:
            logger.info("[STARTUP] Beginning sequential sensor initialization")
            
            # Initialize water level sensors first
            logger.info("[STARTUP] Initializing water level sensors...")
            WaterLevel.load_all_sensors()
            time.sleep(0.5)  # Allow time for initialization to complete
            
            # Initialize relays - create a single instance which will load addresses
            logger.info("[STARTUP] Initializing relay system...")
            Relay()
            time.sleep(0.5)  # Allow time for relay status requests to complete
            
            # Initialize pH sensors with delay
            logger.info("[STARTUP] Initializing pH sensors...")
            pH.load_all_sensors()
            time.sleep(0.5)  # Critical delay to prevent bus contention
            
            # Initialize EC sensors with delay
            logger.info("[STARTUP] Initializing EC sensors...")
            EC.load_all_sensors()
            time.sleep(0.5)  # Critical delay to prevent bus contention
            
            # Initialize DO sensors (currently disabled)
            # logger.info("[STARTUP] Initializing DO sensors...")
            # DO.load_all_sensors()
            # time.sleep(0.5)
            
            logger.info("[STARTUP] All sensors initialized successfully with proper sequencing")
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

    def apply_sprinkler_startup_configuration(self):
        """Apply sprinkler_on_at_startup operational value to relay hardware on startup."""
        try:
            logger.info("[STARTUP] Checking sprinkler_on_at_startup configuration...")
            
            if not os.path.exists(self.config_file):
                logger.warning(f"Config file {self.config_file} does not exist")
                return
                
            self.config.read(self.config_file)
            
            if not self.config.has_section('Sprinkler'):
                logger.info("No Sprinkler section found in config - skipping sprinkler startup configuration")
                return
            
            if not self.config.has_option('Sprinkler', 'sprinkler_on_at_startup'):
                logger.info("No sprinkler_on_at_startup option found - skipping sprinkler startup configuration")
                return
            
            # Get operational value (second value)
            operational_value = self._parse_config_value('Sprinkler', 'sprinkler_on_at_startup', preferred_index=1)
            
            # Convert string boolean to actual boolean
            if isinstance(operational_value, str) and operational_value.lower() in ('true', 'false'):
                startup_enabled = operational_value.lower() == 'true'
            else:
                startup_enabled = bool(operational_value)
            
            logger.info(f"[STARTUP] sprinkler_on_at_startup operational value: {startup_enabled}")
            
            # Get relay instance
            relay = Relay()
            if not relay:
                logger.warning("No relay hardware available - cannot apply sprinkler startup configuration")
                return
                
            # Apply startup configuration to hardware
            if startup_enabled:
                logger.info("[STARTUP] Turning ON sprinklers due to sprinkler_on_at_startup = true")
                relay.set_sprinklers(True)
                logger.info("[STARTUP] Sprinklers turned ON successfully")
            else:
                logger.info("[STARTUP] Sprinklers remain OFF due to sprinkler_on_at_startup = false")
                # Explicitly turn off to ensure clean state
                relay.set_sprinklers(False)
                logger.info("[STARTUP] Sprinklers explicitly turned OFF")
            
            logger.info("[STARTUP] Sprinkler startup configuration applied successfully")
            
        except Exception as e:
            logger.error(f"Error applying sprinkler startup configuration: {e}")
            logger.exception("Full exception details:")

    def initialize_sprinkler_scheduling(self):
        """Initialize the recurring sprinkler scheduling chain on startup (MOQ-96)."""
        try:
            from src.sprinkler_static import is_sprinkler_scheduling_enabled, get_sprinkler_config, parse_duration

            if not is_sprinkler_scheduling_enabled():
                logger.info("[STARTUP] Sprinkler scheduling disabled - skipping schedule init")
                return

            on_duration_str, wait_duration_str = get_sprinkler_config()
            on_seconds = parse_duration(on_duration_str)

            if on_seconds <= 0:
                logger.info("[STARTUP] Sprinkler duration is 0 - skipping schedule init")
                return

            # Check if sprinkler_on_at_startup is true — if so, start a cycle now
            # (the relay was already toggled by apply_sprinkler_startup_configuration)
            startup_enabled = False
            if self.config.has_option('Sprinkler', 'sprinkler_on_at_startup'):
                val = self._parse_config_value('Sprinkler', 'sprinkler_on_at_startup', 1)
                startup_enabled = isinstance(val, str) and val.lower() == 'true'

            if startup_enabled:
                # Relay is already ON, start the controller cycle (schedules stop + next)
                self.sprinkler_controller.start_sprinkler_cycle()
                logger.info("[STARTUP] Sprinkler scheduling chain started (on_at_startup=true)")
            else:
                # Relay is OFF, schedule the first cycle after wait_duration
                from src.sprinkler_static import schedule_next_sprinkler_cycle_static
                schedule_next_sprinkler_cycle_static()
                logger.info("[STARTUP] Next sprinkler cycle scheduled (on_at_startup=false)")
        except Exception as e:
            logger.error(f"Error initializing sprinkler scheduling: {e}")

    def apply_plumbing_startup_configuration(self):
        """Apply plumbing startup configuration to relay hardware.

        Iterates PLUMBING_STARTUP_DEVICES and sets each relay using the
        operational (second) value from the PLUMBING config section.
        """
        try:
            logger.info("[STARTUP] Checking plumbing startup configuration...")

            if not os.path.exists(self.config_file):
                logger.warning(f"Config file {self.config_file} does not exist")
                return

            self.config.read(self.config_file)

            if not self.config.has_section('PLUMBING'):
                logger.info("No PLUMBING section found in config - skipping plumbing startup configuration")
                return

            # Get relay instance
            relay = Relay()
            if not relay:
                logger.warning("No relay hardware available - cannot apply plumbing startup configuration")
                return

            for config_key, device_name in self.PLUMBING_STARTUP_DEVICES.items():
                if not self.config.has_option('PLUMBING', config_key):
                    logger.info(f"No {config_key} option found - skipping")
                    continue

                # Get operational value (second value)
                operational_value = self._parse_config_value('PLUMBING', config_key, preferred_index=1)

                # Convert string boolean to actual boolean
                if isinstance(operational_value, str) and operational_value.lower() in ('true', 'false'):
                    startup_enabled = operational_value.lower() == 'true'
                else:
                    startup_enabled = bool(operational_value)

                logger.info(f"[STARTUP] {config_key} operational value: {startup_enabled}")

                # Apply startup configuration to hardware
                try:
                    relay.set_relay(device_name, startup_enabled)
                    state_str = "ON" if startup_enabled else "OFF"
                    logger.info(f"[STARTUP] {device_name} turned {state_str} due to {config_key} = {str(startup_enabled).lower()}")
                except Exception as e:
                    logger.error(f"Error applying {config_key} to hardware: {e}")

            logger.info("[STARTUP] Plumbing startup configuration applied successfully")

        except Exception as e:
            logger.error(f"Error applying plumbing startup configuration: {e}")
            logger.exception("Full exception details:")

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
                    # First, ensure mixing pump is turned off before doing anything else
                    # This guarantees that changing any mixing setting will always reset the mixing state
                    try:
                        from src.sensors.Relay import Relay
                        relay = Relay()
                        if relay:
                            relay.set_mixing_pump(False)
                            logger.info("Mixing pump turned off as part of configuration change procedure")
                    except Exception as e:
                        logger.error(f"Error turning off mixing pump: {e}")
                        
                    # Now update the configuration values using operational values (second value)
                    mixing_interval = self._parse_config_value('Mixing', 'mixing_interval', 1)
                    mixing_duration = self._parse_config_value('Mixing', 'mixing_duration', 1)
                    trigger_mixing_duration = self._parse_config_value('Mixing', 'trigger_mixing_duration', 1)
                    
                    # Configuration is automatically reloaded by individual controllers
                    # No need to explicitly update configuration as simplified controllers read config directly
                    
                    # Only proceed to potentially turning it back on if not in an error state
                    try:
                        # Stop any current mixing cycle first
                        try:
                            self.mixing_controller.stop_current_cycle()
                            logger.info("[CONFIG CHANGE] Stopped current mixing cycle")
                        except Exception as e:
                            logger.warning(f"[CONFIG CHANGE] Error stopping mixing cycle: {e}")
                            
                        # Get mixing duration - USING THE PARSED VALUE
                        logger.info(f"Using parsed mixing_duration: '{mixing_duration}'")
                        
                        mixing_seconds = self._time_to_seconds(mixing_duration)
                        logger.info(f"[CONFIG CHANGE] Parsed mixing duration: {mixing_duration} = {mixing_seconds} seconds")
                        
                        # Only activate the mixing pump if duration is positive
                        if mixing_seconds > 0:
                            logger.info(f"[CONFIG CHANGE] Mixing duration > 0 ({mixing_duration}), starting mixing cycle")
                            # Use simplified mixing controller
                            try:
                                self.mixing_controller.start_mixing_cycle()
                                logger.info("[CONFIG CHANGE] Successfully started mixing cycle with new configuration")
                            except Exception as e:
                                logger.error(f"[CONFIG CHANGE] Error starting mixing cycle: {e}")
                        else:
                            logger.info(f"[CONFIG CHANGE] Mixing duration is zero ({mixing_duration}), keeping pump off")
                            
                    except Exception as e:
                        logger.error(f"[CONFIG CHANGE] Error during mixing configuration change: {e}")
                        logger.exception("Full exception details:")
                            
                    logger.info("Mixing configuration updated")
                
                elif section == 'NutrientPump':
                    # Parse using the second value (operational value) if available
                    nutrient_on_duration = self._parse_config_value('NutrientPump', 'nutrient_pump_on_duration', 1)
                    nutrient_wait_duration = self._parse_config_value('NutrientPump', 'nutrient_pump_wait_duration', 1)
                    ph_on_duration = self._parse_config_value('NutrientPump', 'ph_pump_on_duration', 1)
                    ph_wait_duration = self._parse_config_value('NutrientPump', 'ph_pump_wait_duration', 1)
                    
                    # Configuration is automatically reloaded by individual controllers
                    # No need to explicitly update configuration as simplified controllers read config directly
                    
                    # Initialize Relay connection
                    from src.sensors.Relay import Relay
                    relay = Relay()
                    
                    # Check nutrient pump duration
                    nutrient_seconds = self._time_to_seconds(nutrient_on_duration)
                    
                    if nutrient_seconds == 0:
                        # Turn off nutrient pumps if duration is set to zero
                        if relay:
                            relay.set_nutrient_pumps(False)
                            logger.info("Nutrient pumps turned off due to zero duration configuration")
                            
                            # Stop any current nutrient cycle
                            try:
                                self.nutrient_controller.stop_current_cycle()
                                logger.info("Stopped current nutrient cycle due to zero duration configuration")
                            except Exception as e:
                                logger.info(f"Nutrient cycle stop exception (may be normal): {e}")
                        else:
                            logger.warning("Failed to turn off nutrient pumps: relay not available")
                    
                    # Check pH pump duration
                    ph_seconds = self._time_to_seconds(ph_on_duration)
                    
                    if ph_seconds == 0:
                        # Turn off pH pumps if duration is set to zero
                        if relay:
                            relay.set_ph_plus_pump(False)
                            relay.set_ph_minus_pump(False)
                            logger.info("pH pumps turned off due to zero duration configuration")
                            
                            # Stop any current pH cycle
                            try:
                                self.ph_controller.stop_current_cycle()
                                logger.info("Stopped current pH cycle due to zero duration configuration")
                            except Exception as e:
                                logger.info(f"pH cycle stop exception (may be normal): {e}")
                        else:
                            logger.warning("Failed to turn off pH pumps: relay not available")
                    
                    # Only trigger nutrient cycle check if we're not turning things off
                    if nutrient_seconds > 0:
                        # Schedule nutrient cycle check (don't start immediately to avoid flash)
                        logger.info("Scheduling nutrient cycle check due to NutrientPump config change")
                        # Let the controller handle this in its own timing to avoid unwanted activation
                    
                    logger.info("NutrientPump configuration updated")
                
                elif section == 'Sprinkler':
                    # First, ensure sprinklers are turned off before doing anything else
                    try:
                        from src.sensors.Relay import Relay
                        relay = Relay()
                        if relay:
                            relay.set_sprinklers(False)
                            logger.info("Sprinklers turned off as part of configuration change procedure")
                    except Exception as e:
                        logger.error(f"Error turning off sprinklers: {e}")

                    # Check master toggle: sprinkler_scheduling_enabled
                    scheduling_enabled = True  # Default to enabled for backward compatibility
                    if self.config.has_option('Sprinkler', 'sprinkler_scheduling_enabled'):
                        scheduling_value = self._parse_config_value('Sprinkler', 'sprinkler_scheduling_enabled', 1)
                        if isinstance(scheduling_value, str):
                            scheduling_enabled = scheduling_value.lower() == 'true'
                        else:
                            scheduling_enabled = bool(scheduling_value)
                    logger.info(f"[CONFIG CHANGE] sprinkler_scheduling_enabled: {scheduling_enabled}")

                    if not scheduling_enabled:
                        logger.info("[CONFIG CHANGE] Sprinkler scheduling is DISABLED - stopping all cycles and clearing schedule")
                        try:
                            self.sprinkler_controller.stop_current_cycle()
                            from src.sprinkler_static import stop_sprinkler_schedule
                            stop_sprinkler_schedule()
                        except Exception as e:
                            logger.warning(f"[CONFIG CHANGE] Error stopping sprinkler schedule: {e}")
                        logger.info("Sprinkler configuration updated (scheduling disabled)")
                        continue

                    # Parse new values
                    sprinkler_on_duration = self._parse_config_value('Sprinkler', 'sprinkler_on_duration', 1)
                    sprinkler_wait_duration = self._parse_config_value('Sprinkler', 'sprinkler_wait_duration', 1)
                    sprinkler_on_seconds = self._time_to_seconds(sprinkler_on_duration)

                    # Get old values for comparison (last_config_state still holds pre-change values)
                    old_on_duration = "00:00:00"
                    old_wait_duration = "00:00:00"
                    if self.event_handler and hasattr(self.event_handler, 'last_config_state'):
                        old_sprinkler = self.event_handler.last_config_state.get('Sprinkler', {})
                        old_on_raw = old_sprinkler.get('sprinkler_on_duration', '')
                        old_wait_raw = old_sprinkler.get('sprinkler_wait_duration', '')
                        if ',' in old_on_raw:
                            old_on_duration = old_on_raw.split(',')[1].strip()
                        if ',' in old_wait_raw:
                            old_wait_duration = old_wait_raw.split(',')[1].strip()

                    old_on_seconds = self._time_to_seconds(old_on_duration)
                    old_wait_seconds = self._time_to_seconds(old_wait_duration)
                    new_wait_seconds = self._time_to_seconds(sprinkler_wait_duration)

                    logger.info(f"[CONFIG CHANGE] Sprinkler on_duration: {old_on_duration} -> {sprinkler_on_duration}")
                    logger.info(f"[CONFIG CHANGE] Sprinkler wait_duration: {old_wait_duration} -> {sprinkler_wait_duration}")

                    # Stop any current cycle
                    try:
                        self.sprinkler_controller.stop_current_cycle()
                        logger.info("[CONFIG CHANGE] Stopped current sprinkler cycle")
                    except Exception as e:
                        logger.warning(f"[CONFIG CHANGE] Error stopping sprinkler cycle: {e}")

                    # Sentinel: wait_duration of 99:99:99 or 00:00:00 means "disable scheduling"
                    DISABLE_SENTINEL_SECONDS = self._time_to_seconds("99:99:99")
                    scheduling_disabled_by_wait = (new_wait_seconds == 0 or new_wait_seconds >= DISABLE_SENTINEL_SECONDS)

                    if sprinkler_on_seconds <= 0 or scheduling_disabled_by_wait:
                        reason = "on_duration=0" if sprinkler_on_seconds <= 0 else f"wait_duration={sprinkler_wait_duration} (disabled)"
                        logger.info(f"[CONFIG CHANGE] Sprinkler scheduling OFF: {reason}")
                        try:
                            from src.sprinkler_static import stop_sprinkler_schedule
                            stop_sprinkler_schedule()
                        except Exception as e:
                            logger.warning(f"[CONFIG CHANGE] Error stopping sprinkler schedule: {e}")
                    elif sprinkler_on_seconds > old_on_seconds:
                        # on_duration increased → farmer wants more watering → immediate run
                        logger.info(f"[CONFIG CHANGE] on_duration INCREASED ({old_on_duration} -> {sprinkler_on_duration}), starting immediate sprinkler cycle")
                        try:
                            self.sprinkler_controller.start_sprinkler_cycle()
                        except Exception as e:
                            logger.error(f"[CONFIG CHANGE] Error starting sprinkler cycle: {e}")
                    elif new_wait_seconds < old_wait_seconds:
                        # wait_duration decreased → farmer wants more frequent watering → immediate run
                        logger.info(f"[CONFIG CHANGE] wait_duration DECREASED ({old_wait_duration} -> {sprinkler_wait_duration}), starting immediate sprinkler cycle")
                        try:
                            self.sprinkler_controller.start_sprinkler_cycle()
                        except Exception as e:
                            logger.error(f"[CONFIG CHANGE] Error starting sprinkler cycle: {e}")
                    else:
                        # on_duration unchanged/decreased, wait_duration unchanged/increased → just reschedule
                        logger.info(f"[CONFIG CHANGE] No urgency increase, scheduling next cycle with wait_duration={sprinkler_wait_duration}")
                        try:
                            from src.sprinkler_static import schedule_next_sprinkler_cycle_static
                            schedule_next_sprinkler_cycle_static()
                        except Exception as e:
                            logger.error(f"[CONFIG CHANGE] Error scheduling next sprinkler cycle: {e}")

                    logger.info("Sprinkler configuration updated")
                
                elif section == 'EC':
                    if 'EC' in self.config:
                        need_reload_targets = True
                        logger.info("Scheduling EC check due to EC config change")
                        from src.nutrient_static import schedule_next_nutrient_cycle_static
                        schedule_next_nutrient_cycle_static()
                        logger.info("EC configuration updated")
                
                elif section == 'pH':
                    if 'pH' in self.config:
                        # Configuration is automatically reloaded by individual controllers
                        # No need to explicitly update configuration as simplified controllers read config directly
                        
                        # Update sensor targets
                        need_reload_targets = True
                        
                        # Schedule pH check (don't start immediately to avoid flash)
                        logger.info("Scheduling pH check due to pH config change")
                        # Let the controller handle this in its own timing
                        logger.info("pH configuration updated")
                
                elif section == 'WaterLevel':
                    # Water level targets affect valve control
                    need_reload_targets = True
                    
                    # Trigger immediate water level check
                    logger.info("Triggering immediate water level check due to WaterLevel config change")
                    self.water_level_controller.force_check_now()
                    logger.info("WaterLevel configuration updated")
                
                elif section == 'PLUMBING':
                    # Apply plumbing startup configuration immediately when config changes
                    logger.info("PLUMBING configuration changed, applying startup values to hardware")
                    self.apply_plumbing_startup_configuration()
                    logger.info("PLUMBING configuration updated")
            
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
            
            # Configuration is automatically reloaded by individual controllers
            # The simplified controllers read the configuration files directly
            # No need to explicitly update configuration parameters
            logger.info("Configuration reload completed - simplified controllers will read updated config directly")

            # EC and pH targets are now managed by simplified controllers
            # Controllers will read configuration directly from config files
            logger.info("EC and pH configuration will be read by respective controllers")
                
            logger.info("Full configuration reloaded successfully")
            
            # Trigger immediate checks when configuration changes
            logger.info("Running immediate controller checks due to configuration change...")
            
            # Skip immediate pH and nutrient checks - let controllers run on their own schedules
            try:
                logger.info("Skipping immediate pH/nutrient checks - controllers will run on schedule")
                # Do NOT trigger immediate cycles - this prevents unwanted pump activation
            except Exception as e:
                logger.info(f"Controller trigger exception (may be normal): {e}")
            
            # Trigger immediate water level check
            try:
                self.water_level_controller.force_check_now()
                logger.info("Triggered water level controller check")
            except Exception as e:
                logger.info(f"Water level controller trigger exception (may be normal): {e}")
            
            # Trigger immediate sprinkler check
            try:
                # Get sprinkler on_duration from config
                sprinkler_on_duration = self.config.get('Sprinkler', 'sprinkler_on_duration').split(',')[0]
                sprinkler_on_seconds = self._time_to_seconds(sprinkler_on_duration)
                
                # Only run the sprinkler if the duration is not zero
                if sprinkler_on_seconds > 0:
                    logger.info("Running immediate sprinkler check due to configuration change")
                    self.sprinkler_controller.start_sprinkler_cycle()
                    logger.info("Triggered sprinkler controller check")
                else:
                    logger.info("Sprinkler cycle skipped: zero duration configured")
            except Exception as e:
                logger.info(f"Sprinkler controller trigger exception (may be normal): {e}")
            
            logger.info("Immediate controller checks completed")
            
        except Exception as e:
            logger.error(f"Error reloading configuration: {e}")

    def start(self):
        """Start the Ripple controller"""
        try:
            logger.info("Starting Ripple controller")
            # Old scheduler removed - simplified controllers auto-start

            # Run immediate checks for all systems at startup
            self._run_startup_checks()

            # Write initial status file
            self.write_status_file()
            logger.info("Initial status file written to data/system_status.txt")

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
                self.water_level_controller.force_check_now()
            except Exception as e:
                logger.error(f"[Startup] Error during water level check: {e}")
                
            # 2. Skip initial pH check - pH pumps start OFF at reboot
            try:
                logger.info("[Startup] Skipping initial pH cycle - pH pumps start OFF at reboot")
                # Do NOT call start_ph_cycle() - pH controller will check levels in its own scheduled cycles
            except Exception as e:
                logger.error(f"[Startup] Error during pH cycle check: {e}")
                
            # 3. Skip initial nutrient cycle check - nutrients start OFF at reboot
            try:
                logger.info("[Startup] Skipping initial nutrient cycle - nutrients start OFF at reboot")
                # Do NOT call start_nutrient_cycle() - this causes the brief flash
                # Nutrient controller will check EC levels in its own scheduled cycles
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
                    self.mixing_controller.start_mixing_cycle()
                else:
                    logger.info("[Startup] Mixing pump duration is zero, not activating")
            except Exception as e:
                logger.error(f"[Startup] Error during mixing pump check: {e}")
                
            # 5. Check and activate sprinklers if needed
            try:
                self._activate_sprinklers_on_startup()
                self._activate_nutrient_pumps_on_startup()
                self._activate_mixing_pumps_on_startup()
                self._activate_ph_pumps_on_startup()
                self._activate_water_level_monitoring_on_startup()
            except Exception as e:
                logger.error(f"[Startup] Error during component activation: {e}")
                
            logger.info("==== STARTUP CHECKS AND ACTIVATIONS COMPLETE ====")
            
        except Exception as e:
            logger.error(f"Error running startup checks: {e}")
            logger.exception("Full exception details:")

    def _activate_sprinklers_on_startup(self):
        """Initialize simplified sprinkler system on startup - respects sprinkler_scheduling_enabled and sprinkler_on_at_startup configuration"""
        try:
            logger.info("==== INITIALIZING SIMPLIFIED SPRINKLER SYSTEM ====")
            
            # Check sprinkler configuration exists
            if not self.config.has_section('Sprinkler'):
                logger.info("[Startup] No Sprinkler section found - sprinkler system not started")
                return
            
            # Check master toggle: sprinkler_scheduling_enabled
            scheduling_enabled = True  # Default to enabled for backward compatibility
            if self.config.has_option('Sprinkler', 'sprinkler_scheduling_enabled'):
                scheduling_value = self._parse_config_value('Sprinkler', 'sprinkler_scheduling_enabled', preferred_index=1)
                if isinstance(scheduling_value, str):
                    scheduling_enabled = scheduling_value.lower() == 'true'
                else:
                    scheduling_enabled = bool(scheduling_value)
            
            logger.info(f"[Startup] sprinkler_scheduling_enabled: {scheduling_enabled}")
            
            if not scheduling_enabled:
                logger.info("[Startup] Sprinkler scheduling is DISABLED - no automatic cycles will run")
                return
                
            if not self.config.has_option('Sprinkler', 'sprinkler_on_at_startup'):
                logger.info("[Startup] No sprinkler_on_at_startup option found - sprinkler system not started")
                return
            
            # Get operational value (second value)
            operational_value = self._parse_config_value('Sprinkler', 'sprinkler_on_at_startup', preferred_index=1)
            
            # Convert string boolean to actual boolean
            if isinstance(operational_value, str) and operational_value.lower() in ('true', 'false'):
                startup_enabled = operational_value.lower() == 'true'
            else:
                startup_enabled = bool(operational_value)
            
            logger.info(f"[Startup] sprinkler_on_at_startup operational value: {startup_enabled}")
            
            # Check if sprinkler duration is valid
            sprinkler_on_duration = self._parse_config_value('Sprinkler', 'sprinkler_on_duration', preferred_index=1)
            sprinkler_wait_duration = self._parse_config_value('Sprinkler', 'sprinkler_wait_duration', preferred_index=1)
            
            on_seconds = self._time_to_seconds(sprinkler_on_duration)
            wait_seconds = self._time_to_seconds(sprinkler_wait_duration)
            
            if on_seconds == 0:
                logger.warning("[Startup] Sprinkler duration is 0, not initializing sprinkler system")
                return
                
            if startup_enabled:
                logger.info("[Startup] Starting sprinkler system immediately (enabled at startup)")
                success = self.sprinkler_controller.start_sprinkler_cycle()
                
                if success:
                    logger.info("[Startup] Simplified sprinkler system STARTED (enabled at startup)")
                else:
                    logger.info("[Startup] Sprinkler system not started (duration may be 0 or already running)")
            else:
                logger.info("[Startup] Sprinkler system not started immediately (disabled at startup)")
                
                # Even if not starting immediately, we should schedule the first cycle
                logger.info(f"[Startup] Scheduling first sprinkler cycle to run in {sprinkler_wait_duration}")
                
                # Import and use the static scheduling function
                from src.sprinkler_static import schedule_next_sprinkler_cycle_static
                schedule_next_sprinkler_cycle_static()
                logger.info("[Startup] First sprinkler cycle scheduled successfully")
                
        except Exception as e:
            logger.error(f"Error initializing simplified sprinkler system: {e}")
            logger.exception("Full exception details:")

    def _activate_nutrient_pumps_on_startup(self):
        """Initialize simplified nutrient system on startup with automatic EC-based dosing"""
        try:
            logger.info("==== INITIALIZING SIMPLIFIED NUTRIENT SYSTEM WITH AUTO-DOSING ====")

            # Ensure nutrient pumps are OFF at reboot before starting auto-dosing
            from src.sensors.Relay import Relay
            relay = Relay()
            if relay:
                # Explicitly turn off nutrient pumps at startup
                relay.set_nutrient_pump("A", False)
                relay.set_nutrient_pump("B", False)
                relay.set_nutrient_pump("C", False)
                logger.info("[Startup] Nutrient pumps explicitly set to OFF at reboot")
            else:
                logger.warning("[Startup] No relay available to ensure nutrient pumps are off")

            # Initialize automatic EC-based nutrient dosing schedule
            from src.nutrient_static import initialize_nutrient_schedule
            success = initialize_nutrient_schedule()

            if success:
                logger.info("[Startup] Automatic EC-based nutrient dosing schedule initialized successfully")
            else:
                logger.info("[Startup] Nutrient dosing schedule not started (duration may be 0)")

        except Exception as e:
            logger.error(f"Error initializing simplified nutrient system: {e}")
            logger.exception("Full exception details:")

    def _activate_mixing_pumps_on_startup(self):
        """Initialize simplified mixing system on startup"""
        try:
            logger.info("==== INITIALIZING SIMPLIFIED MIXING SYSTEM ====")
            
            # Use the simplified mixing controller
            success = self.mixing_controller.start_mixing_cycle()
            
            if success:
                logger.info("[Startup] Simplified mixing system started successfully")
            else:
                logger.info("[Startup] Mixing system not started (duration may be 0 or already running)")
                
        except Exception as e:
            logger.error(f"Error initializing simplified mixing system: {e}")
            logger.exception("Full exception details:")

    def _activate_ph_pumps_on_startup(self):
        """Initialize simplified pH system on startup - pH PUMPS START OFF"""
        try:
            logger.info("==== INITIALIZING SIMPLIFIED pH SYSTEM (OFF AT STARTUP) ====")
            
            # NEW BEHAVIOR: Ensure pH pumps are OFF at reboot
            from src.sensors.Relay import Relay
            relay = Relay()
            if relay:
                # Explicitly turn off pH pumps at startup
                relay.set_ph_plus_pump(False)
                relay.set_ph_minus_pump(False)
                logger.info("[Startup] pH pumps explicitly set to OFF at reboot")
            else:
                logger.warning("[Startup] No relay available to ensure pH pumps are off")
                
            # Do NOT call start_ph_cycle() - keep them off  
            logger.info("[Startup] pH system initialized in OFF state (no auto-start)")
                
        except Exception as e:
            logger.error(f"Error initializing simplified pH system: {e}")
            logger.exception("Full exception details:")

    def _activate_water_level_monitoring_on_startup(self):
        """Initialize simplified water level monitoring on startup"""
        try:
            logger.info("==== INITIALIZING SIMPLIFIED WATER LEVEL MONITORING ====")
            
            # Use the simplified water level controller
            success = self.water_level_controller.start_water_level_monitoring()
            
            if success:
                logger.info("[Startup] Simplified water level monitoring started successfully")
            else:
                logger.info("[Startup] Water level monitoring not started (interval may be 0 or already running)")
                
        except Exception as e:
            logger.error(f"Error initializing simplified water level monitoring: {e}")
            logger.exception("Full exception details:")

    def shutdown(self):
        """Shutdown the Ripple controller"""
        try:
            logger.info("Shutting down Ripple controller")
            
            # Shutdown simplified controllers first
            if hasattr(self, 'sprinkler_controller'):
                self.sprinkler_controller.shutdown()
            if hasattr(self, 'nutrient_controller'):
                self.nutrient_controller.shutdown()
            if hasattr(self, 'mixing_controller'):
                self.mixing_controller.shutdown()
            if hasattr(self, 'ph_controller'):
                self.ph_controller.shutdown()
            if hasattr(self, 'water_level_controller'):
                self.water_level_controller.shutdown()
                
            # Old scheduler removed - simplified controllers handle their own shutdown
            if self.observer:
                self.observer.stop()
                self.observer.join(timeout=5)  # Add timeout to prevent indefinite blocking
                if self.observer.is_alive():
                    logger.warning("File observer did not stop cleanly within timeout")
                logger.info("Configuration and action file monitoring stopped")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

    def write_status_file(self):
        """Write human-readable system status to a text file for debugging.

        Creates a status file in the data directory with current system state,
        similar to lumina-edge's scheduled_tasks_main.txt approach.
        
        Reads from saved_sensor_data.json cache (populated by main loop) rather
        than querying sensors directly - avoids creating fresh instances with
        empty data.
        """
        try:
            status_file = os.path.join(self.data_dir, 'system_status.txt')
            sensor_data_file = os.path.join(self.data_dir, 'saved_sensor_data.json')

            # Get current timestamp
            now = datetime.now()
            
            # Load cached sensor data
            cached_data = {}
            try:
                if os.path.exists(sensor_data_file):
                    with open(sensor_data_file, 'r') as f:
                        cached_data = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load cached sensor data: {e}")

            # Collect system status
            lines = []
            lines.append("=" * 60)
            lines.append("RIPPLE SYSTEM STATUS")
            lines.append(f"Generated: {now.strftime('%Y-%m-%d %H:%M:%S')}")
            lines.append("=" * 60)
            lines.append("")

            # Relay states - read from cached data
            lines.append("RELAY STATES:")
            lines.append("-" * 40)
            try:
                relay_metrics = cached_data.get('data', {}).get('relay_metrics', {})
                relay_points = relay_metrics.get('measurements', {}).get('points', [])
                if relay_points:
                    for point in relay_points:
                        device = point.get('tags', {}).get('device', 'none')
                        if device and device != 'none':
                            status = "ON" if point.get('fields', {}).get('status', 0) else "OFF"
                            lines.append(f"  {device}: {status}")
                else:
                    # Fallback: try raw relay array
                    relays = cached_data.get('relays', {})
                    if relays:
                        for name, states in relays.items():
                            if name != 'last_updated' and isinstance(states, list):
                                lines.append(f"  {name}: {states}")
                    else:
                        lines.append("  (No relay data available)")
            except Exception as e:
                lines.append(f"  (Error reading relays: {e})")
            lines.append("")

            # Water level sensors - read from cached data
            lines.append("WATER LEVELS:")
            lines.append("-" * 40)
            try:
                water_data = cached_data.get('data', {}).get('water_metrics', {})
                # Look for water level specific data in the cache
                found_water = False
                for key, value in water_data.items():
                    if 'level' in key.lower() or 'water' in key.lower():
                        measurements = value.get('measurements', {}).get('points', [])
                        for point in measurements:
                            location = point.get('tags', {}).get('location', 'unknown')
                            level = point.get('fields', {}).get('value', 'N/A')
                            lines.append(f"  {location}: {level}%")
                            found_water = True
                if not found_water:
                    lines.append("  (No water level data available)")
            except Exception as e:
                lines.append(f"  (Error reading water levels: {e})")
            lines.append("")

            # pH sensors - read from cached data
            lines.append("PH SENSORS:")
            lines.append("-" * 40)
            try:
                ph_data = cached_data.get('data', {}).get('water_metrics', {}).get('ph', {})
                ph_points = ph_data.get('measurements', {}).get('points', [])
                if ph_points:
                    for point in ph_points:
                        location = point.get('tags', {}).get('location', 'unknown')
                        value = point.get('fields', {}).get('value', 'N/A')
                        temp = point.get('fields', {}).get('temperature', 'N/A')
                        lines.append(f"  {location}: pH {value} (temp: {temp}°C)")
                else:
                    lines.append("  (No pH data available)")
            except Exception as e:
                lines.append(f"  (Error reading pH: {e})")
            lines.append("")

            # EC sensors - read from cached data
            lines.append("EC SENSORS:")
            lines.append("-" * 40)
            try:
                ec_data = cached_data.get('data', {}).get('water_metrics', {}).get('ec', {})
                ec_points = ec_data.get('measurements', {}).get('points', [])
                if ec_points:
                    for point in ec_points:
                        location = point.get('tags', {}).get('location', 'unknown')
                        value = point.get('fields', {}).get('value', 'N/A')
                        tds = point.get('fields', {}).get('tds', 'N/A')
                        temp = point.get('fields', {}).get('temperature', 'N/A')
                        lines.append(f"  {location}: EC {value} mS/cm, TDS {tds} ppm (temp: {temp}°C)")
                else:
                    lines.append("  (No EC data available)")
            except Exception as e:
                lines.append(f"  (Error reading EC: {e})")
            lines.append("")

            # Controller states
            lines.append("CONTROLLER STATES:")
            lines.append("-" * 40)
            try:
                if self.sprinkler_controller:
                    enabled = getattr(self.sprinkler_controller, 'scheduling_enabled', 'N/A')
                    lines.append(f"  Sprinkler scheduling: {'Enabled' if enabled else 'Disabled'}")
                if self.nutrient_controller:
                    lines.append(f"  Nutrient controller: Active")
                if self.ph_controller:
                    lines.append(f"  pH controller: Active")
                if self.mixing_controller:
                    lines.append(f"  Mixing controller: Active")
                if self.water_level_controller:
                    lines.append(f"  Water level controller: Active")
            except Exception as e:
                lines.append(f"  (Error reading controller states: {e})")
            lines.append("")

            # Next update
            lines.append(f"Next status update: ~5 minutes")
            lines.append("=" * 60)

            # Write to file
            with open(status_file, 'w') as f:
                f.write('\n'.join(lines))

            logger.debug(f"Status file updated: {status_file}")

        except Exception as e:
            logger.error(f"Error writing status file: {e}")

    def _check_nutrient_scheduler_health(self):
        """Check if the nutrient scheduler chain is alive, reinitialize if broken"""
        try:
            scheduler = globals.get_scheduler()
            if not scheduler:
                return

            has_start = scheduler.get_job('nutrient_start') is not None
            has_stop = scheduler.get_job('nutrient_stop') is not None

            if not has_start and not has_stop:
                logger.warning("[HEALTH] Nutrient scheduler chain broken - no nutrient_start or nutrient_stop jobs found")
                from src.nutrient_static import initialize_nutrient_schedule
                initialize_nutrient_schedule()
                logger.info("[HEALTH] Nutrient scheduler recovered - chain was broken")
        except Exception as e:
            logger.error(f"[HEALTH] Error checking nutrient scheduler: {e}")

    def run_main_loop(self):
        """Main loop for the Ripple controller"""
        logger.info("Starting main control loop")

        loop_count = 0
        try:
            while True:
                # Get data from all sensors
                self.update_sensor_data()

                # Save sensor data
                self.save_sensor_data()

                # Update status file immediately after sensor data is saved
                # This ensures system_status.txt always reflects latest sensor data
                self.write_status_file()

                # Process any pending commands or events
                self.process_events()

                # Check nutrient scheduler health every ~60s (6 loops * 10s)
                loop_count += 1
                if loop_count % 6 == 0:
                    self._check_nutrient_scheduler_health()

                # Periodic action file check as failsafe (in case watchdog misses events)
                # Runs every loop (10s) - safe because process_actions() has early-exit checks
                try:
                    self.event_handler.process_actions()
                except Exception as e:
                    logger.error(f"Error in periodic action check: {e}")

                # Wait for next cycle
                time.sleep(10)  # 10 second interval between sensor readings

        except KeyboardInterrupt:
            logger.info("Main loop interrupted by user")
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            logger.exception("Full exception details:")
            
    def update_sensor_data(self):
        """Trigger async sensor reads. Individual modules save data via helpers.save_sensor_data()."""
        try:
            WaterLevel.get_statuses_async()
            time.sleep(0.5)

            relay_instance = Relay()
            if relay_instance:
                relay_instance.get_status()
            time.sleep(0.5)

            pH.get_statuses_async()
            time.sleep(0.5)

            EC.get_statuses_async()
        except Exception as e:
            logger.error(f"Error updating sensor data: {e}")
            
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
            # Use the pH controller to run pH correction
            logger.info(f"Triggering automatic pH correction, current pH: {current_ph}")
            self.ph_controller.start_ph_cycle()
            logger.info("pH correction cycle started")
        except Exception as e:
            logger.error(f"Error triggering pH correction: {e}")
            logger.exception("Full exception details:")

    def process_events(self):
        """Process any pending events or commands."""
        # This method can be expanded to handle scheduled tasks,
        # respond to sensor thresholds, etc.
        pass

    def save_sensor_data(self):
        """Update last_updated timestamp in sensor data file.
        Individual sensor/relay modules handle their own data saving via helpers.save_sensor_data()."""
        try:
            helpers.save_sensor_data(["devices"], {
                "last_updated": helpers.datetime_to_iso8601()
            })
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
                
                # Note: Job cleanup now handled by simplified sprinkler controller
                logger.info("Sprinkler job cleanup handled by simplified controller")
            else:
                logger.error("Failed to get relay instance in scheduler job")
        except Exception as e:
            logger.error(f"Error in _direct_stop_sprinklers: {e}")
            logger.exception("Full exception details:")
            
    def _log_all_scheduler_jobs(self):
        """Legacy method - scheduling now handled by simplified controllers"""
        logger.info("_log_all_scheduler_jobs called - scheduling now handled by simplified controllers")
        logger.info("Use individual controller status methods for job information")

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

    def _parse_config_value(self, section, key, preferred_index=1):
        """Parse configuration values that may have comma-separated parts.
        
        Args:
            section (str): Config section name
            key (str): Config key name
            preferred_index (int): Index of value to use (0 for first, 1 for second/operational)
            
        Returns:
            str: Parsed value with whitespace and quotes removed
        """
        try:
            raw_value = self.config.get(section, key)
            
            if ',' in raw_value:
                parts = raw_value.split(',')
                if len(parts) > preferred_index:
                    # Use the preferred index (usually 1 for operational value)
                    value = parts[preferred_index].strip()
                else:
                    # Fall back to first value if preferred index doesn't exist
                    value = parts[0].strip()
            else:
                # No comma, just use the whole value
                value = raw_value.strip()
                
            # Strip any quotes
            value = value.strip('"\'')
            
            logger.info(f"Parsed config value for {section}.{key}: '{raw_value}' -> '{value}' (using index {preferred_index})")
            return value
        except Exception as e:
            logger.error(f"Error parsing config value for {section}.{key}: {e}")
            # Return first part as a fallback
            try:
                return self.config.get(section, key).split(',')[0].strip()
            except Exception:
                return ""

if __name__ == "__main__":
    try:
        controller = RippleController()
        # Start the main control loop
        controller.start()
    except Exception as e:
        logger.error(f"Error starting Ripple controller: {e}")
        logger.exception("Full exception details:") 