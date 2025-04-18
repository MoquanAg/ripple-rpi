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
        self.initialize_sensors()

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
            # Update water level sensor readings
            water_levels = WaterLevel.get_statuses_async()
            if water_levels:
                logger.debug(f"Water levels: {water_levels}")
            
            # Update relay states
            relay_instance = Relay()
            if relay_instance:
                relay_instance.get_status()
                if relay_instance.relay_statuses:
                    logger.debug(f"Relay states: {relay_instance.relay_statuses}")
            
            # Update DO sensor readings
            # do_statuses = DO.get_statuses_async()
            # if do_statuses:
            #     logger.debug(f"DO sensor readings: {do_statuses}")
            
            # Update pH sensor readings
            ph_statuses = pH.get_statuses_async()
            if ph_statuses:
                logger.debug(f"pH sensor readings: {ph_statuses}")
            
            # Update EC sensor readings
            ec_statuses = EC.get_statuses_async()
            if ec_statuses:
                logger.debug(f"EC sensor readings: {ec_statuses}")
                    
        except Exception as e:
            logger.error(f"Error updating sensor data: {e}")
            
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