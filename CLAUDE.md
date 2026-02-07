# Ripple

Intelligent fertigation control system for vertical farming. Automates nutrient dosing, pH control, water management, and irrigation scheduling. Runs on Raspberry Pi CM5.

## Tech Stack

- Python 3.11
- FastAPI + Uvicorn (REST API on port 5000)
- lumina-modbus-server (TCP bridge at `~/lumina-modbus-server`, port 8888)
- APScheduler + SQLite (persistent task scheduling)
- Watchdog (config file hot-reload)
- Pydantic 1.x (data validation)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Ripple Application                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────────┐  │
│  │ main.py  │  │server.py │  │  Simplified Controllers  │  │
│  │Controller│  │ REST API │  │ (sprinkler, nutrient,    │  │
│  │          │  │ :5000    │  │  pH, mixing, water_level)│  │
│  └────┬─────┘  └────┬─────┘  └───────────┬──────────────┘  │
│       │             │                    │                  │
│       └─────────────┴────────────────────┘                  │
│                         │                                   │
│              ┌──────────┴──────────┐                       │
│              │ LuminaModbusClient  │                       │
│              │   (TCP Socket)      │                       │
│              └──────────┬──────────┘                       │
└─────────────────────────┼───────────────────────────────────┘
                          │ TCP :8888
┌─────────────────────────┴───────────────────────────────────┐
│              lumina-modbus-server (~/lumina-modbus-server)  │
│                    Modbus RTU Bridge                        │
└───────────┬─────────────────────────────────┬───────────────┘
            │ Serial                          │ Serial
     ┌──────┴──────┐                   ┌──────┴──────┐
     │  /dev/ttyAMA2   │                   │  /dev/ttyAMA1   │
     │  Sensors (9600) │                   │ Relays (38400)  │
     └─────────────┘                   └─────────────┘
```

## Project Structure

```
main.py             # Main controller orchestrating all subsystems
server.py           # FastAPI REST API server (port 5000)
config/             # device.conf (INI), action.json (commands)
data/               # saved_sensor_data.json, system_status.txt
log/                # Rotating log files
src/
  globals.py        # Global config, scheduler setup, modbus client init
  helpers.py        # Utility functions (JSON parsing, datetime)
  lumina_logger.py  # File-based logging with rotation
  lumina_modbus_client.py        # TCP client to lumina-modbus-server (singleton)
  lumina_modbus_event_emitter.py # Pub-sub for async Modbus responses
  sensors/          # Hardware drivers (pH, EC, DO, water_level, Relay)
  simplified_*_controller.py     # Control modules with dual-layer protection
  *_static.py       # Static functions for scheduler serialization
samples/            # Example JSON files (action.json, instruction sets)
```

## Commands

```bash
# Start full system (main + server)
./start_ripple.sh

# Start components individually
python main.py      # Main controller
python server.py    # REST API server

# Setup/install
./setup_ripple.sh

# Dependencies
pip install -r requirements.txt

# IMPORTANT: lumina-modbus-server must be running first
# cd ~/lumina-modbus-server && ./start_server.sh
```

### Process Management

- **`start_ripple.sh` launches terminal GUI windows**, NOT systemd services. Do NOT use `systemctl` to restart or check status — it won't work.
- Processes typically run inside a tmux session. To restart: send `Ctrl-C` to the tmux panes, then relaunch.

### Logs

- **Always check `log/` directory** for application logs, not tmux pane output (tmux buffers get pushed out by verbose output)
- Log files rotate daily at 2MB max: `log/ripple_*.log`
- Example: `grep -i sprinkler log/ripple_*.log`

## Key Patterns

- **Singleton pattern** for hardware: `LuminaModbusClient`, `Relay` (prevents resource conflicts)
- **TCP Modbus bridge**: LuminaModbusClient connects to lumina-modbus-server via TCP socket (port 8888), which handles actual serial Modbus RTU communication
- **Dual-layer protection**: APScheduler (primary) + failsafe thread (backup) for critical operations
- **Static functions**: Controllers delegate to `*_static.py` modules to avoid APScheduler serialization issues
- **Port-specific locking**: Sequential Modbus access per serial port, parallel across different ports
- **Event-driven**: `ModbusEventEmitter` pub-sub pattern for async response handling
- **Hot-reload**: Watchdog monitors device.conf and action.json for live configuration updates. Old config values are available via `event_handler.last_config_state` during reload (updated *after* `reload_specific_sections()` returns)
- **Batch relay writes**: The relay board gets overwhelmed by rapid sequential Modbus commands. When controlling multiple adjacent relays, use `set_multiple_relays()` (Modbus function 0x10 Write Multiple Registers) instead of sequential `set_relay()` calls. See `set_nutrient_pumps()`, `_control_multiple_sprinklers()`, and `set_pump_from_tank_to_gutters()` for examples. For non-adjacent relays, add a small delay between individual writes.

## Configuration

- `config/device.conf` - System config (sensors, relays, parameters) in INI format
- `config/action.json` - Manual relay commands (JSON)
- Instruction sets - Grow cycle configs from central server (server_instruction_set.json)

### Config Value Format

Many config values use dual-value format: `default_value, operational_value`
- First value: server/default setting
- Second value: current operational setting (what's actually used)

### PLUMBING Section

The `[PLUMBING]` section uses `_on_at_startup` suffixed keys to control which relay devices are ON/OFF at startup. All 7 plumbing devices are configurable:

```ini
[PLUMBING]
ValveOutsideToTank_on_at_startup = true, true
ValveTankToOutside_on_at_startup = false, false
PumpFromTankToGutters_on_at_startup = true, true
MixingPump_on_at_startup = false, false
PumpFromCollectorTrayToTank_on_at_startup = false, false
LiquidCoolingPumpAndFan_on_at_startup = false, false
ValveCO2_on_at_startup = false, false
```

`RippleController.PLUMBING_STARTUP_DEVICES` maps these config keys to relay device names. `apply_plumbing_startup_configuration()` iterates the map and calls `relay.set_relay(device_name, bool_value)` for each. The same method is called on config hot-reload.

### Sprinkler Hot-Reload Behavior

When the `[Sprinkler]` section changes via hot-reload, the system compares old vs new values to decide whether to run sprinklers immediately or just reschedule:

| on_duration | wait_duration | Action |
|-------------|---------------|--------|
| any | `99:99:99` or `00:00:00` | **disable** scheduling |
| set to 0 | any | **disable** scheduling |
| increased | any | **immediate run** |
| any | decreased | **immediate run** |
| unchanged/decreased | unchanged/increased | reschedule only (no immediate run) |

Principle: "farmer wants more watering" (on increased, wait decreased) triggers immediate run. "Farmer wants less watering" (wait increased) just reschedules. Sentinel values disable entirely.

## Hardware

| Port | Baud | Purpose |
|------|------|---------|
| ttyAMA2 | 9600 | Sensors (pH 0x02, EC 0x03, DO 0x04, WaterLevel 0x05) |
| ttyAMA1 | 38400 | Relay board (0x01) - supports 4/8/16-channel boards |

### Relay Board Support

The system supports configurable multi-channel relay boards (4, 8, or 16 channels). The code handles up to 16 ports per board. Channel count depends on hardware configuration in device.conf.

## Important Files

- `main.py` - Entry point, RippleController orchestrator
- `server.py` - FastAPI REST API with HTTP Basic Auth (port 5000)
- `src/globals.py` - Central config, APScheduler instance, modbus client init
- `src/lumina_modbus_client.py` - TCP socket client to lumina-modbus-server (NOT direct serial)
- `src/lumina_modbus_event_emitter.py` - Pub-sub for Modbus responses
- `src/sensors/Relay.py` - Multi-channel relay board control (4/8/16-channel)
- `src/sensors/pH.py`, `ec.py`, `DO.py`, `water_level.py` - Sensor drivers
- `src/simplified_nutrient_controller.py` - Nutrient A/B/C pump control
- `src/simplified_ph_controller.py` - pH up/down pump control
- `src/simplified_sprinkler_controller.py` - Sprinkler scheduling
- `src/simplified_water_level_controller.py` - Tank level and auto-refill
- `src/*_static.py` - Static functions for APScheduler job serialization

## API Endpoints (port 5000)

- `GET /api/v1/status` - Full system status (sensors, relays, config)
- `GET /api/v1/system` - System info and version
- `POST /api/v1/action` - Control relays/devices
- `POST /api/v1/server_instruction_set` - Server-driven configuration
- `POST /api/v1/user_instruction_set` - User manual adjustments
- `GET/POST /api/v1/plumbing` - Plumbing valve/pump configuration
- `GET/POST /api/v1/sprinkler` - Sprinkler configuration
- `POST /api/v1/system/reboot` - Reboot system
- `POST /api/v1/system/restart` - Restart Ripple application

## Development Notes

### Critical Requirements

- **lumina-modbus-server MUST be running** before starting Ripple (provides Modbus RTU bridge on TCP port 8888)
- ALWAYS use singleton pattern for Modbus client and relay access
- Static functions in `*_static.py` cannot reference instance variables (APScheduler constraint)
- Missing hardware should degrade gracefully, not crash

### Best Practices

- Use `LuminaModbusClient` singleton - never create direct serial connections
- All Modbus operations go through lumina-modbus-server TCP bridge
- Check `globals.HAS_*` flags before accessing hardware (e.g., `globals.HAS_RELAY`)
- Use case-insensitive matching for relay device names
- Logs rotate daily at 2MB max per file in `log/` directory
- Test with sensors disconnected to verify graceful degradation

### Debugging

- Check `log/ripple_*.log` for application logs
- Check `data/system_status.txt` for human-readable status (updated every 5 min)
- Check `data/saved_sensor_data.json` for current sensor readings
- Verify lumina-modbus-server is running: `curl http://127.0.0.1:8888` or check its logs

### Common Issues

1. **No sensor data**: Ensure lumina-modbus-server is running
2. **Relay not responding**: Check device.conf RELAY_CONTROL section and Modbus address
3. **API 401 errors**: Check SYSTEM username/password in device.conf
4. **Scheduler jobs not running**: Check APScheduler logs, verify SQLite job store

## Deployed Devices

| Device | WireGuard IP | Description |
|--------|-------------|-------------|
| ripple-dagze-1 | 10.7.0.40 | Dagze farm fertigation controller |

### Deployment

```bash
# SSH to device
ssh lumina@10.7.0.40

# Deploy: pull code, restart
ssh lumina@10.7.0.40 "cd ~/ripple-rpi && git pull origin main"
ssh lumina@10.7.0.40 "curl -s -u 'ripple-rpi:+IHa0UpROx94' http://127.0.0.1:5000/api/v1/system/restart -X POST"

# Verify after restart
ssh lumina@10.7.0.40 "cd ~/ripple-rpi && grep -iE 'error|warning' log/ripple_*.log"
ssh lumina@10.7.0.40 "curl -s -u 'ripple-rpi:+IHa0UpROx94' http://127.0.0.1:5000/api/v1/plumbing | python3 -m json.tool"
```
