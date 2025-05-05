#!/usr/bin/env python3
"""
Example client for the Ripple Fertigation REST API
"""

import requests
import json
import time
from datetime import datetime
from typing import Dict, Any

# API configuration
API_URL = "http://localhost:5000"  # Change to your device's IP address
USERNAME = "ripple-rpi"  # From device.conf
PASSWORD = "+IHa0UpROx94"  # From device.conf

class RippleClient:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip('/')
        self.auth = (username, password)
        
    def get_sensors(self) -> Dict[str, Any]:
        """Get data from all sensors"""
        response = requests.get(f"{self.base_url}/api/v1/sensors", auth=self.auth)
        response.raise_for_status()
        return response.json()
    
    def get_sensor(self, sensor_type: str) -> Dict[str, Any]:
        """Get data from a specific sensor type"""
        response = requests.get(f"{self.base_url}/api/v1/sensors/{sensor_type}", auth=self.auth)
        response.raise_for_status()
        return response.json()
    
    def get_targets(self) -> Dict[str, Any]:
        """Get all target values"""
        response = requests.get(f"{self.base_url}/api/v1/targets", auth=self.auth)
        response.raise_for_status()
        return response.json()
    
    def get_target(self, sensor_type: str) -> Dict[str, Any]:
        """Get target values for a specific sensor type"""
        response = requests.get(f"{self.base_url}/api/v1/targets/{sensor_type}", auth=self.auth)
        response.raise_for_status()
        return response.json()
    
    def control_relay(self, relay_id: str, state: bool) -> Dict[str, Any]:
        """Control a relay"""
        data = {
            "relay_id": relay_id,
            "state": state
        }
        response = requests.post(f"{self.base_url}/api/v1/relay", json=data, auth=self.auth)
        response.raise_for_status()
        return response.json()
    
    def update_target(self, sensor_type: str, target: float, deadband: float, 
                     min_val: float, max_val: float) -> Dict[str, Any]:
        """Update target values for a sensor type"""
        data = {
            "target": target,
            "deadband": deadband,
            "min": min_val,
            "max": max_val
        }
        response = requests.put(f"{self.base_url}/api/v1/targets/{sensor_type}", json=data, auth=self.auth)
        response.raise_for_status()
        return response.json()
    
    def update_instruction_set(self, instruction_set: Dict[str, Any]) -> Dict[str, Any]:
        """Update the instruction set and device configuration"""
        response = requests.post(f"{self.base_url}/api/v1/instruction_set", json=instruction_set, auth=self.auth)
        response.raise_for_status()
        return response.json()
    
    def update_manual_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        """Update device configuration with manual command values"""
        response = requests.post(f"{self.base_url}/api/v1/manual_command", json=command, auth=self.auth)
        response.raise_for_status()
        return response.json()

def get_system_info():
    """Get system information"""
    response = requests.get(f"{API_URL}/", auth=(USERNAME, PASSWORD))
    if response.status_code == 200:
        print("System information retrieved successfully:")
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"Error: {response.status_code} - {response.text}")

def get_all_sensor_data():
    """Get all sensor data"""
    response = requests.get(f"{API_URL}/sensors", auth=(USERNAME, PASSWORD))
    if response.status_code == 200:
        print("All sensor data retrieved successfully:")
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"Error: {response.status_code} - {response.text}")

def get_specific_sensor_data(sensor_type):
    """Get data for a specific sensor type"""
    response = requests.get(f"{API_URL}/sensors/{sensor_type}", auth=(USERNAME, PASSWORD))
    if response.status_code == 200:
        print(f"{sensor_type} data retrieved successfully:")
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"Error: {response.status_code} - {response.text}")

def get_all_targets():
    """Get all target values"""
    response = requests.get(f"{API_URL}/targets", auth=(USERNAME, PASSWORD))
    if response.status_code == 200:
        print("All target values retrieved successfully:")
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"Error: {response.status_code} - {response.text}")

def get_specific_target(sensor_type):
    """Get target values for a specific sensor type"""
    response = requests.get(f"{API_URL}/targets/{sensor_type}", auth=(USERNAME, PASSWORD))
    if response.status_code == 200:
        print(f"{sensor_type} target values retrieved successfully:")
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"Error: {response.status_code} - {response.text}")

def control_relay(relay_id, state):
    """Control a relay"""
    payload = {
        "relay_id": relay_id,
        "state": state
    }
    response = requests.post(f"{API_URL}/relay", json=payload, auth=(USERNAME, PASSWORD))
    if response.status_code == 200:
        print(f"Relay {relay_id} {'activated' if state else 'deactivated'} successfully:")
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"Error: {response.status_code} - {response.text}")

def update_target(sensor_type, target_value, deadband=None, min_value=None, max_value=None):
    """Update target values for a sensor type"""
    payload = {
        "target": target_value
    }
    if deadband is not None:
        payload["deadband"] = deadband
    if min_value is not None:
        payload["min"] = min_value
    if max_value is not None:
        payload["max"] = max_value
        
    response = requests.put(f"{API_URL}/targets/{sensor_type}", json=payload, auth=(USERNAME, PASSWORD))
    if response.status_code == 200:
        print(f"{sensor_type} target values updated successfully:")
        print(json.dumps(response.json(), indent=2))
    else:
        print(f"Error: {response.status_code} - {response.text}")

def poll_sensor_data(interval=5, duration=30):
    """Poll sensor data at regular intervals"""
    print(f"Polling sensor data every {interval} seconds for {duration} seconds...")
    start_time = time.time()
    end_time = start_time + duration
    
    while time.time() < end_time:
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{current_time}] Fetching sensor data...")
        
        try:
            response = requests.get(f"{API_URL}/sensors", auth=(USERNAME, PASSWORD))
            if response.status_code == 200:
                data = response.json()
                
                # Print a summary of the data
                print(f"Timestamp: {data['timestamp']}")
                for sensor_type, values in data['data'].items():
                    if values:
                        print(f"{sensor_type}: {values}")
            else:
                print(f"Error: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"Error polling sensor data: {e}")
            
        # Wait for the next interval
        time.sleep(interval)

def main():
    # Example usage
    client = RippleClient(API_URL, USERNAME, PASSWORD)
    
    # Get all sensor data
    sensors = client.get_sensors()
    print("All sensors:", json.dumps(sensors, indent=2))
    
    # Get specific sensor data
    ph_data = client.get_sensor("pH")
    print("pH sensor:", json.dumps(ph_data, indent=2))
    
    # Control a relay
    result = client.control_relay("NutrientPumpA", True)
    print("Relay control result:", json.dumps(result, indent=2))
    
    # Update target values
    result = client.update_target("pH", 6.5, 0.1, 6.0, 7.0)
    print("Target update result:", json.dumps(result, indent=2))
    
    # Example manual command
    manual_command = {
        "abc_ratio": "1:1:0",
        "target_ec_max": 1.2,
        "target_ec_min": 0.6,
        "target_ec_deadband": 0.1,
        "target_ph_max": 7,
        "target_ph_min": 5,
        "target_ph_deadband": 0.5,
        "sprinkler_on_duration": "00:00:00",
        "sprinkler_wait_duration": "00:00:00",
        "recirculation_wait_duration": "00:00:00",
        "recirculation_on_duration": "00:00:00",
        "target_water_temperature_max": 18,
        "target_water_temperature_min": 18,
        "target_ec": 0.8,
        "target_ph": 6
    }
    result = client.update_manual_command(manual_command)
    print("Manual command result:", json.dumps(result, indent=2))
    
    # Poll sensor data every 5 seconds
    while True:
        try:
            sensors = client.get_sensors()
            print("\nCurrent sensor data:", json.dumps(sensors, indent=2))
            time.sleep(5)
        except KeyboardInterrupt:
            print("\nStopping sensor polling")
            break
        except Exception as e:
            print(f"Error polling sensors: {e}")
            time.sleep(5)

# Run examples
if __name__ == "__main__":
    print("Ripple Fertigation REST API Client Example")
    print("==========================================")
    
    # Get system information
    print("\n1. Getting system information:")
    get_system_info()
    
    # Get all sensor data
    print("\n2. Getting all sensor data:")
    get_all_sensor_data()
    
    # Get specific sensor data
    print("\n3. Getting pH sensor data:")
    get_specific_sensor_data("pH")
    
    # Get all target values
    print("\n4. Getting all target values:")
    get_all_targets()
    
    # Control relay
    print("\n5. Controlling relay:")
    # For example: NutrientPumpA as defined in device.conf
    control_relay("NutrientPumpA", True)  # Turn on
    time.sleep(2)  # Wait a bit
    control_relay("NutrientPumpA", False)  # Turn off
    
    # Update target
    print("\n6. Updating pH target:")
    update_target("pH", 6.8, deadband=0.2)
    
    # Poll sensor data
    print("\n7. Polling sensor data:")
    poll_sensor_data(interval=5, duration=15)  # Poll every 5 seconds for 15 seconds
    
    main() 