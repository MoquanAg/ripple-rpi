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
    """Convert HH:MM:SS format to seconds"""
    hours, minutes, seconds = map(int, time_str.split(':'))
    return hours * 3600 + minutes * 60 + seconds

def update_device_conf(instruction_set: Dict) -> bool:
    """Update device.conf with values from instruction set."""
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
    """System information endpoint"""
    logger.info("System information endpoint accessed")
    return {
        "system": "Ripple Fertigation System",
        "version": "1.0.0",
        "status": "online",
        "last_update": datetime.now().isoformat()
    }

def update_device_conf_from_manual(command: ManualCommand) -> bool:
    """Update device.conf with values from manual command."""
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
    """Update system configuration from instruction set received from server"""
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
    """Update system configuration from user instruction set"""
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
    """Get current system status in a simplified format"""
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
            
            # Water temperature targets
            if config.has_section('WaterTemperature'):
                simplified_status['target_water_temperature'] = float(config.get('WaterTemperature', 'target_water_temperature').split(',')[0])
                simplified_status['target_water_temperature_min'] = float(config.get('WaterTemperature', 'target_water_temperature_min').split(',')[0])
                simplified_status['target_water_temperature_max'] = float(config.get('WaterTemperature', 'target_water_temperature_max').split(',')[0])
                
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
    """Update action configuration and save to action.json"""
    try:
        logger.info(f"Received raw action request: {request}")
        
        # Explicit list of valid API field names with sprinkler as special case
        valid_fields = [
            'device_id',  # Device identifier for device-specific control
            'nutrient_pump_a',
            'nutrient_pump_b',
            'nutrient_pump_c',
            'ph_up_pump',
            'ph_down_pump',
            'valve_outside_to_tank',
            'valve_tank_to_outside',
            'mixing_pump',
            'pump_from_tank_to_gutters',
            'sprinkler',  # Special case that maps to both sprinkler_a and sprinkler_b
            'sprinkler_a',
            'sprinkler_b',
            'pump_from_collector_tray_to_tank'
        ]
        
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
    """Reboot the system using sudo reboot command"""
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
    """Restart Ripple application by calling the headless restart script"""
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

# Run the server if script is executed directly
if __name__ == "__main__":
    logger.info("Starting Ripple API Server on 0.0.0.0:5000")
    uvicorn.run("server:app", host="0.0.0.0", port=5000, reload=False) 