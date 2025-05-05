#!/usr/bin/env python3

import os
import sys
import logging
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

# Set up logging using GlobalLogger
logger = GlobalLogger("RippleAPI").logger
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# Initialize the controller
controller = RippleController()

def update_device_conf(instruction_set: Dict) -> bool:
    """Update device.conf with values from instruction set."""
    try:
        # Read current device.conf
        config = configparser.ConfigParser()
        config.read('config/device.conf')
        
        # Get fertigation settings from instruction set
        fertigation = instruction_set['current_phase']['details']['action_fertigation']
        
        # Update pH settings
        config.set('pH', 'ph_target', f"{fertigation['target_ph']}, {fertigation['target_ph']}")
        config.set('pH', 'ph_deadband', f"{fertigation['target_ph_deadband']}, {fertigation['target_ph_deadband']}")
        config.set('pH', 'ph_min', f"{fertigation['target_ph_min']}, {fertigation['target_ph_min']}")
        config.set('pH', 'ph_max', f"{fertigation['target_ph_max']}, {fertigation['target_ph_max']}")
        
        # Update EC settings
        config.set('EC', 'ec_target', f"{fertigation['target_ec']}, {fertigation['target_ec']}")
        config.set('EC', 'ec_deadband', f"{fertigation['target_ec_deadband']}, {fertigation['target_ec_deadband']}")
        config.set('EC', 'ec_min', f"{fertigation['target_ec_min']}, {fertigation['target_ec_min']}")
        config.set('EC', 'ec_max', f"{fertigation['target_ec_max']}, {fertigation['target_ec_max']}")
        
        # Update NutrientPump settings
        config.set('NutrientPump', 'abc_ratio', f'"{fertigation["abc_ratio"]}", "{fertigation["abc_ratio"]}"')
        
        # Update Sprinkler settings
        config.set('Sprinkler', 'sprinkler_on_duration', '0, 0')
        config.set('Sprinkler', 'sprinkler_wait_duration', '0, 0')
        
        # Update WaterTemperature settings
        config.set('WaterTemperature', 'target_water_temperature', f"{fertigation['target_water_temperature_min']}, {fertigation['target_water_temperature_min']}")
        config.set('WaterTemperature', 'target_water_temperature_min', f"{fertigation['target_water_temperature_min']}, {fertigation['target_water_temperature_min']}")
        config.set('WaterTemperature', 'target_water_temperature_max', f"{fertigation['target_water_temperature_max']}, {fertigation['target_water_temperature_max']}")
        
        # Update Recirculation settings
        config.set('Recirculation', 'recirculation_on_duration', '0, 0')
        config.set('Recirculation', 'recirculation_wait_duration', '0, 0')
        
        # Write updated config back to file
        with open('config/device.conf', 'w') as configfile:
            config.write(configfile)
            
        return True
    except Exception as e:
        logger.error(f"Error updating device.conf: {e}")
        return False

@app.post("/instruction_set", tags=["Control"])
async def update_instruction_set(instruction_set: Dict, username: str = Depends(verify_credentials)):
    """Update the instruction set and device configuration."""
    try:
        # Save instruction set to file
        with open('config/instruction_set.json', 'w') as f:
            json.dump(instruction_set, f, indent=4)
            
        # Update device.conf
        if update_device_conf(instruction_set):
            return {
                "status": "success",
                "message": "Instruction set and device configuration updated successfully",
                "timestamp": datetime.now().isoformat()
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update device configuration"
            )
    except Exception as e:
        logger.error(f"Error updating instruction set: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating instruction set: {str(e)}"
        )

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

# REST API endpoints
@app.get("/", response_model=SystemStatus, tags=["General"])
async def root(username: str = Depends(verify_credentials)):
    """Root endpoint with system information"""
    return {
        "system": "Ripple Fertigation System",
        "version": "1.0.0",
        "status": "online",
        "last_update": datetime.now().isoformat()
    }

@app.get("/sensors", tags=["Sensors"])
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

@app.get("/sensors/{sensor_type}", tags=["Sensors"])
async def get_sensor(sensor_type: str, username: str = Depends(verify_credentials)):
    """Get data for a specific sensor type (pH, EC, WaterLevel, DO, Relay)"""
    try:
        if sensor_type not in ["pH", "EC", "WaterLevel", "DO", "Relay"]:
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
        elif sensor_type == "Relay":
            relay_instance = Relay()
            if relay_instance:
                relay_instance.get_status()
                if relay_instance.relay_statuses:
                    sensor_data = relay_instance.relay_statuses
                    logger.log_sensor_data(["API", "sensors", "Relay"], sensor_data)
        
        return {
            "timestamp": datetime.now().isoformat(),
            "data": sensor_data or {}
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"Error getting {sensor_type} data: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting {sensor_type} data: {str(e)}")

@app.get("/targets", tags=["Targets"])
async def get_all_targets(username: str = Depends(verify_credentials)):
    """Get all sensor target values"""
    try:
        logger.log_sensor_data(["API", "targets"], controller.sensor_targets)
        return {
            "timestamp": datetime.now().isoformat(),
            "data": controller.sensor_targets
        }
    except Exception as e:
        logger.error(f"Error getting target values: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting target values: {str(e)}")

@app.get("/targets/{sensor_type}", tags=["Targets"])
async def get_target(sensor_type: str, username: str = Depends(verify_credentials)):
    """Get target values for a specific sensor type"""
    try:
        if sensor_type not in controller.sensor_targets:
            raise HTTPException(status_code=404, detail=f"Target values for {sensor_type} not found")
        
        logger.log_sensor_data(["API", "targets", sensor_type], controller.sensor_targets[sensor_type])
        return {
            "timestamp": datetime.now().isoformat(),
            "data": controller.sensor_targets[sensor_type]
        }
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"Error getting {sensor_type} target values: {e}")
        raise HTTPException(status_code=500, detail=f"Error getting {sensor_type} target values: {str(e)}")

@app.post("/relay", tags=["Control"])
async def control_relay(relay_control: RelayControl, username: str = Depends(verify_credentials)):
    """Control a relay by ID"""
    try:
        relay_instance = Relay()
        result = relay_instance.set_relay(relay_control.relay_id, relay_control.state)
        logger.info(f"Relay control: {relay_control.relay_id} set to {relay_control.state}")
        logger.log_sensor_data(["API", "control", "relay", relay_control.relay_id], relay_control.state)
        return {
            "timestamp": datetime.now().isoformat(),
            "success": True, 
            "message": f"Relay {relay_control.relay_id} set to {relay_control.state}", 
            "result": result
        }
    except Exception as e:
        logger.error(f"Error controlling relay: {e}")
        raise HTTPException(status_code=500, detail=f"Error controlling relay: {str(e)}")

@app.put("/targets/{sensor_type}", tags=["Control"])
async def update_target(sensor_type: str, target_update: TargetUpdate, username: str = Depends(verify_credentials)):
    """Update target values for a sensor type"""
    try:
        if sensor_type not in ["pH", "EC", "WaterLevel", "DO"]:
            raise HTTPException(status_code=404, detail=f"Sensor type {sensor_type} not found")
        
        # Update target in controller
        if sensor_type in controller.sensor_targets:
            # Update only the provided values
            target_dict = controller.sensor_targets[sensor_type]
            if target_update.target is not None:
                target_dict['target'] = target_update.target
            if target_update.deadband is not None:
                target_dict['deadband'] = target_update.deadband
            if target_update.min is not None:
                target_dict['min'] = target_update.min
            if target_update.max is not None:
                target_dict['max'] = target_update.max
            
            logger.info(f"Updated {sensor_type} targets: {target_dict}")
            logger.log_sensor_data(["API", "control", "targets", sensor_type], target_dict)
            
            return {
                "timestamp": datetime.now().isoformat(),
                "success": True, 
                "message": f"{sensor_type} targets updated", 
                "targets": target_dict
            }
        else:
            raise HTTPException(status_code=404, detail=f"Target values for {sensor_type} not found")
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        logger.error(f"Error updating targets: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating targets: {str(e)}")

# Run the server if script is executed directly
if __name__ == "__main__":
    logger.info("Starting Ripple API Server on 0.0.0.0:8000")
    uvicorn.run("server:app", host="0.0.0.0", port=5000, reload=False) 