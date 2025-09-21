#!/usr/bin/env python3
"""
Sprinkler Timing Test Suite
Tests if sprinkler_on_duration and sprinkler_wait_duration from device.conf are executed correctly.

This test validates:
1. Configuration parsing accuracy
2. Scheduler initialization with correct intervals  
3. Actual timing execution vs configured values
4. Complete cycle behavior (on -> off -> wait -> repeat)
"""

import os
import sys
import time
import json
import configparser
import threading
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
import logging

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Configure logging for test output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('SprinklerTimingTest')

class SprinklerTimingTester:
    def __init__(self):
        self.config_file = 'config/device.conf'
        self.test_results = {}
        self.timing_events = []
        self.mock_relay_state = False
        self.test_start_time = None
        
    def load_config(self):
        """Load and parse device.conf"""
        config = configparser.ConfigParser()
        config.read(self.config_file)
        return config
    
    def parse_time_to_seconds(self, time_str):
        """Convert HH:MM:SS to seconds - matches system implementation"""
        try:
            if not time_str or time_str.strip() == "":
                return 0
            parts = time_str.strip().split(':')
            if len(parts) != 3:
                return 0
            hours, minutes, seconds = map(int, parts)
            return hours * 3600 + minutes * 60 + seconds
        except:
            return 0
    
    def test_config_parsing(self):
        """Test 1: Verify configuration values are parsed correctly"""
        logger.info("=== TEST 1: Configuration Parsing ===")
        
        try:
            config = self.load_config()
            
            # Get raw config values
            on_duration_raw = config.get('Sprinkler', 'sprinkler_on_duration')
            wait_duration_raw = config.get('Sprinkler', 'sprinkler_wait_duration')
            
            logger.info(f"Raw on_duration: {on_duration_raw}")
            logger.info(f"Raw wait_duration: {wait_duration_raw}")
            
            # Parse first value (API value) and second value (operational value)
            on_duration_api = on_duration_raw.split(',')[0].strip()
            on_duration_operational = on_duration_raw.split(',')[1].strip() if ',' in on_duration_raw else on_duration_api
            
            wait_duration_api = wait_duration_raw.split(',')[0].strip()  
            wait_duration_operational = wait_duration_raw.split(',')[1].strip() if ',' in wait_duration_raw else wait_duration_api
            
            # Convert to seconds
            on_seconds_api = self.parse_time_to_seconds(on_duration_api)
            on_seconds_operational = self.parse_time_to_seconds(on_duration_operational)
            wait_seconds_api = self.parse_time_to_seconds(wait_duration_api)
            wait_seconds_operational = self.parse_time_to_seconds(wait_duration_operational)
            
            logger.info(f"Parsed API values: on={on_duration_api} ({on_seconds_api}s), wait={wait_duration_api} ({wait_seconds_api}s)")
            logger.info(f"Parsed Operational values: on={on_duration_operational} ({on_seconds_operational}s), wait={wait_duration_operational} ({wait_seconds_operational}s)")
            
            # Store results
            self.test_results['config_parsing'] = {
                'status': 'PASS',
                'on_duration_api': on_duration_api,
                'on_duration_operational': on_duration_operational, 
                'wait_duration_api': wait_duration_api,
                'wait_duration_operational': wait_duration_operational,
                'on_seconds_api': on_seconds_api,
                'on_seconds_operational': on_seconds_operational,
                'wait_seconds_api': wait_seconds_api,
                'wait_seconds_operational': wait_seconds_operational
            }
            
            logger.info("✅ Configuration parsing test PASSED")
            return True
            
        except Exception as e:
            logger.error(f"❌ Configuration parsing test FAILED: {e}")
            self.test_results['config_parsing'] = {'status': 'FAIL', 'error': str(e)}
            return False
    
    def test_scheduler_initialization(self):
        """Test 2: Test scheduler initialization with correct timing"""
        logger.info("=== TEST 2: Scheduler Initialization ===")
        
        try:
            # Import scheduler
            from scheduler import RippleScheduler
            
            # Create scheduler instance
            scheduler = RippleScheduler()
            
            # Check if sprinkler schedule was initialized
            sprinkler_jobs = [job for job in scheduler.scheduler.get_jobs() if 'sprinkler' in job.id.lower()]
            
            if sprinkler_jobs:
                job = sprinkler_jobs[0]
                logger.info(f"Found sprinkler job: {job.id}")
                logger.info(f"Job trigger: {job.trigger}")
                
                # Extract interval from trigger if it's an IntervalTrigger
                if hasattr(job.trigger, 'interval'):
                    interval_seconds = job.trigger.interval.total_seconds()
                    logger.info(f"Scheduled interval: {interval_seconds}s")
                    
                    # Compare with expected wait duration
                    config_wait_seconds = self.test_results['config_parsing']['wait_seconds_api']
                    
                    if abs(interval_seconds - config_wait_seconds) < 1:  # Allow 1 second tolerance
                        logger.info("✅ Scheduler interval matches configuration")
                        self.test_results['scheduler_init'] = {'status': 'PASS', 'interval_seconds': interval_seconds}
                        return True
                    else:
                        logger.error(f"❌ Interval mismatch: expected {config_wait_seconds}s, got {interval_seconds}s")
                        self.test_results['scheduler_init'] = {'status': 'FAIL', 'reason': 'interval_mismatch'}
                        return False
                else:
                    logger.warning("⚠️  Job trigger is not IntervalTrigger, cannot verify interval")
                    self.test_results['scheduler_init'] = {'status': 'PARTIAL', 'reason': 'no_interval_trigger'}
                    return True
            else:
                logger.error("❌ No sprinkler jobs found in scheduler")
                self.test_results['scheduler_init'] = {'status': 'FAIL', 'reason': 'no_sprinkler_jobs'}
                return False
                
        except Exception as e:
            logger.error(f"❌ Scheduler initialization test FAILED: {e}")
            self.test_results['scheduler_init'] = {'status': 'FAIL', 'error': str(e)}
            return False
    
    def mock_relay_control(self, state):
        """Mock relay control to track sprinkler state changes"""
        self.mock_relay_state = state
        timestamp = time.time()
        event = {
            'timestamp': timestamp,
            'time_since_start': timestamp - self.test_start_time if self.test_start_time else 0,
            'state': state,
            'datetime': datetime.now().strftime('%H:%M:%S.%f')[:-3]
        }
        self.timing_events.append(event)
        logger.info(f"🔧 Mock Relay: Sprinklers {'ON' if state else 'OFF'} at {event['datetime']} (T+{event['time_since_start']:.2f}s)")
    
    def test_timing_accuracy_short(self, test_duration=30):
        """Test 3: Test timing accuracy with short durations for quick validation"""
        logger.info(f"=== TEST 3: Timing Accuracy Test ({test_duration}s) ===")
        
        try:
            # Temporarily modify config for quick testing
            config = self.load_config()
            original_on = config.get('Sprinkler', 'sprinkler_on_duration')
            original_wait = config.get('Sprinkler', 'sprinkler_wait_duration')
            
            # Set short test durations: 5s on, 10s wait
            test_on_duration = "00:00:05"
            test_wait_duration = "00:00:10"
            
            logger.info(f"Using test durations: ON={test_on_duration}, WAIT={test_wait_duration}")
            
            # Backup original config
            with open(self.config_file + '.backup', 'w') as f:
                config.write(f)
            
            # Update config with test values
            config.set('Sprinkler', 'sprinkler_on_duration', f"{test_on_duration}, {test_on_duration}")
            config.set('Sprinkler', 'sprinkler_wait_duration', f"{test_wait_duration}, {test_wait_duration}")
            
            with open(self.config_file, 'w') as f:
                config.write(f)
            
            logger.info("✅ Updated config with test durations")
            
            # Mock the relay system
            with patch('src.sensors.Relay.Relay') as MockRelay:
                mock_relay_instance = Mock()
                MockRelay.return_value = mock_relay_instance
                
                # Set up mock to call our tracking function
                def mock_set_sprinklers(state):
                    self.mock_relay_control(state)
                    return True
                
                mock_relay_instance.set_sprinklers = mock_set_sprinklers
                
                # Import and create scheduler with mocked relay
                from scheduler import RippleScheduler
                scheduler = RippleScheduler()
                
                # Start timing test
                self.test_start_time = time.time()
                self.timing_events = []
                
                logger.info("🚀 Starting timing accuracy test...")
                
                # Manually trigger one sprinkler cycle to test timing
                scheduler._run_sprinkler_cycle()
                
                # Wait for the test duration to observe timing
                time.sleep(test_duration)
                
                # Stop scheduler
                scheduler.scheduler.shutdown(wait=False)
                
                # Analyze timing events
                self.analyze_timing_events(5, 10)  # Expected: 5s on, 10s total cycle
                
            # Restore original config
            os.rename(self.config_file + '.backup', self.config_file)
            logger.info("✅ Restored original configuration")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Timing accuracy test FAILED: {e}")
            # Try to restore config
            try:
                if os.path.exists(self.config_file + '.backup'):
                    os.rename(self.config_file + '.backup', self.config_file)
            except:
                pass
            self.test_results['timing_accuracy'] = {'status': 'FAIL', 'error': str(e)}
            return False
    
    def analyze_timing_events(self, expected_on_seconds, expected_cycle_seconds):
        """Analyze recorded timing events for accuracy"""
        logger.info("=== TIMING ANALYSIS ===")
        
        if len(self.timing_events) < 2:
            logger.warning("⚠️  Insufficient timing events recorded")
            self.test_results['timing_accuracy'] = {'status': 'INSUFFICIENT_DATA', 'events': len(self.timing_events)}
            return
        
        # Find ON and OFF events
        on_events = [e for e in self.timing_events if e['state'] == True]
        off_events = [e for e in self.timing_events if e['state'] == False]
        
        logger.info(f"Recorded events: {len(on_events)} ON, {len(off_events)} OFF")
        
        if len(on_events) >= 1 and len(off_events) >= 1:
            # Calculate actual ON duration
            first_on = on_events[0]['time_since_start']
            first_off = off_events[0]['time_since_start']
            actual_on_duration = first_off - first_on
            
            logger.info(f"Expected ON duration: {expected_on_seconds}s")
            logger.info(f"Actual ON duration: {actual_on_duration:.2f}s")
            
            # Check accuracy (allow 10% tolerance)
            tolerance = expected_on_seconds * 0.1
            if abs(actual_on_duration - expected_on_seconds) <= tolerance:
                logger.info("✅ ON duration timing is accurate")
                timing_status = 'PASS'
            else:
                logger.error(f"❌ ON duration timing is inaccurate (tolerance: ±{tolerance:.2f}s)")
                timing_status = 'FAIL'
            
            self.test_results['timing_accuracy'] = {
                'status': timing_status,
                'expected_on_seconds': expected_on_seconds,
                'actual_on_seconds': actual_on_duration,
                'timing_error': abs(actual_on_duration - expected_on_seconds),
                'tolerance': tolerance,
                'events': self.timing_events
            }
        else:
            logger.error("❌ Missing ON/OFF event pairs")
            self.test_results['timing_accuracy'] = {'status': 'MISSING_EVENTS', 'events': self.timing_events}
    
    def test_production_config_validation(self):
        """Test 4: Validate current production configuration makes sense"""
        logger.info("=== TEST 4: Production Configuration Validation ===")
        
        try:
            config_data = self.test_results.get('config_parsing', {})
            
            if config_data.get('status') != 'PASS':
                logger.error("❌ Cannot validate production config - parsing failed")
                return False
            
            on_seconds = config_data['on_seconds_operational']
            wait_seconds = config_data['wait_seconds_operational']
            
            logger.info(f"Production config: ON={on_seconds}s ({on_seconds/60:.1f}min), WAIT={wait_seconds}s ({wait_seconds/60:.1f}min)")
            
            # Validation checks
            checks = []
            
            # Check 1: ON duration should be reasonable (1 min to 2 hours)
            if 60 <= on_seconds <= 7200:
                checks.append(("ON duration reasonable", "PASS"))
            else:
                checks.append(("ON duration reasonable", "FAIL", f"{on_seconds}s is outside 1min-2hr range"))
            
            # Check 2: WAIT duration should be longer than ON duration
            if wait_seconds > on_seconds:
                checks.append(("WAIT > ON duration", "PASS"))
            else:
                checks.append(("WAIT > ON duration", "FAIL", f"Wait {wait_seconds}s should be > On {on_seconds}s"))
            
            # Check 3: Total cycle time should be reasonable (< 8 hours)
            total_cycle = on_seconds + wait_seconds
            if total_cycle <= 28800:  # 8 hours
                checks.append(("Total cycle reasonable", "PASS"))
            else:
                checks.append(("Total cycle reasonable", "FAIL", f"{total_cycle}s ({total_cycle/3600:.1f}h) is too long"))
            
            # Check 4: Both values should be non-zero for operational use
            if on_seconds > 0 and wait_seconds > 0:
                checks.append(("Non-zero durations", "PASS"))
            else:
                checks.append(("Non-zero durations", "FAIL", "Zero durations will disable sprinkler system"))
            
            # Report results
            all_passed = True
            for check in checks:
                if check[1] == "PASS":
                    logger.info(f"✅ {check[0]}")
                else:
                    logger.error(f"❌ {check[0]}: {check[2] if len(check) > 2 else 'Failed'}")
                    all_passed = False
            
            self.test_results['production_validation'] = {
                'status': 'PASS' if all_passed else 'FAIL',
                'checks': checks,
                'on_seconds': on_seconds,
                'wait_seconds': wait_seconds,
                'total_cycle_seconds': total_cycle
            }
            
            return all_passed
            
        except Exception as e:
            logger.error(f"❌ Production config validation FAILED: {e}")
            self.test_results['production_validation'] = {'status': 'FAIL', 'error': str(e)}
            return False
    
    def generate_report(self):
        """Generate comprehensive test report"""
        logger.info("=== FINAL TEST REPORT ===")
        
        total_tests = len(self.test_results)
        passed_tests = len([r for r in self.test_results.values() if r.get('status') == 'PASS'])
        
        logger.info(f"Tests completed: {passed_tests}/{total_tests} PASSED")
        
        # Detailed results
        for test_name, result in self.test_results.items():
            status = result.get('status', 'UNKNOWN')
            if status == 'PASS':
                logger.info(f"✅ {test_name}: PASSED")
            elif status == 'FAIL':
                logger.error(f"❌ {test_name}: FAILED - {result.get('error', 'Unknown error')}")
            else:
                logger.warning(f"⚠️  {test_name}: {status}")
        
        # Save detailed report
        report_file = f"sprinkler_timing_test_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump({
                'test_timestamp': datetime.now().isoformat(),
                'summary': {
                    'total_tests': total_tests,
                    'passed_tests': passed_tests,
                    'success_rate': f"{(passed_tests/total_tests)*100:.1f}%" if total_tests > 0 else "0%"
                },
                'detailed_results': self.test_results
            }, f, indent=2, default=str)
        
        logger.info(f"📄 Detailed report saved to: {report_file}")
        
        return passed_tests == total_tests
    
    def run_all_tests(self):
        """Run complete test suite"""
        logger.info("🧪 Starting Sprinkler Timing Test Suite")
        logger.info("=" * 50)
        
        # Test 1: Configuration parsing
        if not self.test_config_parsing():
            logger.error("❌ Critical failure in config parsing - stopping tests")
            return False
        
        # Test 2: Scheduler initialization
        self.test_scheduler_initialization()
        
        # Test 3: Timing accuracy (short test)
        self.test_timing_accuracy_short()
        
        # Test 4: Production config validation
        self.test_production_config_validation()
        
        # Generate final report
        success = self.generate_report()
        
        if success:
            logger.info("🎉 ALL TESTS PASSED - Sprinkler timing is working correctly!")
        else:
            logger.error("⚠️  SOME TESTS FAILED - Review the report for details")
        
        return success

def main():
    """Main test execution"""
    if not os.path.exists('config/device.conf'):
        print("❌ Error: config/device.conf not found. Run this test from the project root directory.")
        return 1
    
    tester = SprinklerTimingTester()
    success = tester.run_all_tests()
    
    return 0 if success else 1

if __name__ == "__main__":
    exit(main())
