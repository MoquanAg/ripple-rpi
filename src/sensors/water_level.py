if __name__ == '__main__':
    from modbus_helpers import *
else:
    from hardware.modbus_helpers import *

import serial
import time
import os, sys
import asyncio

current_dir = os.path.dirname(__file__)
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from lumina_modbus_event_emitter import ModbusResponse

import globals
logger = globals.logger

import math
import helpers

class WaterLevel:

    _instances = {}  # Dictionary to hold multiple instances

    @classmethod
    def load_all_sensors(cls, port='/dev/ttyAMA2'):
        """
        Load and initialize all water level sensors defined in the configuration file.
        Returns True if any sensors were loaded, False otherwise.
        """
        # First check if water level sensor is enabled
        if not globals.HAS_WATER_LEVEL:
            logger.info("Water level sensor is disabled in configuration")
            return False
            
        config = globals.DEVICE_CONFIG_FILE
        
        try:
            if 'SENSORS' in config:
                value = config['SENSORS'].get('WaterLevel')
                if value and not globals.is_invalid_value(value):
                    sensor_id = 'main'
                    instance = cls(sensor_id, port)
                    if instance is not None:
                        logger.info(f"Loaded water level sensor with ID: {sensor_id}")
                        return True
                    else:
                        logger.warning("Failed to initialize water level sensor")
                else:
                    logger.info("Water level sensor is disabled (null/none) in config")
            else:
                logger.info("No 'SENSORS' section found in the configuration file.")
        except Exception as e:
            logger.info(f"Failed to load water level sensors: {e}")
        return False

    @classmethod
    def get_statuses_async(cls):
        """
        Asynchronously get status from all water level sensors.
        """
        if not globals.HAS_WATER_LEVEL:
            return
            
        for _, sensor_instance in WaterLevel._instances.items():
            sensor_instance.get_status_async()
            time.sleep(0.01)  # Small delay between sensors

    def __new__(cls, sensor_id, *args, **kwargs):
        if sensor_id not in cls._instances:
            logger.debug(f"Creating the WaterLevel instance for {sensor_id}.")
            instance = super(WaterLevel, cls).__new__(cls)
            instance.init(sensor_id, *args, **kwargs)  # Initialize the instance
            cls._instances[sensor_id] = instance
        return cls._instances[sensor_id]

    def init(self, sensor_id, port='/dev/ttyAMA2'):
        logger.info(f"Initializing the WaterLevel instance for {sensor_id} in {port}.")
        self.sensor_id = sensor_id
        self.port = port
        self.data_path = globals.SAVED_SENSOR_DATA_PATH
        self.address = 0x27  # Default address from device.conf
        self.ser = serial.Serial()
        self.baud_rate = 9600 
        self.position = "main"
        self.water_level = None
        self.last_updated = None
        self.load_address()

        # Update modbus client initialization
        self.modbus_client = globals.modbus_client
        self.modbus_client.event_emitter.subscribe('WaterLevel', self._handle_response)
        self.pending_commands = {}

    def open_connection(self):
        self.ser = serial.Serial(self.port, self.baud_rate, serial.EIGHTBITS, serial.PARITY_NONE, serial.STOPBITS_ONE)
        
    def close_connection(self):
        self.ser.close()

    def load_address(self):
        config = globals.DEVICE_CONFIG_FILE
        try:
            if 'SENSORS' in config and 'WaterLevel' in config['SENSORS']:
                value = config['SENSORS']['WaterLevel']
                if value.lower() != 'null':
                    parts = value.split(',')
                    if len(parts) >= 5:  # We need at least 5 parts for the address
                        self.address = int(parts[4].strip(), 16)
                        logger.info(f"Water level address loaded: {hex(self.address)}")
                else:
                    logger.info("WaterLevel is disabled (null) in config.")
            else:
                logger.info("Water level address not found in config. Using default address.")
        except FileNotFoundError:
            logger.info(f"Config file not found. Using default address.")
        except ValueError:
            logger.info(f"Invalid address format. Using default: {hex(self.address)}")

    def get_status_async(self):
        """
        Queue a status request command with the modbus client.
        The response will be handled by _handle_response via the event emitter.
        """
        command = bytearray([self.address, 0x03, 0x00, 0x00, 0x00, 0x01])
        command_id = self.modbus_client.send_command(
            device_type='WaterLevel',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=7,  # Address(1) + Function(1) + ByteCount(1) + Data(2) + CRC(2)
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'get_status'}
        logger.debug(f"Sent get status command for WaterLevel_{self.sensor_id} with UUID: {command_id}")

    def _handle_response(self, response: ModbusResponse) -> None:
        """
        Handle responses from the modbus client event emitter.
        """
        # Only process responses for commands that this instance sent
        if response.command_id not in self.pending_commands:
            return
            
        #logger.info(f"Command queued for for WaterLevel_{self.sensor_id} with UUID: {response.command_id}")
        command_info = self.pending_commands[response.command_id]
        if response.status == 'success':
            if command_info['type'] == 'get_status':
                self._process_status_response(response.data)
        elif response.status in ['timeout', 'error', 'connection_lost']:
            logger.warning(f"Command failed with status {response.status} for {self.sensor_id}")
            self.save_null_data()
        del self.pending_commands[response.command_id]

    def _process_status_response(self, data):
        """Process the raw response data from the sensor."""
        if data and len(data) == 7:  # First check if data exists and has correct length
            try:
                # Extract the last two bytes before CRC and convert to decimal
                raw_value = int.from_bytes(data[3:5], byteorder='big')
                # Calculate water level in meters: 5 * value / 1000
                water_level = raw_value / 2000
                
                if water_level < 0 or water_level > 5:  # Add validation for reasonable water level values
                    logger.warning(f"Invalid water level value: {water_level}m for {self.sensor_id}")
                    return
                    
                self.water_level = water_level
                logger.info(f"{self.sensor_id} water level: {water_level}m")
                self.last_updated = helpers.datetime_to_iso8601()
                self.save_data()
            except Exception as e:
                logger.warning(f"Error processing response for {self.sensor_id}: {e}")
                return
        else:
            logger.debug(f"Invalid response from {self.sensor_id} length: {len(data) if data else 0} while should be 7")
            return

    def save_null_data(self):
        self.water_level = None
        self.last_updated = helpers.datetime_to_iso8601()
        self.save_data()

    def save_data(self):
        # Update the sensor-specific configuration in the file
        data = {
            "measurements": {
                "name": "water_metrics",
                "points": [
                    {
                        "tags": {
                            "sensor": "water_level",
                            "measurement": "level",
                            "location": self.sensor_id
                        },
                        "fields": {
                            "value": self.water_level
                        },
                        "timestamp": self.last_updated
                    }
                ]
            }
        }
        helpers.save_sensor_data(['data', 'water_metrics'], data)
        logger.log_sensor_data(['data', 'water_metrics'], data)


if __name__ == "__main__":
    WaterLevel.load_all_sensors(port='/dev/ttyAMA2')

    while True:
        WaterLevel.get_statuses_async()
        time.sleep(10)  # Update every second 