#!/usr/bin/env python3

import os
import sys
import json
import configparser
import subprocess  # Added for system commands
from typing import Dict, List, Optional, Union, Any
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import secrets
from datetime import datetime
import uvicorn

# Add the src directory to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, 'src')
sys.path.append(src_dir)

# Import controller modules
import globals
import helpers
from src.lumina_logger import GlobalLogger
from src.sensors.water_level import WaterLevel
from src.sensors.Relay import Relay
from src.sensors.DO import DO
from src.sensors.pH import pH
from src.sensors.ec import EC
from main import RippleController

# Pydantic models for API requests/responses
class RelayControl(BaseModel):
    relay_id: str
    state: bool

class TargetUpdate(BaseModel):
    target: float
    deadband: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None

class SystemStatus(BaseModel):
    system: str
    version: str
    status: str
    last_update: str

class PlumbingConfig(BaseModel):
    valve_outside_to_tank: Optional[bool] = None
    valve_tank_to_outside: Optional[bool] = None
    pump_from_tank_to_gutters: Optional[bool] = None

class SprinklerConfig(BaseModel):
    sprinkler_on_at_startup: Optional[bool] = None
    sprinkler_on_duration: Optional[str] = None
    sprinkler_wait_duration: Optional[str] = None

class ManualCommand(BaseModel):
    abc_ratio: str
    target_ec_max: float
    target_ec_min: float
    target_ec_deadband: float
    target_ph_max: float
    target_ph_min: float
    target_ph_deadband: float
    sprinkler_on_duration: str
    sprinkler_wait_duration: str
    recirculation_wait_duration: str
    recirculation_on_duration: str
    target_water_temperature_max: float
    target_water_temperature_min: float
    target_ec: float
    target_ph: float

class ActionCommand(BaseModel):
    nutrient_pump_a: Optional[bool] = None
    nutrient_pump_b: Optional[bool] = None
    nutrient_pump_c: Optional[bool] = None
    ph_up_pump: Optional[bool] = None
    ph_down_pump: Optional[bool] = None
    valve_outside_to_tank: Optional[bool] = None
    valve_tank_to_outside: Optional[bool] = None
    mixing_pump: Optional[bool] = None
    pump_from_tank_to_gutters: Optional[bool] = None
    sprinkler_a: Optional[bool] = None
    sprinkler_b: Optional[bool] = None
    pump_from_collector_tray_to_tank: Optional[bool] = None

# Set up logging using GlobalLogger
logger = GlobalLogger("RippleAPI", log_prefix="ripple_server_").logger
logger.info("Starting Ripple API Server")

# Create FastAPI app
app = FastAPI(title="Ripple Fertigation API", 
              description="REST API for monitoring and controlling the Ripple fertigation system",
              version="1.0.0")

# Add CORS middleware to allow requests from other origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Basic authentication
security = HTTPBasic()

# Read credentials from device.conf
config = configparser.ConfigParser()
config.read('config/device.conf')
USERNAME = config.get('SYSTEM', 'username').strip('"')
PASSWORD = config.get('SYSTEM', 'password').strip('"')

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, USERNAME)
    correct_password = secrets.compare_digest(credentials.password, PASSWORD)
    if not (correct_username and correct_password):
        logger.warning(f"Failed authentication attempt for user: {credentials.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    logger.info(f"Successful authentication for user: {credentials.username}")
    return credentials.username

# Initialize the controller
controller = RippleController()

def _time_to_seconds(time_str):
    """
    Convert HH:MM:SS format time string to total seconds.
    
    Parses a time string in HH:MM:SS format and converts it to the total
    number of seconds. This is used for time-based configuration parameters.
    
    Args:
        time_str (str): Time string in HH:MM:SS format
        
    Returns:
        int: Total number of seconds
        
    Example:
        >>> _time_to_seconds("01:30:45")
        5445
        
    Note:
        - Raises ValueError if format is invalid
        - Used for parsing duration parameters in configuration
    """
    hours, minutes, seconds = map(int, time_str.split(':'))
    return hours * 3600 + minutes * 60 + seconds

def _parse_config_value(section, key, config_parser, preferred_index=1):
    """
    Parse configuration values that may have comma-separated parts.
    
    Args:
        section (str): Config section name
        key (str): Config key name 
        config_parser: ConfigParser instance
        preferred_index (int): Index of value to use (0 for default, 1 for operational)
        
    Returns:
        str: Parsed value with whitespace and quotes removed
    """
    try:
        raw_value = config_parser.get(section, key)
        
        if ',' in raw_value:
            parts = raw_value.split(',')
            if len(parts) > preferred_index:
                # Use the preferred index (usually 1 for operational value)
                value = parts[preferred_index].strip()
            else:
                # Fall back to first value if preferred index doesn't exist
                value = parts[0].strip()
        else:
            # No comma, just use the whole value
            value = raw_value.strip()
            
        # Strip any quotes and handle boolean conversion
        value = value.strip('"\'')
        
        # Convert string boolean values to actual booleans
        if value.lower() in ('true', 'false'):
            return value.lower() == 'true'
        
        logger.debug(f"Parsed config value for {section}.{key}: '{raw_value}' -> '{value}' (using index {preferred_index})")
        return value
    except Exception as e:
        logger.error(f"Error parsing config value for {section}.{key}: {e}")
        # Return first part as a fallback
        try:
            return config_parser.get(section, key).split(',')[0].strip()
        except:
            return ""

def get_valid_relay_fields():
    """
    Dynamically read valid relay control fields from device.conf.
    
    Scans the device configuration file to determine which relay control fields
    are valid for the current system configuration. This ensures API requests
    only contain fields that are actually supported by the hardware.
    
    Returns:
        List[str]: List of valid relay control field names
        
    Note:
        - Reads from [RELAY_CONTROLS] section in device.conf
        - Maps config field names to API field names
        - Includes special fields like 'device_id' and 'sprinkler'
        - Returns hardcoded fallback list if config reading fails
        - Used for API request validation
    """
    try:
        config = configparser.ConfigParser()
        config.read('config/device.conf')
        
        if not config.has_section('RELAY_CONTROLS'):
            logger.warning("No [RELAY_CONTROLS] section found in device.conf")
            return []
        
        # Mapping from config field names (lowercase) to API field names
        field_mapping = {
            'nutrient_pump_a': 'nutrient_pump_a',
            'nutrient_pump_b': 'nutrient_pump_b', 
            'nutrient_pump_c': 'nutrient_pump_c',
            'phuppump': 'ph_up_pump',  # configparser converts to lowercase
            'phdownpump': 'ph_down_pump',  # configparser converts to lowercase
            'valve_outside_to_tank': 'valve_outside_to_tank',
            'valve_tank_to_outside': 'valve_tank_to_outside',
            'mixing_pump': 'mixing_pump',
            'pump_from_tank_to_gutters': 'pump_from_tank_to_gutters',
            'sprinkler_a': 'sprinkler_a',
            'sprinkler_b': 'sprinkler_b',
            'pump_from_collector_tray_to_tank': 'pump_from_collector_tray_to_tank',
            'nanobubbler': 'nanobubbler'
        }
        
        valid_fields = []
        
        # Get all keys from RELAY_CONTROLS section and map to API field names
        for key in config.options('RELAY_CONTROLS'):
            if key in field_mapping:
                valid_fields.append(field_mapping[key])
            else:
                # For unmapped fields, convert to lowercase
                api_field = key.lower()
                valid_fields.append(api_field)
        
        # Add special fields that are always valid
        special_fields = ['device_id', 'sprinkler']  # sprinkler is special case for both sprinkler_a and sprinkler_b
        valid_fields.extend(special_fields)
        
        # Remove duplicates while preserving order
        valid_fields = list(dict.fromkeys(valid_fields))
        
        logger.info(f"Loaded {len(valid_fields)} valid relay fields from device.conf: {valid_fields}")
        return valid_fields
        
    except Exception as e:
        logger.error(f"Error reading valid relay fields from device.conf: {e}")
        # Fallback to hardcoded list if config reading fails
        return [
            'device_id', 'nutrient_pump_a', 'nutrient_pump_b', 'nutrient_pump_c',
            'ph_up_pump', 'ph_down_pump', 'valve_outside_to_tank', 'valve_tank_to_outside',
            'mixing_pump', 'pump_from_tank_to_gutters', 'sprinkler', 'sprinkler_a',
            'sprinkler_b', 'pump_from_collector_tray_to_tank', 'nanobubbler'
        ]

def update_device_conf(instruction_set: Dict) -> bool:
    """
    Update device.conf with values from server instruction set.
    
    Processes a server instruction set and updates the device configuration file
    with new fertigation parameters. This function handles the mapping from
    server instruction format to device.conf format while preserving existing
    secondary values in comma-separated entries.
    
    Args:
        instruction_set (Dict): Server instruction set containing fertigation parameters
        
    Returns:
        bool: True if update successful, False otherwise
        
    Note:
        - Updates pH, EC, nutrient pump, sprinkler, water temperature, and recirculation settings
        - Preserves second values in comma-separated configuration entries
        - Writes updated configuration back to device.conf file
        - Logs success/failure and handles exceptions
    """
    try:
        # Read current device.conf
        config = configparser.ConfigParser()
        config.read('config/device.conf')
        
        # Get fertigation settings from instruction set
        fertigation = instruction_set['current_phase']['details']['action_fertigation']
        
        # Update pH settings - keep second value unchanged
        current_ph_target = config.get('pH', 'ph_target').split(',')[1].strip()
        config.set('pH', 'ph_target', f"{fertigation['target_ph']}, {current_ph_target}")
        
        current_ph_deadband = config.get('pH', 'ph_deadband').split(',')[1].strip()
        config.set('pH', 'ph_deadband', f"{fertigation['target_ph_deadband']}, {current_ph_deadband}")
        
        current_ph_min = config.get('pH', 'ph_min').split(',')[1].strip()
        config.set('pH', 'ph_min', f"{fertigation['target_ph_min']}, {current_ph_min}")
        
        current_ph_max = config.get('pH', 'ph_max').split(',')[1].strip()
        config.set('pH', 'ph_max', f"{fertigation['target_ph_max']}, {current_ph_max}")
        
        # Update EC settings - keep second value unchanged
        current_ec_target = config.get('EC', 'ec_target').split(',')[1].strip()
        config.set('EC', 'ec_target', f"{fertigation['target_ec']}, {current_ec_target}")
        
        current_ec_deadband = config.get('EC', 'ec_deadband').split(',')[1].strip()
        config.set('EC', 'ec_deadband', f"{fertigation['target_ec_deadband']}, {current_ec_deadband}")
        
        current_ec_min = config.get('EC', 'ec_min').split(',')[1].strip()
        config.set('EC', 'ec_min', f"{fertigation['target_ec_min']}, {current_ec_min}")
        
        current_ec_max = config.get('EC', 'ec_max').split(',')[1].strip()
        config.set('EC', 'ec_max', f"{fertigation['target_ec_max']}, {current_ec_max}")
        
        # Update NutrientPump settings - keep second value unchanged
        current_abc_ratio = config.get('NutrientPump', 'abc_ratio').split(',')[1].strip()
        config.set('NutrientPump', 'abc_ratio', f'"{fertigation["abc_ratio"]}", {current_abc_ratio}')
        
        # Update Sprinkler settings - keep second value unchanged
        current_sprinkler_on = config.get('Sprinkler', 'sprinkler_on_duration').split(',')[1].strip()
        config.set('Sprinkler', 'sprinkler_on_duration', f"{fertigation['sprinkler_on_duration']}, {current_sprinkler_on}")
        
        current_sprinkler_wait = config.get('Sprinkler', 'sprinkler_wait_duration').split(',')[1].strip()
        config.set('Sprinkler', 'sprinkler_wait_duration', f"{fertigation['sprinkler_wait_duration']}, {current_sprinkler_wait}")
        
        # Update WaterTemperature settings - keep second value unchanged
        current_temp = config.get('WaterTemperature', 'target_water_temperature').split(',')[1].strip()
        config.set('WaterTemperature', 'target_water_temperature', f"{fertigation['target_water_temperature_min']}, {current_temp}")
        
        current_temp_min = config.get('WaterTemperature', 'target_water_temperature_min').split(',')[1].strip()
        config.set('WaterTemperature', 'target_water_temperature_min', f"{fertigation['target_water_temperature_min']}, {current_temp_min}")
        
        current_temp_max = config.get('WaterTemperature', 'target_water_temperature_max').split(',')[1].strip()
        config.set('WaterTemperature', 'target_water_temperature_max', f"{fertigation['target_water_temperature_max']}, {current_temp_max}")
        
        # Update Recirculation settings - keep second value unchanged
        current_recirc_on = config.get('Recirculation', 'recirculation_on_duration').split(',')[1].strip()
        config.set('Recirculation', 'recirculation_on_duration', f"{fertigation['recirculation_on_duration']}, {current_recirc_on}")
        
        current_recirc_wait = config.get('Recirculation', 'recirculation_wait_duration').split(',')[1].strip()
        config.set('Recirculation', 'recirculation_wait_duration', f"{fertigation['recirculation_wait_duration']}, {current_recirc_wait}")
        
        # Write updated config back to file
        with open('config/device.conf', 'w') as configfile:
            config.write(configfile)
            
        logger.info("Successfully updated device.conf with new instruction set")
        return True
    except Exception as e:
        logger.error(f"Error updating device.conf: {e}")
        return False

@app.get("/api/v1/system", response_model=SystemStatus, tags=["General"])
async def system_info(username: str = Depends(verify_credentials)):
    """
    Get system information and status.
    
    Returns basic information about the Ripple Fertigation System including
    system name, version, current status, and last update timestamp.
    
    Returns:
        SystemStatus: System information object containing:
            - system (str): System name "Ripple Fertigation System"
            - version (str): Current system version "1.0.0"
            - status (str): Current system status "online"
            - last_update (str): ISO 8601 timestamp of last update
            
    Note:
        - Requires HTTP Basic Authentication
        - Returns real-time timestamp for last_update field
        - Used for system health monitoring and API discovery
    """
    logger.info("System information endpoint accessed")
    return {
        "system": "Ripple Fertigation System",
        "version": "1.0.0",
        "status": "online",
        "last_update": datetime.now().isoformat()
    }

def update_device_conf_from_manual(command: ManualCommand) -> bool:
    """
    Update device.conf with values from manual command.
    
    Processes a manual command from the user and updates the device configuration
    file with new fertigation parameters. This function handles the mapping from
    manual command format to device.conf format while preserving existing
    secondary values in comma-separated entries.
    
    Args:
        command (ManualCommand): Manual command object containing fertigation parameters
        
    Returns:
        bool: True if update successful, False otherwise
        
    Note:
        - Updates pH, EC, nutrient pump, sprinkler, water temperature, and recirculation settings
        - Preserves second values in comma-separated configuration entries
        - Writes updated configuration back to device.conf file
        - Logs success/failure and handles exceptions
        - Used for manual override of system parameters
    """
    try:
        # Read current device.conf
        config = configparser.ConfigParser()
        config.read('config/device.conf')
        
        # Update pH settings - keep second value unchanged
        current_ph_target = config.get('pH', 'ph_target').split(',')[1].strip()
        config.set('pH', 'ph_target', f"{command.target_ph}, {current_ph_target}")
        
        current_ph_deadband = config.get('pH', 'ph_deadband').split(',')[1].strip()
        config.set('pH', 'ph_deadband', f"{command.target_ph_deadband}, {current_ph_deadband}")
        
        current_ph_min = config.get('pH', 'ph_min').split(',')[1].strip()
        config.set('pH', 'ph_min', f"{command.target_ph_min}, {current_ph_min}")
        
        current_ph_max = config.get('pH', 'ph_max').split(',')[1].strip()
        config.set('pH', 'ph_max', f"{command.target_ph_max}, {current_ph_max}")
        
        # Update EC settings - keep second value unchanged
        current_ec_target = config.get('EC', 'ec_target').split(',')[1].strip()
        config.set('EC', 'ec_target', f"{command.target_ec}, {current_ec_target}")
        
        current_ec_deadband = config.get('EC', 'ec_deadband').split(',')[1].strip()
        config.set('EC', 'ec_deadband', f"{command.target_ec_deadband}, {current_ec_deadband}")
        
        current_ec_min = config.get('EC', 'ec_min').split(',')[1].strip()
        config.set('EC', 'ec_min', f"{command.target_ec_min}, {current_ec_min}")
        
        current_ec_max = config.get('EC', 'ec_max').split(',')[1].strip()
        config.set('EC', 'ec_max', f"{command.target_ec_max}, {current_ec_max}")
        
        # Update NutrientPump settings - keep second value unchanged
        current_abc_ratio = config.get('NutrientPump', 'abc_ratio').split(',')[1].strip()
        config.set('NutrientPump', 'abc_ratio', f'"{command.abc_ratio}", {current_abc_ratio}')
        
        # Update Sprinkler settings - keep second value unchanged
        current_sprinkler_on = config.get('Sprinkler', 'sprinkler_on_duration').split(',')[1].strip()
        config.set('Sprinkler', 'sprinkler_on_duration', f"{command.sprinkler_on_duration}, {current_sprinkler_on}")
        
        current_sprinkler_wait = config.get('Sprinkler', 'sprinkler_wait_duration').split(',')[1].strip()
        config.set('Sprinkler', 'sprinkler_wait_duration', f"{command.sprinkler_wait_duration}, {current_sprinkler_wait}")
        
        # Update WaterTemperature settings - keep second value unchanged
        current_temp = config.get('WaterTemperature', 'target_water_temperature').split(',')[1].strip()
        config.set('WaterTemperature', 'target_water_temperature', f"{command.target_water_temperature_min}, {current_temp}")
        
        current_temp_min = config.get('WaterTemperature', 'target_water_temperature_min').split(',')[1].strip()
        config.set('WaterTemperature', 'target_water_temperature_min', f"{command.target_water_temperature_min}, {current_temp_min}")
        
        current_temp_max = config.get('WaterTemperature', 'target_water_temperature_max').split(',')[1].strip()
        config.set('WaterTemperature', 'target_water_temperature_max', f"{command.target_water_temperature_max}, {current_temp_max}")
        
        # Update Recirculation settings - keep second value unchanged
        current_recirc_on = config.get('Recirculation', 'recirculation_on_duration').split(',')[1].strip()
        config.set('Recirculation', 'recirculation_on_duration', f"{command.recirculation_on_duration}, {current_recirc_on}")
        
        current_recirc_wait = config.get('Recirculation', 'recirculation_wait_duration').split(',')[1].strip()
        config.set('Recirculation', 'recirculation_wait_duration', f"{command.recirculation_wait_duration}, {current_recirc_wait}")
        
        # Write updated config back to file
        with open('config/device.conf', 'w') as configfile:
            config.write(configfile)
            
        logger.info("Successfully updated device.conf with manual command")
        return True
    except Exception as e:
        logger.error(f"Error updating device.conf: {e}")
        return False

@app.post("/api/v1/server_instruction_set", tags=["Control"])
async def update_instruction_set(instruction_set: Dict, username: str = Depends(verify_credentials)):
    """
    Update system configuration from server instruction set.
    
    Applies configuration changes received from the central server. This endpoint
    processes instruction sets that contain fertigation parameters including pH,
    EC, nutrient ratios, sprinkler settings, water temperature targets, and
    recirculation parameters.
    
    Args:
        instruction_set (Dict): Server instruction set containing:
            - current_phase.details.action_fertigation: Fertigation parameters
            - target_ph: pH target value
            - target_ph_deadband: pH deadband for control
            - target_ph_min/max: pH minimum and maximum limits
            - target_ec: EC target value
            - target_ec_deadband: EC deadband for control
            - target_ec_min/max: EC minimum and maximum limits
            - abc_ratio: Nutrient A:B:C ratio
            - sprinkler_on_duration: Sprinkler activation time
            - sprinkler_wait_duration: Sprinkler wait time
            - target_water_temperature_min/max: Water temperature limits
            - recirculation_on_duration: Recirculation activation time
            - recirculation_wait_duration: Recirculation wait time
            
    Returns:
        Dict: Response object containing:
            - status (str): "success" or "error"
            - message (str): Success or error message
            
    Note:
        - Requires HTTP Basic Authentication
        - Updates device.conf file with new parameters
        - Preserves second values in comma-separated configuration entries
        - Returns 500 error if configuration update fails
    """
    try:
        if update_device_conf(instruction_set):
            return {"status": "success", "message": "Instruction set applied successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to apply instruction set")
    except Exception as e:
        logger.error(f"Error applying instruction set: {e}")
        raise HTTPException(status_code=500, detail=f"Error applying instruction set: {str(e)}")

@app.post("/api/v1/user_instruction_set", tags=["Control"])
async def update_manual_command(command: ManualCommand, username: str = Depends(verify_credentials)):
    """
    Update system configuration from user manual command.
    
    Applies configuration changes from user-provided manual commands. This endpoint
    allows direct user control of fertigation parameters through the API, bypassing
    the server instruction set system.
    
    Args:
        command (ManualCommand): Manual command object containing:
            - abc_ratio (str): Nutrient A:B:C ratio
            - target_ec_max/min (float): EC maximum and minimum targets
            - target_ec_deadband (float): EC deadband for control
            - target_ph_max/min (float): pH maximum and minimum targets
            - target_ph_deadband (float): pH deadband for control
            - sprinkler_on_duration (str): Sprinkler activation duration
            - sprinkler_wait_duration (str): Sprinkler wait duration
            - recirculation_wait_duration (str): Recirculation wait duration
            - recirculation_on_duration (str): Recirculation activation duration
            - target_water_temperature_max/min (float): Water temperature limits
            - target_ec (float): Primary EC target value
            - target_ph (float): Primary pH target value
            
    Returns:
        Dict: Response object containing:
            - status (str): "success" or "error"
            - message (str): Success or error message
            
    Note:
        - Requires HTTP Basic Authentication
        - Updates device.conf file with new parameters
        - Preserves second values in comma-separated configuration entries
        - Returns 500 error if configuration update fails
        - Used for manual override and direct user control
    """
    try:
        if update_device_conf_from_manual(command):
            return {"status": "success", "message": "User instruction set applied successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to apply user instruction set")
    except Exception as e:
        logger.error(f"Error applying user instruction set: {e}")
        raise HTTPException(status_code=500, detail=f"Error applying user instruction set: {str(e)}")

@app.get("/api/v1/status", tags=["Status"])
async def get_system_status(username: str = Depends(verify_credentials)):
    """
    Get current system status in a simplified format.
    
    Returns a comprehensive status object containing current sensor readings,
    target values, relay states, and system configuration. This endpoint
    provides a unified view of the entire fertigation system state.
    
    Returns:
        Dict: System status object containing:
            - Sensor readings:
                - ph (float): Current pH value
                - ph_temperature (float): pH sensor temperature
                - ec (float): Current EC value
                - ec_tds (float): Total Dissolved Solids
                - ec_salinity (float): Salinity measurement
                - ec_temperature (float): EC sensor temperature
                - water_level (float): Current water level
            - Target values:
                - target_ph (float): pH target
                - ph_deadband (float): pH deadband
                - ph_min/max (float): pH limits
                - target_ec (float): EC target
                - ec_deadband (float): EC deadband
                - ec_min/max (float): EC limits
                - target_water_level (float): Water level target
                - water_level_deadband (float): Water level deadband
                - water_level_min/max (float): Water level limits
            - Configuration:
                - abc_ratio (str): Nutrient ratio
                - sprinkler_on_duration (str): Sprinkler timing
                - sprinkler_wait_duration (str): Sprinkler wait time
                - target_water_temperature (float): Water temperature target
                - target_water_temperature_min/max (float): Temperature limits
            - Relay states:
                - relays (List[Dict]): List of relay states with port, status, and device info
            - timestamp (str): ISO 8601 timestamp of status update
            
    Note:
        - Requires HTTP Basic Authentication
        - Reads data from saved_sensor_data.json and device.conf
        - Returns 500 error if data cannot be read or processed
        - Used for system monitoring and dashboard display
    """
    try:
        # Read current sensor data
        with open('data/saved_sensor_data.json', 'r') as f:
            sensor_data = json.load(f)
        
        # Extract essential sensor values
        simplified_status = {}
        
        # Extract sensor values
        if 'data' in sensor_data and 'water_metrics' in sensor_data['data']:
            water_metrics = sensor_data['data']['water_metrics']
            
            # Extract pH value
            if 'ph' in water_metrics and 'measurements' in water_metrics['ph']:
                ph_points = water_metrics['ph']['measurements']['points']
                if ph_points:
                    simplified_status['ph'] = ph_points[-1]['fields']['value']
                    simplified_status['ph_temperature'] = ph_points[-1]['fields']['temperature']
            
            # Extract EC value
            if 'ec' in water_metrics and 'measurements' in water_metrics['ec']:
                ec_points = water_metrics['ec']['measurements']['points']
                if ec_points:
                    simplified_status['ec'] = ec_points[-1]['fields']['value']
                    # Extract additional EC data
                    simplified_status['ec_tds'] = ec_points[-1]['fields'].get('tds')
                    simplified_status['ec_salinity'] = ec_points[-1]['fields'].get('salinity')
                    simplified_status['ec_temperature'] = ec_points[-1]['fields'].get('temperature')
            
            # Extract water level
            if 'water_level' in water_metrics and 'measurements' in water_metrics['water_level']:
                water_level_points = water_metrics['water_level']['measurements']['points']
                if water_level_points:
                    simplified_status['water_level'] = water_level_points[-1]['fields']['value']
        
        # Extract target values from config file
        try:
            config = configparser.ConfigParser()
            config.read('config/device.conf')
            
            # pH targets
            if config.has_section('pH'):
                simplified_status['target_ph'] = float(config.get('pH', 'ph_target').split(',')[0])
                simplified_status['ph_deadband'] = float(config.get('pH', 'ph_deadband').split(',')[0])
                simplified_status['ph_min'] = float(config.get('pH', 'ph_min').split(',')[0])
                simplified_status['ph_max'] = float(config.get('pH', 'ph_max').split(',')[0])
            
            # EC targets
            if config.has_section('EC'):
                simplified_status['target_ec'] = float(config.get('EC', 'ec_target').split(',')[0])
                simplified_status['ec_deadband'] = float(config.get('EC', 'ec_deadband').split(',')[0])
                simplified_status['ec_min'] = float(config.get('EC', 'ec_min').split(',')[0])
                simplified_status['ec_max'] = float(config.get('EC', 'ec_max').split(',')[0])
            
            # Water level targets
            if config.has_section('WaterLevel'):
                simplified_status['target_water_level'] = float(config.get('WaterLevel', 'water_level_target').split(',')[0])
                simplified_status['water_level_deadband'] = float(config.get('WaterLevel', 'water_level_deadband').split(',')[0])
                simplified_status['water_level_min'] = float(config.get('WaterLevel', 'water_level_min').split(',')[0])
                simplified_status['water_level_max'] = float(config.get('WaterLevel', 'water_level_max').split(',')[0])
            
            # Nutrient pump settings
            if config.has_section('NutrientPump'):
                simplified_status['abc_ratio'] = config.get('NutrientPump', 'abc_ratio').split(',')[0].strip('"')
            
            # Sprinkler settings
            if config.has_section('Sprinkler'):
                simplified_status['sprinkler_on_duration'] = config.get('Sprinkler', 'sprinkler_on_duration').split(',')[0].strip('"')
                simplified_status['sprinkler_wait_duration'] = config.get('Sprinkler', 'sprinkler_wait_duration').split(',')[0].strip('"')
                # Add sprinkler_on_at_startup operational value
                if config.has_option('Sprinkler', 'sprinkler_on_at_startup'):
                    startup_value = _parse_config_value('Sprinkler', 'sprinkler_on_at_startup', config, preferred_index=1)
                    simplified_status['sprinkler_on_at_startup'] = startup_value
            
            # Water temperature targets
            if config.has_section('WaterTemperature'):
                simplified_status['target_water_temperature'] = float(config.get('WaterTemperature', 'target_water_temperature').split(',')[0])
                simplified_status['target_water_temperature_min'] = float(config.get('WaterTemperature', 'target_water_temperature_min').split(',')[0])
                simplified_status['target_water_temperature_max'] = float(config.get('WaterTemperature', 'target_water_temperature_max').split(',')[0])
            
            # Plumbing operational values
            if config.has_section('PLUMBING'):
                simplified_status['plumbing'] = {}
                for key in config.options('PLUMBING'):
                    operational_value = _parse_config_value('PLUMBING', key, config, preferred_index=1)
                    api_key = key.lower()
                    simplified_status['plumbing'][api_key] = operational_value
                
        except Exception as e:
            logger.warning(f"Error reading config targets: {e}")
        
        # Extract relay states in the desired format
        if 'data' in sensor_data and 'relay_metrics' in sensor_data['data']:
            relay_points = sensor_data['data']['relay_metrics']['measurements']['points']
            relay_list = []
            for point in relay_points:
                if 'tags' in point and 'fields' in point:
                    relay_list.append({
                        "port": str(point['tags']['port_index']),
                        "status": bool(point['fields']['status']),
                        "as": point['tags']['device']
                    })
            simplified_status['relays'] = relay_list
        
        # Add timestamp
        simplified_status['timestamp'] = helpers.datetime_to_iso8601()
        
        return simplified_status
    except Exception as e:
        logger.error(f"Error getting system status: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting system status: {str(e)}")

@app.post("/api/v1/action", tags=["Control"])
async def update_action(request: dict, username: str = Depends(verify_credentials)):
    """
    Update action configuration and save to action.json.
    
    Controls relay states and device actions through the API. This endpoint
    validates relay control requests, processes special cases like sprinkler
    control, and saves the configuration to action.json for the control system.
    
    Args:
        request (dict): Action request object containing:
            - device_id (str, optional): Device identifier for device-specific control
            - relay control fields (bool): State for various relays including:
                - nutrient_pump_a/b/c: Nutrient pump controls
                - ph_up_pump/ph_down_pump: pH adjustment pumps
                - valve_outside_to_tank/valve_tank_to_outside: Valve controls
                - mixing_pump: Mixing pump control
                - pump_from_tank_to_gutters: Tank to gutter pump
                - sprinkler/sprinkler_a/sprinkler_b: Sprinkler controls
                - pump_from_collector_tray_to_tank: Collector tray pump
                - nanobubbler: Nanobubbler control
            
    Returns:
        Dict: Response object containing:
            - status (str): "success" or "error"
            - message (str): Success or error message
            
    Note:
        - Requires HTTP Basic Authentication
        - Validates field names against device.conf configuration
        - Validates field types (device_id as string, others as boolean)
        - Special handling for sprinkler control with device_id support
        - Saves processed request to config/action.json
        - Returns error for invalid fields or types
    """
    try:
        logger.info(f"Received raw action request: {request}")
        
        # Dynamically read valid API field names from device.conf
        valid_fields = get_valid_relay_fields()
        
        # Check for invalid fields
        invalid_fields = []
        for field in request:
            if field not in valid_fields:
                invalid_fields.append(field)
                
        if invalid_fields:
            error_msg = f"Invalid action fields: {', '.join(invalid_fields)}"
            logger.warning(error_msg)
            return {
                "status": "error",
                "message": error_msg
            }
        
        # Check for valid field types
        for field, value in request.items():
            if field == 'device_id':
                # device_id should be a string
                if not isinstance(value, str):
                    error_msg = f"Field {field} must be a string, got {type(value).__name__}"
                    logger.warning(error_msg)
                    return {
                        "status": "error",
                        "message": error_msg
                    }
            else:
                # All other fields should be boolean
                if not isinstance(value, bool):
                    error_msg = f"Field {field} must be a boolean, got {type(value).__name__}"
                    logger.warning(error_msg)
                    return {
                        "status": "error",
                        "message": error_msg
                    }
        
        # Process special case for sprinkler with device_id support
        processed_request = request.copy()
        device_id = processed_request.pop('device_id', None)  # Extract device_id if present
        
        if 'sprinkler' in processed_request:
            sprinkler_value = processed_request.pop('sprinkler')
            
            if device_id:
                # Use device-specific sprinkler control - execute directly
                logger.info(f"Using device-specific sprinkler control for device_id: {device_id}, value: {sprinkler_value}")
                try:
                    from src.sensors.Relay import Relay
                    relay = Relay()
                    if relay:
                        result = relay.set_sprinklers_with_device_id(device_id, sprinkler_value)
                        logger.info(f"Device-specific sprinkler control result: {result}")
                    else:
                        logger.warning("No relay hardware available for device-specific sprinkler control")
                except Exception as e:
                    logger.error(f"Error in device-specific sprinkler control: {e}")
                    logger.exception("Full exception details:")
            else:
                # Legacy behavior: Set both sprinkler relays to the same value
                processed_request['sprinkler_a'] = sprinkler_value
                processed_request['sprinkler_b'] = sprinkler_value
                logger.info(f"Mapped 'sprinkler' to both sprinkler_a and sprinkler_b with value {sprinkler_value}")
        
        # Save to action.json
        with open('config/action.json', 'w') as f:
            json.dump(processed_request, f, indent=2)
            
        logger.info(f"Action updated successfully: {processed_request}")
        return {"status": "success", "message": "Action updated successfully"}
    except Exception as e:
        logger.error(f"Error updating action: {e}")
        return {
            "status": "error",
            "message": f"Error updating action: {str(e)}"
        }

@app.post("/api/v1/system/reboot", tags=["System"])
async def system_reboot(username: str = Depends(verify_credentials)):
    """
    Reboot the system using sudo reboot command.
    
    Initiates a system reboot by executing the sudo reboot command. This
    endpoint provides remote system restart capability for maintenance
    and troubleshooting purposes.
    
    Returns:
        Dict: Response object containing:
            - status (str): "success"
            - message (str): "System reboot initiated"
            
    Note:
        - Requires HTTP Basic Authentication
        - Executes sudo reboot command using subprocess
        - Returns immediately after initiating reboot
        - System will be unavailable during reboot process
        - Use with caution as it will interrupt all operations
    """
    try:
        logger.info("System reboot requested by user")
        
        # Execute reboot command
        subprocess.Popen(['sudo', 'reboot'], 
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)
        
        return {"status": "success", "message": "System reboot initiated"}
    except Exception as e:
        logger.error(f"Error initiating system reboot: {e}")
        raise HTTPException(status_code=500, detail=f"Error initiating system reboot: {str(e)}")

@app.post("/api/v1/system/restart", tags=["System"])
async def system_restart(username: str = Depends(verify_credentials)):
    """
    Restart Ripple application by calling the headless restart script.
    
    Restarts the Ripple fertigation application without rebooting the entire
    system. This endpoint executes the start_ripple_headless.sh script to
    gracefully restart the application services.
    
    Returns:
        Dict: Response object containing:
            - status (str): "success"
            - message (str): "Ripple application restart initiated"
            
    Note:
        - Requires HTTP Basic Authentication
        - Executes start_ripple_headless.sh script using subprocess
        - Returns immediately after initiating restart
        - Application will be temporarily unavailable during restart
        - System remains operational, only application services restart
    """
    try:
        logger.info("Ripple application restart requested by user")
        
        # Get the path to the headless script
        ripple_path = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.join(ripple_path, 'start_ripple_headless.sh')
        
        # Execute the script in the background
        subprocess.Popen(['bash', script_path], 
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)
        
        return {"status": "success", "message": "Ripple application restart initiated"}
    except Exception as e:
        logger.error(f"Error restarting Ripple application: {e}")
        raise HTTPException(status_code=500, detail=f"Error restarting Ripple application: {str(e)}")

@app.get("/api/v1/plumbing", tags=["Plumbing"])
async def get_plumbing_config(username: str = Depends(verify_credentials)):
    """
    Get current plumbing configuration (operational values).
    
    Returns the operational values from the PLUMBING section of device.conf.
    These are the second values in the comma-separated format which represent
    the current operational state of plumbing devices.
    
    Returns:
        Dict: Plumbing configuration object containing:
            - valve_outside_to_tank (bool): Current state of valve from outside to tank
            - valve_tank_to_outside (bool): Current state of valve from tank to outside  
            - pump_from_tank_to_gutters (bool): Current state of pump from tank to gutters
            
    Note:
        - Requires HTTP Basic Authentication
        - Reads operational values (second value) from PLUMBING section
        - Returns 500 error if configuration cannot be read
    """
    try:
        config = configparser.ConfigParser()
        config.read('config/device.conf')
        
        plumbing_config = {}
        
        if config.has_section('PLUMBING'):
            # Read operational values (index 1) from PLUMBING section
            for key in config.options('PLUMBING'):
                operational_value = _parse_config_value('PLUMBING', key, config, preferred_index=1)
                # Convert to snake_case for API consistency
                api_key = key.lower()
                if isinstance(operational_value, str) and operational_value.lower() in ('true', 'false'):
                    plumbing_config[api_key] = operational_value.lower() == 'true'
                else:
                    plumbing_config[api_key] = operational_value
        
        logger.info(f"Retrieved plumbing configuration: {plumbing_config}")
        return plumbing_config
        
    except Exception as e:
        logger.error(f"Error getting plumbing configuration: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting plumbing configuration: {str(e)}")

@app.post("/api/v1/plumbing", tags=["Plumbing"])
async def update_plumbing_config(plumbing_config: PlumbingConfig, username: str = Depends(verify_credentials)):
    """
    Update plumbing configuration operational values.
    
    Updates the operational values (second values) in the PLUMBING section of device.conf
    while preserving the default values (first values). Also applies the changes
    immediately to the relay hardware.
    
    Args:
        plumbing_config (PlumbingConfig): Plumbing configuration object containing:
            - valve_outside_to_tank (bool, optional): State of valve from outside to tank
            - valve_tank_to_outside (bool, optional): State of valve from tank to outside
            - pump_from_tank_to_gutters (bool, optional): State of pump from tank to gutters
            
    Returns:
        Dict: Response object containing:
            - status (str): "success" or "error"
            - message (str): Success or error message
            - applied_changes (dict): Changes that were applied
            
    Note:
        - Requires HTTP Basic Authentication
        - Updates operational values (second value) in device.conf
        - Preserves default values (first value) in configuration
        - Immediately applies changes to relay hardware
        - Returns 500 error if configuration update fails
    """
    try:
        config = configparser.ConfigParser()
        config.read('config/device.conf')
        
        applied_changes = {}
        
        # Ensure PLUMBING section exists
        if not config.has_section('PLUMBING'):
            config.add_section('PLUMBING')
        
        # Map API field names to config field names
        field_mapping = {
            'valve_outside_to_tank': 'ValveOutsideToTank',
            'valve_tank_to_outside': 'ValveTankToOutside', 
            'pump_from_tank_to_gutters': 'PumpFromTankToGutters'
        }
        
        # Update provided fields
        for api_field, value in plumbing_config.dict(exclude_unset=True).items():
            if value is not None and api_field in field_mapping:
                config_field = field_mapping[api_field]
                
                # Get current value to preserve default (first) value
                if config.has_option('PLUMBING', config_field):
                    current_value = config.get('PLUMBING', config_field)
                    if ',' in current_value:
                        default_value = current_value.split(',')[0].strip()
                    else:
                        default_value = current_value.strip()
                else:
                    # If field doesn't exist, use the new value as default too
                    default_value = str(value).lower()
                
                # Set new value with preserved default
                new_value = f"{default_value}, {str(value).lower()}"
                config.set('PLUMBING', config_field, new_value)
                applied_changes[api_field] = value
                
                logger.info(f"Updated {config_field}: {new_value}")
        
        # Write updated config back to file
        with open('config/device.conf', 'w') as configfile:
            config.write(configfile)
        
        # Apply changes to relay hardware immediately
        if applied_changes:
            relay = controller.relays.get('relay')
            if relay:
                for api_field, value in applied_changes.items():
                    try:
                        if api_field == 'valve_outside_to_tank':
                            relay.set_valve_outside_to_tank(value)
                        elif api_field == 'valve_tank_to_outside':
                            relay.set_valve_tank_to_outside(value)
                        elif api_field == 'pump_from_tank_to_gutters':
                            relay.set_pump_from_tank_to_gutters(value)
                        logger.info(f"Applied {api_field} = {value} to relay hardware")
                    except Exception as e:
                        logger.warning(f"Failed to apply {api_field} to hardware: {e}")
            else:
                logger.warning("No relay hardware available to apply plumbing changes")
        
        logger.info(f"Successfully updated plumbing configuration: {applied_changes}")
        return {
            "status": "success", 
            "message": "Plumbing configuration updated successfully",
            "applied_changes": applied_changes
        }
        
    except Exception as e:
        logger.error(f"Error updating plumbing configuration: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating plumbing configuration: {str(e)}")

@app.get("/api/v1/sprinkler", tags=["Sprinkler"])
async def get_sprinkler_config(username: str = Depends(verify_credentials)):
    """
    Get current sprinkler configuration (operational values).
    
    Returns the operational values from the Sprinkler section of device.conf.
    These are the second values in the comma-separated format which represent
    the current operational state of sprinkler settings.
    
    Returns:
        Dict: Sprinkler configuration object containing:
            - sprinkler_on_at_startup (bool): Whether sprinklers turn on at system startup
            - sprinkler_on_duration (str): Duration sprinklers stay on
            - sprinkler_wait_duration (str): Wait time between sprinkler cycles
            
    Note:
        - Requires HTTP Basic Authentication
        - Reads operational values (second value) from Sprinkler section
        - Returns 500 error if configuration cannot be read
    """
    try:
        config = configparser.ConfigParser()
        config.read('config/device.conf')
        
        sprinkler_config = {}
        
        if config.has_section('Sprinkler'):
            # Read operational values (index 1) from Sprinkler section
            for key in config.options('Sprinkler'):
                operational_value = _parse_config_value('Sprinkler', key, config, preferred_index=1)
                # Convert to snake_case for API consistency
                api_key = key.lower()
                sprinkler_config[api_key] = operational_value
        
        logger.info(f"Retrieved sprinkler configuration: {sprinkler_config}")
        return sprinkler_config
        
    except Exception as e:
        logger.error(f"Error getting sprinkler configuration: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting sprinkler configuration: {str(e)}")

@app.post("/api/v1/sprinkler", tags=["Sprinkler"])
async def update_sprinkler_config(sprinkler_config: SprinklerConfig, username: str = Depends(verify_credentials)):
    """
    Update sprinkler configuration operational values.
    
    Updates the operational values (second values) in the Sprinkler section of device.conf
    while preserving the default values (first values). Also applies the changes
    immediately to the sprinkler system.
    
    Args:
        sprinkler_config (SprinklerConfig): Sprinkler configuration object containing:
            - sprinkler_on_at_startup (bool, optional): Whether sprinklers turn on at startup
            - sprinkler_on_duration (str, optional): Duration sprinklers stay on (HH:MM:SS)
            - sprinkler_wait_duration (str, optional): Wait time between cycles (HH:MM:SS)
            
    Returns:
        Dict: Response object containing:
            - status (str): "success" or "error"
            - message (str): Success or error message
            - applied_changes (dict): Changes that were applied
            
    Note:
        - Requires HTTP Basic Authentication
        - Updates operational values (second value) in device.conf
        - Preserves default values (first value) in configuration
        - For sprinkler_on_at_startup changes, applies immediately to hardware
        - Returns 500 error if configuration update fails
    """
    try:
        config = configparser.ConfigParser()
        config.read('config/device.conf')
        
        applied_changes = {}
        
        # Ensure Sprinkler section exists
        if not config.has_section('Sprinkler'):
            config.add_section('Sprinkler')
        
        # Update provided fields
        for api_field, value in sprinkler_config.dict(exclude_unset=True).items():
            if value is not None:
                # Get current value to preserve default (first) value
                if config.has_option('Sprinkler', api_field):
                    current_value = config.get('Sprinkler', api_field)
                    if ',' in current_value:
                        default_value = current_value.split(',')[0].strip()
                    else:
                        default_value = current_value.strip()
                else:
                    # If field doesn't exist, use the new value as default too
                    if isinstance(value, bool):
                        default_value = str(value).lower()
                    else:
                        default_value = str(value)
                
                # Set new value with preserved default
                if isinstance(value, bool):
                    new_value = f"{default_value}, {str(value).lower()}"
                else:
                    new_value = f"{default_value}, {str(value)}"
                    
                config.set('Sprinkler', api_field, new_value)
                applied_changes[api_field] = value
                
                logger.info(f"Updated {api_field}: {new_value}")
        
        # Write updated config back to file
        with open('config/device.conf', 'w') as configfile:
            config.write(configfile)
        
        # Apply sprinkler_on_at_startup changes immediately if present
        if 'sprinkler_on_at_startup' in applied_changes:
            startup_value = applied_changes['sprinkler_on_at_startup']
            relay = controller.relays.get('relay')
            if relay:
                try:
                    if startup_value:
                        # Turn on sprinklers if startup is enabled
                        relay.set_sprinklers(True)
                        logger.info(f"Applied sprinkler_on_at_startup = {startup_value} - sprinklers turned ON")
                    else:
                        # Turn off sprinklers if startup is disabled
                        relay.set_sprinklers(False)
                        logger.info(f"Applied sprinkler_on_at_startup = {startup_value} - sprinklers turned OFF")
                except Exception as e:
                    logger.warning(f"Failed to apply sprinkler_on_at_startup to hardware: {e}")
            else:
                logger.warning("No relay hardware available to apply sprinkler startup changes")
        
        # NOTE: No need to reschedule future cycles here
        # The file system watcher will handle config changes and the sprinkler controller
        # will automatically schedule the next cycle when the current cycle stops
        if 'sprinkler_wait_duration' in applied_changes:
            logger.info("[API] Wait duration changed - next cycle will use new duration when current cycle stops")
        
        logger.info(f"Successfully updated sprinkler configuration: {applied_changes}")
        return {
            "status": "success", 
            "message": "Sprinkler configuration updated successfully",
            "applied_changes": applied_changes
        }
        
    except Exception as e:
        logger.error(f"Error updating sprinkler configuration: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating sprinkler configuration: {str(e)}")

# Run the server if script is executed directly
if __name__ == "__main__":
    logger.info("Starting Ripple API Server on 0.0.0.0:5000")
    uvicorn.run("server:app", host="0.0.0.0", port=5000, reload=False) 