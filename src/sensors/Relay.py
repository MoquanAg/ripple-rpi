import serial
import time
import os, sys

current_dir = os.path.dirname(__file__)
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from lumina_modbus_event_emitter import ModbusResponse

import globals

logger = globals.logger
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
        self.baud_rate = 9600
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
                status_byte = data[3]
                relay_name = command_info.get("relay_name")
                logger.debug(f"Status byte: {status_byte}, Relay name: {relay_name}")
                if relay_name:
                    # Convert relay name to match config sections (e.g., relay_one -> RELAY_ONE)
                    config_section = relay_name.upper()
                    # Initialize the relay_statuses dict for this relay if it doesn't exist
                    if config_section not in self.relay_statuses:
                        self.relay_statuses[config_section] = [None] * 8
                    self.relay_statuses[config_section] = [(status_byte >> i) & 1 for i in range(8)]
                    self.last_updated = helpers.datetime_to_iso8601()
                    logger.info(f"{config_section} statuses: {self.relay_statuses[config_section]}")
                    # Save data for just this relay
                    self.save_data(relay_name=config_section)
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
                command = bytearray([address, 0x01, 0x00, 0x00, 0x00, 0x08])
                logger.debug(f"Command bytes: {[f'0x{b:02X}' for b in command]}")
                
                timeout = 2.0
                command_id = self.modbus_client.send_command(
                    device_type="relay",
                    port=self.port,  # Use the port from config
                    command=command,
                    baudrate=self.baud_rate,
                    response_length=6,
                    timeout=timeout,
                )
                
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
        """Load relay addresses from config file"""
        config = globals.DEVICE_CONFIG_FILE
        try:
            self.relay_addresses = {}
            logger.info(f"Available config sections: {config.sections()}")
            if "RELAY_CONTROL" in config:
                logger.info(f"RELAY_CONTROL section content: {dict(config['RELAY_CONTROL'])}")
                for key, value in config["RELAY_CONTROL"].items():
                    # Skip comments and process relay entries
                    if key.upper().startswith('RELAY'):
                        # Parse the comma-separated value string
                        parts = value.split(',')
                        if len(parts) >= 5:  # We need at least 5 parts for the address
                            hex_address = int(parts[4].strip(), 16)
                            self.relay_addresses[key.upper()] = hex_address
                            logger.info(f"Loaded {key.upper()} address: 0x{hex_address:02X} (decimal: {hex_address})")
                logger.info(f"Final relay_addresses: {self.relay_addresses}")
            else:
                logger.info("No RELAY_CONTROL section found in config. Using default address.")
        except ValueError as e:
            logger.warning(f"Invalid address format in config: {e}")
        except Exception as e:
            logger.warning(f"Error loading relay addresses: {e}")

    def save_null_data(self):
        """Save null data in the new format."""
        self.relay_statuses = {}
        self.last_updated = helpers.datetime_to_iso8601()
        
        null_relay_data = {
            "last_updated": self.last_updated
        }
        for relay_name in self.relay_addresses.keys():
            null_relay_data[relay_name.lower()] = [0] * 8
        
        # Add last_updated to null devices data as well
        null_devices_data = {
            "last_updated": self.last_updated
        }
        
        helpers.save_sensor_data(["relays"], null_relay_data)
        helpers.save_sensor_data(["devices"], null_devices_data)

    def save_data(self, relay_name=None):
        """
        Save status data in the new format.
        """
        try:
            # If relay_name is provided, only process that relay
            relays_to_process = [relay_name] if relay_name else self.relay_addresses.keys()
            
            # Create metrics data structure
            metrics_data = {
                "measurements": {
                    "name": "relay_metrics",
                    "points": []
                }
            }
            
            # Process relay status points
            for current_relay in relays_to_process:
                if current_relay in self.relay_statuses:
                    for port_index, status in enumerate(self.relay_statuses[current_relay]):
                        point = {
                            "tags": {
                                "relay_board": current_relay.lower(),
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
                        
                        # Update device info if port is assigned
                        if current_relay in globals.DEVICE_CONFIG_FILE:
                            for device_name, index in globals.DEVICE_CONFIG_FILE[current_relay].items():
                                if device_name.lower() == 'port':
                                    continue
                                try:
                                    if int(index) == port_index:
                                        point["tags"]["port_type"] = "assigned"
                                        point["tags"]["device"] = device_name.lower()
                                        point["fields"]["is_assigned"] = True
                                except (ValueError, IndexError):
                                    continue
                                    
                        metrics_data["measurements"]["points"].append(point)
            
            # Save relay points
            helpers.save_sensor_data(["data", "relay_metrics"], metrics_data)
            logger.log_sensor_data(["data", "relay_metrics"], metrics_data)
            
            # Save relay configuration
            config_data = {
                "relay_configuration": {
                    relay.lower(): {
                        "total_ports": 8,
                        "assigned_ports": [],
                        "unassigned_ports": list(range(8))
                    } for relay in relays_to_process
                }
            }
            
            # Update port assignments in configuration
            for relay in relays_to_process:
                if relay in globals.DEVICE_CONFIG_FILE:
                    assigned = []
                    for device_name, index in globals.DEVICE_CONFIG_FILE[relay].items():
                        if device_name.lower() != 'port':
                            try:
                                port = int(index)
                                assigned.append(port)
                            except ValueError:
                                continue
                    
                    config_data["relay_configuration"][relay.lower()]["assigned_ports"] = sorted(assigned)
                    config_data["relay_configuration"][relay.lower()]["unassigned_ports"] = sorted(list(set(range(8)) - set(assigned)))
            
            helpers.save_sensor_data(["data", "relay_metrics", "configuration"], config_data)
            logger.log_sensor_data(["data", "relay_metrics", "configuration"], config_data)

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
        if not 1 <= len(states) <= 12:
            logger.warning("Must provide between 1 and 8 relay states")
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

    def set_valve_from_tank_to_outside(self, status):
        """Control valve for flow from tank to outside.
        
        Args:
            status (bool): True to open valve, False to close
        """
        if not any(key in self.relay_addresses for key in ['RELAYONE']):
            logger.info("No tank-to-outside valve hardware present in RELAY_ONE")
            return

        logger.info(f"Setting tank-to-outside valve to {status}")
        try:
            # Get all relay assignments from config
            assignments = globals.DEVICE_CONFIG_FILE['RELAY_ASSIGNMENTS']
            
            # Search through all relay groups for ValveTankToOutside
            for group_name, devices in assignments.items():
                if not group_name.startswith('Relay_'):
                    continue
                    
                device_list = devices.split(',')
                for i, device in enumerate(device_list):
                    if device.strip() == 'ValveTankToOutside':
                        # Extract the base index from group name
                        base_index = int(group_name.split('_')[2])
                        valve_index = i + base_index
                        
                        if status:
                            self.turn_on("RELAYONE", valve_index)
                        else:
                            self.turn_off("RELAYONE", valve_index)
                        return
                        
            raise KeyError("ValveTankToOutside not found in any relay assignments")
                
        except KeyError as e:
            logger.warning(f"Missing configuration for tank-to-outside valve: {e}")
        except Exception as e:
            logger.error(f"Error controlling tank-to-outside valve: {e}")

    def set_valve_from_outside_to_tank(self, status):
        """Control valve for flow from outside to tank.
        
        Args:
            status (bool): True to open valve, False to close
        """
        if not any(key in self.relay_addresses for key in ['RELAYONE']):
            logger.info("No outside-to-tank valve hardware present in RELAY_ONE")
            return

        logger.info(f"Setting outside-to-tank valve to {status}")
        try:
            # Get all relay assignments from config
            assignments = globals.DEVICE_CONFIG_FILE['RELAY_ASSIGNMENTS']
            
            # Search through all relay groups for ValveOutsideToTank
            for group_name, devices in assignments.items():
                if not group_name.startswith('Relay_'):
                    continue
                    
                device_list = devices.split(',')
                for i, device in enumerate(device_list):
                    if device.strip() == 'ValveOutsideToTank':
                        # Extract the base index from group name
                        base_index = int(group_name.split('_')[2])
                        valve_index = i + base_index
                        
                        if status:
                            self.turn_on("RELAYONE", valve_index)
                        else:
                            self.turn_off("RELAYONE", valve_index)
                        return
                        
            raise KeyError("ValveOutsideToTank not found in any relay assignments")
                
        except KeyError as e:
            logger.warning(f"Missing configuration for outside-to-tank valve: {e}")
        except Exception as e:
            logger.error(f"Error controlling outside-to-tank valve: {e}")

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
        """Control both sprinkler A and B together.
        
        Args:
            status (bool): True to turn on sprinklers, False to turn off
        """
        if not any(key in self.relay_addresses for key in ['RELAYONE']):
            logger.info("No sprinkler hardware present in RELAY_ONE")
            return

        logger.info(f"Setting sprinklers to {status}")
        try:
            # Get all relay assignments from config
            assignments = globals.DEVICE_CONFIG_FILE['RELAY_ASSIGNMENTS']
            
            # Find indices for both sprinklers
            sprinkler_a_index = None
            sprinkler_b_index = None
            for group_name, devices in assignments.items():
                if not group_name.startswith('Relay_'):
                    continue
                    
                device_list = devices.split(',')
                base_index = int(group_name.split('_')[2])
                
                for i, device in enumerate(device_list):
                    device = device.strip()
                    if device == 'SprinklerA':
                        sprinkler_a_index = i + base_index
                    elif device == 'SprinklerB':
                        sprinkler_b_index = i + base_index
            
            if sprinkler_a_index is None or sprinkler_b_index is None:
                raise KeyError("SprinklerA or SprinklerB not found in any relay assignments")
            
            # Control both sprinklers together using set_two_relays
            self.set_two_relays(
                "RELAYONE",
                min(sprinkler_a_index, sprinkler_b_index),
                [status, status]  # Same status for both sprinklers
            )
                
        except KeyError as e:
            logger.warning(f"Missing configuration for sprinklers: {e}")
        except Exception as e:
            logger.error(f"Error controlling sprinklers: {e}")

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
            
            # Search through all relay groups for pHPlusPump
            for group_name, devices in assignments.items():
                if not group_name.startswith('Relay_'):
                    continue
                    
                device_list = devices.split(',')
                for i, device in enumerate(device_list):
                    if device.strip() == 'pHPlusPump':
                        # Extract the base index from group name (e.g., 0 from "Relay_ONE_0_to_3")
                        base_index = int(group_name.split('_')[2])
                        pump_index = i + base_index
                        
                        if status:
                            self.turn_on("RELAYONE", pump_index)
                        else:
                            self.turn_off("RELAYONE", pump_index)
                        return
                        
            raise KeyError("pHPlusPump not found in any relay assignments")
                
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
            
            # Search through all relay groups for pHMinusPump
            for group_name, devices in assignments.items():
                if not group_name.startswith('Relay_'):
                    continue
                    
                device_list = devices.split(',')
                for i, device in enumerate(device_list):
                    if device.strip() == 'pHMinusPump':
                        # Extract the base index from group name (e.g., 4 from "Relay_ONE_4_to_7")
                        base_index = int(group_name.split('_')[2])
                        pump_index = i + base_index
                        
                        if status:
                            self.turn_on("RELAYONE", pump_index)
                        else:
                            self.turn_off("RELAYONE", pump_index)
                        return
                        
            raise KeyError("pHMinusPump not found in any relay assignments")
                
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
        """Control mixing pump.
        
        Args:
            status (bool): True to turn on pump, False to turn off
        """
        if not any(key in self.relay_addresses for key in ['RELAYONE']):
            logger.info("No mixing pump hardware present in RELAY_ONE")
            return

        logger.info(f"Setting mixing pump to {status}")
        try:
            # Get all relay assignments from config
            assignments = globals.DEVICE_CONFIG_FILE['RELAY_ASSIGNMENTS']
            
            # Search through all relay groups for MixingPump
            for group_name, devices in assignments.items():
                if not group_name.startswith('Relay_'):
                    continue
                    
                device_list = devices.split(',')
                for i, device in enumerate(device_list):
                    if device.strip() == 'MixingPump':
                        # Extract the base index from group name
                        base_index = int(group_name.split('_')[2])
                        pump_index = i + base_index
                        
                        if status:
                            self.turn_on("RELAYONE", pump_index)
                        else:
                            self.turn_off("RELAYONE", pump_index)
                        return
                        
            raise KeyError("MixingPump not found in any relay assignments")
                
        except KeyError as e:
            logger.warning(f"Missing configuration for mixing pump: {e}")
        except Exception as e:
            logger.error(f"Error controlling mixing pump: {e}")


if __name__ == "__main__":
    relay = Relay()
    if relay is not None:  # Only proceed if device is enabled
        # Example usage of various methods
        relay.set_mixing_pump(True)
        time.sleep(1)
        relay.set_mixing_pump(False)
        
        # Test tank valve control
        relay.set_valve_from_outside_to_tank(True)
        time.sleep(1)
        relay.set_valve_from_outside_to_tank(False)
        
        relay.set_valve_from_tank_to_outside(True)
        time.sleep(1)
        relay.set_valve_from_tank_to_outside(False)
        
        # Test sprinklers
        relay.set_sprinklers(True)
        time.sleep(1)
        relay.set_sprinklers(False)
        
        # Test collector tray pump
        relay.set_pump_from_collector_tray_to_tank(True)
        time.sleep(1)
        relay.set_pump_from_collector_tray_to_tank(False)
        
        # Test pH pumps
        relay.set_ph_plus_pump(True)
        time.sleep(1)
        relay.set_ph_plus_pump(False)
        
        relay.set_ph_minus_pump(True)
        time.sleep(1)
        relay.set_ph_minus_pump(False)
        
        # Test nutrient pumps
        relay.set_nutrient_pumps(True)
        time.sleep(1)
        relay.set_nutrient_pumps(False)
        
        # Test tank to gutters pump
        relay.set_pump_from_tank_to_gutters(True)
        time.sleep(1)
        relay.set_pump_from_tank_to_gutters(False)