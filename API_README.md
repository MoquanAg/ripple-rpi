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

### General

- `GET /api/v1/`: Get system information
  - Response: General system status and version information

### Sensors

- `GET /api/v1/sensors`: Get all sensor data
  - Response: Data from all sensors (pH, EC, Water Level, DO, Relay)

- `GET /api/v1/sensors/{sensor_type}`: Get data for a specific sensor type
  - Path Parameters:
    - `sensor_type`: One of "pH", "EC", "WaterLevel", "DO", "Relay"
  - Response: Data from the specified sensor type

### Targets

- `GET /api/v1/targets`: Get all target values
  - Response: Target values for all sensor types

- `GET /api/v1/targets/{sensor_type}`: Get target values for a specific sensor type
  - Path Parameters:
    - `sensor_type`: One of "pH", "EC", "WaterLevel", "DO"
  - Response: Target values for the specified sensor type

### Control

- `POST /api/v1/relay`: Control a relay
  - Request Body:
    ```json
    {
      "relay_id": "NutrientPumpA", 
      "state": true
    }
    ```
  - Response: Success status and result details

- `PUT /api/v1/targets/{sensor_type}`: Update target values for sensors
  - Path Parameters:
    - `sensor_type`: One of "pH", "EC", "WaterLevel", "DO"
  - Request Body:
    ```json
    {
      "target": 7.0,
      "deadband": 0.1,
      "min": 6.5,
      "max": 7.5
    }
    ```
  - Response: Updated target values

- `POST /api/v1/instruction_set`: Update the instruction set and device configuration
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

- `POST /api/v1/manual_command`: Update device configuration with manual command values
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
  "timestamp": "2023-06-01T12:34:56.789012",
  "data": {
    // Response data specific to the endpoint
  }
}
```

For control endpoints, the format is:
```json
{
  "timestamp": "2023-06-01T12:34:56.789012",
  "success": true,
  "message": "Operation succeeded",
  "result": {
    // Additional result information
  }
}
```

## Example Client

See `client_example.py` for example code on how to interact with the API using Python. The example shows how to:

1. Retrieve sensor data
2. Control relays
3. Update target parameters
4. Poll sensor data at regular intervals

## Integrating with Other Systems

To integrate this API with other systems on your network:

1. Make HTTP requests to the appropriate endpoints
2. Use HTTP Basic Authentication with your credentials
3. For sensor monitoring, poll the `/api/v1/sensors` endpoint at appropriate intervals
4. For control, use the `/api/v1/relay` and `/api/v1/targets/{sensor_type}` endpoints 