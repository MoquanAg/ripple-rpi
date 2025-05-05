import serial
import time
import os, sys

current_dir = os.path.dirname(__file__)
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from lumina_modbus_event_emitter import ModbusResponse

import globals
from src.lumina_logger import GlobalLogger

logger = GlobalLogger("RippleRelay", log_prefix="ripple_").logger
import helpers


class Relay:
    _instance = None  # Class variable to hold the singleton instance

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            # Check if Relay is enabled in config
            if not globals.HAS_RELAY:
                logger.info("Relay control is disabled in configuration")
                return None
                
            logger.debug(f"Creating Relay instance.")
            cls._instance = super(Relay, cls).__new__(cls)
            cls._instance.init(*args, **kwargs)  # Initialize the instance
            cls._instance.modbus_client = globals.modbus_client
            cls._instance.modbus_client.event_emitter.subscribe(
                "relay", cls._instance._handle_response
            )
            cls._instance.pending_commands = {}
        return cls._instance

    def init(self, port=None):
        # Use port from config if available, otherwise use default
        config = globals.DEVICE_CONFIG_FILE
        self.port = globals.get_device_port('RELAY_CONTROL', 'RelayOne', '/dev/ttyAMA4')
        self.data_path = globals.SAVED_SENSOR_DATA_PATH
        self.address = 0x01  # Default address
        self.ser = serial.Serial()
        # Get baud rate from config file
        self.baud_rate = globals.get_device_baudrate('RELAY_CONTROL', 'RelayOne', 38400)
        self.relay_statuses = {}  # Changed to dict to store multiple relay states
        self.last_updated = None
        self.load_addresses()  # Changed from load_address to load_addresses

    def _handle_response(self, response: ModbusResponse) -> None:
        """
        Handle responses from the modbus client event emitter.
        """
        #logger.info(f"Command queued for for relay with UUID: {response.command_id}")
        if response.command_id in self.pending_commands:
            command_info = self.pending_commands[response.command_id]
            if response.status == "success":
                logger.debug(f"Response data: {response.data}")  # Debug the response data
                logger.debug(f"Command info: {command_info}")    # Debug the command info
                if command_info["type"] == "get_status":
                    self._process_status_response(response.data, command_info)
                elif command_info["type"] in ["turn_on", "turn_off"]:
                    self._process_control_response(response.data, command_info)
            elif response.status in ["timeout", "error", "connection_lost"]:
                logger.warning(
                    f"Command failed with status {response.status} for command id {response.command_id}"
                )
                self.save_null_data()
            del self.pending_commands[response.command_id]

    def _process_status_response(self, data, command_info):
        """Process the raw response data from the sensor."""
        logger.debug(f"Processing status response - Data: {data}, Command Info: {command_info}")
        if data and len(data) >= 5:
            try:
                status_byte = data[3]  # First status byte
                relay_name = command_info.get("relay_name")
                logger.debug(f"Status byte: {status_byte}, Relay name: {relay_name}")
                if relay_name:
                    # Use the exact relay name from the config
                    # Initialize the relay_statuses dict for this relay if it doesn't exist
                    if relay_name not in self.relay_statuses:
                        self.relay_statuses[relay_name] = [0] * 16  # Initialize with 16 ports
                    
                    # Update the first 8 ports from the status byte
                    port_statuses = [(status_byte >> i) & 1 for i in range(8)]
                    
                    # Handle 16 ports (read the second byte if available)
                    if len(data) >= 6:
                        status_byte_2 = data[4]  # Second status byte
                        port_statuses.extend([(status_byte_2 >> i) & 1 for i in range(8)])
                    else:
                        # If no second byte, keep last 8 ports at 0
                        port_statuses.extend([0] * 8)
                    
                    # Ensure exactly 16 ports
                    self.relay_statuses[relay_name] = port_statuses[:16]
                    
                    self.last_updated = helpers.datetime_to_iso8601()
                    logger.info(f"{relay_name} statuses: {self.relay_statuses[relay_name]}")
                    # Save data for just this relay
                    self.save_data(relay_name=relay_name)
            except Exception as e:
                logger.warning(f"Error processing relay status response: {e}")
                logger.exception("Full exception details:")
                return
        else:
            logger.debug(f"Invalid response length: {len(data) if data else 0}")
            return

    def _process_control_response(self, data, command_info):
        """Process response from turn on/off commands."""
        logger.debug(f"Processing control response - Data: {[hex(b) for b in data] if data else None}")
        logger.debug(f"Command info: {command_info}")
        
        if not data:
            logger.warning("No data received in control response")
            return
        
        if len(data) < 8:
            logger.warning(f"Invalid control response length: {len(data)}")
            return

        try:
            # Get the correct address for the device
            device_name = command_info.get('device', '').upper()
            expected_address = self.relay_addresses.get(device_name, self.address)
            
            # Verify response format
            if data[0] != expected_address:
                logger.warning(f"Address mismatch - Expected: 0x{expected_address:02X}, Got: 0x{data[0]:02X}")
                return
            
            if data[1] != 0x05:  # Function code for single coil write
                logger.warning(f"Unexpected function code: 0x{data[1]:02X}")
                return
            
            # Check if the response matches the command
            relay_index = command_info.get('relay')
            if data[2] != 0x00 or data[3] != relay_index:
                logger.warning(f"Relay index mismatch - Expected: {relay_index}, Got: {data[3]}")
                return
            
            # Verify the status matches (0xFF00 for ON, 0x0000 for OFF)
            expected_status = 0xFF if command_info['type'] == 'turn_on' else 0x00
            if data[4] != expected_status:
                logger.warning(f"Status mismatch - Expected: 0x{expected_status:02X}, Got: 0x{data[4]:02X}")
                return
            
            logger.info(f"Relay {command_info['type']} command successful for {device_name}[{relay_index}]")
            
        except Exception as e:
            logger.warning(f"Error processing relay control response: {e}")
            logger.exception("Full exception details:")

    def get_status(self):
        """Queue status request commands for all configured relays."""
        for relay_name, address in self.relay_addresses.items():
            logger.info(f"Sending status request to {relay_name} at address 0x{address:02X}")
            try:
                # Request status for 16 coils (0x00 to 0x0F)
                command = bytearray([address, 0x01, 0x00, 0x00, 0x00, 0x10])
                logger.info(f"Command bytes: {[f'0x{b:02X}' for b in command]}")
                
                timeout = 2.0
                command_id = self.modbus_client.send_command(
                    device_type="relay",
                    port=self.port,  # Use the port from config
                    command=command,
                    baudrate=self.baud_rate,
                    response_length=6,  # This should be 7 for 16 ports
                    timeout=timeout,
                )
                logger.info(f"baudrate: {self.baud_rate}")
                # Track the pending command with timestamp
                self.pending_commands[command_id] = {
                    "type": "get_status",
                    "relay_name": relay_name,
                    "timestamp": time.time(),
                    "timeout": timeout
                }
                
            except Exception as e:
                logger.error(f"Failed to send command for {relay_name}: {e}")
                self.save_null_data()

    def turn_on(self, device_name, relay_index):
        """Queue a turn on command with the modbus client."""
        # Get the correct address for the device from relay_addresses
        address = self.relay_addresses.get(device_name.upper(), self.address)
        command = bytearray([address, 0x05, 0x00, relay_index, 0xFF, 0x00])
        command_id = self.modbus_client.send_command(
            device_type="relay",
            port=self.port,  # Use the port from config
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=0.5,
        )
        self.pending_commands[command_id] = {
            "type": "turn_on",
            "device": device_name,
            "relay": relay_index,
        }
        logger.debug(
            f"Sent turn on command for relay {relay_index} with UUID: {command_id}"
        )

    def turn_off(self, device_name, relay_index):
        """Queue a turn off command with the modbus client."""
        # Get the correct address for the device from relay_addresses
        address = self.relay_addresses.get(device_name.upper(), self.address)
        command = bytearray([address, 0x05, 0x00, relay_index, 0x00, 0x00])
        command_id = self.modbus_client.send_command(
            device_type="relay",
            port=self.port,  # Use the port from config
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=0.5,
        )
        self.pending_commands[command_id] = {
            "type": "turn_off",
            "device": device_name,
            "relay": relay_index,
        }
        logger.debug(
            f"Sent turn off command for relay {relay_index} with UUID: {command_id}"
        )

    def load_addresses(self):
        """Load relay addresses and assignments from config file"""
        config = globals.DEVICE_CONFIG_FILE
        try:
            self.relay_addresses = {}
            self.relay_board_names = {}  # Map from config key to display name
            
            logger.info(f"Available config sections: {config.sections()}")
            if "RELAY_CONTROL" in config:
                logger.info(f"RELAY_CONTROL section content: {dict(config['RELAY_CONTROL'])}")
                for key, value in config["RELAY_CONTROL"].items():
                    # Process all relay entries
                    parts = value.split(',')
                    if len(parts) >= 5:  # We need at least 5 parts for the address
                        hex_address = int(parts[4].strip(), 16)
                        # Use the exact key from the config (e.g., "relayone")
                        self.relay_addresses[key] = hex_address
                        
                        # Construct relay_board name as "relay_type" (e.g., "relay_ripple")
                        # from the first two comma-separated values
                        if len(parts) >= 2:
                            relay_type = parts[0].strip()
                            relay_name = parts[1].strip()
                            board_name = f"{relay_type}_{relay_name}"
                            self.relay_board_names[key] = board_name
                            logger.info(f"Relay board name for {key}: {board_name}")
                        
                        logger.info(f"Loaded {key} address: 0x{hex_address:02X} (decimal: {hex_address})")
                logger.info(f"Final relay_addresses: {self.relay_addresses}")
                logger.info(f"Final relay_board_names: {self.relay_board_names}")
            else:
                logger.info("No RELAY_CONTROL section found in config. Using default address.")
                
            # Load relay assignments
            if "RELAY_ASSIGNMENTS" in config:
                self.relay_assignments = {}
                
                # Parse the relay assignments explicitly from the config format
                # Example: relay_one_0_to_3 = NutrientPumpA, NutrientPumpB, NutrientPumpC, pHUpPump
                for key, value in config["RELAY_ASSIGNMENTS"].items():
                    if key.startswith('relay_'):
                        parts = key.split('_')
                        if len(parts) >= 5 and parts[3] == 'to':
                            relay_group = parts[1]  # Keep exact case: 'one' instead of 'ONE'
                            start_index = int(parts[2])     # Get '0' from 'relay_one_0_to_3'
                            end_index = int(parts[4])       # Get '3' from 'relay_one_0_to_3'
                            
                            devices = [d.strip() for d in value.split(',')]
                            
                            if len(devices) != (end_index - start_index + 1):
                                logger.warning(f"Number of devices ({len(devices)}) doesn't match range {start_index}-{end_index}")
                            
                            # Find the config key for this relay group
                            relay_key = None
                            for k in self.relay_addresses.keys():
                                if relay_group in k:
                                    relay_key = k
                                    break
                            
                            if relay_key is None:
                                logger.warning(f"Could not find relay key for group {relay_group}")
                                continue
                                
                            # Get the board name for this relay
                            board_name = self.relay_board_names.get(relay_key, f"relay_{relay_group}")
                            
                            # Assign each device to its port
                            for i, device in enumerate(devices):
                                if i < (end_index - start_index + 1):
                                    port_index = start_index + i
                                    self.relay_assignments[device] = {
                                        'relay_group': relay_group,
                                        'index': port_index,
                                        'relay_name': relay_key,
                                        'board_name': board_name
                                    }
                                    logger.info(f"Assigned {device} to {board_name} port {port_index}")
                
                logger.info(f"Loaded {len(self.relay_assignments)} relay assignments: {self.relay_assignments}")
            else:
                logger.warning("No RELAY_ASSIGNMENTS section found in config")
                
        except ValueError as e:
            logger.warning(f"Invalid address format in config: {e}")
        except Exception as e:
            logger.warning(f"Error loading relay addresses: {e}")
            logger.exception("Full exception details:")

    def _get_relay_info(self, device_name):
        """Get relay name and index for a device name."""
        if device_name in self.relay_assignments:
            info = self.relay_assignments[device_name]
            return info.get('relay_name', None), info.get('index', None)
        return None, None

    def save_null_data(self):
        """Save null data in the new format."""
        self.relay_statuses = {}
        self.last_updated = helpers.datetime_to_iso8601()
        
        null_relay_data = {
            "last_updated": self.last_updated
        }
        
        # For each relay in relay_addresses, create a null status array
        for relay_name in self.relay_addresses.keys():
            board_name = self.relay_board_names.get(relay_name, relay_name)
            null_relay_data[board_name] = [0] * 16  # 16 ports with status 0
        
        # Add last_updated to null devices data as well
        null_devices_data = {
            "last_updated": self.last_updated
        }
        
        helpers.save_sensor_data(["relays"], null_relay_data)
        helpers.save_sensor_data(["devices"], null_devices_data)
        
        # Also save null relay metrics data
        self._save_null_metrics_data()

    def save_data(self, relay_name=None):
        """
        Save status data in the new format.
        """
        try:
            # If relay_name is provided, only process that relay
            relays_to_process = [relay_name] if relay_name else self.relay_addresses.keys()
            
            # Create metrics data structure for relay_metrics
            metrics_data = {
                "measurements": {
                    "name": "relay_metrics",
                    "points": []
                }
            }
            
            # Keep track of assigned ports for configuration
            assigned_ports_map = {}
            
            # Process relay status points for each relay
            for current_relay in relays_to_process:
                # Get the board name for this relay
                board_name = self.relay_board_names.get(current_relay, current_relay)
                
                # Initialize assigned ports for this relay
                assigned_ports_map[current_relay] = []
                
                # Ensure we can access up to 16 ports even if we only have status for 8
                status_array = self.relay_statuses.get(current_relay, [0] * 16)
                if len(status_array) < 16:
                    status_array.extend([0] * (16 - len(status_array)))
                
                # Create points for all 16 ports
                for port_index in range(16):
                    status = status_array[port_index] if port_index < len(status_array) else 0
                    
                    # Default to unassigned
                    point = {
                        "tags": {
                            "relay_board": board_name,  # Use the board name from config
                            "port_index": port_index,
                            "port_type": "unassigned",
                            "device": "none"
                        },
                        "fields": {
                            "status": status,
                            "is_assigned": False,
                            "raw_status": status
                        },
                        "timestamp": self.last_updated
                    }
                    
                    # Check if port is assigned to a device
                    for device_name, info in self.relay_assignments.items():
                        if info.get('relay_name') == current_relay and info.get('index') == port_index:
                            point["tags"]["port_type"] = "assigned"
                            point["tags"]["device"] = device_name
                            point["fields"]["is_assigned"] = True
                            assigned_ports_map[current_relay].append(port_index)
                            break
                    
                    metrics_data["measurements"]["points"].append(point)
            
            # Save relay metrics points
            helpers.save_sensor_data(["data", "relay_metrics"], metrics_data)
            
            # Save relay configuration
            config_data = {
                "relay_configuration": {}
            }
            
            # Update configuration with assigned and unassigned ports
            for relay in relays_to_process:
                assigned = assigned_ports_map.get(relay, [])
                board_name = self.relay_board_names.get(relay, relay)
                
                config_data["relay_configuration"][board_name] = {
                    "total_ports": 16,
                    "assigned_ports": sorted(assigned),
                    "unassigned_ports": sorted(list(set(range(16)) - set(assigned)))
                }
                
                logger.info(f"Relay {board_name} assigned ports: {sorted(assigned)}")
                logger.info(f"Relay {board_name} unassigned ports: {sorted(list(set(range(16)) - set(assigned)))}")
            
            helpers.save_sensor_data(["data", "relay_metrics", "configuration"], config_data)
            
            # Update relay status in the main structure
            relay_data = {
                "last_updated": self.last_updated
            }
            
            # Create full relay status structure
            for current_relay in relays_to_process:
                # Ensure we have status for all 16 ports
                status_array = self.relay_statuses.get(current_relay, [0] * 16)
                if len(status_array) < 16:
                    status_array.extend([0] * (16 - len(status_array)))
                
                # Use the board name from config
                board_name = self.relay_board_names.get(current_relay, current_relay)
                relay_data[board_name] = status_array[:16]  # Ensure exactly 16 elements
            
            # Save relay status
            helpers.save_sensor_data(["relays"], relay_data)
            
            # Update devices data
            devices_data = {
                "last_updated": self.last_updated
            }
            helpers.save_sensor_data(["devices"], devices_data)
            
            logger.info(f"Saved relay data with assignments.")
            
        except Exception as e:
            logger.error(f"Error in save_data: {e}")
            logger.exception("Full exception details:")

    # Convenience methods for controlling specific devices
    def set_nanobubbler(self, status):
        if not globals.HAS_NANOBUBBLER:
            logger.info("No nanobubbler hardware present, skipping set_nanobubbler")
            return

        """Set nanobubbler status."""
        logger.info(f"Setting nanobubbler to {status}")
        if status:
            self.turn_on(globals.RELAY_NAME, globals.Nanobubbler)
        else:
            self.turn_off(globals.RELAY_NAME, globals.Nanobubbler)

    def set_substrate_feed_pump(self, status):
        if not globals.MODEL.lower() == "substrate":
            logger.info("Not a substrate model, skipping set_substrate_feed_pump")
            return

        try:
            # Get the relay assignments from config
            assignments = globals.DEVICE_CONFIG_FILE['RELAY_ASSIGNMENTS']
            irrigation_assignments = assignments.get('Relay_IRRIGATION_4_to_7', '').split(',')
            
            # Find indices for feed pumps
            feed_pump_a_index = None
            feed_pump_b_index = None
            for i, device in enumerate(irrigation_assignments):
                device = device.strip()
                if device == 'FeedPumpA':
                    feed_pump_a_index = i + 4  # Offset by 4 since this is 4_to_7 group
                elif device == 'FeedPumpB':
                    feed_pump_b_index = i + 4  # Offset by 4 since this is 4_to_7 group
            
            if feed_pump_a_index is None or feed_pump_b_index is None:
                raise KeyError("FeedPumpA or FeedPumpB not found in RELAY_IRRIGATION_4_to_7 assignments")

            if status:
                self.set_multiple_relays(
                    "RELAY_IRRIGATION",
                    min(feed_pump_a_index, feed_pump_b_index),
                    [True, True],
                )
            else:
                self.set_multiple_relays(
                    "RELAY_IRRIGATION",
                    min(feed_pump_a_index, feed_pump_b_index),
                    [False, False],
                )
        except KeyError as e:
            logger.warning(f"Missing configuration for substrate feed pumps: {e}")
        except Exception as e:
            logger.error(f"Error controlling substrate feed pumps: {e}")

    def set_substrate_drain_pump(self, status):
        if not globals.MODEL.lower() == "substrate":
            logger.info("Not a substrate model, skipping set_substrate_drain_pump")
            return

        try:
            # Get the relay assignments from config
            assignments = globals.DEVICE_CONFIG_FILE['RELAY_ASSIGNMENTS']
            irrigation_assignments = assignments.get('Relay_IRRIGATION_4_to_7', '').split(',')
            
            # Find indices for drain pumps
            drain_pump_a_index = None
            drain_pump_b_index = None
            for i, device in enumerate(irrigation_assignments):
                device = device.strip()
                if device == 'DrainPumpA':
                    drain_pump_a_index = i + 4  # Offset by 4 since this is 4_to_7 group
                elif device == 'DrainPumpB':
                    drain_pump_b_index = i + 4  # Offset by 4 since this is 4_to_7 group
            
            if drain_pump_a_index is None or drain_pump_b_index is None:
                raise KeyError("DrainPumpA or DrainPumpB not found in RELAY_IRRIGATION_4_to_7 assignments")

            if status:
                self.set_multiple_relays(
                    "RELAY_IRRIGATION",
                    min(drain_pump_a_index, drain_pump_b_index),
                    [True, True],
                )
            else:
                self.set_multiple_relays(
                    "RELAY_IRRIGATION",
                    min(drain_pump_a_index, drain_pump_b_index),
                    [False, False],
                )
        except KeyError as e:
            logger.warning(f"Missing configuration for substrate drain pumps: {e}")
        except Exception as e:
            logger.error(f"Error controlling substrate drain pumps: {e}")

    def set_substrate_actuator(self, direction, turn_off_pumps=False):
        logger.info(f"set_substrate_actuator: direction: {direction}, turn_off_pumps: {turn_off_pumps}")
        if not globals.MODEL.lower() == "substrate":
            logger.info("Not a substrate model, skipping set_substrate_actuator")
            return

        relay_name = "RELAY_IRRIGATION"

        actuator_positive_a_index = int(
            globals.DEVICE_CONFIG_FILE[relay_name]["ActuatorPositiveA"]
        )
        actuator_positive_b_index = int(
            globals.DEVICE_CONFIG_FILE[relay_name]["ActuatorPositiveB"]
        )
        actuator_negative_a_index = int(
            globals.DEVICE_CONFIG_FILE[relay_name]["ActuatorNegativeA"]
        )
        actuator_negative_b_index = int(
            globals.DEVICE_CONFIG_FILE[relay_name]["ActuatorNegativeB"]
        )

        # Get pump indices if we need to turn them off
        if turn_off_pumps:
            feed_pump_a_index = int(globals.DEVICE_CONFIG_FILE[relay_name]["FeedPumpA"])
            feed_pump_b_index = int(globals.DEVICE_CONFIG_FILE[relay_name]["FeedPumpB"])
            drain_pump_a_index = int(globals.DEVICE_CONFIG_FILE[relay_name]["DrainPumpA"])
            drain_pump_b_index = int(globals.DEVICE_CONFIG_FILE[relay_name]["DrainPumpB"])

        # Support for numerical values
        if isinstance(direction, (int, float)):
            if direction == 1:
                direction = "release"
            elif direction == 0:
                direction = "off"
            elif direction == -1:
                direction = "retract"
            else:
                logger.warning(f"Invalid numerical direction: {direction}. Must be -1, 0, or 1.")
                return

        # Prepare actuator states based on direction
        actuator_states = [False, False, False, False]  # Default to all off
        if direction == "release":
            actuator_states = [True, True, False, False]
        elif direction == "retract":
            actuator_states = [False, False, True, True]
        # "off" will use the default [False, False, False, False]

        # If turn_off_pumps is True, append pump states (all False)
        if turn_off_pumps:
            pump_states = [False, False, False, False]  # Turn off all pumps
            all_states = actuator_states + pump_states
            self.set_multiple_relays(relay_name, actuator_positive_a_index, all_states)
        else:
            # Original behavior with just actuator states
            self.set_multiple_relays(relay_name, actuator_positive_a_index, actuator_states)

    def set_multiple_relays(self, device_name, starting_relay_index, states):
        """
        Set multiple consecutive relays with a single command.
        
        Args:
            device_name (str): Name of the device
            starting_relay_index (int): Starting relay index
            states (list): List of boolean values indicating desired states (1 to 8 states)
        """
        logger.info(f"Setting {len(states)} relays starting at index {starting_relay_index} with states {states}")
        if not 1 <= len(states) <= 16:
            logger.warning("Must provide between 1 and 16 relay states")
            return
        
        # Get the correct address for the device from relay_addresses
        address = self.relay_addresses.get(device_name.upper(), self.address)
        
        num_registers = len(states)
        byte_count = num_registers * 2  # Each register needs 2 bytes
        
        # Create state bytes - each relay state needs two bytes (0x00, 0x01 for ON, 0x00, 0x00 for OFF)
        state_bytes = []
        for state in states:
            state_bytes.extend([0x00, 0x01] if state else [0x00, 0x00])
        
        command = bytearray([
            address,          # Device address (now using correct address)
            0x10,            # Function code (write multiple registers)
            0x00,            # Starting address high byte
            starting_relay_index,  # Starting address low byte
            0x00, num_registers,  # Number of registers to write
            byte_count,      # Byte count
            *state_bytes     # State bytes
        ])
        
        command_id = self.modbus_client.send_command(
            device_type="relay",
            port=self.port,
            command=command,
            baudrate=self.baud_rate,
            response_length=8,
            timeout=0.5,
        )
        logger.info(f"baudrate: {self.baud_rate}")
        self.pending_commands[command_id] = {
            "type": f"set_{num_registers}_relays",
            "device": device_name,
            "starting_relay": starting_relay_index,
            "states": states
        }
        logger.info(
            f"Sent set_{num_registers}_relays command starting at relay {starting_relay_index} "
            f"Command: {command}, UUID: {command_id}"
        )

    # Convenience methods to maintain the original API
    def set_four_relays(self, device_name, starting_relay_index, states):
        """Wrapper for set_multiple_relays with 4 states"""
        if len(states) != 4:
            logger.warning("set_four_relays requires exactly 4 states")
            return
        return self.set_multiple_relays(device_name, starting_relay_index, states)

    def set_three_relays(self, device_name, starting_relay_index, states):
        """Wrapper for set_multiple_relays with 3 states"""
        if len(states) != 3:
            logger.warning("set_three_relays requires exactly 3 states")
            return
        return self.set_multiple_relays(device_name, starting_relay_index, states)

    def set_two_relays(self, device_name, starting_relay_index, states):
        """Wrapper for set_multiple_relays with 2 states"""
        if len(states) != 2:
            logger.warning("set_two_relays requires exactly 2 states")
            return
        return self.set_multiple_relays(device_name, starting_relay_index, states)

    def set_valve_from_outside_to_tank(self, status):
        """Control valve for flow from outside to tank."""
        logger.info(f"Setting outside-to-tank valve to {status}")
        relay_group, index = self._get_relay_info("ValveOutsideToTank")
        if relay_group and index:
            if status:
                self.turn_on(relay_group, index)
            else:
                self.turn_off(relay_group, index)
        else:
            logger.warning("ValveOutsideToTank not found in relay assignments")

    def set_valve_from_tank_to_outside(self, status):
        """Control valve for flow from tank to outside."""
        logger.info(f"Setting tank-to-outside valve to {status}")
        relay_group, index = self._get_relay_info("ValveTankToOutside")
        if relay_group and index:
            if status:
                self.turn_on(relay_group, index)
            else:
                self.turn_off(relay_group, index)
        else:
            logger.warning("ValveTankToOutside not found in relay assignments")

    def set_pump_recirculation(self, status):
        """Control recirculation pump.
        
        Args:
            status (bool): True to turn on pump, False to turn off
        """
        if not any(key in self.relay_addresses for key in ['RELAYTWO']):
            logger.info("No recirculation pump hardware present in RELAY_TWO")
            return

        logger.info(f"Setting recirculation pump to {status}")
        try:
            # Get the relay assignments from config
            assignments = globals.DEVICE_CONFIG_FILE['RELAY_ASSIGNMENTS']
            relay_two_assignments = assignments.get('Relay_TWO_0_to_3', '').split(',')
            
            # Find the index of PumpRecirculation in the assignments
            for i, device in enumerate(relay_two_assignments):
                if device.strip() == 'PumpRecirculation':
                    pump_index = i
                    break
            else:
                raise KeyError("PumpRecirculation not found in RELAY_TWO_0_to_3 assignments")
            
            if status:
                self.turn_on("RELAYTWO", pump_index)
            else:
                self.turn_off("RELAYTWO", pump_index)
                
        except KeyError as e:
            logger.warning(f"Missing configuration for recirculation pump: {e}")
        except Exception as e:
            logger.error(f"Error controlling recirculation pump: {e}")

    def set_pump_from_tank_to_gutters(self, status):
        """Control pump from tank to gutters.
        
        Args:
            status (bool): True to turn on pump, False to turn off
        """
        if not any(key in self.relay_addresses for key in ['RELAYONE']):
            logger.info("No tank-to-gutters pump hardware present in RELAY_ONE")
            return

        logger.info(f"Setting tank-to-gutters pump to {status}")
        try:
            # Get all relay assignments from config
            assignments = globals.DEVICE_CONFIG_FILE['RELAY_ASSIGNMENTS']
            
            # Search through all relay groups for PumpFromTankToGutters
            for group_name, devices in assignments.items():
                if not group_name.startswith('Relay_'):
                    continue
                    
                device_list = devices.split(',')
                for i, device in enumerate(device_list):
                    if device.strip() == 'PumpFromTankToGutters':
                        # Extract the base index from group name
                        base_index = int(group_name.split('_')[2])
                        pump_index = i + base_index
                        
                        if status:
                            self.turn_on("RELAYONE", pump_index)
                        else:
                            self.turn_off("RELAYONE", pump_index)
                        return
                        
            raise KeyError("PumpFromTankToGutters not found in any relay assignments")
                
        except KeyError as e:
            logger.warning(f"Missing configuration for tank-to-gutters pump: {e}")
        except Exception as e:
            logger.error(f"Error controlling tank-to-gutters pump: {e}")

    def set_sprinklers(self, status):
        """Control both sprinkler A and B together."""
        logger.info(f"Setting sprinklers to {status}")
        relay_group_a, index_a = self._get_relay_info("SprinklerA")
        relay_group_b, index_b = self._get_relay_info("SprinklerB")
        
        if relay_group_a and index_a and relay_group_b and index_b:
            if status:
                self.turn_on(relay_group_a, index_a)
                self.turn_on(relay_group_b, index_b)
            else:
                self.turn_off(relay_group_a, index_a)
                self.turn_off(relay_group_b, index_b)
        else:
            logger.warning("SprinklerA or SprinklerB not found in relay assignments")

    def set_pump_from_collector_tray_to_tank(self, status):
        """Control pump from collector tray to tank.
        
        Args:
            status (bool): True to turn on pump, False to turn off
        """
        if not any(key in self.relay_addresses for key in ['RELAYONE']):
            logger.info("No collector tray pump hardware present in RELAY_ONE")
            return

        logger.info(f"Setting collector tray pump to {status}")
        try:
            # Get the relay assignments from config
            assignments = globals.DEVICE_CONFIG_FILE['RELAY_ASSIGNMENTS']
            relay_one_assignments = assignments.get('Relay_ONE_8_to_11', '').split(',')
            
            # Find the index of PumpFromCollectorTrayToTank
            for i, device in enumerate(relay_one_assignments):
                if device.strip() == 'PumpFromCollectorTrayToTank':
                    pump_index = i + 8  # Offset by 8 since this is 8_to_11 group
                    break
            else:
                raise KeyError("PumpFromCollectorTrayToTank not found in RELAY_ONE_8_to_11 assignments")
            
            if status:
                self.turn_on("RELAYONE", pump_index)
            else:
                self.turn_off("RELAYONE", pump_index)
                
        except KeyError as e:
            logger.warning(f"Missing configuration for collector tray pump: {e}")
        except Exception as e:
            logger.error(f"Error controlling collector tray pump: {e}")

    def set_ph_plus_pump(self, status):
        """Control pH plus pump.
        
        Args:
            status (bool): True to turn on pump, False to turn off
        """
        if not any(key in self.relay_addresses for key in ['RELAYONE']):
            logger.info("No pH plus pump hardware present in RELAY_ONE")
            return

        logger.info(f"Setting pH plus pump to {status}")
        try:
            # Get all relay assignments from config
            assignments = globals.DEVICE_CONFIG_FILE['RELAY_ASSIGNMENTS']
            
            # Search through all relay groups for pHUpPump
            for group_name, devices in assignments.items():
                if not group_name.startswith('Relay_'):
                    continue
                    
                device_list = devices.split(',')
                for i, device in enumerate(device_list):
                    if device.strip() == 'pHUpPump':
                        # Extract the base index from group name (e.g., 0 from "Relay_ONE_0_to_3")
                        base_index = int(group_name.split('_')[2])
                        pump_index = i + base_index
                        
                        if status:
                            self.turn_on("RELAYONE", pump_index)
                        else:
                            self.turn_off("RELAYONE", pump_index)
                        return
                        
            raise KeyError("pHUpPump not found in any relay assignments")
                
        except KeyError as e:
            logger.warning(f"Missing configuration for pH plus pump: {e}")
        except Exception as e:
            logger.error(f"Error controlling pH plus pump: {e}")

    def set_ph_minus_pump(self, status):
        """Control pH minus pump.
        
        Args:
            status (bool): True to turn on pump, False to turn off
        """
        if not any(key in self.relay_addresses for key in ['RELAYONE']):
            logger.info("No pH minus pump hardware present in RELAY_ONE")
            return

        logger.info(f"Setting pH minus pump to {status}")
        try:
            # Get all relay assignments from config
            assignments = globals.DEVICE_CONFIG_FILE['RELAY_ASSIGNMENTS']
            
            # Search through all relay groups for pHDownPump
            for group_name, devices in assignments.items():
                if not group_name.startswith('Relay_'):
                    continue
                    
                device_list = devices.split(',')
                for i, device in enumerate(device_list):
                    if device.strip() == 'pHDownPump':
                        # Extract the base index from group name (e.g., 4 from "Relay_ONE_4_to_7")
                        base_index = int(group_name.split('_')[2])
                        pump_index = i + base_index
                        
                        if status:
                            self.turn_on("RELAYONE", pump_index)
                        else:
                            self.turn_off("RELAYONE", pump_index)
                        return
                        
            raise KeyError("pHDownPump not found in any relay assignments")
                
        except KeyError as e:
            logger.warning(f"Missing configuration for pH minus pump: {e}")
        except Exception as e:
            logger.error(f"Error controlling pH minus pump: {e}")

    def set_nutrient_pumps(self, status):
        """Control all three nutrient pumps (A, B, C) together.
        
        Args:
            status (bool): True to turn on all pumps, False to turn off all
        """
        if not any(key in self.relay_addresses for key in ['RELAYONE']):
            logger.info("No nutrient pump hardware present in RELAY_ONE")
            return

        logger.info(f"Setting all nutrient pumps to {status}")
        try:
            # Get all relay assignments from config
            assignments = globals.DEVICE_CONFIG_FILE['RELAY_ASSIGNMENTS']
            
            # Find indices for all nutrient pumps
            pump_indices = []
            for group_name, devices in assignments.items():
                if not group_name.startswith('Relay_'):
                    continue
                    
                device_list = devices.split(',')
                base_index = int(group_name.split('_')[2])
                
                for i, device in enumerate(device_list):
                    device = device.strip()
                    if device in ['NutrientPumpA', 'NutrientPumpB', 'NutrientPumpC']:
                        pump_indices.append(i + base_index)
            
            if len(pump_indices) != 3:
                raise KeyError("Could not find all three nutrient pumps in relay assignments")
            
            # Control all three pumps together using set_three_relays
            self.set_three_relays(
                "RELAYONE",
                min(pump_indices),
                [status, status, status]  # Same status for all three pumps
            )
                
        except KeyError as e:
            logger.warning(f"Missing configuration for nutrient pumps: {e}")
        except Exception as e:
            logger.error(f"Error controlling nutrient pumps: {e}")

    def set_nutrient_pump(self, pump_letter, status):
        """Control individual nutrient pump (A/B/C).
        
        Args:
            pump_letter (str): Pump letter (A, B, or C)
            status (bool): True to turn on pump, False to turn off
        """
        if not any(key in self.relay_addresses for key in ['RELAYONE']):
            logger.info("No nutrient pump hardware present in RELAY_ONE")
            return

        logger.info(f"Setting nutrient pump {pump_letter} to {status}")
        try:
            # Get all relay assignments from config
            assignments = globals.DEVICE_CONFIG_FILE['RELAY_ASSIGNMENTS']
            
            # Search through all relay groups for the specified nutrient pump
            for group_name, devices in assignments.items():
                if not group_name.startswith('Relay_'):
                    continue
                    
                device_list = devices.split(',')
                pump_name = f'NutrientPump{pump_letter}'
                
                for i, device in enumerate(device_list):
                    if device.strip() == pump_name:
                        # Extract the base index from group name
                        base_index = int(group_name.split('_')[2])
                        pump_index = i + base_index
                        
                        if status:
                            self.turn_on("RELAYONE", pump_index)
                        else:
                            self.turn_off("RELAYONE", pump_index)
                        return
                        
            raise KeyError(f"{pump_name} not found in any relay assignments")
                
        except KeyError as e:
            logger.warning(f"Missing configuration for nutrient pump {pump_letter}: {e}")
        except Exception as e:
            logger.error(f"Error controlling nutrient pump {pump_letter}: {e}")

    def set_mixing_pump(self, status):
        """Control mixing pump."""
        logger.info(f"Setting mixing pump to {status}")
        relay_group, index = self._get_relay_info("MixingPump")
        if relay_group and index:
            if status:
                self.turn_on(relay_group, index)
            else:
                self.turn_off(relay_group, index)
        else:
            logger.warning("MixingPump not found in relay assignments")

    def _save_null_metrics_data(self):
        """Save null data for relay metrics."""
        metrics_data = {
            "measurements": {
                "name": "relay_metrics",
                "points": []
            }
        }
        
        # Keep track of assigned ports for configuration
        assigned_ports_map = {}
        
        # Create points for all relays
        for current_relay in self.relay_addresses.keys():
            board_name = self.relay_board_names.get(current_relay, current_relay)
            assigned_ports_map[board_name] = []
            
            # Create points for all 16 ports
            for port_index in range(16):
                # Default to unassigned
                point = {
                    "tags": {
                        "relay_board": board_name,
                        "port_index": port_index,
                        "port_type": "unassigned",
                        "device": "none"
                    },
                    "fields": {
                        "status": 0,
                        "is_assigned": False,
                        "raw_status": 0
                    },
                    "timestamp": self.last_updated
                }
                
                # Check if port is assigned to a device
                for device_name, info in self.relay_assignments.items():
                    if info.get('relay_name') == current_relay and info.get('index') == port_index:
                        point["tags"]["port_type"] = "assigned"
                        point["tags"]["device"] = device_name
                        point["fields"]["is_assigned"] = True
                        assigned_ports_map[board_name].append(port_index)
                        break
                
                metrics_data["measurements"]["points"].append(point)
        
        # Save relay metrics points
        helpers.save_sensor_data(["data", "relay_metrics"], metrics_data)
        
        # Save relay configuration
        config_data = {
            "relay_configuration": {}
        }
        
        # Update configuration with assigned and unassigned ports
        for relay in self.relay_addresses.keys():
            board_name = self.relay_board_names.get(relay, relay)
            assigned = assigned_ports_map.get(board_name, [])
            
            config_data["relay_configuration"][board_name] = {
                "total_ports": 16,
                "assigned_ports": sorted(assigned),
                "unassigned_ports": sorted(list(set(range(16)) - set(assigned)))
            }
            
            logger.info(f"Relay {board_name} assigned ports: {sorted(assigned)}")
        
        helpers.save_sensor_data(["data", "relay_metrics", "configuration"], config_data)


if __name__ == "__main__":
    relay = Relay()
    if relay is not None:  # Only proceed if device is enabled
        # Example usage of various methods
        
        
        relay.set_multiple_relays("RELAYONE", 0, [True, True, True, True, True, True, True, True, True, True, True, True, True, True, True, True])
        time.sleep(5)
        relay.set_multiple_relays("RELAYONE", 0, [False, False, False, False, False, False, False, False, False, False, False, False, False, False, False, False])
        time.sleep(1)
        # while True:
        #     relay.get_status()
        #     time.sleep(10)
        
        # relay.set_mixing_pump(True)
        # time.sleep(1)
        # relay.set_mixing_pump(False)
        
        # # Test tank valve control
        # relay.set_valve_from_outside_to_tank(True)
        # time.sleep(1)
        # relay.set_valve_from_outside_to_tank(False)
        
        # relay.set_valve_from_tank_to_outside(True)
        # time.sleep(1)
        # relay.set_valve_from_tank_to_outside(False)
        
        # # Test sprinklers
        # relay.set_sprinklers(True)
        # time.sleep(1)
        # relay.set_sprinklers(False)
        
        # # Test collector tray pump
        # relay.set_pump_from_collector_tray_to_tank(True)
        # time.sleep(1)
        # relay.set_pump_from_collector_tray_to_tank(False)
        
        # # Test pH pumps
        # relay.set_ph_plus_pump(True)
        # time.sleep(1)
        # relay.set_ph_plus_pump(False)
        
        # relay.set_ph_minus_pump(True)
        # time.sleep(1)
        # relay.set_ph_minus_pump(False)
        
        # # Test nutrient pumps
        # relay.set_nutrient_pumps(True)
        # time.sleep(1)
        # relay.set_nutrient_pumps(False)
        
        # # Test tank to gutters pump
        # relay.set_pump_from_tank_to_gutters(True)
        # time.sleep(1)
        # relay.set_pump_from_tank_to_gutters(False)