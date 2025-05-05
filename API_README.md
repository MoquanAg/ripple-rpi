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

## Logging

The API server logs are stored in the `log/` directory with the prefix `ripple_server_`. Log files follow the format:
```
ripple_server_YYYYMMDD_NNN.log
```
where:
- `YYYYMMDD` is the date (e.g., 20250505)
- `NNN` is a sequential number starting from 001

Log files are automatically rotated when they reach 2MB or at the start of a new day. Each log entry includes:
- Timestamp
- Source file
- Function name
- Message

Example log entry:
```
2025-05-05 19:21:13,727 - server.py - <module> - Starting Ripple API Server
```

## Authentication

All API endpoints require HTTP Basic Authentication. Use the username and password configured in `device.conf` under the `[SYSTEM]` section.

## API Endpoints

The API has been simplified to focus on only essential functions with a clear separation of concerns. The server writes to config files and reads sensor data from files populated by the main controller.

### System Information

- `GET /api/v1/system`: Get system information
  - Response: General system status and version information
  - Example response:
    ```json
    {
      "system": "Ripple Fertigation System",
      "version": "1.0.0",
      "status": "online",
      "last_update": "2023-06-01T12:34:56.789012"
    }
    ```

### System Status

- `GET /api/v1/status`: Get full system status
  - Response: Complete system status including all sensor readings and relay states
  - Returns the raw sensor data as collected by the main controller

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

- `POST /api/v1/server_instruction_set`: Update the instruction set and device configuration
  - Request Body: JSON instruction set (see example below)
  - Response: Success status and result details
  - Example Request Body:
    ```json
    {
      "status": "success",
      "message": "Grow cycle created for device looper-sjtu",
      "grow_cycle_id": "3c52f63a-3625-4aa9-ba5d-5fbf745abbcc",
      "device_id": "looper-sjtu",
      "model_id": "7aa1fa76-a8d2-4be9-bec5-194d96428af7",
      "model_name": "多类叶菜",
      "starting_phase": "seedling",
      "starting_phase_name": "育苗",
      "phases_count": 2,
      "version": "1.0.0",
      "msg_time": "2025-05-05T10:54:11.876357+08:00",
      "type": "start_new_grow",
      "current_phase": {
        "key": "seedling",
        "name": "育苗",
        "details": {
          "id": 5,
          "name": "育苗",
          "days_min": 4,
          "days_max": 14,
          "day_duration": "14:00:00",
          "model": "7aa1fa76-a8d2-4be9-bec5-194d96428af7",
          "phase_key": "seedling",
          "is_starting_Phase": true,
          "action_fertigation": {
            "id": 5,
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
        }
      }
    }
    ```

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

## Integrating with Other Systems

To integrate this API with other systems on your network:

1. Make HTTP requests to the appropriate endpoints
2. Use HTTP Basic Authentication with your credentials
3. For system monitoring, poll the `/api/v1/status` endpoint
4. For control, use the `/api/v1/action` endpoint
5. For configuration, use the server or user instruction set endpoints 