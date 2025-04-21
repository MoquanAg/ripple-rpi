import os
import configparser
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError
from datetime import datetime
import json
import queue
from lumina_modbus_client import LuminaModbusClient
import ast

# Absolute path of the current directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

#############################################
#############################################
# Logger
LOG_FOLDER_PATH = os.path.join(BASE_DIR, "..", "log")
os.makedirs(LOG_FOLDER_PATH, exist_ok=True)
from lumina_logger import GlobalLogger

logger = GlobalLogger().logger


#############################################
#############################################
# Intervals
SENSOR_DATA_FETCH_INTERVAL = 30
SENSOR_DATA_UPLOAD_INTERVAL = 60

REALTIME_MODE = False
REALTIME_MODE_SENSOR_DATA_FETCH_INTERVAL = 10
REALTIME_MODE_SENSOR_DATA_UPLOAD_INTERVAL = 10

# System reboot configuration
DAILY_REBOOT_ENABLED = True
DAILY_REBOOT_HOUR = 4
DAILY_REBOOT_MINUTE = 0

#############################################
#############################################
# Configuration files

SYSTEM_CONF_PATH = os.path.join(BASE_DIR, "..", "system.conf")
SYSTEM_CONFIG_FILE = configparser.ConfigParser()
if not os.path.exists(SYSTEM_CONF_PATH):
    logger.error(f"System configuration file not found at {SYSTEM_CONF_PATH}")
else:
    loaded_files = SYSTEM_CONFIG_FILE.read(SYSTEM_CONF_PATH)
    if not loaded_files:
        logger.error(f"Failed to load system configuration from {SYSTEM_CONF_PATH}")

DEVICE_CONF_PATH = os.path.join(BASE_DIR, "..", "device.conf")
DEVICE_CONFIG_FILE = configparser.ConfigParser()
if not os.path.exists(DEVICE_CONF_PATH):
    logger.error(f"Device configuration file not found at {DEVICE_CONF_PATH}")
else:
    loaded_files = DEVICE_CONFIG_FILE.read(DEVICE_CONF_PATH)
    if not loaded_files:
        logger.error(f"Failed to load device configuration from {DEVICE_CONF_PATH}")
    else:
        # Verify the SENSORS section exists
        if 'SENSORS' not in DEVICE_CONFIG_FILE:
            logger.warning("No 'SENSORS' section found in device configuration")
        else:
            logger.info("Device configuration loaded successfully")


# Get availabilities from device config
def get_availability(key, default=0):
    """Get device availability from SYSTEM section or sensor definition"""
    try:
        device_name = key
        # First check if the device has a non-null entry in SENSORS or CLIMATE_CONTROL
        if key.startswith('has_'):
            device_name = key[4:]  # Remove 'has_' prefix
            
        device_name = device_name.replace('_', '')
        
        # Handle special case for solar sensor
        if device_name == 'solarsensor':
            device_name = 'solarirradiance'
            
        # print(f"Checking availability for device_name: {device_name}")
        
        # Check SYSTEM section
        if 'SYSTEM' in DEVICE_CONFIG_FILE and device_name in DEVICE_CONFIG_FILE['SYSTEM']:
            value = DEVICE_CONFIG_FILE['SYSTEM'][device_name]
            return not is_invalid_value(value)
            
        # Check SENSORS section
        if 'SENSORS' in DEVICE_CONFIG_FILE and device_name in DEVICE_CONFIG_FILE['SENSORS']:
            value = DEVICE_CONFIG_FILE['SENSORS'][device_name].split(',')[0]  # Get first field
            return not is_invalid_value(value)
            
        # Check CLIMATE_CONTROL section
        if 'CLIMATE_CONTROL' in DEVICE_CONFIG_FILE and device_name in DEVICE_CONFIG_FILE['CLIMATE_CONTROL']:
            value = DEVICE_CONFIG_FILE['CLIMATE_CONTROL'][device_name].split(',')[0]  # Get first field
            return not is_invalid_value(value)
            
        # Special handling for relay - check RELAY_CONTROL section
        if device_name == 'relay':
            # Check if RELAY_CONTROL section exists and has any relay entries
            if 'RELAY_CONTROL' in DEVICE_CONFIG_FILE:
                for key in DEVICE_CONFIG_FILE['RELAY_CONTROL']:
                    if key.lower().startswith('relay'):
                        value = DEVICE_CONFIG_FILE['RELAY_CONTROL'][key].split(',')[0]
                        if not is_invalid_value(value):
                            return True
            return False
            
        return bool(default)
    except Exception as e:
        logger.warning(f"Error in get_availability for {key}: {e}")
        return bool(default)

def is_invalid_value(value):
    """Check if a value is considered invalid/disabled (null or none)"""
    if not value:  # Handle empty or None values
        return True
    value_lower = str(value).lower().strip()
    return value_lower in ['null', 'none', '']

def count_enabled_devices(prefix, section):
    """Count number of enabled (non-null) devices with given prefix in section"""
    try:
        count = 0
        if section in DEVICE_CONFIG_FILE:
            for key, value in DEVICE_CONFIG_FILE[section].items():
                if key.upper().startswith(prefix.upper()):
                    # Parse the value - if it's a comma-separated string, check first part
                    parts = [p.strip() for p in value.split(',')]
                    # Consider device enabled if neither full value nor first part is null/none
                    if not is_invalid_value(value) and not is_invalid_value(parts[0]):
                        count += 1
        return count
    except:
        return 0

def get_availability_value(key, default=0):
    """Get numeric values from SYSTEM section or count enabled devices"""
    try:
        # Special handling for device counts
        if key == "num_thc_sensors":
            return count_enabled_devices("THC_", "SENSORS")
        if key == "num_gutters":
            return int(DEVICE_CONFIG_FILE.get("SYSTEM", "num_gutters", fallback=default))
        return int(DEVICE_CONFIG_FILE.get('SYSTEM', key))
    except:
        return default

def get_device_address(section, key, default_hex='0x00'):
    """Get device address from appropriate section"""
    try:
        if section in DEVICE_CONFIG_FILE and key in DEVICE_CONFIG_FILE[section]:
            value = DEVICE_CONFIG_FILE[section][key].split(',')[4].strip()  # Get address from 5th field
            return int(value, 16)
        return int(default_hex, 16)
    except:
        return int(default_hex, 16)

def get_device_port(section, key, default_port='/dev/ttyAMA2'):
    """Get device port from appropriate section"""
    try:
        if section in DEVICE_CONFIG_FILE and key in DEVICE_CONFIG_FILE[section]:
            return DEVICE_CONFIG_FILE[section][key].split(',')[3].strip()  # Get port from 4th field
        return default_port
    except:
        return default_port

def get_device_position(section, key, default_position=''):
    """Get device position from appropriate section"""
    try:
        if section in DEVICE_CONFIG_FILE and key in DEVICE_CONFIG_FILE[section]:
            return DEVICE_CONFIG_FILE[section][key].split(',')[1].strip()  # Get position from 2nd field
        return default_position
    except:
        return default_position

def get_device_baudrate(section, key, default_baudrate=9600):
    """Get device baudrate from appropriate section"""
    try:
        if section in DEVICE_CONFIG_FILE and key in DEVICE_CONFIG_FILE[section]:
            return int(DEVICE_CONFIG_FILE[section][key].split(',')[5].strip())  # Get baudrate from 6th field
        return default_baudrate
    except:
        return default_baudrate

# Map system values to availabilities
MOTOR_SET = get_availability_value("motor_set")
HAS_LASER = get_availability("laser")
NUM_GUTTERS = get_availability_value("num_gutters")
NUM_THC_SENSORS = get_availability_value("num_thc_sensors")
HAS_NANOBUBBLER = get_availability("nanobubbler")
HAS_LIQUID_COOLING = get_availability("liquid_cooling")
HAS_SPRINKLER = get_availability("sprinkler")
HAS_CO2 = get_availability("co2")
HAS_DO_SENSOR = get_availability("do_sensor")
HAS_AC_CONTROL = get_availability("ac_control")
HAS_SOLAR_SENSOR = get_availability("solar_sensor")
HAS_THERMAL_IMAGING = get_availability("thermal_imaging")
HAS_PUMP_NUTRIENT_TANK_TO_GUTTERS = get_availability("pump_nutrient_tank_to_gutters")
HAS_RELAY = get_availability("relay")
HAS_WATER_METER = get_availability("water_meter")
HAS_WATER_LEVEL = get_availability("water_level")
HAS_FRESH_AIR_SYSTEM = get_availability("fresh_air_system")
HAS_DEHUMIDIFIER = get_availability("dehumidifier")
HAS_FERTIGATION = get_availability("fertigation")
FERTIGATION_MODEL = DEVICE_CONFIG_FILE.get("SYSTEM", "fertigation_model", fallback="none")


#############################################
#############################################
# Local data persistence

DATA_FOLDER_PATH = os.path.join(BASE_DIR, "..", "data")
os.makedirs(DATA_FOLDER_PATH, exist_ok=True)
SAVED_SENSOR_DATA_PATH = os.path.join(DATA_FOLDER_PATH, "saved_sensor_data.json")
SENSOR_DATA_LOG_PATH = os.path.join(DATA_FOLDER_PATH, "sensor_data")

# Add near the top with other file paths
DEVICE_STATUS_PATH = os.path.join(DATA_FOLDER_PATH, "device_status.json")

def saved_sensor_data():
    try:
        # Attempt to open and load the JSON file
        with open(SAVED_SENSOR_DATA_PATH, "r") as file:
            sensor_data = json.load(file)
            return sensor_data
    except:
        return None


#############################################
#############################################
# Relay
def get_relay_assignment(relay_board, index):
    """Get relay assignment from config file"""
    try:
        section = "RELAY_ASSIGNMENTS"
        key = f"Relay_{relay_board}_{index}_to_{index+3}"
        if section in DEVICE_CONFIG_FILE and key in DEVICE_CONFIG_FILE[section]:
            assignments = DEVICE_CONFIG_FILE[section][key].split(',')
            return [x.strip() for x in assignments]
        return []
    except:
        return []

# Get relay assignments
CO2Valve = -1
LiquidCoolingPumpAndFan = -1
Sprinkler = -1
PumpFromNutrientTankToGutters = -1
Laser = -1
Nanobubbler = -1

# Parse ONE_0_to_3
relay_one_0_3 = get_relay_assignment("ONE", 0)
if len(relay_one_0_3) >= 4:
    PumpFromNutrientTankToGutters = 0 if "PumpFromNutrientTankToGutters" in relay_one_0_3 else -1
    Sprinkler = 2 if "Sprinkler" in relay_one_0_3 else -1

# Parse TWO_0_to_3
relay_two_0_3 = get_relay_assignment("TWO", 0)
if len(relay_two_0_3) >= 4:
    Laser = 0 if "LaserA" in relay_two_0_3 else -1

# Parse TWO_4_to_7
relay_two_4_7 = get_relay_assignment("TWO", 4)
if len(relay_two_4_7) >= 4:
    CO2Valve = 4 if "CO2A" in relay_two_4_7 else -1

#############################################
#############################################
# Loop Logging
LOOP_INTERVAL = 30  # seconds
LOOP_LOG_FREQUENCY = 1  # times
LOOP_COUNT = 0


def SHOULD_LOG():
    global LOOP_COUNT
    if LOOP_COUNT % LOOP_LOG_FREQUENCY == 0:
        return True
    return False


#############################################
#############################################

RELAY_NAME = "relay"
RELAY_ADDRESS = get_device_address('RELAY_CONTROL', 'RelayOne', '0x10')

#############################################
#############################################
# APScheduler
scheduler = BackgroundScheduler()
_scheduler_running = False  # Add this flag to track scheduler state


def start_scheduler():
    global scheduler, _scheduler_running
    if not _scheduler_running:
        scheduler = BackgroundScheduler()
        scheduler.start()
        _scheduler_running = True
        
        # Add daily reboot job if enabled
        if DAILY_REBOOT_ENABLED:
            from system_reboot import safe_system_reboot
            scheduler.add_job(
                safe_system_reboot,
                'cron',
                hour=DAILY_REBOOT_HOUR,
                minute=DAILY_REBOOT_MINUTE,
                id='daily_system_reboot'
            )
            logger.info(f"Scheduled daily system reboot for {DAILY_REBOOT_HOUR:02d}:{DAILY_REBOOT_MINUTE:02d}")


def shutdown_scheduler():
    global _scheduler_running
    logger.info("Shutting down scheduler...")
    try:
        if _scheduler_running:
            scheduler.shutdown(wait=False)  # Don't wait for jobs to complete
            _scheduler_running = False
            logger.info("Scheduler shutdown complete")
    except Exception as e:
        logger.error(f"Error during scheduler shutdown: {e}")


def is_scheduler_running():
    return _scheduler_running and scheduler.running


# Update the existing scheduler.start() call
if not _scheduler_running:
    start_scheduler()


def remove_scheduler_job(job_id):
    try:
        scheduler.remove_job(job_id)
        logger.info(f"Removed existing job from BackgroundScheduler: {job_id}")
    except:
        logger.info(f"No existing job found in BackgroundScheduler with id: {job_id}")


def list_scheduler_jobs():
    jobs = sorted(scheduler.get_jobs(), key=lambda x: x.id)

    # Create a dictionary to store job information
    scheduler_data = {
        "background_scheduler": [],
        "last_updated": datetime.now().isoformat(),
    }

    if jobs:
        logger.info("\n")
        logger.info("Scheduled tasks:")

        for job in jobs:
            job_info = get_job_info(job, "BackgroundScheduler")
            scheduler_data["background_scheduler"].append(job_info)
            log_job_info(job, "BackgroundScheduler")

        logger.info("\n")
    else:
        logger.info("No scheduled tasks found.")

    # Save scheduler data
    logger.log_sensor_data(["data", "scheduler"], scheduler_data)


def get_job_info(job, scheduler_type):
    """Extract relevant job information into a dictionary"""
    job_info = {
        "scheduler_type": scheduler_type,
        "task_id": job.id,
        "next_run_time": (
            job.next_run_time.isoformat()
            if hasattr(job, "next_run_time") and job.next_run_time
            else None
        ),
        "trigger": str(job.trigger),
        "function": job.func.__name__,
        "args": str(job.args),
        "kwargs": str(job.kwargs),
    }
    return job_info


def log_job_info(job, scheduler_type):
    logger.info(f"Scheduler: {scheduler_type}")
    logger.info(f"Task ID: {job.id}")
    if hasattr(job, "next_run_time") and job.next_run_time:
        logger.info(f"Next Run Time: {job.next_run_time}")
    else:
        logger.info("Next Run Time: None")
    logger.info(f"Trigger: {job.trigger}")
    logger.info(f"Function: {job.func.__name__}")
    logger.info(f"Arguments: {job.args}")
    logger.info(f"Keyword Arguments: {job.kwargs}")
    logger.info("------------------------")


def should_task_be_executing(task_id):
    job = scheduler.get_job(task_id)

    if job:
        current_time = datetime.now()

        # Check if the job has a next_run_time attribute
        if hasattr(job, "next_run_time") and job.next_run_time:
            start_time = job.next_run_time.replace(tzinfo=None)
        else:
            logger.info(
                f"Job {task_id} has no next_run_time. Assuming it should not be executing."
            )
            return False

        try:
            end_job = scheduler.get_job(f"{task_id}_end")
            if end_job and hasattr(end_job, "next_run_time"):
                end_run_time = end_job.next_run_time.replace(tzinfo=None)
            else:
                end_run_time = None
        except JobLookupError:
            end_run_time = None

        if start_time <= current_time and (
            end_run_time is None or current_time < end_run_time
        ):
            logger.info("Task should be executing")
            return True
        else:
            logger.info("Task should not be executing")
            return False
    else:
        logger.info(f"No job found for task_id: {task_id}")
        return False


modbus_command_queue = queue.Queue()

modbus_client = LuminaModbusClient()
modbus_client.connect()  # or modbus_client.connect(host='your_host', port=your_port)
