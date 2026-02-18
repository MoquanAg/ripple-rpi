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

logger = GlobalLogger("RippleNPK", log_prefix="ripple_").logger

try:
    # Try importing when running from main directory
    import src.helpers as helpers
except ImportError:
    # Import when running from src directory
    import helpers


class NPK:
    """
    Soil NPK (Nitrogen/Phosphorus/Potassium) index sensor with Modbus RTU communication.

    Model: DC-SNPK-S01. Measures soil fertility indices via RS485 Modbus RTU.
    Values are unitless indices (0-1999), approximately equivalent to mg/kg
    under normal soil conditions.

    Register Map:
    - 0x001E: Nitrogen index (read-only)
    - 0x001F: Phosphorus index (read-only)
    - 0x0020: Potassium index (read-only)
    - 0x0100: Device address (read/write, 0-252)
    - 0x0101: Baud rate (read/write, 2400/4800/9600)
    """

    REGISTERS = {
        'nitrogen': 0x001E,
        'phosphorus': 0x001F,
        'potassium': 0x0020,
        'slave_addr': 0x0100,
        'baudrate': 0x0101,
    }

    _instances = {}  # Dictionary to hold multiple instances

    @classmethod
    def load_all_sensors(cls, port='/dev/ttyAMA2'):
        config = globals.DEVICE_CONFIG_FILE

        try:
            if 'SENSORS' in config:
                for key, value in config['SENSORS'].items():
                    if key.upper().startswith("NPK_"):
                        if value.strip().lower().startswith('null'):
                            logger.info(f"NPK sensor {key} is disabled (null configuration), skipping initialization")
                            continue

                        sensor_id = key
                        cls(sensor_id, port)
                        logger.info(f"Loaded NPK sensor with ID: {sensor_id}")
            else:
                logger.info("No 'SENSORS' section found in the configuration file.")
        except Exception as e:
            logger.info(f"Failed to load NPK sensors: {e}")

    @classmethod
    def get_statuses_async(cls):
        for _, sensor_instance in NPK._instances.items():
            sensor_instance.get_status_async()
            time.sleep(0.01)

    def __new__(cls, sensor_id, *args, **kwargs):
        if sensor_id not in cls._instances:
            logger.debug(f"Creating the NPK instance for {sensor_id}.")
            instance = super(NPK, cls).__new__(cls)
            instance.init(sensor_id, *args, **kwargs)
            cls._instances[sensor_id] = instance
        return cls._instances[sensor_id]

    def init(self, sensor_id, port='/dev/ttyAMA2'):
        logger.info(f"Initializing the NPK instance for {sensor_id} in {port}.")
        self.sensor_id = sensor_id
        self.port = globals.get_device_port('SENSORS', sensor_id, port)
        self.data_path = globals.SAVED_SENSOR_DATA_PATH
        self.address = globals.get_device_address('SENSORS', sensor_id, '0x01')
        self.baud_rate = globals.get_device_baudrate('SENSORS', sensor_id, 9600)
        self.position = globals.get_device_position('SENSORS', sensor_id, "main")
        self.nitrogen = None
        self.phosphorus = None
        self.potassium = None
        self.last_updated = None

        logger.info(f"NPK sensor {sensor_id} loaded with address: {hex(self.address)}")

        self.modbus_client = globals.modbus_client
        self.modbus_client.event_emitter.subscribe('NPK', self._handle_response)
        self.pending_commands = {}

    def get_status_async(self):
        """Read N, P, K registers (0x001E-0x0020) in a single request."""
        command = bytearray([
            self.address,
            0x03,            # Read Holding Registers
            0x00, 0x1E,      # Starting address (0x001E = nitrogen)
            0x00, 0x03       # Number of registers (3: N, P, K)
        ])
        command_id = self.modbus_client.send_command(
            device_type='NPK',
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=11,  # 1(addr) + 1(func) + 1(byte_count) + 6(data) + 2(CRC)
            timeout=0.5
        )
        self.pending_commands[command_id] = {'type': 'get_status'}
        logger.debug(f"Sent get status command for NPK_{self.sensor_id} with UUID: {command_id}")

    def _handle_response(self, response: ModbusResponse) -> None:
        if response.command_id not in self.pending_commands:
            return

        command_info = self.pending_commands[response.command_id]
        if response.status == 'success':
            if command_info['type'] == 'get_status':
                self._process_status_response(response.data)
        elif response.status in ['timeout', 'error', 'connection_lost']:
            logger.warning(f"Command failed with status {response.status} for {self.sensor_id}")
            self.save_null_data()
        del self.pending_commands[response.command_id]

    def _process_status_response(self, data):
        """Process the raw response data. Each value is a 16-bit unsigned integer (0-1999)."""
        if data and len(data) == 11:  # addr(1) + func(1) + byte_count(1) + data(6) + CRC(2)
            try:
                nitrogen = int.from_bytes(data[3:5], byteorder='big')
                phosphorus = int.from_bytes(data[5:7], byteorder='big')
                potassium = int.from_bytes(data[7:9], byteorder='big')

                # Validate: sensor range is 0-1999
                for name, val in [('nitrogen', nitrogen), ('phosphorus', phosphorus), ('potassium', potassium)]:
                    if val > 1999:
                        logger.warning(f"Invalid {name} value: {val} for {self.sensor_id}")
                        self.save_null_data()
                        return

                self.nitrogen = nitrogen
                self.phosphorus = phosphorus
                self.potassium = potassium
                self.last_updated = helpers.datetime_to_iso8601()

                logger.info(f"{self.sensor_id} - N: {nitrogen}, P: {phosphorus}, K: {potassium}")
                self.save_data()
            except Exception as e:
                logger.warning(f"Error processing response for {self.sensor_id}: {e}")
                self.save_null_data()
        else:
            logger.debug(f"Invalid response from {self.sensor_id} length: {len(data) if data else 0} while should be 11")
            self.save_null_data()

    def save_null_data(self):
        self.nitrogen = None
        self.phosphorus = None
        self.potassium = None
        self.last_updated = helpers.datetime_to_iso8601()
        self.save_data()

    def save_data(self):
        data = {
            "measurements": {
                "name": "soil_metrics",
                "points": [
                    {
                        "tags": {
                            "sensor": "npk",
                            "measurement": "npk",
                            "location": self.sensor_id
                        },
                        "fields": {
                            "nitrogen": self.nitrogen,
                            "phosphorus": self.phosphorus,
                            "potassium": self.potassium,
                        },
                        "timestamp": self.last_updated
                    }
                ]
            }
        }
        helpers.save_sensor_data(['data', 'soil_metrics', 'npk'], data)
        logger.log_sensor_data(['data', 'soil_metrics', 'npk'], data)

    def is_connected(self):
        try:
            response = self.modbus_client.read_holding_registers(
                port=self.port,
                address=self.REGISTERS['nitrogen'],  # 0x001E
                count=1,
                slave_addr=self.address,
                baudrate=self.baud_rate,
                timeout=0.5,
                device_name='NPK_connectivity_check'
            )
            connected = not response.isError() and response.registers is not None
            if not connected:
                logger.debug(f"NPK sensor {self.sensor_id} not responding")
            return connected
        except Exception as e:
            logger.debug(f"NPK sensor {self.sensor_id} connectivity check failed: {e}")
            return False

    @classmethod
    def get_connection_statuses(cls):
        statuses = {}
        for sensor_id, sensor_instance in cls._instances.items():
            statuses[sensor_id] = sensor_instance.is_connected()
        return statuses


if __name__ == "__main__":
    NPK.load_all_sensors(port='/dev/ttyAMA2')

    while True:
        NPK.get_statuses_async()
        time.sleep(5)
