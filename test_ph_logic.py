#!/usr/bin/env python3

import argparse

def test_ph_selection(current_ph, target_ph):
    """
    Simplified test function that shows what would happen with pH control
    
    Args:
        current_ph (float): Current pH reading
        target_ph (float): Target pH value
    """
    print(f"\n===== pH CONTROL LOGIC TEST =====")
    print(f"Current pH: {current_ph}")
    print(f"Target pH: {target_ph}")
    print("------------------------------")
    
    # Logic for pH pump selection:
    # If current pH is LOWER than target → Use pH UP pump
    # If current pH is HIGHER than target → Use pH DOWN pump
    
    if current_ph < target_ph:
        selected_pump = "pH UP"
        print(f"pH is TOO LOW: {current_ph} < {target_ph}")
        print(f"Action: ACTIVATE {selected_pump} PUMP")
    else:
        selected_pump = "pH DOWN"
        print(f"pH is TOO HIGH: {current_ph} > {target_ph}")
        print(f"Action: ACTIVATE {selected_pump} PUMP")
    
    print("==============================\n")
    return selected_pump

def main():
    """Main entry point for the test script"""
    parser = argparse.ArgumentParser(description='Test pH pump selection logic')
    parser.add_argument('--current', type=float, default=7.0, help='Current pH value (default: 7.0)')
    parser.add_argument('--target', type=float, default=6.0, help='Target pH value (default: 6.0)')
    
    args = parser.parse_args()
    test_ph_selection(args.current, args.target)

if __name__ == "__main__":
    main() 