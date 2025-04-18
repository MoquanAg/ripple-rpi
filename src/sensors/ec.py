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

class EC:

    # Register addresses from the register map based on the provided table
    REGISTERS = {
        'ec': 0x0000,             # EC value (mS/cm, multiply by 1000 for µS/cm)
        'resistance': 0x0002,     # Resistance value (Ω·cm)
        'temperature': 0x0004,    # Temperature (°C)
        'tds': 0x0006,            # TDS value (ppm/mg/L)
        'salinity': 0x0008,       # Salinity (ppm/mg/L)
        'ec_constant': 0x000A,    # EC constant
        'compensation_coef': 0x000C, # Compensation coefficient
        'manual_temp': 0x000E,    # Manual temperature compensation
        'temp_offset': 0x0010,    # Temperature offset
        'baudrate': 0x0012,       # Baud rate
        'device_addr': 0x0014,    # Device address
        'filter_seconds': 0x0016, # Filter seconds
        'electrode_sensitivity': 0x0018, # Electrode sensitivity
        'compensation_mode': 0x001A, # Compensation mode (0=Auto, 1=Manual)
        'sensor_type': 0x001C,    # Sensor type (50.0=PT1000, 50.1=NTC10K)
        'ma_high_point': 0x0020,  # 4-20mA high point
        'slave_addr': 0x0050,     # Slave address (1-253)
        'sort_order': 0x0032,     # Sort order (0=Normal, 1=Reverse)
        'temp_sensor_type': 0x0033, # Temperature sensor type (0=PT1000, 1=NTC10K)
        'factory_reset': 0x0064,  # Factory reset (1=Reset)
        'reset_baudrate_addr': 0x270F # Reset baudrate and address (1=Reset)
    }
    
    # Map of baudrate values to actual baudrate
    BAUDRATE_VALUES = {
        2400: 0,
        4800: 1,
        9600: 2,
        19200: 3,
        38400: 4,
        43000: 5,
        57600: 6
    }

    _instances = {}  # Dictionary to hold multiple instances

    @classmethod
    def load_all_sensors(cls, port='/dev/ttyAMA2'):
        """
        Load and initialize all EC sensors defined in the configuration file.
        """
        config = globals.DEVICE_CONFIG_FILE
        
        try:
            if 'SENSORS' in config:
                for key, value in config['SENSORS'].items():
                    if key.upper().startswith("EC_"):
                        # Parse the sensor configuration
                        parts = [p.strip() for p in value.split(',')]
                        if len(parts) >= 5:  # We need at least 5 parts for the full configuration
                            sensor_id = key
                            cls(sensor_id, port)
                            logger.info(f"Loaded EC sensor with ID: {sensor_id}")
                        else:
                            logger.warning(f"Invalid configuration format for EC sensor {key}: {value}")
            else:
                logger.warning("No 'SENSORS' section found in the configuration file.")
        except Exception as e:
            logger.error(f"Failed to load EC sensors: {e}")
            logger.exception("Full exception details:")

    @classmethod
    def get_statuses_async(cls):
        """
        Asynchronously get status from all EC sensors.
        """
        tasks = []
        for _, sensor_instance in EC._instances.items():
            sensor_instance.get_status_async()
            time.sleep(0.01)  # Small delay between sensors

    def __new__(cls, sensor_id, *args, **kwargs):
        if sensor_id not in cls._instances:
            logger.debug(f"Creating the EC instance for {sensor_id}.")
            instance = super(EC, cls).__new__(cls)
            instance.init(sensor_id, *args, **kwargs)  # Initialize the instance
            cls._instances[sensor_id] = instance
        return cls._instances[sensor_id]

    def init(self, sensor_id, port='/dev/ttyAMA2'):
        logger.info(f"Initializing the EC instance for {sensor_id} in {port}.")
        self.sensor_id = sensor_id
        self.port = port
        self.data_path = globals.SAVED_SENSOR_DATA_PATH
        self.address = None  # Remove default address
        self.ser = serial.Serial()
        self.baud_rate = 9600 
        self.position = "main"
        self.ec = None
        self.temperature = None
        self.tds = None
        self.salinity = None
        self.last_updated = None
        self.load_address()

        # Update modbus client initialization
        self.modbus_client = globals.modbus_client
        self.modbus_client.event_emitter.subscribe('EC', self._handle_response)
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
                    if key.upper().startswith("EC_") and key.upper().endswith(self.sensor_id.upper()):
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
                            logger.warning(f"Invalid configuration format for EC sensor {key}: {value}")
            
            # If we get here, we couldn't load from config, try reading from sensor
            logger.info(f"Attempting to read address from sensor {self.sensor_id} directly...")
            self._read_address_from_sensor()
            
        except Exception as e:
            logger.error(f"Error loading EC sensor address: {e}")
            logger.exception("Full exception details:")

    def _read_address_from_sensor(self):
        """
        Attempt to read the slave address directly from the sensor using register 0x0050.
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
                    0x00, 0x50,    # Register address 0x0050 (slave address)
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
                    if 1 <= actual_address <= 253:
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
        Reads essential sensor data registers up to temperature offset.
        """
        command = bytearray([
            self.address,     # Slave address
            0x03,            # Function code (Read Holding Registers)
            0x00, 0x00,      # Starting address (0x0000 - EC value)
            0x00, 0x10       # Number of registers to read (16 registers to get up to temp_offset at 0x0010)
        ])
        command_id = self.modbus_client.send_command(
            device_type='EC',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=37,  # 1(addr) + 1(func) + 1(byte count) + 32(data) + 2(CRC)
            timeout=1.0
        )
        self.pending_commands[command_id] = {'type': 'get_status'}
        logger.debug(f"Sent get status command for EC_{self.sensor_id} with UUID: {command_id}")

    def read_offset_async(self):
        """Read the current EC offset value."""
        command = bytearray([
            self.address,
            0x03,           # Read holding registers
            0x00, 0x10,    # Register address 0x0010
            0x00, 0x01     # Read 1 register
        ])
        command_id = self.modbus_client.send_command(
            device_type='EC',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=7,  # 1(addr) + 1(func) + 1(byte count) + 2(data) + 2(CRC)
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'read_offset'}

    def write_offset_async(self, offset):
        """
        Write EC offset value.
        offset: EC offset value
        """
        # Convert offset to internal format if needed
        offset_value = int(offset)
        if offset_value < -32768 or offset_value > 32767:
            logger.error(f"Invalid offset value {offset}. Must be between -32768 and 32767")
            return

        command = bytearray([
            self.address,
            0x06,           # Write single register
            0x00, 0x10,    # Register address 0x0010
            (offset_value >> 8) & 0xFF,
            offset_value & 0xFF
        ])
        command_id = self.modbus_client.send_command(
            device_type='EC',
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
            device_type='EC',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=7,
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'read_slave_address'}

    def write_slave_address_async(self, new_address):
        """
        Write new slave address to the sensor using command 0x06.
        Valid range: 1-254
        Note: After changing the address, you'll need to reconnect using the new address.
        
        This follows the protocol format shown in the documentation:
        Device ID | Function Code | Start Address (High) | Start Address (Low) | Data (High) | Data (Low) | CRC (Low) | CRC (High)
          0x01    |     0x06      |        0x00         |       0x14         |    0x00     |   0x02     |   0x48    |    0x0F
        """
        if not (1 <= new_address <= 254):
            logger.error(f"Invalid slave address {new_address}. Must be between 1 and 254")
            return None

        # Following the exact format shown in the documentation
        command = bytearray([
            self.address,    # Device ID address (current)
            0x06,            # Function code for writing device address
            0x00, 0x14,      # Start address for device address (0x0014)
            0x00, new_address  # New device address (high byte always 0x00)
        ])
        
        command_id = self.modbus_client.send_command(
            device_type='EC',
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

    def set_device_address_command(self, new_address):
        """
        Creates a command following the specific format for changing device address.
        This method returns the raw command bytes that match the exact example in the documentation.
        
        Format:
        Device ID | Function Code | Start Address (High) | Start Address (Low) | Data (High) | Data (Low) | CRC (Low) | CRC (High)
          0x01    |     0x06      |        0x00         |       0x14         |    0x00     |   0x02     |   0x48    |    0x0F
        """
        if not (1 <= new_address <= 254):
            logger.error(f"Invalid address {new_address}. Must be between 1 and 254")
            return None
            
        # Create the command without CRC
        cmd = bytearray([
            self.address,    # Current device ID
            0x06,            # Function code
            0x00, 0x14,      # Start address
            0x00, new_address  # New device address
        ])
        
        # Calculate CRC-16 for the command
        crc = self._calculate_crc16(cmd)
        cmd.append(crc & 0xFF)         # CRC low byte
        cmd.append((crc >> 8) & 0xFF)  # CRC high byte
        
        return cmd
        
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

    def get_additional_data_async(self):
        """
        Queue a request for the additional data registers beyond the basic set.
        This reads registers from 0x0012 to 0x0020 (baud rate through 4-20mA high point).
        
        Note: It's a common Modbus issue when trying to read too many registers at once,
        especially over serial connections. Some reasons include:
        1. Device buffer limitations
        2. Timing constraints in serial communication
        3. Protocol overhead increases with larger requests
        4. Some devices have maximum PDU size limits
        5. Higher chance of transmission errors with longer messages
        
        The solution is to break up large requests into smaller ones as done here.
        """
        command = bytearray([
            self.address,    # Slave address
            0x03,            # Function code (Read Holding Registers)
            0x00, 0x12,      # Starting address (0x0012 - baudrate)
            0x00, 0x10       # Number of registers to read (16 registers to get the remaining data)
        ])
        command_id = self.modbus_client.send_command(
            device_type='EC',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=37,  # 1(addr) + 1(func) + 1(byte count) + 32(data) + 2(CRC)
            timeout=1.0
        )
        self.pending_commands[command_id] = {'type': 'get_additional_data'}
        logger.debug(f"Sent get additional data command for EC_{self.sensor_id} with UUID: {command_id}")

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
                    
                    if response.data[2] >= 16:  # Make sure we have enough bytes
                        # Parse EC value
                        ec_bytes = bytearray([response.data[5], response.data[6], response.data[3], response.data[4]])
                        ec = struct.unpack('>f', ec_bytes)[0]
                        print(f"  EC: {ec:.5f} µS/cm")
                        
                        # Parse Resistance value
                        resistance_bytes = bytearray([response.data[9], response.data[10], response.data[7], response.data[8]])
                        resistance = struct.unpack('>f', resistance_bytes)[0]
                        print(f"  Resistance: {resistance:.5f}")
                        
                        # Parse Temperature value
                        temp_bytes = bytearray([response.data[13], response.data[14], response.data[11], response.data[12]])
                        temp = struct.unpack('>f', temp_bytes)[0]
                        print(f"  Temperature: {temp:.2f}°C")
                        
                        # Parse TDS value
                        tds_bytes = bytearray([response.data[17], response.data[18], response.data[15], response.data[16]])
                        tds = struct.unpack('>f', tds_bytes)[0]
                        print(f"  TDS: {tds:.2f} ppm")
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
            elif command_info['type'] == 'get_additional_data':
                logger.debug(f"Received additional data for {self.sensor_id}: {response.data.hex(' ')}")
                self._process_additional_data_response(response.data)
            elif command_info['type'] == 'read_offset':
                # Offset is signed 16-bit value
                offset = int.from_bytes(response.data[3:5], byteorder='big', signed=True)
                logger.info(f"Current EC offset: {offset}")
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
            if response.data:
                logger.debug(f"Partial data received: {response.data.hex(' ')}")
            
        del self.pending_commands[response.command_id]

    def _process_status_response(self, data):
        logger.debug(f"Processing status response for {self.sensor_id}: {data.hex(' ')}")
        """Process the raw response data from the sensor."""
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
                
                # Extract values from the response using the correct byte order
                # Data format: [addr, func, byte_count, data...]
                self.sensor_data = {}  # Store all sensor data
                
                # Process each register pair as a float value
                for key, addr in self.REGISTERS.items():
                    # Calculate data offset: Starting after header (3 bytes), plus register offset
                    # Each register is 2 bytes, so multiply by 2
                    data_offset = 3 + (addr * 2)
                    
                    # Check if we have enough data for this register
                    if data_offset + 4 <= len(data):
                        try:
                            # Reorder bytes: e.g. d4 b8 3e 0b becomes 3e 0b d4 b8
                            value_bytes = bytearray([
                                data[data_offset+2], data[data_offset+3], 
                                data[data_offset], data[data_offset+1]
                            ])
                            value = struct.unpack('>f', value_bytes)[0]
                            self.sensor_data[key] = value
                            logger.debug(f"Register {key} at 0x{addr:04X}: {value}")
                            # Print important registers to console
                            if key in ['ec', 'temperature', 'tds', 'salinity', 'resistance']:
                                print(f"  {key.capitalize()} (0x{addr:04X}): {value}")
                        except struct.error as e:
                            logger.warning(f"Could not unpack float for {key} at offset {data_offset}: {e}")
                            self.sensor_data[key] = None
                        except IndexError as e:
                            logger.warning(f"Index error for {key} at offset {data_offset}: {e}")
                            self.sensor_data[key] = None
                    else:
                        logger.debug(f"Skipping register {key} at 0x{addr:04X} (offset {data_offset}), not enough data")
                
                # Update main values for backward compatibility
                self.ec = self.sensor_data.get('ec')
                if self.ec is not None:
                    self.ec *= 1000  # Convert from mS/cm to µS/cm as per the documentation
                    print(f"  EC (converted): {self.ec:.5f} µS/cm")
                
                self.temperature = self.sensor_data.get('temperature')
                self.tds = self.sensor_data.get('tds')
                self.salinity = self.sensor_data.get('salinity')
                
                self.last_updated = helpers.datetime_to_iso8601()
                
                # Log the main values
                main_values = f"{self.sensor_id} - "
                if self.ec is not None:
                    main_values += f"EC: {self.ec:.5f} µS/cm, "
                if self.tds is not None:
                    main_values += f"TDS: {self.tds:.2f} ppm, "
                if self.salinity is not None: 
                    main_values += f"Salinity: {self.salinity:.2f} ppm, "
                if self.temperature is not None:
                    main_values += f"Temperature: {self.temperature:.2f}°C"
                
                logger.info(main_values)
                
                # Log additional values
                if len(self.sensor_data) > 4:  # If we have more than the main 4 values
                    additional = f"{self.sensor_id} - Additional data: "
                    if self.sensor_data.get('resistance') is not None:
                        additional += f"Resistance: {self.sensor_data.get('resistance'):.2f} Ω·cm, "
                    if self.sensor_data.get('ec_constant') is not None:
                        additional += f"EC Constant: {self.sensor_data.get('ec_constant'):.2f}, "
                    if self.sensor_data.get('compensation_coef') is not None:
                        additional += f"Comp Coef: {self.sensor_data.get('compensation_coef'):.2f}, "
                    if self.sensor_data.get('manual_temp') is not None:
                        additional += f"Manual Temp: {self.sensor_data.get('manual_temp'):.2f}°C"
                    
                    logger.debug(additional)
                
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

    def _process_additional_data_response(self, data):
        """Process the additional data response."""
        logger.debug(f"Processing additional data response for {self.sensor_id}: {data.hex(' ')}")
        # Print to console for debugging
        print(f"\nAdditional data response from {self.sensor_id}:")
        print(f"Raw data: {data.hex(' ')}")
        
        if data and len(data) >= 7:
            try:
                # Make sure byte_count is correct
                byte_count = data[2]
                logger.debug(f"Received byte count: {byte_count}, data length: {len(data)}")
                print(f"  Address: {data[0]}")
                print(f"  Function: {data[1]}")
                print(f"  Byte count: {byte_count}")
                
                if len(data) < 3 + byte_count:
                    logger.warning(f"Incomplete additional data received, expected {byte_count} bytes, got {len(data)-3}")
                    print(f"  Incomplete data received, expected {byte_count} bytes, got {len(data)-3}")
                    return
                
                # Process registers starting from 0x0012
                # The data starts at index 3
                # The first register in this response is 0x0012 (baudrate)
                start_register = 0x0012
                
                # Process each register in the response
                for i in range(0, byte_count, 4):
                    if i + 4 <= byte_count:
                        # Calculate the current register address
                        current_addr = start_register + (i // 4)
                        
                        # Find the key for this address if it exists in REGISTERS
                        reg_key = None
                        for key, addr in self.REGISTERS.items():
                            if addr == current_addr:
                                reg_key = key
                                break
                        
                        if reg_key:
                            try:
                                # Reorder bytes: e.g. d4 b8 3e 0b becomes 3e 0b d4 b8
                                value_bytes = bytearray([
                                    data[3+i+2], data[3+i+3], 
                                    data[3+i], data[3+i+1]
                                ])
                                value = struct.unpack('>f', value_bytes)[0]
                                self.sensor_data[reg_key] = value
                                logger.debug(f"Additional register {reg_key} at 0x{current_addr:04X}: {value}")
                                print(f"  {reg_key.capitalize()} (0x{current_addr:04X}): {value}")
                            except struct.error as e:
                                logger.warning(f"Could not unpack float for {reg_key} at 0x{current_addr:04X}: {e}")
                                print(f"  Error unpacking {reg_key} at 0x{current_addr:04X}: {e}")
                            except IndexError as e:
                                logger.warning(f"Index error for {reg_key} at 0x{current_addr:04X}: {e}")
                                print(f"  Index error for {reg_key} at 0x{current_addr:04X}: {e}")
                
                # Log additional values
                additional = f"{self.sensor_id} - Additional data: "
                if self.sensor_data.get('baudrate') is not None:
                    additional += f"Baud Rate: {self.sensor_data.get('baudrate'):.0f}, "
                if self.sensor_data.get('device_addr') is not None:
                    additional += f"Device Addr: {self.sensor_data.get('device_addr'):.0f}, "
                if self.sensor_data.get('filter_seconds') is not None:
                    additional += f"Filter Seconds: {self.sensor_data.get('filter_seconds'):.1f}, "
                if self.sensor_data.get('electrode_sensitivity') is not None:
                    additional += f"Electrode Sensitivity: {self.sensor_data.get('electrode_sensitivity'):.2f}, "
                if self.sensor_data.get('compensation_mode') is not None:
                    additional += f"Compensation Mode: {self.sensor_data.get('compensation_mode'):.0f}, "
                if self.sensor_data.get('sensor_type') is not None:
                    additional += f"Sensor Type: {self.sensor_data.get('sensor_type'):.1f}, "
                if self.sensor_data.get('ma_high_point') is not None:
                    additional += f"4-20mA High Point: {self.sensor_data.get('ma_high_point'):.1f}"
                
                logger.debug(additional)
                print(f"  Summary: {additional}")
                
                # Update saved data with the new values
                self.save_data()
                
            except Exception as e:
                logger.warning(f"Error processing additional data for {self.sensor_id}: {e}")
                logger.exception("Full exception details:")
                print(f"  Error processing data: {e}")
        else:
            logger.debug(f"Invalid additional data length from {self.sensor_id}: {len(data) if data else 0}")
            print(f"  Invalid data length: {len(data) if data else 0}")

    def _update_address_in_config(self, new_address):
        """Update the sensor's address in the configuration file."""
        try:
            config = globals.DEVICE_CONFIG_FILE
            if 'SENSORS' in config:
                for key, value in config['SENSORS'].items():
                    if key.upper().startswith("EC_") and key.upper().endswith(self.sensor_id.upper()):
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
        self.ec = None
        self.temperature = None
        self.tds = None
        self.salinity = None
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
                            "sensor": "ec",
                            "measurement": "ec",
                            "location": self.sensor_id
                        },
                        "fields": {
                            "value": self.ec,
                            "temperature": self.temperature,
                            "tds": self.tds,
                            "salinity": self.salinity,
                            "resistance": self.sensor_data.get('resistance'),
                            "ec_constant": self.sensor_data.get('ec_constant'),
                            "compensation_coef": self.sensor_data.get('compensation_coef'),
                            "temperature_offset": self.sensor_data.get('temp_offset'),
                            "electrode_sensitivity": self.sensor_data.get('electrode_sensitivity')
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
        Get connection status for all EC sensors.
        Returns a dictionary with sensor IDs as keys and connection status as values.
        """
        statuses = {}
        for sensor_id, sensor_instance in cls._instances.items():
            statuses[sensor_id] = sensor_instance.is_connected()
        return statuses

    # Write functions for writable registers
    
    def write_ec_constant_async(self, value):
        """
        Write EC constant value.
        value: EC constant as float
        """
        return self._write_float_register_async('ec_constant', value)
        
    def write_compensation_coef_async(self, value):
        """
        Write compensation coefficient value.
        value: Compensation coefficient as float (typically around 2.0)
        """
        return self._write_float_register_async('compensation_coef', value)
        
    def write_manual_temp_async(self, value):
        """
        Write manual temperature compensation value.
        value: Temperature in °C as float
        """
        return self._write_float_register_async('manual_temp', value)
        
    def write_temp_offset_async(self, value):
        """
        Write temperature offset value.
        value: Temperature offset in °C as float
        """
        return self._write_float_register_async('temp_offset', value)
        
    def write_baudrate_async(self, baudrate):
        """
        Write baudrate value.
        baudrate: Baudrate value (one of 2400, 4800, 9600, 19200, 38400, 43000, 57600)
        
        Note: After changing baudrate, you'll need to reconnect using the new baudrate.
        """
        if baudrate not in self.BAUDRATE_VALUES:
            logger.error(f"Invalid baudrate {baudrate}. Must be one of {list(self.BAUDRATE_VALUES.keys())}")
            return None
            
        value = self.BAUDRATE_VALUES[baudrate]
        return self._write_int_register_async('baudrate', value)
        
    def write_device_addr_async(self, address):
        """
        Write device address value.
        address: Device address (1-254)
        
        Note: This is different from the Modbus slave address.
        """
        if not (1 <= address <= 254):
            logger.error(f"Invalid device address {address}. Must be between 1 and 254")
            return None
            
        return self._write_int_register_async('device_addr', address)
        
    def write_filter_seconds_async(self, seconds):
        """
        Write filter seconds value.
        seconds: Filter time in seconds (integer)
        """
        if seconds < 0:
            logger.error(f"Invalid filter seconds {seconds}. Must be a positive value")
            return None
            
        return self._write_int_register_async('filter_seconds', seconds)
        
    def write_compensation_mode_async(self, mode):
        """
        Write temperature compensation mode.
        mode: 0 for automatic, 1 for manual
        """
        if mode not in [0, 1]:
            logger.error(f"Invalid compensation mode {mode}. Must be 0 (automatic) or 1 (manual)")
            return None
            
        return self._write_int_register_async('compensation_mode', mode)
        
    def write_sensor_type_async(self, sensor_type):
        """
        Write sensor type.
        sensor_type: 0 for PT1000, 1 for NTC10K
        """
        if sensor_type not in [0, 1]:
            logger.error(f"Invalid sensor type {sensor_type}. Must be 0 (PT1000) or 1 (NTC10K)")
            return None
            
        # Convert to the format expected by the device (50.0 for PT1000, 50.1 for NTC10K)
        value = 50.0 if sensor_type == 0 else 50.1
        return self._write_float_register_async('sensor_type', value)
        
    def write_ma_high_point_async(self, value):
        """
        Write 4-20mA high point value.
        value: High point value as float
        """
        return self._write_float_register_async('ma_high_point', value)
        
    def write_sort_order_async(self, reverse=False):
        """
        Write sort order.
        reverse: True for reverse order, False for normal order
        """
        value = 1 if reverse else 0
        return self._write_int_register_async('sort_order', value)
        
    def write_temp_sensor_type_async(self, sensor_type):
        """
        Write temperature sensor type.
        sensor_type: 0 for PT1000, 1 for NTC10K
        """
        if sensor_type not in [0, 1]:
            logger.error(f"Invalid temperature sensor type {sensor_type}. Must be 0 (PT1000) or 1 (NTC10K)")
            return None
            
        return self._write_int_register_async('temp_sensor_type', sensor_type)
        
    def factory_reset_async(self):
        """
        Reset the device to factory settings.
        """
        return self._write_int_register_async('factory_reset', 1)
        
    def reset_baudrate_and_address_async(self):
        """
        Reset baudrate and device address to default values.
        """
        return self._write_int_register_async('reset_baudrate_addr', 1)
    
    # Helper methods for writing registers
    
    def _write_float_register_async(self, register_name, value):
        """
        Helper method to write a float value to a register.
        """
        if register_name not in self.REGISTERS:
            logger.error(f"Unknown register name: {register_name}")
            return None
            
        addr = self.REGISTERS[register_name]
        
        # Convert float to appropriate byte format
        # The device expects the float bytes in reversed order
        float_bytes = struct.pack('>f', float(value))
        # Swap the byte order to match device expectations
        # Convert e.g. 3e 0b e0 91 to e0 91 3e 0b
        swapped_bytes = bytearray([float_bytes[2], float_bytes[3], float_bytes[0], float_bytes[1]])
        
        # Modbus uses 16-bit registers, so we need to send two registers
        command = bytearray([
            self.address,      # Slave address
            0x10,              # Function code (Write Multiple Registers)
            (addr >> 8) & 0xFF, addr & 0xFF,  # Register address
            0x00, 0x02,        # Number of registers (2 for a float)
            0x04,              # Byte count (4 bytes for a float)
            swapped_bytes[0], swapped_bytes[1],  # First register
            swapped_bytes[2], swapped_bytes[3]   # Second register
        ])
        
        command_id = self.modbus_client.send_command(
            device_type='EC',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,  # Standard response for function 0x10
            timeout=1.0
        )
        
        self.pending_commands[command_id] = {
            'type': f'write_{register_name}',
            'value': value
        }
        
        logger.debug(f"Sent write command for {register_name} with value {value}")
        return command_id
        
    def _write_int_register_async(self, register_name, value):
        """
        Helper method to write an integer value to a register.
        For signed integers, we use a single register (16-bits).
        """
        if register_name not in self.REGISTERS:
            logger.error(f"Unknown register name: {register_name}")
            return None
            
        addr = self.REGISTERS[register_name]
        
        # Convert int to 16-bit signed integer
        value = int(value)
        if value < 0:
            value = 0x10000 + value  # Convert to two's complement
        
        command = bytearray([
            self.address,      # Slave address
            0x06,              # Function code (Write Single Register)
            (addr >> 8) & 0xFF, addr & 0xFF,  # Register address
            (value >> 8) & 0xFF, value & 0xFF  # Register value
        ])
        
        command_id = self.modbus_client.send_command(
            device_type='EC',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,  # Standard response for function 0x06
            timeout=1.0
        )
        
        self.pending_commands[command_id] = {
            'type': f'write_{register_name}',
            'value': value
        }
        
        logger.debug(f"Sent write command for {register_name} with value {value}")
        return command_id

if __name__ == "__main__":
    # Load all sensors
    EC.load_all_sensors(port='/dev/ttyAMA2')

    # Check connection status of all sensors
    connection_statuses = EC.get_connection_statuses()
    
    # # Change address to 0x21 (33) if requested
    # print("Changing device address to 0x21 (33)...")
    # for sensor_id, sensor_instance in EC._instances.items():
    #     print(f"Changing address for sensor {sensor_id}")
    #     # Show the exact command that will be sent
    #     cmd = sensor_instance.set_device_address_command(0x21)
    #     print(f"Command to be sent: {cmd.hex(' ')}")
        
    #     # Send the command to change address
    #     cmd_id = sensor_instance.write_slave_address_async(0x21)
    #     print(f"Command sent with ID: {cmd_id}")
    #     time.sleep(2) 
    
    # Now run the normal loop
    print("\nStarting normal polling loop:")
    while True:
        print("Getting basic status data from all sensors...")
        EC.get_statuses_async()
        # Wait a bit before requesting additional data
        time.sleep(1)
        # Get additional data for all sensors
        print("Getting additional data from all sensors...")
        for _, sensor_instance in EC._instances.items():
            sensor_instance.get_additional_data_async()
            time.sleep(0.1)  # Small delay between sensors
        time.sleep(30)  # Update every 30 seconds 