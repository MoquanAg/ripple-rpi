#!/usr/bin/env python3

import os
import sys
import time
import logging

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger('test_direct_relay')

# Import relay class dynamically to avoid circular imports
def import_relay_class():
    # Add the src directory to the Python path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    src_dir = os.path.join(current_dir, 'src')
    
    if src_dir not in sys.path:
        sys.path.append(src_dir)
        
    # Import globally necessary modules first
    import importlib
    if 'globals' not in sys.modules:
        importlib.import_module('globals')
    
    # Now import Relay
    from src.sensors.Relay import Relay
    return Relay

def test_direct_relay_control():
    """Test direct relay control bypassing the API and device name mapping."""
    logger.info("Initializing relay module...")
    
    try:
        # Import relay class
        Relay = import_relay_class()
        
        logger.info("Creating relay instance...")
        relay = Relay()
        
        if relay is None:
            logger.error("Failed to initialize relay - relay control may be disabled")
            return
        
        # Print all relay info for debugging
        logger.info("\nRelay Information:")
        logger.info(f"Relay addresses: {relay.relay_addresses}")
        logger.info(f"Port: {relay.port}")
        logger.info(f"Baud rate: {relay.baud_rate}")
        
        # Use direct modbus commands to control relays
        logger.info("Testing direct relay control for nutrient pumps...")
        
        relay_indices = [0, 1, 2]  # Nutrient pumps A, B, C are usually on indices 0, 1, 2
        
        # Get the first relay name from relay_addresses
        if not relay.relay_addresses:
            logger.error("No relay addresses found!")
            return
            
        relay_name = list(relay.relay_addresses.keys())[0]
        logger.info(f"Using relay board name: {relay_name}")
        
        for idx in relay_indices:
            logger.info(f"\nTesting relay index {idx}...")
            
            # Turn relay ON
            logger.info(f"Turning ON relay {idx}")
            relay.turn_on(relay_name, idx)
            time.sleep(2)
            
            # Turn relay OFF
            logger.info(f"Turning OFF relay {idx}")
            relay.turn_off(relay_name, idx)
            time.sleep(2)
        
        logger.info("\nTesting nutrient pumps directly using set_nutrient_pump method...")
        pump_letters = ["A", "B", "C"]
        
        for letter in pump_letters:
            logger.info(f"\nTesting nutrient pump {letter}...")
            
            # Turn pump ON
            logger.info(f"Turning ON nutrient pump {letter}")
            relay.set_nutrient_pump(letter, True)
            time.sleep(2)
            
            # Turn pump OFF
            logger.info(f"Turning OFF nutrient pump {letter}")
            relay.set_nutrient_pump(letter, False)
            time.sleep(2)
            
        logger.info("\nTesting complete!")
        
    except Exception as e:
        logger.error(f"Error in direct relay test: {e}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    test_direct_relay_control() 