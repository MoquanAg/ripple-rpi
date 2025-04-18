import serial
import time
import os, sys
import struct

current_dir = os.path.dirname(__file__)
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from lumina_modbus_event_emitter import ModbusResponse

import globals
logger = globals.logger

import math
import helpers

class WaterLevel:

    # Register addresses from the register map based on the provided table
    REGISTERS = {
        'level': 0x0000,          # Water level value
        'temperature': 0x0002,    # Temperature (°C)
        'zero_point': 0x0004,     # Zero point calibration
        'unit': 0x0006,           # Pressure unit (0-Mpa/°C, 1-Kpa, 2-Pa, 3-Bar, 4-Mbar, 5-kg/cm², 6-psi, 7-mh₂o, 8-mmh₂o)
        'decimal_places': 0x0003, # Decimal places (0-3 for decimal point positions)
        'range_min': 0x0005,      # Transmitter range min point (-32768-32767)
        'range_max': 0x0006,      # Transmitter range max point (-32768-32767)
        'zero_offset': 0x000c,    # Zero point offset (default is 0)
        'baudrate': 0x0001,       # Baud rate (0-1200, 1-2400, 2-4800, 3-9600, 4-19200, 5-38400, 6-57600, 7-115200)
        'slave_addr': 0x0000,     # Slave address (1-255)
        'factory_reset': 0x000F,  # Factory reset (0-save to user area)
        'restore_factory': 0x0010 # Restore factory parameters (1)
    }
    
    # Map of baudrate values to actual baudrate
    BAUDRATE_VALUES = {
        1200: 0,
        2400: 1,
        4800: 2,
        9600: 3,
        19200: 4,
        38400: 5,
        57600: 6,
        115200: 7
    }
    
    # Map of unit values to actual units
    UNIT_VALUES = {
        "MPa/°C": 0,
        "KPa": 1,
        "Pa": 2,
        "Bar": 3,
        "Mbar": 4,
        "kg/cm²": 5,
        "psi": 6,
        "mh₂o": 7,
        "mmh₂o": 8
    }
    
    # Map for decimal places
    DECIMAL_PLACES = {
        0: "0",      # No decimal places
        1: "0.0",    # 1 decimal place
        2: "0.00",   # 2 decimal places
        3: "0.000"   # 3 decimal places
    }

    _instances = {}  # Dictionary to hold multiple instances

    @classmethod
    def load_all_sensors(cls, port='/dev/ttyAMA2'):
        """
        Load and initialize all water level sensors defined in the configuration file.
        """
        config = globals.DEVICE_CONFIG_FILE
        
        try:
            if 'SENSORS' in config:
                for key, value in config['SENSORS'].items():
                    if key.upper().startswith("WATER_LEVEL_"):
                        # Parse the sensor configuration
                        parts = [p.strip() for p in value.split(',')]
                        if len(parts) >= 5:  # We need at least 5 parts for the full configuration
                            sensor_id = key
                            cls(sensor_id, port)
                            logger.info(f"Loaded Water Level sensor with ID: {sensor_id}")
                        else:
                            logger.warning(f"Invalid configuration format for Water Level sensor {key}: {value}")
            else:
                logger.warning("No 'SENSORS' section found in the configuration file.")
        except Exception as e:
            logger.error(f"Failed to load Water Level sensors: {e}")
            logger.exception("Full exception details:")

    @classmethod
    def get_statuses_async(cls):
        """
        Asynchronously get status from all water level sensors.
        """
        tasks = []
        for _, sensor_instance in WaterLevel._instances.items():
            sensor_instance.get_status_async()
            time.sleep(0.01)  # Small delay between sensors

    def __new__(cls, sensor_id, *args, **kwargs):
        if sensor_id not in cls._instances:
            logger.debug(f"Creating the Water Level instance for {sensor_id}.")
            instance = super(WaterLevel, cls).__new__(cls)
            instance.init(sensor_id, *args, **kwargs)  # Initialize the instance
            cls._instances[sensor_id] = instance
        return cls._instances[sensor_id]

    def init(self, sensor_id, port='/dev/ttyAMA2'):
        logger.info(f"Initializing the Water Level instance for {sensor_id} in {port}.")
        self.sensor_id = sensor_id
        self.port = port
        self.data_path = globals.SAVED_SENSOR_DATA_PATH
        self.address = None  # Remove default address
        self.ser = serial.Serial()
        self.baud_rate = 9600 
        self.position = "main"
        self.level = None
        self.temperature = None
        self.unit = None
        self.last_updated = None
        self.load_address()

        # Update modbus client initialization
        self.modbus_client = globals.modbus_client
        self.modbus_client.event_emitter.subscribe('water_level', self._handle_response)
        self.pending_commands = {}

    def open_connection(self):
        self.ser = serial.Serial(self.port, self.baud_rate, serial.EIGHTBITS, serial.PARITY_NONE, serial.STOPBITS_ONE)
        
    def close_connection(self):
        self.ser.close()

    def load_address(self):
        """
        Load the sensor's Modbus slave address from configuration.
        First tries to read from config file, if that fails, tries to read from sensor directly.
        """
        config = globals.DEVICE_CONFIG_FILE
        try:
            if 'SENSORS' in config:
                for key, value in config['SENSORS'].items():
                    if key.upper().startswith("WATER_LEVEL_") and key.upper().endswith(self.sensor_id.upper()):
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
                            logger.warning(f"Invalid configuration format for Water Level sensor {key}: {value}")
            
            # If we get here, we couldn't load from config, try reading from sensor
            logger.info(f"Attempting to read address from sensor {self.sensor_id} directly...")
            self._read_address_from_sensor()
            
        except Exception as e:
            logger.error(f"Error loading Water Level sensor address: {e}")
            logger.exception("Full exception details:")

    def _read_address_from_sensor(self):
        """
        Attempt to read the slave address directly from the sensor using register 0x0000.
        This is used when the address is not available in the config file.
        """
        # We need to try common addresses since we don't know the current address
        common_addresses = [1, 2, 3, 4, 5]  # Add more if needed
        
        for test_address in common_addresses:
            try:
                self.address = test_address
                command = bytearray([
                    test_address,
                    0x03,           # Read holding registers
                    0x00, 0x00,    # Register address 0x0000 (slave address)
                    0x00, 0x01     # Read 1 register
                ])
                
                # Try to open serial connection
                if not self.ser.is_open:
                    self.ser.port = self.port
                    self.ser.baudrate = self.baud_rate
                    self.ser.timeout = 0.5
                    self.ser.open()
                
                # Send command
                self.ser.write(command)
                response = self.ser.read(7)  # 7 bytes expected for this response
                
                if len(response) == 7 and response[0] == test_address:
                    actual_address = response[4]  # Second byte of the value
                    if 1 <= actual_address <= 255:
                        self.address = actual_address
                        logger.info(f"Successfully read address {actual_address} from sensor {self.sensor_id}")
                        return
            
            except Exception as e:
                logger.debug(f"Failed to read address using test address {test_address}: {e}")
            
            finally:
                if self.ser.is_open:
                    self.ser.close()
        
        # If we get here, we couldn't read the address
        logger.warning(f"Could not read address from sensor {self.sensor_id}. Using default address 1")
        self.address = 1

    def get_status_async(self):
        """
        Queue a status request command with the modbus client.
        Reads essential sensor data registers: level and temperature.
        """
        command = bytearray([
            self.address,     # Slave address
            0x03,            # Function code (Read Holding Registers)
            0x00, 0x00,      # Starting address (0x0000 - level value)
            0x00, 0x04       # Number of registers to read (4 registers to get level and temperature)
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=13,  # 1(addr) + 1(func) + 1(byte count) + 8(data) + 2(CRC)
            timeout=1.0
        )
        self.pending_commands[command_id] = {'type': 'get_status'}
        logger.debug(f"Sent get status command for water_level_{self.sensor_id} with UUID: {command_id}")

    def read_unit_async(self):
        """Read the current pressure unit setting."""
        command = bytearray([
            self.address,
            0x03,           # Read holding registers
            0x00, 0x06,    # Register address 0x0006 (unit)
            0x00, 0x01     # Read 1 register
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=7,  # 1(addr) + 1(func) + 1(byte count) + 2(data) + 2(CRC)
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'read_unit'}

    def write_unit_async(self, unit):
        """
        Write unit value.
        unit: Pressure unit (0-Mpa/°C, 1-Kpa, 2-Pa, 3-Bar, 4-Mbar, 5-kg/cm², 6-psi, 7-mh₂o, 8-mmh₂o)
        """
        # Convert unit name to value if string is provided
        if isinstance(unit, str):
            if unit.upper() in {k.upper(): v for k, v in self.UNIT_VALUES.items()}:
                unit_value = self.UNIT_VALUES[unit.upper()]
            else:
                logger.error(f"Invalid unit name {unit}. Must be one of {list(self.UNIT_VALUES.keys())}")
                return
        else:
            unit_value = int(unit)
            if unit_value < 0 or unit_value > 8:
                logger.error(f"Invalid unit value {unit}. Must be between 0 and 8")
                return

        command = bytearray([
            self.address,
            0x06,           # Write single register
            0x00, 0x06,    # Register address 0x0006
            0x00, unit_value
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'write_unit', 'value': unit_value}

    def read_decimal_places_async(self):
        """Read the current decimal places setting."""
        command = bytearray([
            self.address,
            0x03,           # Read holding registers
            0x00, 0x03,    # Register address 0x0003 (decimal places)
            0x00, 0x01     # Read 1 register
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=7,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'read_decimal_places'}

    def write_decimal_places_async(self, decimal_places):
        """
        Write decimal places setting.
        decimal_places: Number of decimal places (0-3)
        """
        if not (0 <= decimal_places <= 3):
            logger.error(f"Invalid decimal places value {decimal_places}. Must be between 0 and 3")
            return

        command = bytearray([
            self.address,
            0x06,           # Write single register
            0x00, 0x03,    # Register address 0x0003
            0x00, decimal_places
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'write_decimal_places', 'value': decimal_places}

    def read_zero_offset_async(self):
        """Read the current zero offset value."""
        command = bytearray([
            self.address,
            0x03,           # Read holding registers
            0x00, 0x0c,    # Register address 0x000c
            0x00, 0x01     # Read 1 register
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=7,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'read_zero_offset'}

    def write_zero_offset_async(self, offset):
        """
        Write zero offset value.
        offset: Zero offset value (-32768 to 32767)
        """
        offset_value = int(offset)
        if offset_value < -32768 or offset_value > 32767:
            logger.error(f"Invalid offset value {offset}. Must be between -32768 and 32767")
            return

        command = bytearray([
            self.address,
            0x06,           # Write single register
            0x00, 0x0c,    # Register address 0x000c
            (offset_value >> 8) & 0xFF,
            offset_value & 0xFF
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'write_zero_offset', 'value': offset}

    def read_slave_address_async(self):
        """Read the current slave address."""
        command = bytearray([
            self.address,
            0x03,           # Read holding registers
            0x00, 0x00,    # Register address 0x0000
            0x00, 0x01     # Read 1 register
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
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
        Valid range: 1-255
        Note: After changing the address, you'll need to reconnect using the new address.
        """
        if not (1 <= new_address <= 255):
            logger.error(f"Invalid slave address {new_address}. Must be between 1 and 255")
            return None

        # Create command to write slave address
        command = bytearray([
            self.address,   # Current device ID
            0x06,           # Function code for writing
            0x00, 0x00,     # Register address 0x0000
            0x00, new_address  # New address
        ])
        
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,  # 8 bytes response
            timeout=2.0
        )
        
        self.pending_commands[command_id] = {
            'type': 'write_slave_address',
            'value': new_address,
            'old_address': self.address
        }
        
        logger.info(f"Sent command to change slave address from {self.address} to {new_address}")
        return command_id 

    def read_baudrate_async(self):
        """Read the current baudrate setting."""
        command = bytearray([
            self.address,
            0x03,           # Read holding registers
            0x00, 0x01,    # Register address 0x0001 (baudrate)
            0x00, 0x01     # Read 1 register
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=7,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'read_baudrate'}

    def write_baudrate_async(self, baudrate):
        """
        Write baudrate value.
        baudrate: Baudrate value (one of 1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200)
        
        Note: After changing baudrate, you'll need to reconnect using the new baudrate.
        """
        if baudrate not in self.BAUDRATE_VALUES:
            logger.error(f"Invalid baudrate {baudrate}. Must be one of {list(self.BAUDRATE_VALUES.keys())}")
            return None
            
        value = self.BAUDRATE_VALUES[baudrate]
        command = bytearray([
            self.address,
            0x06,           # Write single register
            0x00, 0x01,    # Register address 0x0001
            0x00, value
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'write_baudrate', 'value': baudrate}
        return command_id

    def factory_reset_async(self):
        """
        Save current settings to user area.
        """
        command = bytearray([
            self.address,
            0x06,           # Write single register
            0x00, 0x0F,    # Register address 0x000F
            0x00, 0x00     # Value to save to user area
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'factory_reset'}
        return command_id
        
    def restore_factory_params_async(self):
        """
        Restore device to factory parameters.
        """
        command = bytearray([
            self.address,
            0x06,           # Write single register
            0x00, 0x10,    # Register address 0x0010
            0x00, 0x01     # Value to restore factory parameters
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'restore_factory_params'}
        return command_id

    def read_range_min_async(self):
        """Read the transmitter range minimum point."""
        command = bytearray([
            self.address,
            0x03,           # Read holding registers
            0x00, 0x05,    # Register address 0x0005
            0x00, 0x01     # Read 1 register
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=7,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'read_range_min'}

    def write_range_min_async(self, value):
        """
        Write transmitter range minimum point.
        value: Range minimum (-32768 to 32767)
        """
        range_min = int(value)
        if range_min < -32768 or range_min > 32767:
            logger.error(f"Invalid range minimum value {value}. Must be between -32768 and 32767")
            return

        command = bytearray([
            self.address,
            0x06,           # Write single register
            0x00, 0x05,    # Register address 0x0005
            (range_min >> 8) & 0xFF,
            range_min & 0xFF
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'write_range_min', 'value': range_min}

    def read_range_max_async(self):
        """Read the transmitter range maximum point."""
        command = bytearray([
            self.address,
            0x03,           # Read holding registers
            0x00, 0x06,    # Register address 0x0006
            0x00, 0x01     # Read 1 register
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=7,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'read_range_max'}

    def write_range_max_async(self, value):
        """
        Write transmitter range maximum point.
        value: Range maximum (-32768 to 32767)
        """
        range_max = int(value)
        if range_max < -32768 or range_max > 32767:
            logger.error(f"Invalid range maximum value {value}. Must be between -32768 and 32767")
            return

        command = bytearray([
            self.address,
            0x06,           # Write single register
            0x00, 0x06,    # Register address 0x0006
            (range_max >> 8) & 0xFF,
            range_max & 0xFF
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'write_range_max', 'value': range_max}

    def _calculate_crc16(self, data):
        """
        Calculate CRC-16 for Modbus RTU.
        This is the standard CRC-16 calculation used in Modbus RTU protocol.
        """
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc = crc >> 1
        return crc

    def _handle_response(self, response: ModbusResponse) -> None:
        """Handle responses from the modbus client event emitter."""
        # Check for our test commands
        if hasattr(self, 'test_command_ids') and response.command_id in self.test_command_ids:
            print(f"\nReceived response for test command {self.test_command_ids[response.command_id]}:")
            if response.status == 'success':
                print(f"Raw data: {response.data.hex(' ')}")
                # Try to interpret the raw data
                if len(response.data) >= 7:  # Check if we have enough data
                    print(f"  Address: {response.data[0]}")
                    print(f"  Function: {response.data[1]}")
                    print(f"  Byte count: {response.data[2]}")
                    
                    if response.data[2] >= 8:  # Make sure we have enough bytes
                        # Parse level value
                        level_bytes = bytearray([response.data[5], response.data[6], response.data[3], response.data[4]])
                        level = struct.unpack('>f', level_bytes)[0]
                        print(f"  Level: {level:.5f}")
                        
                        # Parse Temperature value
                        temp_bytes = bytearray([response.data[9], response.data[10], response.data[7], response.data[8]])
                        temp = struct.unpack('>f', temp_bytes)[0]
                        print(f"  Temperature: {temp:.2f}°C")
            else:
                print(f"Command failed: {response.status}")
                
            return
            
        # Regular command handling
        if response.command_id not in self.pending_commands:
            return
            
        command_info = self.pending_commands[response.command_id]
        if response.status == 'success':
            if command_info['type'] == 'get_status':
                # Log raw data for debugging
                logger.debug(f"Received data for {self.sensor_id}: {response.data.hex(' ')}")
                self._process_status_response(response.data)
            elif command_info['type'] == 'read_unit':
                unit_value = response.data[4]  # Second byte of the value
                unit_key = next((k for k, v in self.UNIT_VALUES.items() if v == unit_value), f"Unknown ({unit_value})")
                logger.info(f"Current pressure unit: {unit_key}")
            elif command_info['type'] == 'read_decimal_places':
                decimal_places = response.data[4]  # Second byte of the value
                format_str = self.DECIMAL_PLACES.get(decimal_places, f"Unknown ({decimal_places})")
                logger.info(f"Current decimal places setting: {decimal_places} ({format_str})")
            elif command_info['type'] == 'read_zero_offset':
                # Offset is signed 16-bit value
                offset = int.from_bytes(response.data[3:5], byteorder='big', signed=True)
                logger.info(f"Current zero offset: {offset}")
            elif command_info['type'] == 'read_range_min':
                range_min = int.from_bytes(response.data[3:5], byteorder='big', signed=True)
                logger.info(f"Current range minimum: {range_min}")
            elif command_info['type'] == 'read_range_max':
                range_max = int.from_bytes(response.data[3:5], byteorder='big', signed=True)
                logger.info(f"Current range maximum: {range_max}")
            elif command_info['type'] == 'read_baudrate':
                baudrate_value = response.data[4]  # Second byte of the value
                baudrate = next((k for k, v in self.BAUDRATE_VALUES.items() if v == baudrate_value), f"Unknown ({baudrate_value})")
                logger.info(f"Current baudrate: {baudrate}")
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
            elif command_info['type'] == 'factory_reset':
                logger.info(f"Successfully saved settings to user area")
            elif command_info['type'] == 'restore_factory_params':
                logger.info(f"Successfully restored factory parameters")
        elif response.status in ['timeout', 'error', 'connection_lost']:
            logger.warning(f"Command {command_info['type']} failed with status {response.status}")
            if response.data:
                logger.debug(f"Partial data received: {response.data.hex(' ')}")
            
        del self.pending_commands[response.command_id]

    def _process_status_response(self, data):
        """Process the raw response data from the sensor."""
        logger.debug(f"Processing status response for {self.sensor_id}: {data.hex(' ')}")
        
        # Print to console for debugging
        print(f"\nStatus response from {self.sensor_id}:")
        print(f"Raw data: {data.hex(' ')}")
        
        if data and len(data) >= 7:  # At minimum we need addr(1) + func(1) + byte_count(1) + data(≥4)
            try:
                # Make sure byte_count is correct
                byte_count = data[2]
                logger.debug(f"Received byte count: {byte_count}, data length: {len(data)}")
                print(f"  Address: {data[0]}")
                print(f"  Function: {data[1]}")
                print(f"  Byte count: {byte_count}")
                
                if len(data) < 3 + byte_count:
                    logger.warning(f"Incomplete data received, expected {byte_count} bytes, got {len(data)-3}")
                    print(f"  Incomplete data received, expected {byte_count} bytes, got {len(data)-3}")
                    self.save_null_data()
                    return
                
                # Extract values from the response
                self.sensor_data = {}  # Store all sensor data
                
                # Process each register pair
                if byte_count >= 8:  # We expect 8 bytes for 4 registers
                    try:
                        # Register 0x0000-0x0001 (First pair)
                        reg0_value = (data[3] << 8) | data[4]
                        print(f"  Register 0x0000: {reg0_value} (Slave address)")
                        
                        # Register 0x0001-0x0002 (Second pair)
                        reg1_value = (data[5] << 8) | data[6]
                        baudrate = next((k for k, v in self.BAUDRATE_VALUES.items() if v == reg1_value), "Unknown")
                        print(f"  Register 0x0001: {reg1_value} (Baudrate: {baudrate})")
                        
                        # Register 0x0002-0x0003 (Third pair)
                        reg2_value = (data[7] << 8) | data[8]
                        unit = next((k for k, v in self.UNIT_VALUES.items() if v == reg2_value), "Unknown")
                        print(f"  Register 0x0002: {reg2_value} (Pressure unit: {unit})")
                        
                        # Register 0x0003-0x0004 (Fourth pair)
                        reg3_value = (data[9] << 8) | data[10]
                        decimal_format = self.DECIMAL_PLACES.get(reg3_value, "Unknown")
                        print(f"  Register 0x0003: {reg3_value} (Decimal places: {decimal_format})")
                        
                        # Get the raw integer values for level
                        level_raw = int.from_bytes(data[3:7], byteorder='big', signed=True)
                        level = level_raw / 10000.0
                        
                        self.level = level
                        self.unit = unit
                        self.sensor_data['level'] = level
                        self.sensor_data['unit'] = unit
                        logger.debug(f"Level at 0x0004: {level} {unit}")
                        print(f"  Level: {level:.4f} {unit}")
                        
                    except Exception as e:
                        logger.warning(f"Could not parse register values: {e}")
                        self.level = None
                        self.unit = None
                        self.sensor_data['level'] = None
                        self.sensor_data['unit'] = None
                
                self.last_updated = helpers.datetime_to_iso8601()
                
                # Log the main values
                main_values = f"{self.sensor_id} - "
                if self.level is not None:
                    main_values += f"Level: {self.level:.4f} {self.unit if self.unit else ''}"
                
                logger.info(main_values)
                
                self.save_data()
                
            except Exception as e:
                logger.warning(f"Error processing response for {self.sensor_id}: {e}")
                logger.exception("Full exception details:")
                print(f"  Error processing data: {e}")
                self.save_null_data()
        else:
            logger.debug(f"Invalid response length from {self.sensor_id}: {len(data) if data else 0}")
            print(f"  Invalid response length: {len(data) if data else 0}")
            self.save_null_data()

    def _update_address_in_config(self, new_address):
        """Update the sensor's address in the configuration file."""
        try:
            config = globals.DEVICE_CONFIG_FILE
            if 'SENSORS' in config:
                for key, value in config['SENSORS'].items():
                    if key.upper().startswith("WATER_LEVEL_") and key.upper().endswith(self.sensor_id.upper()):
                        parts = [p.strip() for p in value.split(',')]
                        if len(parts) >= 5:
                            parts[4] = hex(new_address)  # Update address in 5th position
                            config['SENSORS'][key] = ','.join(parts)
                            # Save config file based on your config system
                            logger.info(f"Updated address in configuration for sensor {self.sensor_id}")
                            return
            logger.warning(f"Could not update address in configuration for sensor {self.sensor_id}")
        except Exception as e:
            logger.error(f"Error updating address in configuration: {e}")

    def save_null_data(self):
        self.level = None
        self.temperature = None  # Keep this for backward compatibility
        self.unit = None
        self.sensor_data = {}
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
                            "measurement": "water_level",
                            "location": self.sensor_id
                        },
                        "fields": {
                            "value": self.level,
                            "unit": self.unit
                        },
                        "timestamp": self.last_updated
                    }
                ]
            }
        }
        helpers.save_sensor_data(['data', 'water_metrics'], data)
        logger.log_sensor_data(['data', 'water_metrics'], data)
        
    def is_connected(self):
        """
        Check if the sensor is physically connected by checking hardware flow control signals.
        Returns True if the port exists and hardware signals indicate a device is connected, False otherwise.
        """
        try:
            if not os.path.exists(self.port):
                logger.debug(f"Port {self.port} does not exist")
                return False
                
            # Try to open the port with hardware flow control
            test_ser = serial.Serial()
            test_ser.port = self.port
            test_ser.baudrate = self.baud_rate
            test_ser.rts = True  # Enable RTS
            test_ser.dtr = True  # Enable DTR
            test_ser.open()
            
            # Check if we can read hardware signals
            connected = test_ser.dsr  # Check DSR signal
            test_ser.close()
            
            if not connected:
                logger.debug(f"Port {self.port} exists but no device detected (no DSR signal)")
            return connected
            
        except (serial.SerialException, OSError) as e:
            logger.debug(f"Port {self.port} is not accessible: {e}")
            return False

    @classmethod
    def get_connection_statuses(cls):
        """
        Get connection status for all water level sensors.
        Returns a dictionary with sensor IDs as keys and connection status as values.
        """
        statuses = {}
        for sensor_id, sensor_instance in cls._instances.items():
            statuses[sensor_id] = sensor_instance.is_connected()
        return statuses

if __name__ == "__main__":
    # Load all sensors
    WaterLevel.load_all_sensors(port='/dev/ttyAMA2')

    # Check connection status of all sensors
    connection_statuses = WaterLevel.get_connection_statuses()
    
    # Now run the normal loop
    print("\nStarting normal polling loop:")
    while True:
        print("Getting basic status data from all water level sensors...")
        WaterLevel.get_statuses_async()
        time.sleep(10)  # Update every 10 seconds 