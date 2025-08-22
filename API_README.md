# Ripple Fertigation System REST API

This API provides a RESTful interface to monitor sensor data and control the Ripple Fertigation system.

## Getting Started

1. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Start the API server:
   ```
   python server.py
   ```

3. The server will start on port 5000. You can access the API at:
   ```
   http://<device-ip>:5000
   ```

## Authentication

All API endpoints require HTTP Basic Authentication. Use the username and password configured in `device.conf` under the `[SYSTEM]` section.

## API Endpoints

### System Information

- `GET /api/v1/system`: Get system information
  - Response: General system status and version information
  - Example response:
    ```json
    {
      "system": "Ripple Fertigation System",
      "version": "1.0.0",
      "status": "online",
      "last_update": "2025-05-05T19:21:13.727"
    }
    ```

### System Status

- `GET /api/v1/status`: Get system status
  - Response: Simplified system status with essential sensor readings and relay states
  - Example response:
    ```json
    {
      "ph": 5.83,
      "ph_temperature": 22.5,
      "ec": 0.91,
      "ec_tds": 454.45,
      "ec_salinity": 499.89,
      "ec_temperature": 22.35,
      "water_level": 80,
      "target_ph": 6.0,
      "ph_deadband": 0.5,
      "ph_min": 5.0,
      "ph_max": 7.0,
      "target_ec": 0.8,
      "ec_deadband": 0.1,
      "ec_min": 0.6,
      "ec_max": 1.2,
      "target_water_level": 80,
      "water_level_deadband": 10,
      "water_level_min": 50,
      "water_level_max": 100,
      "abc_ratio": "1:1:0",
      "sprinkler_on_duration": "01:10:00",
      "sprinkler_wait_duration": "03:00:00",
      "target_water_temperature": 18.0,
      "target_water_temperature_min": 18.0,
      "target_water_temperature_max": 18.0,
      "relays": [
        {"port": "0", "status": false, "as": "none"},
        {"port": "1", "status": false, "as": "none"},
        {"port": "5", "status": true, "as": "ValveOutsideToTank"},
        {"port": "7", "status": true, "as": "MixingPump"},
        {"port": "8", "status": true, "as": "PumpFromTankToGutters"},
        {"port": "9", "status": true, "as": "SprinklerA"},
        {"port": "10", "status": true, "as": "SprinklerB"}
      ],
      "timestamp": "2025-08-22T18:26:56+0800"
    }
    ```

### Control

- `POST /api/v1/action`: Control relays/devices
  - Request Body: A JSON object with action fields and boolean values
    ```json
    {
      "mixing_pump": true,
      "sprinkler": false
    }
    ```
  - Response: Success status and message
  - Note: The `sprinkler` field will automatically control both sprinkler_a and sprinkler_b relays for safety
  - Valid fields: `nutrient_pump_a`, `nutrient_pump_b`, `nutrient_pump_c`, `ph_up_pump`, `ph_down_pump`, `valve_outside_to_tank`, `valve_tank_to_outside`, `mixing_pump`, `pump_from_tank_to_gutters`, `sprinkler`, `sprinkler_a`, `sprinkler_b`, `pump_from_collector_tray_to_tank`

- `POST /api/v1/server_instruction_set`: Update the instruction set and device configuration
  - Request Body: JSON instruction set from central server
  - Response: Success status and result details

- `POST /api/v1/user_instruction_set`: Update device configuration with user instruction values
  - Request Body:
    ```json
    {
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
    ```
  - Response: Success status and result details

### System Management

- `POST /api/v1/system/reboot`: Reboot the system
  - Response: Success status and message
  - Note: This will restart the entire Raspberry Pi

- `POST /api/v1/system/restart`: Restart the Ripple application
  - Response: Success status and message
  - Note: This restarts only the Ripple application, not the entire system

## API Response Format

All API responses follow this format:
```json
{
  "status": "success",
  "message": "Operation succeeded",
  "data": {
    // Response data specific to the endpoint
  }
}
```

Or in case of errors:
```json
{
  "status": "error",
  "message": "Error description"
}
```

## Logging

The API server logs are stored in the `log/` directory with the prefix `ripple_server_`. Log files follow the format:
```
ripple_server_YYYYMMDD_NNN.log
```
where:
- `YYYYMMDD` is the date (e.g., 20250505)
- `NNN` is a sequential number starting from 001

Log files are automatically rotated when they reach 2MB or at the start of a new day.

## Integrating with Other Systems

To integrate this API with other systems on your network:

1. Make HTTP requests to the appropriate endpoints
2. Use HTTP Basic Authentication with your credentials
3. For system monitoring, poll the `/api/v1/status` endpoint
4. For control, use the `/api/v1/action` endpoint
5. For configuration, use the server or user instruction set endpoints 