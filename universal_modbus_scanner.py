#!/usr/bin/env python3
"""
Universal Modbus Scanner - Tests multiple function codes
Finds both relays (0x01) and sensors (0x03, 0x04).
"""

import serial
import time
import struct

# Configuration
PORT = '/dev/ttyAMA2'
BAUDRATE = 38400
TIMEOUT = 0.2  # 200ms timeout

# Modbus function codes to test
FUNCTION_CODES = {
    0x01: "Read Coils (Relays)",
    0x03: "Read Holding Registers (Sensors)",
    0x04: "Read Input Registers (Sensors)"
}

def calculate_crc16(data):
    """Calculate Modbus CRC16."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc

def test_function_code(ser, address, function_code):
    """
    Test a specific address with a specific function code.
    Returns (found, response, raw_bytes_received).
    """
    # Create appropriate Modbus RTU command based on function code
    if function_code == 0x01:
        # Read Coil Status (for relays)
        command = bytearray([address, function_code, 0x00, 0x00, 0x00, 0x10])
    elif function_code in [0x03, 0x04]:
        # Read Holding/Input Registers (for sensors)
        command = bytearray([address, function_code, 0x00, 0x00, 0x00, 0x08])
    else:
        return "UNSUPPORTED", None, 0
    
    # Calculate and append CRC
    crc = calculate_crc16(command)
    command.append(crc & 0xFF)
    command.append((crc >> 8) & 0xFF)
    
    try:
        # Flush buffers
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        
        # Send command
        ser.write(command)
        
        # Wait for response
        time.sleep(TIMEOUT)
        
        # Check if ANY data available
        bytes_waiting = ser.in_waiting
        if bytes_waiting > 0:
            response = ser.read(bytes_waiting)
            
            # Check if it looks like a valid Modbus response
            if len(response) >= 5 and response[0] == address and response[1] == function_code:
                return "VALID", response, bytes_waiting
            elif len(response) > 0:
                return "PARTIAL", response, bytes_waiting
        
        return "NONE", None, 0
        
    except Exception as e:
        return "ERROR", str(e).encode(), 0

def scan_address_all_functions(ser, address):
    """
    Test a single address with all function codes.
    Returns dict with results for each function code.
    """
    results = {}
    
    for func_code, description in FUNCTION_CODES.items():
        status, response, bytes_count = test_function_code(ser, address, func_code)
        results[func_code] = {
            'status': status,
            'response': response,
            'bytes': bytes_count,
            'description': description
        }
        time.sleep(0.05)  # Small delay between function code tests
    
    return results

def identify_device_type(results):
    """
    Identify what type of device this is based on which function codes it responds to.
    """
    responds_to = []
    for func_code, result in results.items():
        if result['status'] == 'VALID':
            responds_to.append(func_code)
    
    if not responds_to:
        return "Unknown", "No valid responses"
    
    if 0x01 in responds_to and 0x03 not in responds_to and 0x04 not in responds_to:
        return "Relay", "Responds only to 0x01 (Read Coils)"
    elif (0x03 in responds_to or 0x04 in responds_to) and 0x01 not in responds_to:
        return "Sensor", f"Responds to {', '.join([f'0x{fc:02X}' for fc in responds_to if fc in [0x03, 0x04]])}"
    elif 0x01 in responds_to and (0x03 in responds_to or 0x04 in responds_to):
        return "Hybrid/Misconfigured", "Responds to both relay AND sensor commands (unusual)"
    else:
        return "Unknown", f"Responds to {', '.join([f'0x{fc:02X}' for fc in responds_to])}"

def main():
    """Main scanner function."""
    print("=" * 70)
    print("Universal Modbus Scanner - ALL FUNCTION CODES")
    print("=" * 70)
    print(f"Port: {PORT}")
    print(f"Baud Rate: {BAUDRATE}")
    print(f"Timeout: {TIMEOUT}s")
    print("\nTesting function codes:")
    for code, desc in FUNCTION_CODES.items():
        print(f"  0x{code:02X} - {desc}")
    print("=" * 70)
    print()
    
    found_devices = {}
    
    try:
        # Open serial port
        ser = serial.Serial(
            port=PORT,
            baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=TIMEOUT
        )
        
        time.sleep(0.5)
        
        print("Scanning addresses 0x01 to 0xFF...\n")
        
        # Scan all addresses
        for address in range(0x01, 0x100):
            results = scan_address_all_functions(ser, address)
            
            # Check if any function code got a valid response
            has_valid_response = any(r['status'] == 'VALID' for r in results.values())
            
            if has_valid_response:
                found_devices[address] = results
                device_type, type_info = identify_device_type(results)
                
                print(f"\n{'='*70}")
                print(f"✓ DEVICE FOUND AT 0x{address:02X} (decimal: {address})")
                print(f"{'='*70}")
                print(f"Device Type: {device_type}")
                print(f"Details: {type_info}")
                print()
                
                for func_code, result in results.items():
                    if result['status'] == 'VALID':
                        print(f"  0x{func_code:02X} ({result['description']}):")
                        print(f"    ✓ VALID RESPONSE")
                        print(f"    Data: {' '.join([f'0x{b:02X}' for b in result['response']])}")
                        print(f"    Length: {len(result['response'])} bytes")
                    elif result['status'] == 'PARTIAL':
                        print(f"  0x{func_code:02X} ({result['description']}):")
                        print(f"    ⚠ Partial response (might be noise)")
                        print(f"    Data: {' '.join([f'0x{b:02X}' for b in result['response']])}")
                    else:
                        print(f"  0x{func_code:02X} ({result['description']}): No response")
                print()
            
            # Progress indicator every 32 addresses
            if address % 32 == 0:
                print(f"Progress: {address}/255 ({int(address/255*100)}%)")
            
            time.sleep(0.05)
        
        ser.close()
        
        # Print summary
        print()
        print("=" * 70)
        print("SCAN COMPLETE - SUMMARY")
        print("=" * 70)
        
        if found_devices:
            print(f"\n✓ Found {len(found_devices)} device(s):\n")
            
            # Group by device type
            relays = []
            sensors = []
            hybrids = []
            unknowns = []
            
            for addr, results in found_devices.items():
                device_type, _ = identify_device_type(results)
                if device_type == "Relay":
                    relays.append(addr)
                elif device_type == "Sensor":
                    sensors.append(addr)
                elif device_type == "Hybrid/Misconfigured":
                    hybrids.append(addr)
                else:
                    unknowns.append(addr)
            
            if relays:
                print("RELAYS:")
                for addr in relays:
                    print(f"  0x{addr:02X} (decimal: {addr})")
                    print(f"    device.conf: relayone = relay, ripple, \"Relay\", {PORT}, 0x{addr:02X}, {BAUDRATE}")
                print()
            
            if sensors:
                print("SENSORS:")
                for addr in sensors:
                    results = found_devices[addr]
                    func_codes = [fc for fc, r in results.items() if r['status'] == 'VALID']
                    print(f"  0x{addr:02X} (decimal: {addr}) - Responds to: {', '.join([f'0x{fc:02X}' for fc in func_codes])}")
                    
                    # Suggest config line based on common addresses
                    if addr == 0x10:
                        print(f"    device.conf: ph_main = ph, main, \"pH Sensor\", {PORT}, 0x{addr:02X}, {BAUDRATE}")
                    elif addr == 0x20:
                        print(f"    device.conf: ec_main = ec, main, \"EC Sensor\", {PORT}, 0x{addr:02X}, {BAUDRATE}")
                    elif addr == 0x30:
                        print(f"    device.conf: water_level_main = water_level, main, \"Water Level\", {PORT}, 0x{addr:02X}, {BAUDRATE}")
                    else:
                        print(f"    device.conf: sensor_x = sensor, main, \"Sensor\", {PORT}, 0x{addr:02X}, {BAUDRATE}")
                print()
            
            if hybrids:
                print("⚠ HYBRID/MISCONFIGURED DEVICES:")
                for addr in hybrids:
                    print(f"  0x{addr:02X} (decimal: {addr})")
                    print(f"    WARNING: Responds to both relay AND sensor commands")
                    print(f"    This is unusual - device may be misconfigured")
                print()
            
            if unknowns:
                print("❓ UNKNOWN DEVICES:")
                for addr in unknowns:
                    print(f"  0x{addr:02X} (decimal: {addr})")
                print()
        else:
            print("\n✗ No devices found.")
            print("\nTroubleshooting:")
            print("  1. Check device power")
            print("  2. Check wiring (A to A, B to B, or try swapping)")
            print("  3. Try different baud rates")
            print("  4. Check port is correct")
        
        print()
        
    except serial.SerialException as e:
        print(f"\n✗ Error: Could not open serial port {PORT}")
        print(f"Details: {e}")
        return 1
    except KeyboardInterrupt:
        print("\n\nScan interrupted by user.")
        return 130
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())

