#!/usr/bin/env python3

import os
import sys
import time
import logging
from typing import Dict, List, Optional, Union, Any

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

logger = globals.logger

class RippleController:
    def __init__(self):
        """Initialize the Ripple controller."""
        self.water_level_sensors = {}  # Dict to store water level sensor instances
        self.relays = {}  # Dict to store relay instances
        self.sensor_targets = {}  # Dict to store sensor target values
        self.initialize_sensors()
        self.load_sensor_targets()

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
            import configparser
            config = configparser.ConfigParser()
            config.read('device.conf')
            
            # Load pH targets
            ph_target = config.get('pH', 'ph_target').split(',')[1].strip()
            ph_deadband = config.get('pH', 'ph_deadband').split(',')[1].strip()
            ph_min = config.get('pH', 'ph_min').split(',')[1].strip()
            ph_max = config.get('pH', 'ph_max').split(',')[1].strip()
            
            # Load EC targets
            ec_target = config.get('EC', 'ec_target').split(',')[1].strip()
            ec_deadband = config.get('EC', 'ec_deadband').split(',')[1].strip()
            ec_min = config.get('EC', 'ec_min').split(',')[1].strip()
            ec_max = config.get('EC', 'ec_max').split(',')[1].strip()
            
            # Load Water Level targets
            water_level_target = config.get('WaterLevel', 'water_level_target').split(',')[1].strip()
            water_level_deadband = config.get('WaterLevel', 'water_level_deadband').split(',')[1].strip()
            water_level_min = config.get('WaterLevel', 'water_level_min').split(',')[1].strip()
            water_level_max = config.get('WaterLevel', 'water_level_max').split(',')[1].strip()
            
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

    def run_main_loop(self):
        """Main loop for the Ripple controller."""
        """Main loop for the Ripple controller."""
        logger.info("Starting main control loop")
        try:
            while True:
                # Get data from all sensors
                self.update_sensor_data()
                
                # Process any pending commands or events
                self.process_events()
                
                # Wait for next cycle
                time.sleep(10)  # 2 second interval between sensor readings
                
        except KeyboardInterrupt:
            logger.info("Main loop interrupted by user")
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            logger.exception("Full exception details:")
            
    def update_sensor_data(self):
        """Update data from all connected sensors."""
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
            
            

if __name__ == "__main__":
    try:
        controller = RippleController()
        # Start the main control loop
        controller.run_main_loop()
    except Exception as e:
        logger.error(f"Error starting Ripple controller: {e}")
        logger.exception("Full exception details:") 