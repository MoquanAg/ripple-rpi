# Quick Scan Guide

## TL;DR

```bash
# 1. Start the modbus server (required!)
cd ~/lumina-modbus-server && ./start_server.sh

# 2. Navigate to the ripple-rpi directory
cd ~/ripple-rpi

# 3. Quick scan for devices (recommended)
./scan_modbus_devices.py --quick

# 4. Copy the output config to config/device.conf
```

## Common Commands

**Important**: Always run from the project root directory (`~/ripple-rpi`)

```bash
# Quick scan (fast, covers most cases)
./scan_modbus_devices.py --quick

# Full scan (all addresses, takes longer)
./scan_modbus_devices.py

# Scan specific ports only
./scan_modbus_devices.py --ports ttyAMA1,ttyAMA2

# Sequential mode (easier to read, slower)
./scan_modbus_devices.py --quick --sequential

# Help
./scan_modbus_devices.py --help
```

## What Gets Detected

- ✓ pH sensors (typically at 9600 baud)
- ✓ EC sensors (typically at 9600 baud)
- ✓ DO sensors (typically at 9600 baud)
- ✓ Water level sensors (typically at 9600 baud)
- ✓ Relay boards (typically at 38400 baud)

## Output Example

```
✓ ttyAMA2: Found pH at 0x02 (9600 baud) - pH: 7.14, Temp: 24.3°C
✓ ttyAMA2: Found EC at 0x03 (9600 baud) - EC: 1.450 mS/cm

Configuration snippets for device.conf:
[SENSORS]
pH_main = pH, main, ttyAMA2, 9600, 0x02
EC_main = EC, main, ttyAMA2, 9600, 0x03
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "lumina-modbus-server not running" | `cd ~/lumina-modbus-server && ./start_server.sh` |
| No devices found | Check wiring, try `--bauds 2400,4800,9600,19200,38400` |
| Too slow | Use `--quick` or reduce ports `--ports ttyAMA2` |

See [SCANNER_README.md](src/sensors/SCANNER_README.md) for full documentation.
