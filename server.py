#!/usr/bin/env python3

import os
import sys
import json
import configparser
import subprocess  # Added for system commands
import threading
from typing import Dict, List, Optional, Union, Any
from fastapi import FastAPI, HTTPException, Depends, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import secrets
import time
from datetime import datetime
import uvicorn

# Add the src directory to the Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, 'src')
sys.path.append(src_dir)

# Import controller modules
import src.globals as globals
import src.helpers as helpers
from src.lumina_logger import GlobalLogger
from src.sensors.water_level import WaterLevel
from src.sensors.Relay import Relay
from src.sensors.DO import DO
from src.sensors.pH import pH
from src.sensors.ec import EC
from src.sensor_scanner import SensorScanner, ScanRequest

try:
    from audit_event import audit
except Exception:
    audit = None

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
    valve_outside_to_tank_on_at_startup: Optional[bool] = None
    valve_tank_to_outside_on_at_startup: Optional[bool] = None
    pump_from_tank_to_gutters_on_at_startup: Optional[bool] = None
    mixing_pump_on_at_startup: Optional[bool] = None
    pump_from_collector_tray_to_tank_on_at_startup: Optional[bool] = None
    liquid_cooling_pump_and_fan_on_at_startup: Optional[bool] = None
    valve_co2_on_at_startup: Optional[bool] = None

class SprinklerConfig(BaseModel):
    sprinkler_on_at_startup: Optional[bool] = None
    sprinkler_on_duration: Optional[str] = None
    sprinkler_wait_duration: Optional[str] = None

class FertigationConfig(BaseModel):
    """Unified fertigation configuration. All fields optional — omitted fields keep current device.conf values."""
    abc_ratio: Optional[str] = None
    target_ec_max: Optional[float] = None
    target_ec_min: Optional[float] = None
    target_ec_deadband: Optional[float] = None
    target_ec: Optional[float] = None
    target_ph_max: Optional[float] = None
    target_ph_min: Optional[float] = None
    target_ph_deadband: Optional[float] = None
    target_ph: Optional[float] = None
    sprinkler_on_duration: Optional[str] = None
    sprinkler_wait_duration: Optional[str] = None
    recirculation_wait_duration: Optional[str] = None
    recirculation_on_duration: Optional[str] = None
    target_water_temperature_max: Optional[float] = None
    target_water_temperature_min: Optional[float] = None

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

class DrainRequest(BaseModel):
    action: str  # 'start' or 'stop'
    target_level: Optional[float] = None
    drain_amount: Optional[float] = None
    duration_seconds: Optional[int] = None
    mode: Optional[str] = 'drain'  # 'drain', 'flush', 'full_drain'
    reason: Optional[str] = 'manual'

class HeartbeatRequest(BaseModel):
    timestamp: Optional[float] = None
    edge_id: Optional[str] = None

# Set up logging using GlobalLogger
logger = GlobalLogger("RippleAPI", log_prefix="ripple_server_").logger
logger.info("Starting Ripple API Server")

# Operating mode: "passive" (Edge controls) or "autonomous" (Ripple controls)
_mode_lock = threading.Lock()
_current_mode = "autonomous"  # Start autonomous until Edge checks in
_last_heartbeat_time = 0.0    # time.time() of last heartbeat
_edge_ip = None               # IP of Edge device (captured from heartbeat sender)
HEARTBEAT_TIMEOUT_S = 60      # Switch to autonomous after 60s without heartbeat

def get_mode():
    with _mode_lock:
        return _current_mode

def set_mode(mode):
    global _current_mode
    with _mode_lock:
        old = _current_mode
        _current_mode = mode
        if old != mode:
            logger.info(f"Mode changed: {old} -> {mode}")

def get_last_heartbeat_time():
    with _mode_lock:
        return _last_heartbeat_time

def update_heartbeat(edge_ip=None):
    global _last_heartbeat_time, _edge_ip
    with _mode_lock:
        _last_heartbeat_time = time.time()
        if edge_ip:
            _edge_ip = edge_ip

def get_edge_ip():
    with _mode_lock:
        return _edge_ip

# Create FastAPI app
app = FastAPI(title="Ripple Fertigation API", 
              description="REST API for monitoring and controlling the Ripple fertigation system",
              version="1.0.0")

# Add CORS middleware - restrict to local network access only
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:8000",
        "http://0.0.0.0:8000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Basic authentication
security = HTTPBasic()

# Read credentials from device.conf with validation
config = configparser.ConfigParser()
config_path = os.path.join(current_dir, 'config', 'device.conf')

# Default credentials (should be overridden by config)
USERNAME = "admin"
PASSWORD = "admin"

try:
    if os.path.exists(config_path):
        config.read(config_path)
        if config.has_section('SYSTEM'):
            if config.has_option('SYSTEM', 'username'):
                USERNAME = config.get('SYSTEM', 'username').strip('"').strip()
            if config.has_option('SYSTEM', 'password'):
                PASSWORD = config.get('SYSTEM', 'password').strip('"').strip()

            if not USERNAME or not PASSWORD:
                logger.warning("Empty username or password in config, using defaults")
                USERNAME = USERNAME or "admin"
                PASSWORD = PASSWORD or "admin"
        else:
            logger.warning("No SYSTEM section in device.conf, using default credentials")
    else:
        logger.error(f"Config file not found at {config_path}, using default credentials")
except Exception as e:
    logger.error(f"Error reading config file: {e}, using default credentials")

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
        except Exception:
            return ""


def _safe_get_first_value(config_parser, section, key, default=""):
    """
    Safely get the first comma-separated value from a config entry.

    Args:
        config_parser: ConfigParser instance
        section (str): Config section name
        key (str): Config key name
        default (str): Default value if first value doesn't exist

    Returns:
        str: The first value or default
    """
    try:
        raw_value = config_parser.get(section, key)
        parts = raw_value.split(',')
        return parts[0].strip()
    except Exception as e:
        logger.warning(f"Could not get first value for {section}.{key}: {e}")
        return default


def _safe_get_second_value(config_parser, section, key, default=""):
    """
    Safely get the second comma-separated value from a config entry.

    Args:
        config_parser: ConfigParser instance
        section (str): Config section name
        key (str): Config key name
        default (str): Default value if second value doesn't exist

    Returns:
        str: The second value or default
    """
    try:
        raw_value = config_parser.get(section, key)
        parts = raw_value.split(',')
        if len(parts) > 1:
            return parts[1].strip()
        return default
    except Exception as e:
        logger.warning(f"Could not get second value for {section}.{key}: {e}")
        return default

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

_config_write_lock = threading.Lock()

def update_device_conf_from_config(cfg: FertigationConfig) -> bool:
    """Update device.conf with provided fertigation config values.
    Only updates fields that are not None — omitted fields keep current values."""
    try:
        with _config_write_lock:
            return _update_device_conf_locked(cfg)
    except Exception as e:
        logger.error(f"Error updating device.conf: {e}")
        return False

def _update_device_conf_locked(cfg: FertigationConfig) -> bool:
    """Internal: update device.conf while holding _config_write_lock."""
    config = configparser.ConfigParser()
    config.read('config/device.conf')

    # pH settings
    if cfg.target_ph is not None:
        ref = _safe_get_first_value(config, 'pH', 'ph_target', str(cfg.target_ph))
        config.set('pH', 'ph_target', f"{ref}, {cfg.target_ph}")
    if cfg.target_ph_deadband is not None:
        ref = _safe_get_first_value(config, 'pH', 'ph_deadband', str(cfg.target_ph_deadband))
        config.set('pH', 'ph_deadband', f"{ref}, {cfg.target_ph_deadband}")
    if cfg.target_ph_min is not None:
        ref = _safe_get_first_value(config, 'pH', 'ph_min', str(cfg.target_ph_min))
        config.set('pH', 'ph_min', f"{ref}, {cfg.target_ph_min}")
    if cfg.target_ph_max is not None:
        ref = _safe_get_first_value(config, 'pH', 'ph_max', str(cfg.target_ph_max))
        config.set('pH', 'ph_max', f"{ref}, {cfg.target_ph_max}")

    # EC settings
    if cfg.target_ec is not None:
        ref = _safe_get_first_value(config, 'EC', 'ec_target', str(cfg.target_ec))
        config.set('EC', 'ec_target', f"{ref}, {cfg.target_ec}")
    if cfg.target_ec_deadband is not None:
        ref = _safe_get_first_value(config, 'EC', 'ec_deadband', str(cfg.target_ec_deadband))
        config.set('EC', 'ec_deadband', f"{ref}, {cfg.target_ec_deadband}")
    if cfg.target_ec_min is not None:
        ref = _safe_get_first_value(config, 'EC', 'ec_min', str(cfg.target_ec_min))
        config.set('EC', 'ec_min', f"{ref}, {cfg.target_ec_min}")
    if cfg.target_ec_max is not None:
        ref = _safe_get_first_value(config, 'EC', 'ec_max', str(cfg.target_ec_max))
        config.set('EC', 'ec_max', f"{ref}, {cfg.target_ec_max}")

    # NutrientPump
    if cfg.abc_ratio is not None:
        ref = _safe_get_first_value(config, 'NutrientPump', 'abc_ratio', f'"{cfg.abc_ratio}"')
        config.set('NutrientPump', 'abc_ratio', f'{ref}, "{cfg.abc_ratio}"')

    # Sprinkler
    if cfg.sprinkler_on_duration is not None:
        ref = _safe_get_first_value(config, 'Sprinkler', 'sprinkler_on_duration', cfg.sprinkler_on_duration)
        config.set('Sprinkler', 'sprinkler_on_duration', f"{ref}, {cfg.sprinkler_on_duration}")
    if cfg.sprinkler_wait_duration is not None:
        ref = _safe_get_first_value(config, 'Sprinkler', 'sprinkler_wait_duration', cfg.sprinkler_wait_duration)
        config.set('Sprinkler', 'sprinkler_wait_duration', f"{ref}, {cfg.sprinkler_wait_duration}")

    # WaterTemperature
    if cfg.target_water_temperature_min is not None:
        ref = _safe_get_first_value(config, 'WaterTemperature', 'target_water_temperature', str(cfg.target_water_temperature_min))
        config.set('WaterTemperature', 'target_water_temperature', f"{ref}, {cfg.target_water_temperature_min}")
        ref_min = _safe_get_first_value(config, 'WaterTemperature', 'target_water_temperature_min', str(cfg.target_water_temperature_min))
        config.set('WaterTemperature', 'target_water_temperature_min', f"{ref_min}, {cfg.target_water_temperature_min}")
    if cfg.target_water_temperature_max is not None:
        ref = _safe_get_first_value(config, 'WaterTemperature', 'target_water_temperature_max', str(cfg.target_water_temperature_max))
        config.set('WaterTemperature', 'target_water_temperature_max', f"{ref}, {cfg.target_water_temperature_max}")

    # Recirculation (section may not exist on all devices)
    if config.has_section('Recirculation'):
        if cfg.recirculation_on_duration is not None:
            ref = _safe_get_first_value(config, 'Recirculation', 'recirculation_on_duration', cfg.recirculation_on_duration)
            config.set('Recirculation', 'recirculation_on_duration', f"{ref}, {cfg.recirculation_on_duration}")
        if cfg.recirculation_wait_duration is not None:
            ref = _safe_get_first_value(config, 'Recirculation', 'recirculation_wait_duration', cfg.recirculation_wait_duration)
            config.set('Recirculation', 'recirculation_wait_duration', f"{ref}, {cfg.recirculation_wait_duration}")

    with open('config/device.conf', 'w') as configfile:
        config.write(configfile)

    logger.info(f"Updated device.conf: {cfg.dict(exclude_none=True)}")
    return True

@app.get("/api/v1/config", tags=["General"])
async def get_device_config(username: str = Depends(verify_credentials)):
    """Return current device.conf as raw INI text with SHA256 hash."""
    import hashlib
    config_path = os.path.join(current_dir, 'config', 'device.conf')
    with open(config_path, 'r') as f:
        config_text = f.read()
    config_hash = hashlib.sha256(config_text.encode()).hexdigest()
    return {
        "config_text": config_text,
        "config_hash": config_hash,
    }

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

@app.post("/api/v1/heartbeat", tags=["Control"])
async def receive_heartbeat(request: Request, hb: HeartbeatRequest = HeartbeatRequest(), username: str = Depends(verify_credentials)):
    """Receive heartbeat from Lumina-Edge. Keeps Ripple in passive mode."""
    edge_ip = request.client.host if request.client else None
    update_heartbeat(edge_ip=edge_ip)
    if get_mode() != "passive":
        old_mode = get_mode()
        set_mode("passive")
        if audit:
            audit.emit("mode_change", "passive_mode",
                       source="system",
                       value={"previous_mode": old_mode, "trigger": "heartbeat_received"},
                       details=f"Edge heartbeat received, switching from {old_mode} to passive")
    return {
        "status": "success",
        "mode": get_mode(),
        "timestamp": time.time()
    }

@app.get("/api/v1/mode", tags=["Status"])
async def get_current_mode(username: str = Depends(verify_credentials)):
    """Get current operating mode."""
    return {
        "mode": get_mode(),
        "last_heartbeat": get_last_heartbeat_time(),
        "timeout_s": HEARTBEAT_TIMEOUT_S
    }

@app.post("/api/v1/instruction_set", tags=["Control"])
async def update_fertigation_config(cfg: FertigationConfig, username: str = Depends(verify_credentials)):
    """Unified endpoint for updating fertigation configuration.
    All fields are optional — only provided fields are updated in device.conf."""
    try:
        changed_fields = cfg.model_dump(exclude_unset=True)
        if update_device_conf_from_config(cfg):
            if audit and changed_fields:
                audit.emit("config_change", "fertigation_config_update",
                           resource="fertigation", source="user_cloud",
                           value=changed_fields, user_name=username,
                           details=f"Updated {len(changed_fields)} fertigation fields")
            return {"status": "success", "message": "Configuration applied successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to apply configuration")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error applying configuration: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/server_instruction_set", tags=["Control"])
async def update_instruction_set(instruction_set: Dict, username: str = Depends(verify_credentials)):
    """Legacy endpoint. Extracts action_fertigation and delegates to unified config update."""
    try:
        fertigation = instruction_set['current_phase']['details']['action_fertigation']
        cfg = FertigationConfig(**fertigation)
        if update_device_conf_from_config(cfg):
            return {"status": "success", "message": "Instruction set applied successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to apply instruction set")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error applying instruction set: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/user_instruction_set", tags=["Control"])
async def update_manual_command(command: FertigationConfig, username: str = Depends(verify_credentials)):
    """Legacy endpoint. Delegates to unified config update."""
    try:
        if update_device_conf_from_config(command):
            return {"status": "success", "message": "User instruction set applied successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to apply user instruction set")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error applying user instruction set: {e}")
        raise HTTPException(status_code=500, detail=str(e))

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
            
            # pH targets (read operational value = second comma-separated value)
            if config.has_section('pH'):
                simplified_status['target_ph'] = float(config.get('pH', 'ph_target').split(',')[1].strip())
                simplified_status['ph_deadband'] = float(config.get('pH', 'ph_deadband').split(',')[1].strip())
                simplified_status['ph_min'] = float(config.get('pH', 'ph_min').split(',')[1].strip())
                simplified_status['ph_max'] = float(config.get('pH', 'ph_max').split(',')[1].strip())

            # EC targets (read operational value = second comma-separated value)
            if config.has_section('EC'):
                simplified_status['target_ec'] = float(config.get('EC', 'ec_target').split(',')[1].strip())
                simplified_status['ec_deadband'] = float(config.get('EC', 'ec_deadband').split(',')[1].strip())
                simplified_status['ec_min'] = float(config.get('EC', 'ec_min').split(',')[1].strip())
                simplified_status['ec_max'] = float(config.get('EC', 'ec_max').split(',')[1].strip())

            # Water level targets (read operational value = second comma-separated value)
            if config.has_section('WaterLevel'):
                simplified_status['target_water_level'] = float(config.get('WaterLevel', 'water_level_target').split(',')[1].strip())
                simplified_status['water_level_deadband'] = float(config.get('WaterLevel', 'water_level_deadband').split(',')[1].strip())
                simplified_status['water_level_min'] = float(config.get('WaterLevel', 'water_level_min').split(',')[1].strip())
                simplified_status['water_level_max'] = float(config.get('WaterLevel', 'water_level_max').split(',')[1].strip())

            # Nutrient pump settings (read operational value = second comma-separated value)
            if config.has_section('NutrientPump'):
                simplified_status['abc_ratio'] = config.get('NutrientPump', 'abc_ratio').split(',')[1].strip().strip('"')

            # Sprinkler settings (read operational value = second comma-separated value)
            if config.has_section('Sprinkler'):
                simplified_status['sprinkler_on_duration'] = config.get('Sprinkler', 'sprinkler_on_duration').split(',')[1].strip().strip('"')
                simplified_status['sprinkler_wait_duration'] = config.get('Sprinkler', 'sprinkler_wait_duration').split(',')[1].strip().strip('"')
                # Add sprinkler_on_at_startup operational value
                if config.has_option('Sprinkler', 'sprinkler_on_at_startup'):
                    startup_value = _parse_config_value('Sprinkler', 'sprinkler_on_at_startup', config, preferred_index=1)
                    simplified_status['sprinkler_on_at_startup'] = startup_value
            
            # Water temperature targets (read operational value = second comma-separated value)
            if config.has_section('WaterTemperature'):
                simplified_status['target_water_temperature'] = float(config.get('WaterTemperature', 'target_water_temperature').split(',')[1].strip())
                simplified_status['target_water_temperature_min'] = float(config.get('WaterTemperature', 'target_water_temperature_min').split(',')[1].strip())
                simplified_status['target_water_temperature_max'] = float(config.get('WaterTemperature', 'target_water_temperature_max').split(',')[1].strip())
            
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

        # Execute relay commands directly for immediate feedback
        # This ensures the action is actually performed, not just written to file
        execution_results = {}
        failed_actions = []

        if processed_request:
            try:
                from src.sensors.Relay import Relay
                relay = Relay()

                if relay:
                    # API field name to device name mapping
                    api_to_device = {
                        'nutrient_pump_a': 'NutrientPumpA',
                        'nutrient_pump_b': 'NutrientPumpB',
                        'nutrient_pump_c': 'NutrientPumpC',
                        'ph_up_pump': 'pHUpPump',
                        'ph_down_pump': 'pHDownPump',
                        'valve_outside_to_tank': 'ValveOutsideToTank',
                        'valve_tank_to_outside': 'ValveTankToOutside',
                        'mixing_pump': 'MixingPump',
                        'pump_from_tank_to_gutters': 'PumpFromTankToGutters',
                        'sprinkler_a': 'SprinklerA',
                        'sprinkler_b': 'SprinklerB',
                        'pump_from_collector_tray_to_tank': 'PumpFromCollectorTrayToTank',
                        'nanobubbler': 'Nanobubbler'
                    }

                    for action, state in processed_request.items():
                        device_name = api_to_device.get(action)
                        if device_name:
                            try:
                                result = relay.set_relay(device_name, state)
                                execution_results[action] = {"success": True, "result": result}
                                logger.info(f"Executed {action} -> {device_name} = {state}, result: {result}")
                            except Exception as e:
                                execution_results[action] = {"success": False, "error": str(e)}
                                failed_actions.append(action)
                                logger.error(f"Failed to execute {action}: {e}")
                        else:
                            logger.warning(f"No device mapping for action: {action}")
                            execution_results[action] = {"success": False, "error": "No device mapping"}
                            failed_actions.append(action)
                else:
                    logger.warning("No relay hardware available")
                    for action in processed_request:
                        execution_results[action] = {"success": False, "error": "No relay hardware"}
                        failed_actions.append(action)

            except Exception as e:
                logger.error(f"Error executing relay commands: {e}")
                for action in processed_request:
                    execution_results[action] = {"success": False, "error": str(e)}
                    failed_actions.append(action)

        # Save to action.json as backup/log (main.py will also see this)
        with open('config/action.json', 'w') as f:
            json.dump(processed_request, f, indent=2)

        if audit:
            audit.emit("user_command", "relay_action",
                       resource=",".join(processed_request.keys()) if processed_request else None,
                       source="user_cloud", user_name=username,
                       value=processed_request,
                       status="success" if not failed_actions else "partial",
                       details=f"Failed: {failed_actions}" if failed_actions else None)

        # Return detailed status
        if failed_actions:
            logger.warning(f"Some actions failed: {failed_actions}")
            return {
                "status": "partial",
                "message": f"Some actions failed: {failed_actions}",
                "results": execution_results
            }

        logger.info(f"All actions executed successfully: {processed_request}")
        return {
            "status": "success",
            "message": "All actions executed successfully",
            "results": execution_results
        }
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
        Dict: Plumbing configuration with _on_at_startup keys for all plumbing devices
            
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
        plumbing_config (PlumbingConfig): Plumbing configuration with _on_at_startup
            fields for all 7 plumbing devices (all optional booleans)
            
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
    # Maps API field names to (config_key, relay_device_name)
    field_mapping = {
        'valve_outside_to_tank_on_at_startup': ('ValveOutsideToTank_on_at_startup', 'ValveOutsideToTank'),
        'valve_tank_to_outside_on_at_startup': ('ValveTankToOutside_on_at_startup', 'ValveTankToOutside'),
        'pump_from_tank_to_gutters_on_at_startup': ('PumpFromTankToGutters_on_at_startup', 'PumpFromTankToGutters'),
        'mixing_pump_on_at_startup': ('MixingPump_on_at_startup', 'MixingPump'),
        'pump_from_collector_tray_to_tank_on_at_startup': ('PumpFromCollectorTrayToTank_on_at_startup', 'PumpFromCollectorTrayToTank'),
        'liquid_cooling_pump_and_fan_on_at_startup': ('LiquidCoolingPumpAndFan_on_at_startup', 'LiquidCoolingPumpAndFan'),
        'valve_co2_on_at_startup': ('ValveCO2_on_at_startup', 'ValveCO2'),
    }

    try:
        config = configparser.ConfigParser()
        config.read('config/device.conf')

        applied_changes = {}

        # Ensure PLUMBING section exists
        if not config.has_section('PLUMBING'):
            config.add_section('PLUMBING')

        # Update provided fields
        for api_field, value in plumbing_config.model_dump(exclude_unset=True).items():
            if value is not None and api_field in field_mapping:
                config_field, device_name = field_mapping[api_field]

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
            relay = Relay()
            if relay:
                for api_field, value in applied_changes.items():
                    _, device_name = field_mapping[api_field]
                    try:
                        relay.set_relay(device_name, value)
                        logger.info(f"Applied {device_name} = {value} to relay hardware")
                    except Exception as e:
                        logger.warning(f"Failed to apply {device_name} to hardware: {e}")
            else:
                logger.warning("No relay hardware available to apply plumbing changes")

        logger.info(f"Successfully updated plumbing configuration: {applied_changes}")

        if audit and applied_changes:
            audit.emit("config_change", "plumbing_config_update",
                       resource="plumbing", source="user_cloud",
                       value=applied_changes, user_name=username,
                       details=f"Updated {len(applied_changes)} plumbing fields")

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
        for api_field, value in sprinkler_config.model_dump(exclude_unset=True).items():
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
            relay = Relay()
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

        if audit and applied_changes:
            audit.emit("config_change", "sprinkler_config_update",
                       resource="sprinkler", source="user_cloud",
                       value=applied_changes, user_name=username,
                       details=f"Updated {len(applied_changes)} sprinkler fields")

        return {
            "status": "success",
            "message": "Sprinkler configuration updated successfully",
            "applied_changes": applied_changes
        }
        
    except Exception as e:
        logger.error(f"Error updating sprinkler configuration: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating sprinkler configuration: {str(e)}")

@app.post("/api/v1/drain", tags=["WaterLevel"])
async def drain_control(request: DrainRequest, username: str = Depends(verify_credentials)):
    """Start or stop a tank drain/flush."""
    from src.water_level_static import start_drain, stop_drain

    if request.action == 'stop':
        stop_drain("API stop")
        return {"status": "ok", "message": "Drain stopped"}
    elif request.action == 'start':
        result = start_drain(
            target_level=request.target_level,
            drain_amount=request.drain_amount,
            duration_seconds=request.duration_seconds,
            reason=request.reason or 'manual',
            mode=request.mode or 'drain',
        )
        if result['status'] == 'error':
            raise HTTPException(status_code=400, detail=result['message'])
        return result
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {request.action}. Use 'start' or 'stop'.")

@app.get("/api/v1/drain", tags=["WaterLevel"])
async def drain_status(username: str = Depends(verify_credentials)):
    """Get current drain status."""
    from src.water_level_static import get_drain_status
    return get_drain_status()

@app.post("/api/v1/scan", tags=["Diagnostics"])
async def scan_sensors(request: ScanRequest = None, username: str = Depends(verify_credentials)):
    """Scan for Modbus sensors across ports, baud rates, and addresses."""
    if request is None:
        request = ScanRequest()

    scanner = SensorScanner(
        modbus_client=globals.modbus_client,
        ports=request.ports,
        baud_rates=request.baud_rates,
        addr_start=request.addr_start,
        addr_end=request.addr_end,
        sensor_types=request.sensor_types,
        short_circuit=request.short_circuit,
    )

    start_time = time.time()
    results = scanner.scan()
    duration = time.time() - start_time

    return {
        "status": "completed",
        "sensors_found": results,
        "scan_parameters": {
            "ports": request.ports,
            "baud_rates": request.baud_rates,
            "addr_start": f"0x{request.addr_start:02x}",
            "addr_end": f"0x{request.addr_end:02x}",
            "sensor_types": request.sensor_types,
            "short_circuit": request.short_circuit,
        },
        "total_probes": len(request.ports) * len(request.baud_rates) * (request.addr_end - request.addr_start + 1),
        "duration_seconds": round(duration, 1),
    }


# Run the server if script is executed directly
if __name__ == "__main__":
    logger.info("Starting Ripple API Server on 0.0.0.0:5000")
    uvicorn.run("server:app", host="0.0.0.0", port=5000, reload=False) 