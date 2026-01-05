import time
import os, sys

# Add the project root to Python path so we can import src modules
current_dir = os.path.dirname(__file__)
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

# Now import with absolute paths that work from anywhere
from src.lumina_modbus_event_emitter import ModbusResponse
import src.globals as globals
from src.lumina_logger import GlobalLogger

logger = GlobalLogger("RipplepH", log_prefix="ripple_").logger

import math
import helpers

class pH:
    """
    pH sensor control system with Modbus RTU communication.
    
    Manages pH sensors that provide acidity/alkalinity measurements in water
    with temperature compensation. Supports multiple sensor instances with
    configurable addresses, baud rates, and calibration parameters.
    
    Features:
    - pH measurement in standard units (0-14 scale)
    - Temperature compensation for accurate readings
    - Configurable pH offset calibration
    - Modbus slave address configuration
    - Automatic data validation and error handling
    - Connection status monitoring via hardware flow control
    - Instance-based singleton pattern for multiple sensors
    
    Register Map:
    - 0x0000: pH value (actual value * 100 for transmission)
    - 0x0001: Temperature in °C (actual value * 10 for transmission)
    - 0x0010: pH offset calibration (actual value * 100, signed)
    - 0x0050: Modbus slave address (1-253)
    
    Communication Protocol:
    - Modbus RTU over serial connection
    - Read holding registers (function code 0x03)
    - Write single register (function code 0x06)
    - Standard 8N1 serial configuration
    - Configurable baud rates (typically 9600)
    
    Args:
        sensor_id (str): Unique identifier for the sensor instance
        port (str): Serial port for Modbus communication (default: '/dev/ttyAMA2')
        
    Note:
        - Docstring created by Claude 3.5 Sonnet on 2024-09-22
        - Implements instance-based singleton pattern for multiple sensors
        - Uses Modbus RTU protocol for communication
        - Supports asynchronous command queuing and response handling
        - Automatically loads configuration from device.conf file
        - Validates pH readings to ensure reasonable values (0-14 range)
        - Supports hardware flow control for connection detection
    """

    # Register addresses from the register map
    REGISTERS = {
        'ph': 0x0000,          # pH value (actual value * 100)
        'temperature': 0x0001,  # Temperature (actual value * 10)
        'offset': 0x0010,      # Offset (actual value * 100), signed
        'slave_addr': 0x0050   # Slave address (1-253)
    }

    _instances = {}  # Dictionary to hold multiple instances

    @classmethod
    def load_all_sensors(cls, port='/dev/ttyAMA2'):
        """
        Load and initialize all pH sensors defined in the configuration file.
        
        Scans the device configuration file for pH sensor definitions and creates
        instances for each configured sensor. Each sensor is initialized with its
        specific configuration parameters including address, baud rate, and position.
        
        Args:
            port (str): Default serial port for sensor communication
            
        Note:
            - Looks for keys starting with 'PH_' in the SENSORS section
            - Creates singleton instances for each sensor ID
            - Validates configuration format before initialization (requires at least 5 parts)
            - Logs warnings for invalid or missing configurations
        """
        config = globals.DEVICE_CONFIG_FILE
        
        try:
            if 'SENSORS' in config:
                for key, value in config['SENSORS'].items():
                    if key.upper().startswith("PH_"):
                        # Parse the sensor configuration
                        parts = [p.strip() for p in value.split(',')]
                        if len(parts) >= 5:  # We need at least 5 parts for the full configuration
                            sensor_id = key
                            cls(sensor_id, port)
                            logger.info(f"Loaded pH sensor with ID: {sensor_id}")
                        else:
                            logger.warning(f"Invalid configuration format for pH sensor {key}: {value}")
            else:
                logger.warning("No 'SENSORS' section found in the configuration file.")
        except Exception as e:
            logger.error(f"Failed to load pH sensors: {e}")
            logger.exception("Full exception details:")

    @classmethod
    def get_statuses_async(cls):
        """
        Asynchronously get status from all pH sensors.
        
        Queues status requests for all initialized pH sensor instances using
        the Modbus client's asynchronous command system. Each sensor will
        process its response independently through the event emitter.
        
        Note:
            - Uses a small delay (0.01s) between sensors to avoid command conflicts
            - Responses are handled asynchronously via _handle_response method
            - Each sensor maintains its own pending commands queue
        """
        tasks = []
        for _, sensor_instance in pH._instances.items():
            sensor_instance.get_status_async()
            time.sleep(0.01)  # Small delay between sensors

    def __new__(cls, sensor_id, *args, **kwargs):
        if sensor_id not in cls._instances:
            logger.debug(f"Creating the pH instance for {sensor_id}.")
            instance = super(pH, cls).__new__(cls)
            instance.init(sensor_id, *args, **kwargs)  # Initialize the instance
            cls._instances[sensor_id] = instance
        return cls._instances[sensor_id]

    def init(self, sensor_id, port='/dev/ttyAMA2'):
        logger.info(f"Initializing the pH instance for {sensor_id} in {port}.")
        self.sensor_id = sensor_id
        self.port = globals.get_device_port('SENSORS', 'pH_main', '/dev/ttyAMA2')
        self.data_path = globals.SAVED_SENSOR_DATA_PATH
        self.address = globals.get_device_address('SENSORS', 'pH_main', '0x11')
        self.baud_rate = globals.get_device_baudrate('SENSORS', 'pH_main', 9600)
        self.position = "main"
        self.ph = None
        self.temperature = None
        self.last_updated = None
        self.sensor_data = {}  # Initialize sensor_data dictionary
        self.load_address()

        # Update modbus client initialization
        self.modbus_client = globals.modbus_client
        self.modbus_client.event_emitter.subscribe('pH', self._handle_response)
        self.pending_commands = {}

    def load_address(self):
        """
        Load the sensor's Modbus slave address from configuration.
        First tries to read from config file, if that fails, tries to read from sensor directly.
        """
        config = globals.DEVICE_CONFIG_FILE
        try:
            if 'SENSORS' in config:
                for key, value in config['SENSORS'].items():
                    # Match either PH_ prefix or pH_ prefix
                    if key.upper().startswith("PH_") and key.upper().endswith(self.sensor_id.upper()):
                        parts = [p.strip() for p in value.split(',')]
                        if len(parts) >= 5:  # We need at least 5 parts for the full configuration
                            try:
                                self.address = int(parts[4], 16)  # Address is in the 5th position
                                self.position = parts[1]  # Position is in the 2nd position
                                logger.info(f"{key} address loaded from config: {hex(self.address)}")
                                return
                            except ValueError:
                                logger.warning(f"Invalid address format in config for {key}: {parts[4]}")
                        else:
                            logger.warning(f"Invalid configuration format for pH sensor {key}: {value}")
            
            # If we get here, we couldn't load from config, try reading from sensor
            logger.info(f"Attempting to read address from sensor {self.sensor_id} directly...")
            self._read_address_from_sensor()
            
        except Exception as e:
            logger.error(f"Error loading pH sensor address: {e}")
            logger.exception("Full exception details:")

    def _read_address_from_sensor(self):
        """
        Attempt to read the slave address directly from the sensor using register 0x0050.
        This is used when the address is not available in the config file.
        Uses LuminaModbusClient for all Modbus communication.
        """
        # We need to try common addresses since we don't know the current address
        common_addresses = [1, 2, 3, 4, 5]  # Add more if needed

        for test_address in common_addresses:
            try:
                # Use LuminaModbusClient's synchronous read_holding_registers
                response = self.modbus_client.read_holding_registers(
                    port=self.port,
                    address=self.REGISTERS['slave_addr'],  # 0x0050
                    count=1,
                    slave_addr=test_address,
                    baudrate=self.baud_rate,
                    timeout=0.5,
                    device_name='pH_addr_probe'
                )

                if not response.isError() and response.registers:
                    actual_address = response.registers[0] & 0xFF  # Get low byte
                    if 1 <= actual_address <= 253:
                        self.address = actual_address
                        logger.info(f"Successfully read address {actual_address} from sensor {self.sensor_id}")
                        return

            except Exception as e:
                logger.debug(f"Failed to read address using test address {test_address}: {e}")

        # If we get here, we couldn't read the address
        logger.warning(f"Could not read address from sensor {self.sensor_id}. Using default address 1")
        self.address = 1

    def get_status_async(self):
        """
        Queue a status request command with the modbus client.
        
        Sends a Modbus RTU read holding registers command to read pH and temperature
        values from registers 0x0000 and 0x0001. The response will be handled
        asynchronously by _handle_response via the event emitter system.
        
        Command Format:
        - Function Code: 0x03 (Read Holding Registers)
        - Starting Address: 0x0000 (pH value register)
        - Number of Registers: 2 (pH and temperature)
        
        Note:
            - Response length expected: 9 bytes
            - Timeout: 0.5 seconds
            - Command ID is stored for response matching
        """
        command = bytearray([
            self.address,     # Slave address
            0x03,            # Function code (Read Holding Registers)
            0x00, 0x00,      # Starting address (0x0000 - pH value)
            0x00, 0x02       # Number of registers to read (2 registers)
        ])
        command_id = self.modbus_client.send_command(
            device_type='pH',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=9,  # 1(addr) + 1(func) + 1(byte count) + 4(data) + 2(CRC)
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'get_status'}
        logger.debug(f"Sent get status command for pH_{self.sensor_id} with UUID: {command_id}")

    def read_offset_async(self):
        """Read the current pH offset value."""
        command = bytearray([
            self.address,
            0x03,           # Read holding registers
            0x00, 0x10,    # Register address 0x0010
            0x00, 0x01     # Read 1 register
        ])
        command_id = self.modbus_client.send_command(
            device_type='pH',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=7,  # 1(addr) + 1(func) + 1(byte count) + 2(data) + 2(CRC)
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'read_offset'}

    def write_offset_async(self, offset):
        """
        Write pH offset value for sensor calibration.
        
        Sets the pH offset calibration value that is applied to all pH readings.
        This is used to calibrate the sensor against known reference solutions.
        
        Args:
            offset (float): pH offset value in pH units (range: -327.68 to 327.67)
            
        Note:
            - Value is internally multiplied by 100 for transmission
            - Uses Modbus function code 0x06 (Write Single Register)
            - Updates register 0x0010 with the calibration value
        """
        # Convert offset to internal format (multiply by 100)
        offset_value = int(offset * 100)
        if offset_value < -32768 or offset_value > 32767:
            logger.error(f"Invalid offset value {offset}. Must be between -327.68 and 327.67")
            return

        command = bytearray([
            self.address,
            0x06,           # Write single register
            0x00, 0x10,    # Register address 0x0010
            (offset_value >> 8) & 0xFF,
            offset_value & 0xFF
        ])
        command_id = self.modbus_client.send_command(
            device_type='pH',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'write_offset', 'value': offset}

    def read_slave_address_async(self):
        """Read the current slave address."""
        command = bytearray([
            self.address,
            0x03,           # Read holding registers
            0x00, 0x50,    # Register address 0x0050
            0x00, 0x01     # Read 1 register
        ])
        command_id = self.modbus_client.send_command(
            device_type='pH',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=7,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'read_slave_address'}

    def write_slave_address_async(self, new_address):
        """
        Write new slave address to the sensor.
        Valid range: 1-253
        Note: After changing the address, you'll need to reconnect using the new address.
        """
        if not (1 <= new_address <= 253):
            logger.error(f"Invalid slave address {new_address}. Must be between 1 and 253")
            return

        command = bytearray([
            self.address,
            0x06,           # Write single register
            0x00, 0x50,    # Register address 0x0050
            0x00, new_address
        ])
        command_id = self.modbus_client.send_command(
            device_type='pH',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=0.5
        )
        self.pending_commands[command_id] = {
            'type': 'write_slave_address', 
            'value': new_address,
            'old_address': self.address
        }

    def _process_status_response(self, data):
        """Process the raw response data from the sensor."""
        if data and len(data) >= 7:  # addr(1) + func(1) + byte_count(1) + data(4)
            try:
                # Extract values from the response
                # Data format: [addr, func, byte_count, data...]
                # Each value is 2 bytes, stored as 16-bit unsigned integer
                
                # pH value (actual value * 100)
                self.ph = int.from_bytes(data[3:5], byteorder='big') / 100.0
                
                # Temperature (actual value * 10)
                self.temperature = int.from_bytes(data[5:7], byteorder='big') / 10.0

                # Validate pH value (0-14 is typical range)
                if self.ph < 0 or self.ph > 14:
                    logger.warning(f"Invalid pH value: {self.ph} for {self.sensor_id}")
                    self.ph = None

                # Validate temperature (-10 to 120°C is typical range)
                if self.temperature < -10 or self.temperature > 120:
                    logger.warning(f"Invalid temperature value: {self.temperature} for {self.sensor_id}")
                    self.temperature = None

                self.last_updated = helpers.datetime_to_iso8601()
                
                logger.info(f"{self.sensor_id} - pH: {self.ph}, Temperature: {self.temperature}°C")
                
                self.save_data()
                
            except Exception as e:
                logger.warning(f"Error processing response for {self.sensor_id}: {e}")
                self.save_null_data()
        else:
            logger.debug(f"Invalid response length from {self.sensor_id}: {len(data) if data else 0}")
            self.save_null_data()

    def _handle_response(self, response: ModbusResponse) -> None:
        """Handle responses from the modbus client event emitter."""
        if response.command_id not in self.pending_commands:
            return
            
        command_info = self.pending_commands[response.command_id]
        if response.status == 'success':
            if command_info['type'] == 'get_status':
                self._process_status_response(response.data)
            elif command_info['type'] == 'read_offset':
                # Offset is signed 16-bit value
                offset = int.from_bytes(response.data[3:5], byteorder='big', signed=True) / 100.0
                logger.info(f"Current pH offset: {offset}")
            elif command_info['type'] == 'read_slave_address':
                address = response.data[4]  # Second byte of the value
                logger.info(f"Current slave address: {address}")
            elif command_info['type'] == 'write_slave_address':
                new_address = command_info['value']
                old_address = command_info['old_address']
                logger.info(f"Successfully changed slave address from {old_address} to {new_address}")
                # Update the instance's address
                self.address = new_address
                # Update the address in the configuration if possible
                self._update_address_in_config(new_address)
            elif command_info['type'].startswith('write_'):
                logger.info(f"Successfully wrote {command_info['type'].replace('write_', '')} "
                          f"value: {command_info.get('value', '')}")
        elif response.status in ['timeout', 'error', 'connection_lost']:
            logger.warning(f"Command {command_info['type']} failed with status {response.status}")
            
        del self.pending_commands[response.command_id]

    def _update_address_in_config(self, new_address):
        """Update the sensor's address in the configuration file."""
        try:
            config = globals.DEVICE_CONFIG_FILE
            if 'SENSORS' in config:
                for key, value in config['SENSORS'].items():
                    if key.upper().startswith("PH_") and key.upper().endswith(self.sensor_id.upper()):
                        parts = [p.strip() for p in value.split(',')]
                        if len(parts) >= 5:
                            parts[4] = hex(new_address)  # Update address in 5th position
                            config['SENSORS'][key] = ','.join(parts)
                            # Save config file - you'll need to implement this based on your config system
                            logger.info(f"Updated address in configuration for sensor {self.sensor_id}")
                            return
            logger.warning(f"Could not update address in configuration for sensor {self.sensor_id}")
        except Exception as e:
            logger.error(f"Error updating address in configuration: {e}")

    def save_null_data(self):
        self.ph = None
        self.temperature = None
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
                            "sensor": "ph",
                            "measurement": "ph",
                            "location": self.sensor_id
                        },
                        "fields": {
                            "value": round(self.ph, 2) if self.ph is not None else None,
                            "temperature": round(self.temperature, 2) if self.temperature is not None else None,
                            "offset": round(self.sensor_data.get('offset', None), 2) if self.sensor_data.get('offset') is not None else None
                        },
                        "timestamp": self.last_updated
                    }
                ]
            }
        }
        helpers.save_sensor_data(['data', 'water_metrics', 'ph'], data)
        logger.log_sensor_data(['data', 'water_metrics', 'ph'], data)
        
    def is_connected(self):
        """
        Check if the sensor is connected by attempting a Modbus read operation.

        Verifies sensor connectivity by sending a Modbus read request through
        the LuminaModbusClient. If the sensor responds successfully, it is
        considered connected.

        Returns:
            bool: True if the sensor responds to Modbus commands, False otherwise.

        Note:
            - Uses LuminaModbusClient for communication through lumina-modbus-server
            - Attempts to read the pH register (0x0000) with a short timeout
            - Returns False on timeout or communication error
        """
        try:
            # Try to read pH register to verify connectivity
            response = self.modbus_client.read_holding_registers(
                port=self.port,
                address=self.REGISTERS['ph'],  # 0x0000
                count=1,
                slave_addr=self.address,
                baudrate=self.baud_rate,
                timeout=0.5,
                device_name='pH_connectivity_check'
            )

            connected = not response.isError() and response.registers is not None
            if not connected:
                logger.debug(f"pH sensor {self.sensor_id} not responding")
            return connected

        except Exception as e:
            logger.debug(f"pH sensor {self.sensor_id} connectivity check failed: {e}")
            return False

    @classmethod
    def get_connection_statuses(cls):
        """
        Get connection status for all pH sensors.
        Returns a dictionary with sensor IDs as keys and connection status as values.
        """
        statuses = {}
        for sensor_id, sensor_instance in cls._instances.items():
            statuses[sensor_id] = sensor_instance.is_connected()
        return statuses

if __name__ == "__main__":
    # Load all sensors
    pH.load_all_sensors(port='/dev/ttyAMA2')

    # Check connection status of all sensors
    connection_statuses = pH.get_connection_statuses()

    while True:
        pH.get_statuses_async()
        time.sleep(3)  # Update every 3 seconds 