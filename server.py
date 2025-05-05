#!/usr/bin/env python3

import os
import sys
import json
import configparser
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

@app.get("/api/v1/", response_model=SystemStatus, tags=["General"])
async def root(username: str = Depends(verify_credentials)):
    """Root endpoint with system information"""
    logger.info("Root endpoint accessed")
    return {
        "system": "Ripple Fertigation System",
        "version": "1.0.0",
        "status": "online",
        "last_update": datetime.now().isoformat()
    }

@app.get("/api/v1/sensors", tags=["Sensors"])
async def get_all_sensors(username: str = Depends(verify_credentials)):
    """Get all sensor data"""
    try:
        sensor_data = {
            "pH": {},
            "EC": {},
            "WaterLevel": {},
            "DO": {},
            "Relay": {}
        }
        
        # Get pH data
        ph_data = pH.get_statuses_async()
        if ph_data:
            sensor_data["pH"] = ph_data
            logger.log_sensor_data(["API", "sensors", "pH"], ph_data)
            
        # Get EC data
        ec_data = EC.get_statuses_async()
        if ec_data:
            sensor_data["EC"] = ec_data
            logger.log_sensor_data(["API", "sensors", "EC"], ec_data)
            
        # Get Water Level data
        wl_data = WaterLevel.get_statuses_async()
        if wl_data:
            sensor_data["WaterLevel"] = wl_data
            logger.log_sensor_data(["API", "sensors", "WaterLevel"], wl_data)
            
        # Get Relay data
        relay_instance = Relay()
        if relay_instance:
            relay_instance.get_status()
            if relay_instance.relay_statuses:
                sensor_data["Relay"] = relay_instance.relay_statuses
                logger.log_sensor_data(["API", "sensors", "Relay"], relay_instance.relay_statuses)
        
        return {
            "timestamp": datetime.now().isoformat(),
            "data": sensor_data
        }
    except Exception as e:
        logger.error(f"Error getting sensor data: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting sensor data: {str(e)}")

@app.get("/api/v1/sensors/{sensor_type}", tags=["Sensors"])
async def get_sensor(sensor_type: str, username: str = Depends(verify_credentials)):
    """Get data for a specific sensor type"""
    try:
        if sensor_type not in ["pH", "EC", "WaterLevel", "DO", "Relay"]:
            logger.warning(f"Invalid sensor type requested: {sensor_type}")
            raise HTTPException(status_code=404, detail=f"Sensor type {sensor_type} not found")
        
        sensor_data = {}
        
        if sensor_type == "pH":
            sensor_data = pH.get_statuses_async()
            logger.log_sensor_data(["API", "sensors", "pH"], sensor_data)
        elif sensor_type == "EC":
            sensor_data = EC.get_statuses_async()
            logger.log_sensor_data(["API", "sensors", "EC"], sensor_data)
        elif sensor_type == "WaterLevel":
            sensor_data = WaterLevel.get_statuses_async()
            logger.log_sensor_data(["API", "sensors", "WaterLevel"], sensor_data)
        elif sensor_type == "DO":
            sensor_data = DO.get_statuses_async()
        elif sensor_type == "Relay":
            relay_instance = Relay()
            if relay_instance:
                relay_instance.get_status()
                sensor_data = relay_instance.relay_statuses
        
        if not sensor_data:
            raise HTTPException(status_code=404, detail=f"No data available for sensor type {sensor_type}")
        
        return {
            "timestamp": datetime.now().isoformat(),
            "data": sensor_data
        }
    except Exception as e:
        logger.error(f"Error getting sensor data for {sensor_type}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting sensor data: {str(e)}")

@app.get("/api/v1/targets", tags=["Targets"])
async def get_all_targets(username: str = Depends(verify_credentials)):
    """Get all target values from device.conf"""
    try:
        config = configparser.ConfigParser()
        config.read('config/device.conf')
        
        targets = {
            "pH": {
                "target": float(config.get('pH', 'ph_target').split(',')[1].strip()),
                "deadband": float(config.get('pH', 'ph_deadband').split(',')[1].strip()),
                "min": float(config.get('pH', 'ph_min').split(',')[1].strip()),
                "max": float(config.get('pH', 'ph_max').split(',')[1].strip())
            },
            "EC": {
                "target": float(config.get('EC', 'ec_target').split(',')[1].strip()),
                "deadband": float(config.get('EC', 'ec_deadband').split(',')[1].strip()),
                "min": float(config.get('EC', 'ec_min').split(',')[1].strip()),
                "max": float(config.get('EC', 'ec_max').split(',')[1].strip())
            },
            "WaterLevel": {
                "target": float(config.get('WaterLevel', 'water_level_target').split(',')[1].strip()),
                "deadband": float(config.get('WaterLevel', 'water_level_deadband').split(',')[1].strip()),
                "min": float(config.get('WaterLevel', 'water_level_min').split(',')[1].strip()),
                "max": float(config.get('WaterLevel', 'water_level_max').split(',')[1].strip())
            }
        }
        
        return targets
    except Exception as e:
        logger.error(f"Error getting target values: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting target values: {str(e)}")

@app.get("/api/v1/targets/{sensor_type}", tags=["Targets"])
async def get_target(sensor_type: str, username: str = Depends(verify_credentials)):
    """Get target values for a specific sensor type"""
    try:
        if sensor_type not in ["pH", "EC", "WaterLevel"]:
            raise HTTPException(status_code=404, detail=f"Target type {sensor_type} not found")
        
        config = configparser.ConfigParser()
        config.read('config/device.conf')
        
        if sensor_type == "pH":
            targets = {
                "target": float(config.get('pH', 'ph_target').split(',')[1].strip()),
                "deadband": float(config.get('pH', 'ph_deadband').split(',')[1].strip()),
                "min": float(config.get('pH', 'ph_min').split(',')[1].strip()),
                "max": float(config.get('pH', 'ph_max').split(',')[1].strip())
            }
        elif sensor_type == "EC":
            targets = {
                "target": float(config.get('EC', 'ec_target').split(',')[1].strip()),
                "deadband": float(config.get('EC', 'ec_deadband').split(',')[1].strip()),
                "min": float(config.get('EC', 'ec_min').split(',')[1].strip()),
                "max": float(config.get('EC', 'ec_max').split(',')[1].strip())
            }
        elif sensor_type == "WaterLevel":
            targets = {
                "target": float(config.get('WaterLevel', 'water_level_target').split(',')[1].strip()),
                "deadband": float(config.get('WaterLevel', 'water_level_deadband').split(',')[1].strip()),
                "min": float(config.get('WaterLevel', 'water_level_min').split(',')[1].strip()),
                "max": float(config.get('WaterLevel', 'water_level_max').split(',')[1].strip())
            }
        
        return targets
    except Exception as e:
        logger.error(f"Error getting target values for {sensor_type}: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting target values: {str(e)}")

@app.post("/api/v1/relay", tags=["Control"])
async def control_relay(relay_control: RelayControl, username: str = Depends(verify_credentials)):
    """Control a specific relay"""
    try:
        relay_instance = Relay()
        if relay_instance:
            success = relay_instance.set_relay(relay_control.relay_id, relay_control.state)
            if success:
                return {"status": "success", "message": f"Relay {relay_control.relay_id} set to {relay_control.state}"}
            else:
                raise HTTPException(status_code=400, detail=f"Failed to set relay {relay_control.relay_id}")
        else:
            raise HTTPException(status_code=500, detail="Failed to initialize relay control")
    except Exception as e:
        logger.error(f"Error controlling relay: {e}")
        raise HTTPException(status_code=500, detail=f"Error controlling relay: {str(e)}")

@app.put("/api/v1/targets/{sensor_type}", tags=["Control"])
async def update_target(sensor_type: str, target_update: TargetUpdate, username: str = Depends(verify_credentials)):
    """Update target values for a specific sensor type"""
    try:
        if sensor_type not in ["pH", "EC", "WaterLevel"]:
            raise HTTPException(status_code=404, detail=f"Target type {sensor_type} not found")
        
        config = configparser.ConfigParser()
        config.read('config/device.conf')
        
        # Get current values
        current_target = config.get(sensor_type, f"{sensor_type.lower()}_target").split(',')[1].strip()
        current_deadband = config.get(sensor_type, f"{sensor_type.lower()}_deadband").split(',')[1].strip()
        current_min = config.get(sensor_type, f"{sensor_type.lower()}_min").split(',')[1].strip()
        current_max = config.get(sensor_type, f"{sensor_type.lower()}_max").split(',')[1].strip()
        
        # Update values if provided
        if target_update.target is not None:
            config.set(sensor_type, f"{sensor_type.lower()}_target", f"{target_update.target}, {current_target}")
        if target_update.deadband is not None:
            config.set(sensor_type, f"{sensor_type.lower()}_deadband", f"{target_update.deadband}, {current_deadband}")
        if target_update.min is not None:
            config.set(sensor_type, f"{sensor_type.lower()}_min", f"{target_update.min}, {current_min}")
        if target_update.max is not None:
            config.set(sensor_type, f"{sensor_type.lower()}_max", f"{target_update.max}, {current_max}")
        
        # Write updated config back to file
        with open('config/device.conf', 'w') as configfile:
            config.write(configfile)
        
        return {"status": "success", "message": f"Updated {sensor_type} targets"}
    except Exception as e:
        logger.error(f"Error updating {sensor_type} targets: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating targets: {str(e)}")

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

@app.post("/api/v1/instruction_set", tags=["Control"])
async def update_instruction_set(instruction_set: Dict, username: str = Depends(verify_credentials)):
    """Update system configuration from instruction set"""
    try:
        if update_device_conf(instruction_set):
            return {"status": "success", "message": "Instruction set applied successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to apply instruction set")
    except Exception as e:
        logger.error(f"Error applying instruction set: {e}")
        raise HTTPException(status_code=500, detail=f"Error applying instruction set: {str(e)}")

@app.post("/api/v1/manual_command", tags=["Control"])
async def update_manual_command(command: ManualCommand, username: str = Depends(verify_credentials)):
    """Update system configuration from manual command"""
    try:
        if update_device_conf_from_manual(command):
            return {"status": "success", "message": "Manual command applied successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to apply manual command")
    except Exception as e:
        logger.error(f"Error applying manual command: {e}")
        raise HTTPException(status_code=500, detail=f"Error applying manual command: {str(e)}")

# Run the server if script is executed directly
if __name__ == "__main__":
    logger.info("Starting Ripple API Server on 0.0.0.0:5000")
    uvicorn.run("server:app", host="0.0.0.0", port=5000, reload=False) 