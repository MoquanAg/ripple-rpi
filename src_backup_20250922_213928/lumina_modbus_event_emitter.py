from typing import Callable, Dict, List, Optional
from dataclasses import dataclass
import queue
import threading
import time
import logging

logger = logging.getLogger(__name__)

@dataclass
class ModbusResponse:
    command_id: str
    data: Optional[bytes]
    device_type: str
    status: str = 'success'  # success, timeout, error, connection_lost
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()

class ModbusEventEmitter:
    """
    Asynchronous event emitter for Modbus response handling and distribution.
    
    Implements a publisher-subscriber pattern for distributing Modbus responses
    to registered callbacks. Features thread-safe operation, queue-based
    processing, and comprehensive monitoring capabilities for high-performance
    sensor data handling.
    
    Features:
    - Publisher-subscriber pattern for response distribution
    - Thread-safe subscription and unsubscription management
    - Asynchronous response processing with dedicated thread
    - Queue-based response buffering with configurable size limits
    - Comprehensive error handling and callback isolation
    - Performance monitoring with queue size tracking
    - Graceful shutdown with thread cleanup
    
    Architecture:
    - Response Queue: Buffers incoming responses for processing
    - Processing Thread: Handles response distribution to subscribers
    - Monitor Thread: Tracks queue performance and health
    - Subscriber Management: Thread-safe callback registration
    
    Usage Pattern:
    1. Subscribe callbacks to device types (e.g., 'pH', 'EC', 'DO')
    2. Emit responses through emit_response() method
    3. Responses are automatically distributed to registered callbacks
    4. Callbacks execute in isolation with error handling
    
    Args:
        max_queue_size (int): Maximum response queue size (default: 1000)
        
    Note:
        - Docstring created by Claude 3.5 Sonnet on 2024-09-22
        - Implements thread-safe publisher-subscriber pattern
        - Provides automatic callback error isolation
        - Includes performance monitoring and health tracking
        - Supports graceful shutdown with proper cleanup
        - Uses daemon threads for automatic cleanup on exit
    """
    def __init__(self, max_queue_size: int = 1000):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._response_queue = queue.Queue(maxsize=max_queue_size)
        self._running = True
        self._lock = threading.Lock()
        
        # Start processing thread
        self._process_thread = threading.Thread(
            target=self._process_responses, 
            name="ModbusEventProcessor",
            daemon=True
        )
        self._process_thread.start()
        
        # Add monitoring thread
        self._monitor_thread = threading.Thread(
            target=self._monitor_queue,
            name="ModbusQueueMonitor",
            daemon=True
        )
        self._monitor_thread.start()
    
    def subscribe(self, device_type: str, callback: Callable) -> None:
        """
        Subscribe a callback function to receive responses for a specific device type.
        
        Registers a callback function to be called whenever a Modbus response
        is received for the specified device type. Multiple callbacks can be
        registered for the same device type and will all be called for each response.
        
        Args:
            device_type (str): Device type identifier (e.g., 'pH', 'EC', 'DO', 'THC')
            callback (Callable): Function to call when responses are received
                - Callback signature: callback(response: ModbusResponse) -> None
                - Response contains command_id, data, device_type, status, timestamp
                
        Note:
            - Thread-safe subscription management
            - Prevents duplicate callback registration
            - Callbacks are called in registration order
            - Each callback executes in isolation with error handling
            - Use unsubscribe() to remove callbacks when no longer needed
        """
        with self._lock:
            if device_type not in self._subscribers:
                self._subscribers[device_type] = []
            if callback not in self._subscribers[device_type]:
                self._subscribers[device_type].append(callback)
                logger.debug(f"Added subscriber for {device_type}")
    
    def unsubscribe(self, device_type: str, callback: Callable) -> None:
        """
        Unsubscribe a callback function from receiving responses for a device type.
        
        Removes a previously registered callback from the subscriber list for
        the specified device type. If the callback is not found, the operation
        is silently ignored.
        
        Args:
            device_type (str): Device type identifier to unsubscribe from
            callback (Callable): Callback function to remove from subscription
            
        Note:
            - Thread-safe unsubscription management
            - Silently ignores non-existent callback references
            - Use this method to clean up callbacks when components are destroyed
            - Prevents memory leaks from accumulated callback references
        """
        with self._lock:
            if device_type in self._subscribers:
                try:
                    self._subscribers[device_type].remove(callback)
                    logger.debug(f"Removed subscriber for {device_type}")
                except ValueError:
                    pass
    
    def emit_response(self, response: ModbusResponse) -> None:
        """
        Emit a Modbus response for asynchronous processing and distribution.
        
        Queues a Modbus response for processing by the response processor thread.
        The response will be distributed to all registered callbacks for the
        corresponding device type. If the queue is full, the response is dropped
        and an error is logged.
        
        Args:
            response (ModbusResponse): Response object containing:
                - command_id (str): Unique command identifier
                - data (Optional[bytes]): Response data bytes
                - device_type (str): Device type for callback routing
                - status (str): Response status ('success', 'timeout', 'error', etc.)
                - timestamp (float): Response timestamp
                
        Note:
            - Non-blocking queue operation with 1-second timeout
            - Responses are processed asynchronously by dedicated thread
            - Queue overflow results in response dropping with error logging
            - Use get_queue_size() to monitor queue health
            - Responses are distributed to all subscribers for the device type
        """
        try:
            self._response_queue.put(response, timeout=1.0)
        except queue.Full:
            logger.error(f"Response queue full, dropping response for {response.device_type}")
    
    def _process_responses(self) -> None:
        """Process responses from the queue and distribute to subscribers."""
        while self._running:
            try:
                response = self._response_queue.get(timeout=0.1)
                with self._lock:
                    subscribers = self._subscribers.get(response.device_type, []).copy()
                
                for callback in subscribers:
                    try:
                        callback(response)
                    except Exception as e:
                        logger.error(f"Error in callback for {response.device_type}: {str(e)}")
                
                self._response_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error processing response: {str(e)}")
    
    def _monitor_queue(self) -> None:
        """Monitor queue size and log warnings if it gets too large."""
        while self._running:
            queue_size = self._response_queue.qsize()
            if queue_size > self._response_queue.maxsize * 0.8:
                logger.warning(f"Response queue is {queue_size}/{self._response_queue.maxsize} full")
            time.sleep(5)
    
    def get_queue_size(self) -> int:
        """Get current size of response queue."""
        return self._response_queue.qsize()
    
    def get_subscriber_count(self, device_type: str = None) -> Dict[str, int]:
        """Get count of subscribers, optionally for specific device type."""
        with self._lock:
            if device_type:
                return {device_type: len(self._subscribers.get(device_type, []))}
            return {dt: len(subs) for dt, subs in self._subscribers.items()}
    
    def stop(self) -> None:
        """Stop the event emitter and its threads."""
        self._running = False
        if self._process_thread.is_alive():
            self._process_thread.join(timeout=1.0)
        if self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=1.0)
        
        # Clear any remaining items
        while not self._response_queue.empty():
            try:
                self._response_queue.get_nowait()
                self._response_queue.task_done()
            except queue.Empty:
                break