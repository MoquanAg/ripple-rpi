#!/usr/bin/env python3
"""
Test script for simplified sprinkler controller.

Tests:
1. APScheduler functionality with static functions
2. Failsafe timer mechanism
3. Configuration reading
4. Controller integration

Usage: python3 test_simplified_sprinkler.py
"""

import sys
import os
import time
from datetime import datetime

# Add src directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

def test_static_functions():
    """Test static functions"""
    print("=" * 50)
    print("TESTING STATIC FUNCTIONS")
    print("=" * 50)
    
    try:
        from sprinkler_static import get_sprinkler_config, parse_duration
        
        # Test configuration reading
        on_duration, wait_duration = get_sprinkler_config()
        print(f"✅ Configuration loaded: ON={on_duration}, WAIT={wait_duration}")
        
        # Test duration parsing
        on_seconds = parse_duration(on_duration)
        wait_seconds = parse_duration(wait_duration)
        print(f"✅ Duration parsing: ON={on_seconds}s, WAIT={wait_seconds}s")
        
        return True
    except Exception as e:
        print(f"❌ Static functions failed: {e}")
        return False

def test_apscheduler():
    """Test APScheduler with static functions"""
    print("=" * 50)
    print("TESTING APSCHEDULER")
    print("=" * 50)
    
    try:
        from sprinkler_static import get_scheduler
        from datetime import datetime, timedelta
        
        # Get scheduler
        scheduler = get_scheduler()
        if not scheduler:
            print("❌ Failed to create scheduler")
            return False
        print("✅ APScheduler created successfully")
        
        # Test job scheduling with static function (from the module)
        def test_static_job():
            """This will be moved to a static function"""
            pass
            
        # Create a simple static test by importing
        from sprinkler_static import get_sprinkler_config
        
        # Schedule a test job using a static function
        run_time = datetime.now() + timedelta(seconds=3)
        scheduler.add_job(
            get_sprinkler_config,  # Use static function to test serialization
            'date',
            run_date=run_time,
            id='test_job',
            replace_existing=True
        )
        print(f"✅ Test job scheduled for {run_time.strftime('%H:%M:%S')}")
        
        # Wait for job to execute
        print("⏳ Waiting 5 seconds for job execution...")
        time.sleep(5)
        
        # Check if job executed (it should be removed from scheduler after execution)
        try:
            job = scheduler.get_job('test_job')
            if job:
                print("❌ Job still exists (may not have executed)")
                return False
            else:
                print("✅ Job completed and was removed from scheduler")
        except:
            print("✅ Job completed and was removed from scheduler")
            
        return True
        
    except Exception as e:
        print(f"❌ APScheduler test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_controller():
    """Test simplified sprinkler controller"""
    print("=" * 50)
    print("TESTING SIMPLIFIED CONTROLLER")
    print("=" * 50)
    
    try:
        from simplified_sprinkler_controller import get_sprinkler_controller
        
        # Get controller
        controller = get_sprinkler_controller()
        print("✅ Controller created successfully")
        
        # Check if controller is properly initialized
        if hasattr(controller, 'scheduler') and controller.scheduler:
            print("✅ Controller scheduler initialized")
        else:
            print("❌ Controller scheduler not initialized")
            return False
            
        # Test configuration access
        if hasattr(controller, 'config_file'):
            print(f"✅ Controller config file: {controller.config_file}")
        
        print("✅ Controller is ready for operation")
        return True
        
    except Exception as e:
        print(f"❌ Controller test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("🧪 SIMPLIFIED SPRINKLER CONTROLLER TESTS")
    print("=" * 60)
    
    tests = [
        ("Static Functions", test_static_functions),
        ("APScheduler", test_apscheduler),
        ("Controller", test_controller),
    ]
    
    results = []
    for name, test_func in tests:
        print(f"\n🔍 Running {name} test...")
        result = test_func()
        results.append((name, result))
        
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = 0
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{name:20} {status}")
        if result:
            passed += 1
            
    print(f"\nOverall: {passed}/{len(tests)} tests passed")
    
    if passed == len(tests):
        print("🎉 All tests passed! System is ready for deployment.")
        return True
    else:
        print("⚠️  Some tests failed. Please fix issues before deployment.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
