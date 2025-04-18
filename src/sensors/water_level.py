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
        'slave_addr': 0x0000,     # Slave address (1-255)
        'baudrate': 0x0001,       # Baud rate (0-7 for different rates)
        'pressure_unit': 0x0002,  # Pressure unit (9-Mpa/°C, 10-Kpa, 11-Pa, 12-Bar, 13-Mbar, 14-kg/cm², 15-psi, 16-mh₂o, 17-mmh₂o)
        'decimal_places': 0x0003, # Decimal places (0-3 for decimal point positions)
        'level': 0x0004,          # Measurement output value (-32768-32767)
        'range_min': 0x0005,      # Range min point (-32768-32767)
        'range_max': 0x0006,      # Range max point (-32768-32767)
        'zero_offset': 0x000C     # Zero offset value (-32768-32767)
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
        "Mpa/°C": 9,
        "KPa": 10,
        "Pa": 11,
        "Bar": 12,
        "Mbar": 13,
        "kg/cm²": 14,
        "psi": 15,
        "mh₂o": 16,
        "mmh₂o": 17
    }
    
    # Map for decimal places
    DECIMAL_PLACES = {
        0: "####",    # No decimal places
        1: "###.#",   # 1 decimal place
        2: "##.##",   # 2 decimal places
        3: "#.###"    # 3 decimal places
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
        Reads registers from 0x0000 to 0x0007 to get all essential sensor data:
        - 0x0000: Slave address
        - 0x0001: Baudrate
        - 0x0002: Pressure unit
        - 0x0003: Decimal places
        - 0x0004: Measurement output value
        - 0x0005: Range min point
        - 0x0006: Range max point
        - 0x0007: Additional settings
        """
        command = bytearray([
            self.address,     # Slave address
            0x03,            # Function code (Read Holding Registers)
            0x00, 0x00,      # Starting address (0x0000)
            0x00, 0x08       # Number of registers to read (8 registers = 16 bytes)
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=21,  # 1(addr) + 1(func) + 1(byte count) + 16(data) + 2(CRC)
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
        unit: Pressure unit (9-Mpa/°C, 10-Kpa, 11-Pa, 12-Bar, 13-Mbar, 14-kg/cm², 15-psi, 16-mh₂o, 17-mmh₂o)
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
            if unit_value < 9 or unit_value > 17:
                logger.error(f"Invalid unit value {unit}. Must be between 9 and 17")
                return

        command = bytearray([
            self.address,
            0x06,           # Write single register
            0x00, 0x02,    # Register address 0x0002 (pressure unit)
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
        """Write decimal places value (0-3)."""
        if not 0 <= decimal_places <= 3:
            logger.error(f"Invalid decimal places {decimal_places}. Must be between 0 and 3")
            return

        command = bytearray([
            self.address,
            0x06,           # Write single register
            0x00, 0x03,    # Register address 0x0003 (decimal places)
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

    def write_zero_offset_async(self, value):
        """Write zero offset value."""
        # Convert to 16-bit signed integer
        if value < -32768 or value > 32767:
            logger.error(f"Invalid zero offset value {value}. Must be between -32768 and 32767")
            return

        # Convert negative values to two's complement
        if value < 0:
            value = 65536 + value

        command = bytearray([
            self.address,
            0x06,           # Write single register
            0x00, 0x0C,    # Register address 0x000C (zero offset)
            (value >> 8) & 0xFF, value & 0xFF
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'write_zero_offset', 'value': value}

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

        command = bytearray([
            self.address,    # Current slave address
            0x06,           # Function code (Write Single Register)
            0x00, 0x00,    # Register address 0x0000
            0x00, new_address  # New address value
        ])
        
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,  # Standard response for function 0x06
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
        """Write baudrate value."""
        # Convert baudrate name to value if string is provided
        if isinstance(baudrate, str):
            if baudrate.upper() in {k.upper(): v for k, v in self.BAUDRATE_VALUES.items()}:
                baud_value = self.BAUDRATE_VALUES[baudrate.upper()]
            else:
                logger.error(f"Invalid baudrate {baudrate}. Must be one of {list(self.BAUDRATE_VALUES.keys())}")
                return
        else:
            baud_value = int(baudrate)
            if baud_value not in self.BAUDRATE_VALUES.values():
                logger.error(f"Invalid baudrate value {baudrate}. Must be one of {list(self.BAUDRATE_VALUES.values())}")
                return

        command = bytearray([
            self.address,
            0x06,           # Write single register
            0x00, 0x01,    # Register address 0x0001 (baudrate)
            0x00, baud_value
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'write_baudrate', 'value': baud_value}

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
        This resets all settings to their factory defaults.
        """
        command = bytearray([
            self.address,
            0x06,           # Function code (Write Single Register)
            0x00, 0x10,    # Register address 0x0010
            0x00, 0x01     # Value 1 to restore factory parameters
        ])
        
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=1.0
        )
        
        self.pending_commands[command_id] = {
            'type': 'restore_factory_params'
        }
        
        logger.info("Sent command to restore factory parameters")
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
        """Write range minimum value."""
        # Convert to 16-bit signed integer
        if value < -32768 or value > 32767:
            logger.error(f"Invalid range min value {value}. Must be between -32768 and 32767")
            return

        # Convert negative values to two's complement
        if value < 0:
            value = 65536 + value

        command = bytearray([
            self.address,
            0x06,           # Write single register
            0x00, 0x05,    # Register address 0x0005 (range min)
            (value >> 8) & 0xFF, value & 0xFF
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'write_range_min', 'value': value}

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
        """Write range maximum value."""
        # Convert to 16-bit signed integer
        if value < -32768 or value > 32767:
            logger.error(f"Invalid range max value {value}. Must be between -32768 and 32767")
            return

        # Convert negative values to two's complement
        if value < 0:
            value = 65536 + value

        command = bytearray([
            self.address,
            0x06,           # Write single register
            0x00, 0x06,    # Register address 0x0006 (range max)
            (value >> 8) & 0xFF, value & 0xFF
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'write_range_max', 'value': value}

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
        
        if data and len(data) >= 7:  # At minimum we need addr(1) + func(1) + byte_count(1) + data(≥4)
            try:
                # Make sure byte_count is correct
                byte_count = data[2]
                logger.debug(f"Received byte count: {byte_count}, data length: {len(data)}")
                
                if len(data) < 3 + byte_count:
                    logger.warning(f"Incomplete data received, expected {byte_count} bytes, got {len(data)-3}")
                    self.save_null_data()
                    return
                
                # Extract values from the response
                self.sensor_data = {}  # Store all sensor data
                
                # Process each register pair
                if byte_count >= 16:  # We expect 16 bytes for 8 registers
                    try:
                        # Register 0x0000: Slave address
                        slave_addr = (data[3] << 8) | data[4]
                        
                        # Register 0x0001: Baudrate
                        baudrate_value = (data[5] << 8) | data[6]
                        baudrate = next((k for k, v in self.BAUDRATE_VALUES.items() if v == baudrate_value), "Unknown")
                        
                        # Register 0x0002: Pressure unit
                        unit_value = (data[7] << 8) | data[8]
                        unit = next((k for k, v in self.UNIT_VALUES.items() if v == unit_value), "Unknown")
                        
                        # Register 0x0003: Decimal places
                        decimal_value = (data[9] << 8) | data[10]
                        decimal_format = self.DECIMAL_PLACES.get(decimal_value, "Unknown")
                        
                        # Register 0x0004: Level value
                        level_raw = (data[11] << 8) | data[12]
                        
                        # Handle negative values (two's complement)
                        if level_raw > 32767:
                            level_raw -= 65536
                        
                        # The raw value is already in cm, just use decimal places for display
                        level = level_raw
                        
                        # Format string based on decimal places setting
                        if decimal_value == 0:  # ####
                            level_str = f"{level:d}"
                        elif decimal_value == 1:  # ###.#
                            level_str = f"{level:.1f}"
                        elif decimal_value == 2:  # ##.##
                            level_str = f"{level:.2f}"
                        elif decimal_value == 3:  # #.###
                            level_str = f"{level:.3f}"
                        else:
                            level_str = f"{level:d}"
                        
                        # Register 0x0005: Range min
                        range_min = (data[13] << 8) | data[14]
                        if range_min > 32767:  # Handle negative values
                            range_min -= 65536
                        
                        # Register 0x0006: Range max
                        range_max = (data[15] << 8) | data[16]
                        if range_max > 32767:  # Handle negative values
                            range_max -= 65536
                        
                        # Register 0x000C: Zero offset
                        if byte_count >= 18:  # Make sure we have the zero offset data
                            zero_offset = (data[17] << 8) | data[18]
                            if zero_offset > 32767:  # Handle negative values
                                zero_offset -= 65536
                            self.sensor_data['zero_offset'] = zero_offset
                        
                        self.level = level
                        self.unit = "cm"  # Always use cm
                        self.sensor_data['level'] = level
                        self.sensor_data['unit'] = "cm"
                        self.sensor_data['range_min'] = range_min
                        self.sensor_data['range_max'] = range_max
                        
                        # Log the main values
                        main_values = f"{self.sensor_id} - "
                        if self.level is not None:
                            main_values += f"Level: {level_str} cm"
                            main_values += f", Range min: {range_min}"
                            main_values += f", Range max: {range_max}"
                            if 'zero_offset' in self.sensor_data:
                                main_values += f", Zero offset: {self.sensor_data['zero_offset']}"
                        
                        logger.info(main_values)
                        
                    except Exception as e:
                        logger.warning(f"Could not parse register values: {e}")
                        self.level = None
                        self.unit = None
                        self.sensor_data['level'] = None
                        self.sensor_data['unit'] = None
                
                self.last_updated = helpers.datetime_to_iso8601()
                self.save_data()
                
            except Exception as e:
                logger.warning(f"Error processing response for {self.sensor_id}: {e}")
                logger.exception("Full exception details:")
                self.save_null_data()
        else:
            logger.debug(f"Invalid response length from {self.sensor_id}: {len(data) if data else 0}")
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
                            "measurement": "level",
                            "location": self.sensor_id
                        },
                        "fields": {
                            "value": round(self.level, 2) if self.level is not None else None,
                            "temperature": round(self.temperature, 2) if self.temperature is not None else None,
                            "pressure_unit": self.sensor_data.get('pressure_unit', None),
                            "decimal_places": self.sensor_data.get('decimal_places', None),
                            "range_min": round(self.sensor_data.get('range_min', None), 2) if self.sensor_data.get('range_min') is not None else None,
                            "range_max": round(self.sensor_data.get('range_max', None), 2) if self.sensor_data.get('range_max') is not None else None,
                            "zero_offset": round(self.sensor_data.get('zero_offset', None), 2) if self.sensor_data.get('zero_offset') is not None else None
                        },
                        "timestamp": self.last_updated
                    }
                ]
            }
        }
        helpers.save_sensor_data(['data', 'water_metrics', 'water_level'], data)
        logger.log_sensor_data(['data', 'water_metrics', 'water_level'], data)
        
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

    def write_slave_addr_async(self, addr):
        """Write slave address."""
        if not 1 <= addr <= 247:
            logger.error(f"Invalid slave address {addr}. Must be between 1 and 247")
            return

        command = bytearray([
            self.address,
            0x06,           # Write single register
            0x00, 0x00,    # Register address 0x0000 (slave address)
            0x00, addr
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'write_slave_addr', 'value': addr}

    def read_status_async(self):
        """Read all sensor registers."""
        command = bytearray([
            self.address,
            0x03,           # Read holding registers
            0x00, 0x00,    # Starting register address (0x0000)
            0x00, 0x0D     # Number of registers to read (13 registers: 0x0000 to 0x000C)
        ])
        command_id = self.modbus_client.send_command(
            device_type='water_level',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=31,  # 1(addr) + 1(func) + 1(byte_count) + 26(data) + 2(crc)
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'read_status'}

if __name__ == "__main__":
    # Load all sensors
    WaterLevel.load_all_sensors(port='/dev/ttyAMA2')

    # Check connection status of all sensors
    connection_statuses = WaterLevel.get_connection_statuses()
    
    # Change address to 0x31 (49) if requested
    # print("\nChanging device addresses to 0x31 (49)...")
    # for sensor_id, sensor_instance in WaterLevel._instances.items():
    #     print(f"Changing address for sensor {sensor_id}")
    #     # Send the command to change address
    #     cmd_id = sensor_instance.write_slave_address_async(0x31)
    #     print(f"Command sent with ID: {cmd_id}")
    #     time.sleep(2)  # Wait for the change to take effect
    
    # Now run the normal loop
    print("\nStarting normal polling loop:")
    while True:
        print("Getting basic status data from all water level sensors...")
        WaterLevel.get_statuses_async()
        time.sleep(10)  # Update every 10 seconds 