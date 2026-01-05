# Modbus Device Scanner

Automatically scans serial ports to detect and identify Modbus RTU devices (sensors and relays).

## Features

- **Parallel Port Scanning**: Scans multiple ports simultaneously for faster results
- **Automatic Device Identification**: Identifies pH, EC, DO, Water Level sensors and Relays
- **Value Validation**: Uses typical value ranges to confirm device types
- **Configuration Output**: Generates ready-to-use device.conf snippets

## Prerequisites

1. **lumina-modbus-server must be running**:
   ```bash
   cd ~/lumina-modbus-server
   ./start_server.sh
   ```

2. The scanner uses the TCP bridge (lumina-modbus-server) to communicate with Modbus devices

## Usage

### Quick Start

From the project root directory:

```bash
# Quick scan with defaults (parallel, common addresses)
./scan_modbus_devices.py --quick

# Full scan (all addresses 0x01-0xFF)
./scan_modbus_devices.py

# Scan specific ports only
./scan_modbus_devices.py --ports ttyAMA1,ttyAMA2

# Scan with specific baud rates
./scan_modbus_devices.py --bauds 9600,38400
```

### Command Line Options

```bash
./scan_modbus_devices.py [OPTIONS]

Options:
  --ports PORTS         Comma-separated list of ports (default: ttyAMA1,ttyAMA2,ttyAMA3,ttyAMA4)
  --bauds BAUDS         Comma-separated baud rates (default: 4800,9600,38400)
  --start-addr ADDR     Start address in hex (default: 0x01)
  --end-addr ADDR       End address in hex (default: 0xFF)
  --timeout SECONDS     Timeout per probe (default: 0.5)
  --quick               Quick scan mode (0x01-0x50, 9600/38400 only)
  --sequential          Scan ports sequentially instead of in parallel
  --help                Show help message
```

### Examples

```bash
# Quick scan (recommended for first-time setup)
./scan_modbus_devices.py --quick

# Scan only two specific ports at 9600 baud
./scan_modbus_devices.py --ports ttyAMA1,ttyAMA2 --bauds 9600

# Full address range scan (takes longer)
./scan_modbus_devices.py --start-addr 0x01 --end-addr 0xFF

# Sequential scan (slower but easier to read output)
./scan_modbus_devices.py --quick --sequential

# Custom timeout for slow devices
./scan_modbus_devices.py --quick --timeout 1.0
```

## Device Detection

The scanner identifies devices by:

### pH Sensors
- Register: 0x0000
- Baud: Typically 9600 (or 4800 if factory reset)
- Value range: 0-14 pH units
- Example: pH: 7.23, Temp: 25.1°C

### EC Sensors
- Register: 0x0000
- Baud: Typically 9600 (or 4800 if factory reset)
- Value range: 0-5 mS/cm
- Example: EC: 1.245 mS/cm

### DO Sensors (Dissolved Oxygen)
- Register: 0x0014
- Baud: Typically 9600 (or 4800 if factory reset)
- Value range: 0-25 mg/L
- Example: DO: 8.45 mg/L

### Water Level Sensors
- Register: 0x0004
- Baud: Typically 9600 (or 4800 if factory reset)
- Value range: -100 to 500 cm
- Example: Level: 42 cm

### Relay Boards
- Register: 0x0000
- Baud: Almost always 38400
- Supports 4/8/16-channel boards

## Output

The scanner provides:

1. **Real-time discovery**: Devices are shown as they're found
2. **Progress tracking**: Overall scan progress percentage
3. **Summary report**: Grouped by device type
4. **Configuration snippets**: Ready-to-paste into device.conf

### Example Output

```
======================================================================
Modbus Device Scanner
======================================================================
Scanning 4 ports × 3 baud rates × 80 addresses
Total attempts: 960
Mode: Parallel (scanning 4 ports simultaneously)
Estimated time: 2.0 minutes
======================================================================

  ✓ ttyAMA2: Found pH           at 0x02 (9600 baud) - pH: 7.14, Temp: 24.3°C
  ✓ ttyAMA2: Found EC           at 0x03 (9600 baud) - EC: 1.450 mS/cm
  ✓ ttyAMA2: Found DO           at 0x04 (9600 baud) - DO: 8.23 mg/L
  ✓ ttyAMA2: Found Water_Level  at 0x05 (9600 baud) - Level: 45 cm
  ✓ ttyAMA1: Found Relay        at 0x01 (38400 baud) - Relay status: 0x00

======================================================================
Scan Complete
======================================================================

Found 5 device(s):

pH Sensors (1):
──────────────────────────────────────────────────────────────────────
  [✓] /dev/ttyAMA2    | Addr: 0x02 (  2) | Baud:   9600 | pH: 7.14, Temp: 24.3°C

EC Sensors (1):
──────────────────────────────────────────────────────────────────────
  [✓] /dev/ttyAMA2    | Addr: 0x03 (  3) | Baud:   9600 | EC: 1.450 mS/cm

...

======================================================================
Configuration snippets for device.conf:
======================================================================

[SENSORS] # pH
pH_main = pH, main, ttyAMA2, 9600, 0x02

[SENSORS] # EC
EC_main = EC, main, ttyAMA2, 9600, 0x03

...
```

## Performance

### Parallel Mode (Default)
- Scans all ports simultaneously
- 4 ports: ~4x faster than sequential
- Recommended for most cases

### Sequential Mode
- Scans one port at a time
- Cleaner output, easier to follow
- Use with `--sequential` flag

### Timing Examples

| Mode       | Ports | Addresses | Est. Time |
|------------|-------|-----------|-----------|
| Quick      | 4     | 0x01-0x50 | 2 min     |
| Quick Seq  | 4     | 0x01-0x50 | 8 min     |
| Full       | 4     | 0x01-0xFF | 6 min     |
| Full Seq   | 4     | 0x01-0xFF | 26 min    |

## Troubleshooting

### "lumina-modbus-server is not running"
Start the server first:
```bash
cd ~/lumina-modbus-server
./start_server.sh
```

### No devices found
1. Check physical connections (RS485 A/B wiring)
2. Verify power to sensors
3. Try a wider baud rate range: `--bauds 2400,4800,9600,19200,38400`
4. Try full address range without `--quick`
5. Increase timeout: `--timeout 1.0`

### Device detected at wrong baud rate (marked with `?`)
- Sensor may need configuration
- Try the detected baud rate in device.conf
- Consider factory reset if available

### Scanner hangs or is very slow
- Use `--quick` for faster initial scan
- Reduce address range: `--end-addr 0x20`
- Check if lumina-modbus-server is responding: `curl http://127.0.0.1:8888`

## Integration with device.conf

After scanning, copy the configuration snippets to `config/device.conf`:

```ini
[SENSORS]
pH_main = pH, main, ttyAMA2, 9600, 0x02
EC_main = EC, main, ttyAMA2, 9600, 0x03
DO_main = DO, main, ttyAMA2, 9600, 0x04
WATER_LEVEL_main = water_level, main, ttyAMA2, 9600, 0x05

[RELAY_CONTROL]
RelayOne = relay, ttyAMA1, 38400, 0x01, 16
```

## Technical Details

### Communication Protocol
- Uses lumina-modbus-server TCP bridge (port 8888)
- Modbus RTU over RS485 serial
- Function code 0x03 (Read Holding Registers)
- Standard 8N1 serial configuration

### Thread Safety
- Parallel scanning uses ThreadPoolExecutor
- Thread-safe device list and progress tracking
- Lock-protected console output

### Device Identification Logic
1. Try to read specific registers for each device type
2. Validate response structure
3. Check if values are in typical range for that sensor
4. Match baud rate against typical values
5. Return best match with confidence indicator
