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

3. The server will start on port 8000. You can access the API at:
   ```
   http://<device-ip>:8000
   ```

## Authentication

All API endpoints require HTTP Basic Authentication. Use the username and password configured in `device.conf` under the `[SYSTEM]` section.

## API Endpoints

### General

- `GET /`: Get system information
  - Response: General system status and version information

### Sensors

- `GET /sensors`: Get all sensor data
  - Response: Data from all sensors (pH, EC, Water Level, DO, Relay)

- `GET /sensors/{sensor_type}`: Get data for a specific sensor type
  - Path Parameters:
    - `sensor_type`: One of "pH", "EC", "WaterLevel", "DO", "Relay"
  - Response: Data from the specified sensor type

### Targets

- `GET /targets`: Get all target values
  - Response: Target values for all sensor types

- `GET /targets/{sensor_type}`: Get target values for a specific sensor type
  - Path Parameters:
    - `sensor_type`: One of "pH", "EC", "WaterLevel", "DO"
  - Response: Target values for the specified sensor type

### Control

- `POST /relay`: Control a relay
  - Request Body:
    ```json
    {
      "relay_id": "NutrientPumpA", 
      "state": true
    }
    ```
  - Response: Success status and result details

- `PUT /targets/{sensor_type}`: Update target values for sensors
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
3. For sensor monitoring, poll the `/sensors` endpoint at appropriate intervals
4. For control, use the `/relay` and `/targets/{sensor_type}` endpoints 