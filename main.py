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
from datetime import datetime

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
        
    def on_modified(self, event):
        if event.src_path == self.controller.config_file:
            logger.info("Configuration file modified, reloading settings")
            self.controller.reload_configuration()
        elif event.src_path == os.path.abspath('config/action.json'):
            logger.info("Action file modified, processing new actions")
            self.process_actions()
            
    def process_actions(self):
        try:
            # Read the action file
            with open('config/action.json', 'r') as f:
                new_actions = json.load(f)
                
            # Check if actions are different from last state
            if new_actions != self.last_action_state:
                logger.info(f"New actions detected: {new_actions}")
                
                # Map API field names to relay names
                relay_mapping = {
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
                
                # Process each action
                for action, state in new_actions.items():
                    relay_name = relay_mapping.get(action)
                    if relay_name:
                        logger.info(f"Setting {relay_name} to {state}")
                        # Get relay instance
                        relay_instance = Relay()
                        if relay_instance:
                            relay_instance.set_relay(relay_name, state)
                        else:
                            logger.warning(f"Failed to get relay instance for {relay_name}")
                    else:
                        logger.warning(f"Unknown action: {action}")
                
                # Update last state
                self.last_action_state = new_actions.copy()
                
                # Clear the action file
                with open('config/action.json', 'w') as f:
                    json.dump({}, f)
                    
                logger.info("Actions processed and file cleared")
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
        self.config = configparser.ConfigParser()
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

    def reload_configuration(self):
        """Reload configuration from device.conf"""
        try:
            # Reload sensor targets
            self.load_sensor_targets()
            
            # Update scheduler configuration
            self.scheduler.update_configuration('MIXING', 'mixing_interval', 
                self.config.get('MIXING', 'mixing_interval').split(',')[0])
            self.scheduler.update_configuration('MIXING', 'mixing_duration', 
                self.config.get('MIXING', 'mixing_duration').split(',')[0])
            self.scheduler.update_configuration('MIXING', 'trigger_mixing_duration', 
                self.config.get('MIXING', 'trigger_mixing_duration').split(',')[0])
                
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
                
            logger.info("Configuration reloaded successfully")
        except Exception as e:
            logger.error(f"Error reloading configuration: {e}")

    def start(self):
        """Start the Ripple controller"""
        try:
            logger.info("Starting Ripple controller")
            self.scheduler.start()
            self.run_main_loop()
        except Exception as e:
            logger.error(f"Error starting Ripple controller: {e}")
            self.shutdown()
            
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
            # Check pH values
            if ph_statuses:
                ph_targets = self.sensor_targets['pH']
                for sensor_name, ph_value in ph_statuses.items():
                    if ph_value < ph_targets['min'] or ph_value > ph_targets['max']:
                        logger.warning(f"pH sensor {sensor_name} value {ph_value} is outside safe range ({ph_targets['min']}-{ph_targets['max']})")
                    elif abs(ph_value - ph_targets['target']) > ph_targets['deadband']:
                        logger.info(f"pH sensor {sensor_name} value {ph_value} is outside target range ({ph_targets['target']}±{ph_targets['deadband']})")
            
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
            
            # Note: DO sensor checking is commented out since DO readings are currently disabled
            # if do_statuses:
            #     for sensor_name, do_value in do_statuses.items():
            #         if do_value < 0 or do_value > 15:
            #             logger.warning(f"DO sensor {sensor_name} value {do_value} is outside safe range (0-15)")
            #         elif abs(do_value - 10) > 0.1:  # Check against deadband
            #             logger.info(f"DO sensor {sensor_name} value {do_value} is outside target range (10±0.1)")
                    
        except Exception as e:
            logger.error(f"Error checking sensor ranges: {e}")
            
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

if __name__ == "__main__":
    try:
        controller = RippleController()
        # Start the main control loop
        controller.start()
    except Exception as e:
        logger.error(f"Error starting Ripple controller: {e}")
        logger.exception("Full exception details:") 