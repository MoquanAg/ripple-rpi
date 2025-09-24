import serial
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

logger = GlobalLogger("RippleDO", log_prefix="ripple_").logger

import math
try:
    # Try importing when running from main directory
    import src.helpers as helpers
except ImportError:
    # Import when running from src directory
    import helpers

class DO:
    """
    Dissolved Oxygen (DO) sensor control system with Modbus RTU communication.
    
    Manages dissolved oxygen sensors that provide oxygen concentration measurements
    in water. Supports multiple sensor instances with configurable addresses,
    baud rates, and measurement parameters.
    
    Features:
    - Dissolved oxygen measurement in mg/L (milligrams per liter)
    - Temperature compensation for accurate readings
    - Configurable baud rates and Modbus addresses
    - Automatic data validation and error handling
    - Oxygenation threshold checking for system control
    - Instance-based singleton pattern for multiple sensors
    
    Register Map:
    - 0x0014: DO value (mg/L, multiplied by 100 for transmission)
    
    Communication Protocol:
    - Modbus RTU over serial connection
    - Read holding registers (function code 0x03)
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
        - Validates DO readings to ensure reasonable values (0-20 mg/L)
        - Provides oxygenation threshold checking (default: <7.0 mg/L)
    """

    _instances = {}  # Dictionary to hold multiple instances

    @classmethod
    def load_all_sensors(cls, port='/dev/ttyAMA2'):
        """
        Load and initialize all DO sensors defined in the configuration file.
        
        Scans the device configuration file for DO sensor definitions and creates
        instances for each configured sensor. Each sensor is initialized with its
        specific configuration parameters including address, baud rate, and position.
        
        Args:
            port (str): Default serial port for sensor communication
            
        Note:
            - Looks for keys starting with 'DO_' in the SENSORS section
            - Creates singleton instances for each sensor ID
            - Validates configuration format before initialization
            - Logs warnings for invalid or missing configurations
        """
        config = globals.DEVICE_CONFIG_FILE
        
        try:
            if 'SENSORS' in config:
                for key, value in config['SENSORS'].items():
                    if key.upper().startswith("DO_"):
                        sensor_id = key
                        cls(sensor_id, port)
                        logger.info(f"Loaded sensor with ID: {sensor_id}")
            else:
                logger.info("No 'SENSORS' section found in the configuration file.")
        except Exception as e:
            logger.info(f"Failed to load sensors: {e}")

    @classmethod
    def get_statuses_async(cls):
        """
        Asynchronously get status from all DO sensors.
        
        Queues status requests for all initialized DO sensor instances using
        the Modbus client's asynchronous command system. Each sensor will
        process its response independently through the event emitter.
        
        Note:
            - Uses a small delay (0.01s) between sensors to avoid command conflicts
            - Responses are handled asynchronously via _handle_response method
            - Each sensor maintains its own pending commands queue
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
        """
        Initialize a DO sensor instance with configuration parameters.
        
        Sets up the sensor with its configuration from the device.conf file,
        initializes the Modbus client connection, and subscribes to response
        events. This method is called automatically when creating a new sensor
        instance.
        
        Args:
            sensor_id (str): Unique identifier for the sensor
            port (str): Serial port for Modbus communication
            
        Note:
            - Loads address, baud rate, and position from configuration
            - Subscribes to 'DO' events from the Modbus client
            - Initializes pending commands queue for async operations
        """
        logger.info(f"Initializing the DO instance for {sensor_id} in {port}.")
        self.sensor_id = sensor_id
        self.port = port
        self.data_path = globals.SAVED_SENSOR_DATA_PATH
        self.address = globals.get_device_address('SENSORS', sensor_id, '0x40')
        self.baud_rate = globals.get_device_baudrate('SENSORS', sensor_id, 9600)
        self.position = globals.get_device_position('SENSORS', sensor_id, "main")
        self.do = None
        self.last_updated = None
        
        logger.info(f"DO sensor {sensor_id} loaded with address: {hex(self.address)}")

        # Update modbus client initialization
        self.modbus_client = globals.modbus_client
        self.modbus_client.event_emitter.subscribe('DO', self._handle_response)
        self.pending_commands = {}

    def open_connection(self):
        self.ser = serial.Serial(self.port, self.baud_rate, serial.EIGHTBITS, serial.PARITY_NONE, serial.STOPBITS_ONE)
        
    def close_connection(self):
        self.ser.close()



    def get_status_async(self):
        """
        Queue a status request command with the modbus client.
        
        Sends a Modbus RTU read holding registers command to read the DO value
        from register 0x0014. The response will be handled asynchronously by
        _handle_response via the event emitter system.
        
        Command Format:
        - Function Code: 0x03 (Read Holding Registers)
        - Starting Address: 0x0014 (DO value register)
        - Number of Registers: 2
        
        Note:
            - Response length expected: 9 bytes
            - Timeout: 0.5 seconds
            - Command ID is stored for response matching
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
        """
        Check if oxygenation is needed based on current DO levels.
        
        Determines whether the water needs additional oxygenation based on
        the current dissolved oxygen reading. Uses a threshold-based approach
        for automated system control.
        
        Returns:
            bool: True if DO level is below threshold (7.0 mg/L), False otherwise
            
        Note:
            - Returns False if DO reading is None (sensor error)
            - Threshold can be adjusted based on system requirements
            - Used for automated pump and aeration control
        """
        if self.do is None:
            return False
        return self.do < 7.0


if __name__ == "__main__":
    DO.load_all_sensors(port='/dev/ttyAMA2')

    while True:
        DO.get_statuses_async()
        time.sleep(5)  # Update every 2 seconds
