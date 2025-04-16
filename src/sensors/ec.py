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

    # Register addresses from the register map (based on test results)
    REGISTERS = {
        'ec': 0x0000,          # EC value (µS/cm, actual value * 10)
        'temperature_ieee': 0x0004,  # Temperature as IEEE 754 float (using registers 0x0004-0x0005)
        'temperature_old': 0x0001,  # Old temperature method ((actual value * 100) + 10000, subtract 10000 and divide by 100 to get °C)
        'tds': 0x0006,         # TDS value (ppm/mg/L)
        'salinity': 0x0008,    # Salinity value
        'offset': 0x0010,      # Offset (signed)
        'slave_addr': 0x0050   # Slave address (1-253)
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
        Reads EC and related values.
        """
        command = bytearray([
            self.address,     # Slave address
            0x03,            # Function code (Read Holding Registers)
            0x00, 0x00,      # Starting address (0x0000 - EC value)
            0x00, 0x09       # Number of registers to read (9 registers to get EC, temp, TDS, salinity)
        ])
        command_id = self.modbus_client.send_command(
            device_type='EC',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=21,  # 1(addr) + 1(func) + 1(byte count) + 18(data) + 2(CRC) - actual received size
            timeout=0.5
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
            device_type='EC',
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
        if data and len(data) >= 21:  # addr(1) + func(1) + byte_count(1) + data(≥18)
            try:
                # Extract values from the response
                # Data format: [addr, func, byte_count, data...]
                # Each value is 2 bytes, stored as 16-bit unsigned integer
                
                # EC value (µS/cm, actual value * 10)
                self.ec = int.from_bytes(data[3:5], byteorder='big') / 10.0
                
                # Temperature using IEEE 754 floating point from registers 0x0004-0x0005
                # Using little endian register order (reg5, reg4)
                if len(data) >= 15:  # Make sure we have enough data for the temperature registers
                    reg4 = int.from_bytes(data[11:13], byteorder='big')
                    reg5 = int.from_bytes(data[13:15], byteorder='big')
                    
                    # Convert to IEEE 754 float (little endian register order)
                    combined = (reg5 << 16) | reg4
                    float_bytes = combined.to_bytes(4, byteorder='big')
                    self.temperature = struct.unpack('>f', float_bytes)[0]
                    
                    # Fall back to the old method if the IEEE value seems wrong
                    if self.temperature < -20 or self.temperature > 150:
                        raw_temp = int.from_bytes(data[5:7], byteorder='big')
                        self.temperature = (raw_temp - 10000) / 100.0 if raw_temp > 10000 else raw_temp / 100.0
                        logger.warning(f"Invalid IEEE temperature value, using fallback: {self.temperature}°C for {self.sensor_id}")
                else:
                    # Use old method if we don't have the IEEE registers
                    raw_temp = int.from_bytes(data[5:7], byteorder='big')
                    self.temperature = (raw_temp - 10000) / 100.0 if raw_temp > 10000 else raw_temp / 100.0
                
                # TDS value (ppm/mg/L) at register 0x0006 (bytes 15-17)
                self.tds = int.from_bytes(data[15:17], byteorder='big')
                
                # Salinity value at register 0x0008 (bytes 19-21)
                self.salinity = int.from_bytes(data[19:21], byteorder='big')

                # Validate temperature with wider range (-20 to 150°C)
                if self.temperature < -20 or self.temperature > 150:
                    logger.warning(f"Invalid temperature value: {self.temperature} for {self.sensor_id}")
                    self.temperature = None

                # Validate EC value (range depends on the sensor, but generally should be positive)
                if self.ec < 0:
                    logger.warning(f"Invalid EC value: {self.ec} for {self.sensor_id}")
                    self.ec = None

                # Validate TDS value (should be positive)
                if self.tds < 0:
                    logger.warning(f"Invalid TDS value: {self.tds} for {self.sensor_id}")
                    self.tds = None

                # Validate salinity value (should be positive)
                if self.salinity < 0:
                    logger.warning(f"Invalid salinity value: {self.salinity} for {self.sensor_id}")
                    self.salinity = None

                self.last_updated = helpers.datetime_to_iso8601()
                
                logger.info(f"{self.sensor_id} - EC: {self.ec} µS/cm, TDS: {self.tds} ppm, " +
                          f"Salinity: {self.salinity}, Temperature: {self.temperature:.2f}°C")
                
                self.save_data()
                
            except Exception as e:
                logger.warning(f"Error processing response for {self.sensor_id}: {e}")
                self.save_null_data()
        else:
            logger.debug(f"Invalid response length from {self.sensor_id}: {len(data) if data else 0}")
            self.save_null_data()

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
                    
                    if response.data[2] >= 4:  # Make sure we have at least 2 registers
                        reg1 = int.from_bytes(response.data[3:5], byteorder='big')
                        reg2 = int.from_bytes(response.data[5:7], byteorder='big')
                        
                        print(f"  Register 1 (raw): {reg1}")
                        print(f"  Register 2 (raw): {reg2}")
                        
                        # If this is the EC+temp command (first registers)
                        if self.test_command_ids[response.command_id] == 1:
                            print(f"  Interpreted as EC: {reg1/10.0} µS/cm")
                            print(f"  Interpreted as Temp: {(reg2-10000)/100.0 if reg2 > 10000 else reg2/100.0} °C")
                        # If this is the second command (registers 0x0004-0x0005)
                        elif self.test_command_ids[response.command_id] == 2:
                            print(f"  Register 0x0004: {reg1}")
                            print(f"  Register 0x0005: {reg2}")
            else:
                print(f"Command failed: {response.status}")
                
            return
            
        # Regular command handling
        if response.command_id not in self.pending_commands:
            return
            
        command_info = self.pending_commands[response.command_id]
        if response.status == 'success':
            if command_info['type'] == 'get_status':
                self._process_status_response(response.data)
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
            
        del self.pending_commands[response.command_id]

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
                            "salinity": self.salinity
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

if __name__ == "__main__":
    # Load all sensors
    EC.load_all_sensors(port='/dev/ttyAMA2')

    # Check connection status of all sensors
    connection_statuses = EC.get_connection_statuses()
    
    # Now run the normal loop
    print("\nStarting normal polling loop:")
    while True:
        EC.get_statuses_async()
        time.sleep(3)  # Update every 3 seconds 