import serial
import time
import os, sys

current_dir = os.path.dirname(__file__)
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from lumina_modbus_event_emitter import ModbusResponse

import globals
logger = globals.logger

import math
import helpers

class DO:

    _instances = {}  # Dictionary to hold multiple instances

    @classmethod
    def load_all_sensors(cls, port='/dev/ttyAMA2'):
        """
        Load and initialize all DO sensors defined in the configuration file.
        """
        config = globals.DEVICE_CONFIG_FILE
        
        try:
            if 'DEVICE' in config:
                for key, value in config['DEVICE'].items():
                    if key.upper().startswith("DO_"):
                        sensor_id = key
                        cls(sensor_id, port)
                        logger.info(f"Loaded sensor with ID: {sensor_id}")
            else:
                logger.info("No 'DEVICE' section found in the configuration file.")
        except Exception as e:
            logger.info(f"Failed to load sensors: {e}")

    @classmethod
    def get_statuses_async(cls):
        """
        Asynchronously get status from all DO sensors.
        """
        tasks = []
        for _, sensor_instance in DO._instances.items():
            sensor_instance.get_status_async()
            time.sleep(0.01)  # Small delay between sensors

    def __new__(cls, sensor_id, *args, **kwargs):
        if sensor_id not in cls._instances:
            logger.debug(f"Creating the DO instance for {sensor_id}.")
            instance = super(DO, cls).__new__(cls)
            instance.init(sensor_id, *args, **kwargs)  # Initialize the instance
            cls._instances[sensor_id] = instance
        return cls._instances[sensor_id]

    def init(self, sensor_id, port='/dev/ttyAMA2'):
        logger.info(f"Initializing the DO instance for {sensor_id} in {port}.")
        self.sensor_id = sensor_id
        self.port = port
        self.data_path = globals.SAVED_SENSOR_DATA_PATH
        self.address = globals.get_device_address('SENSORS', 'DO_main', '0x03')
        self.baud_rate = globals.get_device_baudrate('SENSORS', 'DO_main', 9600)
        self.position = "main"
        self.do = None
        self.last_updated = None
        self.load_address()

        # Update modbus client initialization
        self.modbus_client = globals.modbus_client
        self.modbus_client.event_emitter.subscribe('DO', self._handle_response)
        self.pending_commands = {}

    def open_connection(self):
        self.ser = serial.Serial(self.port, self.baud_rate, serial.EIGHTBITS, serial.PARITY_NONE, serial.STOPBITS_ONE)
        
    def close_connection(self):
        self.ser.close()

    def load_address(self):
        config = globals.DEVICE_CONFIG_FILE
        try:
            if 'DEVICE' in config:
                for key, value in config['DEVICE'].items():
                    if key.upper().startswith(f"DO_{self.sensor_id.upper()}"):
                        self.address = int(value, 16)
                        self.position = self.sensor_id
                        logger.info(f"{key} address loaded: {hex(self.address)}")
                        break
        except FileNotFoundError:
            logger.info(f"Device config not found. Using default address.")
        except ValueError:
            logger.info(f"Invalid address format. Using default: {hex(self.address)}")

    def get_status_async(self):
        """
        Queue a status request command with the modbus client.
        The response will be handled by _handle_response via the event emitter.
        """
        command = bytearray([self.address, 0x03, 0x00, 0x14, 0x00, 0x02])
        command_id = self.modbus_client.send_command(
            device_type='DO',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=9,
            timeout=0.5  # Add explicit timeout
        )
        self.pending_commands[command_id] = {'type': 'get_status'}
        logger.debug(f"Sent get status command for DO_{self.sensor_id} with UUID: {command_id}")

    def _handle_response(self, response: ModbusResponse) -> None:
        """
        Handle responses from the modbus client event emitter.
        """
        # Only process responses for commands that this instance sent
        if response.command_id not in self.pending_commands:
            return
            
        #logger.info(f"Command queued for for DO_{self.sensor_id} with UUID: {response.command_id}")
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
        if data and len(data) == 9:  # First check if data exists and has correct length
            try:
                do = int.from_bytes(data[3:5], byteorder='big') / 100
                if do <= 0 or do > 20:  # Add validation for reasonable DO values
                    logger.warning(f"Invalid DO value: {do}mg/L for {self.sensor_id}")
                    self.save_null_data()
                    return
                    
                self.do = do
                logger.info(f"{self.sensor_id} do: {do}mg/L")
                self.last_updated = helpers.datetime_to_iso8601()
                self.save_data()
            except Exception as e:
                logger.warning(f"Error processing response for {self.sensor_id}: {e}")
                self.save_null_data()
        else:
            logger.debug(f"Invalid response from {self.sensor_id} length: {len(data) if data else 0} while should be 9")
            self.save_null_data()

    def save_null_data(self):
        self.do = None
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
                            "sensor": "dissolved_oxygen",
                            "measurement": "dissolved_oxygen",
                            "location": self.sensor_id
                        },
                        "fields": {
                            "value": self.do
                        },
                        "timestamp": self.last_updated
                    }
                ]
            }
        }
        helpers.save_sensor_data(['data', 'water_metrics'], data)
        logger.log_sensor_data(['data', 'water_metrics'], data)
        
    def should_oxygenate(self):
        if self.do is None:
            return False
        return self.do < 7.0


if __name__ == "__main__":
    DO.load_all_sensors(port='/dev/ttyAMA2')

    while True:
        DO.get_statuses_async()
        time.sleep(1)  # Update every 2 seconds
