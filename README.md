# Ripple
## Intelligent Fertigation Control System

> Ripple: Advanced nutrient mixing and irrigation control system for vertical farming applications

### Quick Links
- [Documentation](#project-context)
- [Installation](#installation)
- [Communication Protocol](#communication-protocol)
- [Error Handling](#error-handling)

### Version
Current Version: 1.0.0-alpha

## Project Context

### Purpose
Ripple automates the preparation and distribution of nutrient solutions for vertical farming by:
- Mixing multiple nutrients (A/B/C) and pH adjusters in precise ratios
- Maintaining target pH, EC (electrical conductivity), and DO levels
- Managing water levels in nutrient tank and return water tray
- Providing real-time monitoring and control
- Implementing UV sterilization cycles

### Core Functionality
1. **Nutrient Management**
   - 3 peristaltic pumps for nutrients (A/B/C)
   - 2 peristaltic pumps for pH adjustment (pH+/pH-)
   - Precise dosing based on EC/pH/DO feedback
   - Automated mixing cycles

2. **Water Management**
   - Nutrient tank level monitoring and control
   - Return water tray level monitoring and control
   - Automated filling/draining
   - Distribution control via valves

3. **System Components**
   - Return water tray with level switch and pump
   - Nutrient tank with level sensor and UV sterilization
   - Water injection system
   - Irrigation and spray systems

4. **Process Flow**
   ```
   1. Monitor return water tray → 2. Auto-drain if needed →
   3. Check nutrient tank level → 4. Auto-fill if needed →
   5. Add nutrients → 6. Mix solution → 7. Check pH/EC/DO →
   8. Adjust if needed → 9. Distribute
   ```

5. **Data Management**
   - 1-second sensor polling interval
   - Local data caching
   - Immediate response to master requests
   - Timestamp for each reading

### System Operation Modes

1. **Auto Mode (Default)**
   - Automatic nutrient dosing based on EC/pH/DO readings
   - Automatic pH control
   - Regular mixing cycles based on timing settings
   - Automatic water refill when enabled
   - UV sterilization cycles
   - All safety checks active

2. **Manual Mode**
   - All operations require explicit commands
   - Safety checks still active
   - Mixing schedule suspended

3. **UV Sterilization Feature**
   When enabled:
   - Every 6 hours:
     1. Start internal circulation pump
     2. Activate UV sterilization
     3. Run for 20 minutes
     4. Stop UV and circulation

4. **Fresh Water Dilution Feature**
   When enabled:
   - If EC > Maximum threshold or pH < Minimum threshold:
      // Check if dilution will help based on outside water properties
      - Skip dilution if:
        * Target is high EC and outside water has high EC
        * Target is low pH and outside water has low pH
      
      1. Start mixing pump if not already running
      2. Wait 10 seconds for mixing
      3. Check readings again
      4. If no improvement (EC still high or pH still low):
         1. Open tank out valve
         2. Lower water level by set amount
         3. Close tank out valve
         4. Open fresh water valve
         5. Refill to original level
         6. Close fresh water valve
         7. Start mixing cycle
         8. Wait for readings to stabilize
         9. Repeat if needed

    Safety conditions:
    - Requires valid sensor readings
    - Respects tank level limits
    - Maximum dilution cycles per day
    - Minimum time between dilutions

5. **Auto Refill Feature**
   When enabled:
   - Monitors nutrient tank level continuously
   - When level drops below refill trigger level (cm):
      1. Open fresh water valve
      2. Monitor water level rise
      3. Close valve when target level reached
      4. Start mixing cycle
    
    Safety conditions:
    - Maximum refill time enforced
    - Requires valid level sensor reading
    - Warning alerts at low/high warning levels
    - Emergency stop at minimum/maximum levels
    - Minimum time between refills

6. **Mixing Logic**
   - Any nutrient pump activation:
     1. Start internal circulation pump
     2. Run for 3 minutes
     3. Stop circulation pump

### Key Design Requirements
- **Reliability**: Continuous operation in agricultural settings
- **Safety**: Multiple checks and failsafes
- **Precision**: Accurate nutrient/pH/EC/DO control
- **Monitoring**: Real-time status and alerts
- **Integration**: JSON communication for remote control

### Development Focus
- Robust communication protocols
- Precise timing for pump control
- Error detection and handling
- Calibration and maintenance features
- Safety-first design approach

## System Overview

This system controls the automated mixing and distribution of nutrient solutions for vertical farming. The system runs on a Raspberry Pi CM4 and uses multiple serial ports for communication.

### System Ports

#### Serial Ports
- **ttyAMA2**
  - Primary communication interface
  - Baud rate: 9600
  - Purpose: Master control system communication (JSON format)

- **ttyAMA3**
  - Secondary serial interface
  - Purpose: Sensor communication (Modbus RTU)

- **ttyAMA4**
  - Relay control interface
  - Purpose: Control of pumps and valves (Modbus RTU)

#### Relay Outputs (12 channels)
```
Application Mapping:
- Channel 1: Nutrient pump A
- Channel 2: Nutrient pump B
- Channel 3: Nutrient pump C
- Channel 4: pH+ pump
- Channel 5: pH- pump
- Channel 6: Nutrient tank fill valve
- Channel 7: Nutrient tank drain valve
- Channel 8: Internal circulation pump + UV
- Channel 9: Irrigation pump
- Channel 10: Sprinkler pump
- Channel 11: Sprinkler valve
- Channel 12: Return water pump
```

#### Sensors
- pH sensor (Modbus address: 0x02)
- EC sensor (Modbus address: 0x03)
- DO sensor (Modbus address: 0x04)
- Water level sensor (Modbus address: 0x05)
- Water meter (Modbus address: 0x06)
- Drain meter (Modbus address: 0x07)
- Return water tray level switch

## Communication Protocol

### Master Communication (ttyAMA2)
- JSON format
- Request/Response structure
- Real-time status updates
- Command interface

Example JSON messages:
```json
// Status request
{
    "command": "get_status",
    "timestamp": 1234567890
}

// Status response
{
    "status": "ok",
    "data": {
        "ph": 6.5,
        "ec": 2.2,
        "do": 5.8,
        "water_level": 100,
        "pumps": {
            "nutrient_a": false,
            "nutrient_b": false,
            "nutrient_c": false,
            "ph_plus": false,
            "ph_minus": false
        }
    },
    "timestamp": 1234567890
}

// Control command
{
    "command": "set_pump",
    "pump": "nutrient_a",
    "state": true,
    "duration": 10,
    "timestamp": 1234567890
}
```

### Sensor Communication (ttyAMA3)
- Modbus RTU protocol
- Uses `lumina_modbus_client.py` for communication
- Event-based updates via `lumina_modbus_event_emitter.py`

Example sensor polling:
```python
from lumina_modbus_client import LuminaModbusClient
from lumina_modbus_event_emitter import ModbusEventEmitter

# Initialize client
client = LuminaModbusClient()
client.connect(port='/dev/ttyAMA3', baudrate=9600)

# Subscribe to sensor updates
def handle_sensor_update(response):
    if response.status == 'success':
        # Process sensor data
        pass

client.event_emitter.subscribe('PH_SENSOR', handle_sensor_update)
client.event_emitter.subscribe('EC_SENSOR', handle_sensor_update)
client.event_emitter.subscribe('DO_SENSOR', handle_sensor_update)
```

### Relay Control (ttyAMA4)
- Modbus RTU protocol
- Uses `lumina_modbus_client.py` for communication
- Direct control of pumps and valves

Example relay control:
```python
# Control nutrient pump A
client.send_command(
    device_type='RELAY',
    port='/dev/ttyAMA4',
    command=bytes([0x01, 0x05, 0x00, 0x00, 0xFF, 0x00])  # Turn on relay 1
)
```

## Error Handling

### Error Types
```python
class SystemError(Exception):
    """Base class for system errors"""
    pass

class SensorError(SystemError):
    """Sensor communication or reading errors"""
    pass

class RelayError(SystemError):
    """Relay control errors"""
    pass

class CommunicationError(SystemError):
    """Communication protocol errors"""
    pass
```

### Error Handling Behavior

1. **Sensor Errors**
   - Three retry attempts for each failed sensor read
   - System continues with last valid reading if within timeout window
   - Emergency stop if critical sensor (pH/EC/DO) fails for extended period

2. **Communication Errors**
   - Automatic retry for failed Modbus transactions
   - Fallback to safe mode if master communication lost
   - Individual sensor isolation on persistent errors

3. **Process Errors**
   - Immediate pump shutdown on abnormal readings
   - Automatic flush cycle on out-of-range pH/EC/DO
   - Alert master system of all error conditions

4. **Safety Responses**
   - Emergency stop on critical errors
   - Automatic valve closure on tank level errors
   - System lockout requiring manual reset for critical failures

## Installation

### Prerequisites
1. Raspberry Pi CM4 with appropriate I/O board
2. Python 3.8 or higher
3. Required Python packages:
   ```bash
   pip install pyserial
   pip install crcmod
   ```

### Setup
1. Enable serial ports in `/boot/config.txt`:
   ```
   enable_uart=1
   dtoverlay=uart2
   dtoverlay=uart3
   dtoverlay=uart4
   ```

2. Set up udev rules for consistent device naming:
   ```bash
   sudo nano /etc/udev/rules.d/99-ripple.rules
   ```
   Add:
   ```
   KERNEL=="ttyAMA*", SYMLINK+="ttyAMA%n"
   ```

3. Install the system:
   ```bash
   git clone https://github.com/your-repo/ripple.git
   cd ripple
   pip install -r requirements.txt
   ```

### Running the System
```bash
python3 ripple_control.py
```

## Project Structure

- `ripple_control.py` - Main control system
- `lumina_modbus_client.py` - Modbus communication client
- `lumina_modbus_event_emitter.py` - Event handling system
- `sensors/` - Sensor interface modules
- `relays/` - Relay control modules
- `utils/` - Utility functions
- `config/` - Configuration files

## Dependencies

- Python 3.8+
- pyserial
- crcmod
- Raspberry Pi CM4
- Appropriate I/O board

## License

This project is licensed under the MIT License - see the LICENSE file for details. 