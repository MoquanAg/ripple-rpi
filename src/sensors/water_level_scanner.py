#!/usr/bin/env python3
"""
Water Level Sensor Scanner
Scans ttyAMA2, ttyAMA3, and ttyAMA4 at 9600 baud to identify which port has the water level sensor.
Distinguishes water level sensors from pH, DO, and EC sensors by response pattern validation.

Author: Linus-style implementation - simple, direct, no bullshit.
"""

import serial
import time
import struct
import sys
import os

# Add parent directory to path for imports
current_dir = os.path.dirname(__file__)
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

try:
    from src.lumina_logger import GlobalLogger
    logger = GlobalLogger("WaterLevelScanner", log_prefix="scanner_").logger
except ImportError:
    try:
        from lumina_logger import GlobalLogger
        logger = GlobalLogger("WaterLevelScanner", log_prefix="scanner_").logger
    except ImportError:
        # Fallback to basic logging for standalone operation
        import logging
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        logger = logging.getLogger("WaterLevelScanner")

class WaterLevelScanner:
    """
    Scanner to identify water level sensor ports.
    Simple, focused, does one thing well.
    """
    
    # Ports to scan
    SCAN_PORTS = ['/dev/ttyAMA2', '/dev/ttyAMA3', '/dev/ttyAMA4']
    
    # All possible addresses (0x00-0xFF)
    ALL_ADDRESSES = list(range(0x00, 0x100))
    
    # Common water level sensor addresses to try first (for quick scan mode)
    COMMON_ADDRESSES = [0x01, 0x31, 0x32, 0x33, 0x34, 0x35]
    
    # Baud rates to test (from water level sensor documentation)
    BAUD_RATES = [1200, 2400, 4800, 9600, 19200, 38400, 57600]
    
    # Serial parameters
    TIMEOUT = 0.5  # Reduced for faster scanning
    
    def __init__(self, exhaustive=True):
        self.results = {}
        self.exhaustive = exhaustive  # If True, scan all addresses and baud rates
        
    def _calculate_crc16(self, data):
        """Calculate CRC-16 for Modbus RTU."""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 0x0001:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc = crc >> 1
        return crc
    
    def _create_water_level_command(self, address):
        """
        Create water level sensor read command.
        Reads registers 0x0000-0x0007 (8 registers) which should return sensor info.
        """
        command = bytearray([
            address,        # Slave address
            0x03,          # Function code (Read Holding Registers)
            0x00, 0x00,    # Starting address (0x0000)
            0x00, 0x08     # Number of registers to read (8 registers)
        ])
        
        # Calculate and append CRC
        crc = self._calculate_crc16(command)
        command.append(crc & 0xFF)        # CRC low byte
        command.append((crc >> 8) & 0xFF) # CRC high byte
        
        return command
    
    def _validate_water_level_response(self, response, expected_address):
        """
        Validate if response matches water level sensor pattern.
        Water level sensors return specific register data that differs from pH/DO/EC.
        """
        if not response or len(response) < 7:
            return False, "Response too short"
            
        # Check address matches
        if response[0] != expected_address:
            return False, f"Address mismatch: expected {expected_address}, got {response[0]}"
            
        # Check function code
        if response[1] != 0x03:
            return False, f"Function code mismatch: expected 0x03, got {response[1]}"
            
        # Check byte count (should be 16 for 8 registers)
        expected_byte_count = 16
        if len(response) < 3 or response[2] != expected_byte_count:
            return False, f"Byte count mismatch: expected {expected_byte_count}, got {response[2] if len(response) > 2 else 'N/A'}"
            
        # Verify we have enough data
        if len(response) < (3 + expected_byte_count + 2):  # header + data + CRC
            return False, f"Incomplete response: expected {3 + expected_byte_count + 2} bytes, got {len(response)}"
            
        # Validate CRC
        data_without_crc = response[:-2]
        calculated_crc = self._calculate_crc16(data_without_crc)
        received_crc = response[-2] | (response[-1] << 8)
        
        if calculated_crc != received_crc:
            return False, f"CRC mismatch: calculated {calculated_crc:04X}, received {received_crc:04X}"
            
        # Water level sensor specific validation:
        # Check if register 0x0004 (level value) contains reasonable data
        try:
            # Register 0x0004 data is at bytes 11-12 (0-indexed: bytes[11], bytes[12])
            level_raw = (response[11] << 8) | response[12]
            
            # Handle signed 16-bit value
            if level_raw > 32767:
                level_raw -= 65536
                
            # Water level should be reasonable (-1000 to +10000 cm range)
            if not (-1000 <= level_raw <= 10000):
                return False, f"Water level value out of range: {level_raw} cm"
            
            # Additional validation: Check if this looks like pH data instead
            # pH sensors often return values like 0x0240 (576 = pH 5.76) in register responses
            # Register 0x0000 (slave address) should match our expected address
            reg0_addr = (response[3] << 8) | response[4]
            if reg0_addr != expected_address:
                return False, f"Slave address register mismatch: expected {expected_address}, got {reg0_addr}"
            
            # Register 0x0001 (baudrate) should be a valid baudrate value (0-7)
            reg1_baud = (response[5] << 8) | response[6]
            if reg1_baud > 7:
                return False, f"Invalid baudrate register value: {reg1_baud} (should be 0-7)"
            
            # Register 0x0002 (pressure unit) should be valid for water level (9-17)
            reg2_unit = (response[7] << 8) | response[8]
            if not (9 <= reg2_unit <= 17):
                return False, f"Invalid pressure unit: {reg2_unit} (should be 9-17 for water level)"
                
        except (IndexError, ValueError) as e:
            return False, f"Error parsing water level data: {e}"
            
        return True, "Valid water level sensor response"
    
    def _probe_port(self, port):
        """
        Probe a single port for water level sensor.
        Returns (found, address, baud_rate, details) tuple.
        """
        logger.info(f"Probing port {port}...")
        
        try:
            # Check if port exists
            if not os.path.exists(port):
                return False, None, None, f"Port {port} does not exist"
            
            # Choose address list based on mode
            addresses = self.ALL_ADDRESSES if self.exhaustive else self.COMMON_ADDRESSES
            baud_rates = self.BAUD_RATES if self.exhaustive else [9600]
            
            total_combinations = len(addresses) * len(baud_rates)
            current_combination = 0
            
            logger.info(f"  Testing {len(baud_rates)} baud rates × {len(addresses)} addresses = {total_combinations} combinations")
            
            # Try each baud rate
            for baud_rate in baud_rates:
                logger.info(f"  Testing baud rate {baud_rate}...")
                
                try:
                    # Open serial connection with current baud rate
                    ser = serial.Serial(
                        port=port,
                        baudrate=baud_rate,
                        bytesize=serial.EIGHTBITS,
                        parity=serial.PARITY_NONE,
                        stopbits=serial.STOPBITS_ONE,
                        timeout=self.TIMEOUT
                    )
                    
                    # Try each address
                    for address in addresses:
                        current_combination += 1
                        
                        # Progress indication every 50 attempts
                        if current_combination % 50 == 0:
                            progress = (current_combination / total_combinations) * 100
                            logger.info(f"    Progress: {current_combination}/{total_combinations} ({progress:.1f}%)")
                        
                        try:
                            # Clear buffers
                            ser.reset_input_buffer()
                            ser.reset_output_buffer()
                            
                            # Send command
                            command = self._create_water_level_command(address)
                            ser.write(command)
                            
                            # Wait for response
                            response = ser.read(100)  # Read up to 100 bytes
                            
                            if response:
                                # Validate response
                                is_valid, reason = self._validate_water_level_response(response, address)
                                
                                if is_valid:
                                    ser.close()
                                    return True, address, baud_rate, f"Water level sensor found at address 0x{address:02X}, baud {baud_rate}"
                                elif len(response) > 5:  # Log interesting responses
                                    logger.debug(f"    Address 0x{address:02X} @ {baud_rate}: {len(response)} bytes - {reason}")
                            
                            # Very small delay between attempts for speed
                            time.sleep(0.02)
                            
                        except Exception as e:
                            # Only log errors for common addresses to avoid spam
                            if address in self.COMMON_ADDRESSES:
                                logger.debug(f"    Error with address 0x{address:02X} @ {baud_rate}: {e}")
                            continue
                    
                    ser.close()
                    
                except serial.SerialException as e:
                    logger.debug(f"  Could not open {port} at {baud_rate} baud: {e}")
                    continue
            
            return False, None, None, "No water level sensor found on this port"
            
        except Exception as e:
            return False, None, None, f"Unexpected error: {e}"
    
    def scan_all_ports(self):
        """
        Scan all configured ports for water level sensors.
        Returns dictionary with results for each port.
        """
        scan_mode = "EXHAUSTIVE" if self.exhaustive else "QUICK"
        logger.info(f"Starting water level sensor scan ({scan_mode} mode)...")
        logger.info(f"Scanning ports: {', '.join(self.SCAN_PORTS)}")
        
        if self.exhaustive:
            logger.info(f"Baud rates: {', '.join(map(str, self.BAUD_RATES))}")
            logger.info(f"Addresses: 0x00-0xFF (256 addresses)")
            total_per_port = len(self.BAUD_RATES) * len(self.ALL_ADDRESSES)
            logger.info(f"Total combinations per port: {total_per_port}")
        else:
            logger.info(f"Baud rate: 9600")
            logger.info(f"Testing addresses: {', '.join([f'0x{addr:02X}' for addr in self.COMMON_ADDRESSES])}")
        
        logger.info(f"Timeout per attempt: {self.TIMEOUT}s")
        
        self.results = {}
        found_sensors = []
        
        for port in self.SCAN_PORTS:
            found, address, baud_rate, details = self._probe_port(port)
            
            self.results[port] = {
                'found': found,
                'address': address,
                'baud_rate': baud_rate,
                'details': details
            }
            
            if found:
                found_sensors.append(f"{port} (0x{address:02X} @ {baud_rate} baud)")
                logger.info(f"✅ FOUND: {port} - {details}")
            else:
                logger.info(f"❌ NOT FOUND: {port} - {details}")
        
        # Summary
        logger.info("\n" + "="*60)
        logger.info("WATER LEVEL SENSOR SCAN RESULTS")
        logger.info("="*60)
        
        if found_sensors:
            logger.info(f"Water level sensors found on: {', '.join(found_sensors)}")
        else:
            logger.info("No water level sensors found on any scanned ports")
            
        logger.info("="*60)
        
        return self.results
    
    def get_water_level_port(self):
        """
        Get the port where water level sensor was found.
        Returns (port, address, baud_rate) tuple or (None, None, None) if not found.
        """
        for port, result in self.results.items():
            if result['found']:
                return port, result['address'], result['baud_rate']
        return None, None, None


def main():
    """Main function for standalone execution."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Water Level Sensor Scanner")
    parser.add_argument("--quick", action="store_true", 
                       help="Quick scan mode (common addresses and 9600 baud only)")
    args = parser.parse_args()
    
    print("Water Level Sensor Scanner")
    if args.quick:
        print("Quick scan mode: Common addresses at 9600 baud")
        scanner = WaterLevelScanner(exhaustive=False)
    else:
        print("Exhaustive scan mode: All addresses (0x00-0xFF) at all baud rates")
        print("This may take several minutes per port...")
        scanner = WaterLevelScanner(exhaustive=True)
    print()
    
    results = scanner.scan_all_ports()
    
    # Print results in a clean format
    print("\nSCAN RESULTS:")
    print("-" * 70)
    
    found_any = False
    for port, result in results.items():
        status = "FOUND" if result['found'] else "NOT FOUND"
        if result['found']:
            details = f" (0x{result['address']:02X} @ {result['baud_rate']} baud)"
            found_any = True
        else:
            details = ""
        print(f"{port:<15} {status}{details}")
    
    print("-" * 70)
    
    if found_any:
        port, address, baud_rate = scanner.get_water_level_port()
        print(f"\nRecommendation: Use {port} with address 0x{address:02X} at {baud_rate} baud for water level sensor")
    else:
        print("\nNo water level sensors detected. Check connections and power.")
        if not args.quick:
            print("Consider trying --quick mode for faster testing with common settings.")
    
    return 0 if found_any else 1


if __name__ == "__main__":
    sys.exit(main())
