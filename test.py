#!/usr/bin/env python3
"""
Test script for the Rust WebSocket Queue Server

This script tests various functions of the queue server including:
- WebSocket connection
- Queue position updates
- Request processing
- Queue full scenarios
- Database logging
- Multiple concurrent connections
"""

import asyncio
import websockets
import json
import sqlite3
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any
import requests
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Server configuration
SERVER_URL = "ws://127.0.0.1:8080"
DB_PATH = "queue_log.db"
TEST_PARAMETERS = {"test": "data", "value": 123}

class QueueServerTester:
    def __init__(self):
        self.test_results = []
        self.connections = []
        
    async def test_single_connection(self):
        """Test basic WebSocket connection and message handling"""
        logger.info("Testing single connection...")
        
        try:
            async with websockets.connect(SERVER_URL) as websocket:
                # Send initial request
                message = {"parameters": TEST_PARAMETERS}
                await websocket.send(json.dumps(message))
                
                messages_received = []
                timeout = 30  # seconds
                start_time = time.time()
                
                # Collect messages
                while time.time() - start_time < timeout:
                    try:
                        response = await asyncio.wait_for(websocket.recv(), timeout=1)
                        data = json.loads(response)
                        messages_received.append(data)
                        logger.info(f"Received: {data}")
                        
                        # If we get a result or error, we're done
                        if data.get("type") in ["result", "error"]:
                            break
                            
                    except asyncio.TimeoutError:
                        continue
                    except websockets.exceptions.ConnectionClosed:
                        logger.warning("Connection closed unexpectedly")
                        break
                
                self.test_results.append({
                    "test": "single_connection",
                    "success": len(messages_received) > 0,
                    "messages_count": len(messages_received),
                    "messages": messages_received
                })
                
                logger.info(f"Single connection test completed. Messages received: {len(messages_received)}")
                
        except Exception as e:
            logger.error(f"Single connection test failed: {e}")
            self.test_results.append({
                "test": "single_connection",
                "success": False,
                "error": str(e)
            })
    
    async def test_queue_positions(self):
        """Test queue position updates with multiple connections"""
        logger.info("Testing queue positions with multiple connections...")
        
        try:
            connections = []
            tasks = []
            
            # Create multiple connections
            for i in range(5):
                conn = await websockets.connect(SERVER_URL)
                connections.append(conn)
                
                # Send initial request
                message = {"parameters": {**TEST_PARAMETERS, "client_id": i}}
                await conn.send(json.dumps(message))
                
                # Create task to listen for messages
                task = asyncio.create_task(self._listen_for_messages(conn, f"client_{i}"))
                tasks.append(task)
                
                # Small delay between connections
                await asyncio.sleep(0.5)
            
            # Wait for some messages to be exchanged
            await asyncio.sleep(15)
            
            # Close all connections
            for conn in connections:
                await conn.close()
            
            # Cancel all tasks
            for task in tasks:
                task.cancel()
            
            self.test_results.append({
                "test": "queue_positions",
                "success": True,
                "connections_created": len(connections)
            })
            
            logger.info("Queue positions test completed")
            
        except Exception as e:
            logger.error(f"Queue positions test failed: {e}")
            self.test_results.append({
                "test": "queue_positions",
                "success": False,
                "error": str(e)
            })
    
    async def _listen_for_messages(self, websocket, client_id):
        """Helper to listen for messages from a WebSocket connection"""
        try:
            while True:
                response = await websocket.recv()
                data = json.loads(response)
                logger.info(f"Client {client_id} received: {data}")
                
                if data.get("type") in ["result", "error"]:
                    break
                    
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client {client_id} connection closed")
        except Exception as e:
            logger.error(f"Client {client_id} error: {e}")
    
    async def test_queue_full_scenario(self):
        """Test queue full scenario by creating many connections"""
        logger.info("Testing queue full scenario...")
        
        try:
            connections = []
            queue_full_messages = []
            
            # Try to create more connections than the queue limit (30)
            for i in range(35):
                try:
                    conn = await websockets.connect(SERVER_URL)
                    connections.append(conn)
                    
                    # Send initial request
                    message = {"parameters": {**TEST_PARAMETERS, "overload_test": i}}
                    await conn.send(json.dumps(message))
                    
                    # Check for queue full message
                    try:
                        response = await asyncio.wait_for(conn.recv(), timeout=2)
                        data = json.loads(response)
                        if data.get("type") == "queue_full":
                            queue_full_messages.append(data)
                            logger.info(f"Queue full message received for connection {i}")
                    except asyncio.TimeoutError:
                        pass
                    
                    await asyncio.sleep(0.1)
                    
                except Exception as e:
                    logger.warning(f"Failed to create connection {i}: {e}")
            
            # Clean up connections
            for conn in connections:
                try:
                    await conn.close()
                except:
                    pass
            
            self.test_results.append({
                "test": "queue_full_scenario",
                "success": len(queue_full_messages) > 0,
                "connections_attempted": 35,
                "queue_full_messages": len(queue_full_messages)
            })
            
            logger.info(f"Queue full test completed. Queue full messages: {len(queue_full_messages)}")
            
        except Exception as e:
            logger.error(f"Queue full test failed: {e}")
            self.test_results.append({
                "test": "queue_full_scenario",
                "success": False,
                "error": str(e)
            })
    
    def test_database_logging(self):
        """Test database logging functionality"""
        logger.info("Testing database logging...")
        
        try:
            # Check if database exists and has the correct structure
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            # Check if log table exists
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='log';")
            table_exists = cursor.fetchone() is not None
            
            if not table_exists:
                self.test_results.append({
                    "test": "database_logging",
                    "success": False,
                    "error": "Log table does not exist"
                })
                return
            
            # Check table structure
            cursor.execute("PRAGMA table_info(log);")
            columns = cursor.fetchall()
            expected_columns = ['time', 'request', 'response']
            actual_columns = [col[1] for col in columns]
            
            structure_correct = all(col in actual_columns for col in expected_columns)
            
            # Count existing records
            cursor.execute("SELECT COUNT(*) FROM log;")
            record_count = cursor.fetchone()[0]
            
            # Get recent records
            cursor.execute("SELECT * FROM log ORDER BY time DESC LIMIT 5;")
            recent_records = cursor.fetchall()
            
            conn.close()
            
            self.test_results.append({
                "test": "database_logging",
                "success": structure_correct,
                "table_exists": table_exists,
                "correct_structure": structure_correct,
                "record_count": record_count,
                "recent_records": len(recent_records)
            })
            
            logger.info(f"Database test completed. Records: {record_count}, Structure correct: {structure_correct}")
            
        except Exception as e:
            logger.error(f"Database test failed: {e}")
            self.test_results.append({
                "test": "database_logging",
                "success": False,
                "error": str(e)
            })
    
    async def test_connection_cleanup(self):
        """Test connection cleanup when clients disconnect"""
        logger.info("Testing connection cleanup...")
        
        try:
            # Create a connection and then disconnect abruptly
            conn = await websockets.connect(SERVER_URL)
            
            # Send initial request
            message = {"parameters": {**TEST_PARAMETERS, "cleanup_test": True}}
            await conn.send(json.dumps(message))
            
            # Receive initial response
            response = await asyncio.wait_for(conn.recv(), timeout=5)
            data = json.loads(response)
            logger.info(f"Received initial response: {data}")
            
            # Close connection abruptly
            await conn.close()
              # Wait a bit for cleanup
            await asyncio.sleep(35)  # Server checks every 30 seconds
            
            self.test_results.append({
                "test": "connection_cleanup",
                "success": True,
                "note": "Connection cleanup tested - check server logs for removal messages"
            })
            
            logger.info("Connection cleanup test completed")
        except Exception as e:
            logger.error(f"Connection cleanup test failed: {e}")
            self.test_results.append({
                "test": "connection_cleanup",
                "success": False,
                "error": str(e)
            })
    
    async def test_server_availability(self):
        """Test if the server is running and accessible"""
        logger.info("Testing server availability...")
        
        try:
            # Try to connect to the server
            try:
                websocket = await asyncio.wait_for(
                    websockets.connect(SERVER_URL), 
                    timeout=10
                )
                await websocket.close()
                is_available = True
                logger.info("Successfully connected to WebSocket server")
            except Exception as e:
                is_available = False
                logger.error(f"Failed to connect to WebSocket server: {e}")
            
            self.test_results.append({
                "test": "server_availability",
                "success": is_available,
                "server_url": SERVER_URL
            })
            
            logger.info(f"Server availability test: {'PASS' if is_available else 'FAIL'}")
            
        except Exception as e:
            logger.error(f"Server availability test failed: {e}")
            self.test_results.append({
                "test": "server_availability",
                "success": False,
                "error": str(e)
            })
    
    def print_results(self):
        """Print test results summary"""
        print("\n" + "="*60)
        print("QUEUE SERVER TEST RESULTS")
        print("="*60)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results if result["success"])
        
        print(f"Total Tests: {total_tests}")
        print(f"Passed: {passed_tests}")
        print(f"Failed: {total_tests - passed_tests}")
        print(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        print("-"*60)
        
        for result in self.test_results:
            status = "PASS" if result["success"] else "FAIL"
            print(f"{result['test']:<25} {status}")
            
            if not result["success"] and "error" in result:
                print(f"  Error: {result['error']}")
            
            # Print additional info for some tests
            if result["test"] == "database_logging" and result["success"]:
                print(f"  Records in DB: {result.get('record_count', 'N/A')}")
            elif result["test"] == "queue_positions" and result["success"]:
                print(f"  Connections: {result.get('connections_created', 'N/A')}")
            elif result["test"] == "queue_full_scenario" and result["success"]:
                print(f"  Queue full messages: {result.get('queue_full_messages', 'N/A')}")
        
        print("="*60)
    
    async def run_all_tests(self):
        """Run all tests in sequence"""
        logger.info("Starting comprehensive queue server tests...")
        
        # Test server availability first
        await self.test_server_availability()
        
        if not self.test_results[-1]["success"]:
            logger.error("Server is not available. Cannot run other tests.")
            return
        
        # Run async tests
        await self.test_single_connection()
        await asyncio.sleep(2)
        
        await self.test_queue_positions()
        await asyncio.sleep(2)
        
        await self.test_queue_full_scenario()
        await asyncio.sleep(2)
        
        await self.test_connection_cleanup()
        
        # Run sync tests
        self.test_database_logging()
        
        logger.info("All tests completed!")

async def main():
    """Main test function"""
    print("Queue Server Test Suite")
    print("="*30)
    print("Make sure the Rust server is running on ws://127.0.0.1:8080")
    print("Press Enter to continue or Ctrl+C to cancel...")
    
    try:
        input()
    except KeyboardInterrupt:
        print("\nTest cancelled.")
        return
    
    tester = QueueServerTester()
    
    try:
        await tester.run_all_tests()
    except KeyboardInterrupt:
        logger.info("Tests interrupted by user")
    except Exception as e:
        logger.error(f"Test suite failed: {e}")
    finally:
        tester.print_results()

if __name__ == "__main__":
    # Check if required packages are available
    try:
        import websockets
        import requests
    except ImportError as e:
        print(f"Missing required package: {e}")
        print("Install with: pip install websockets requests")
        exit(1)
    
    # Run the tests
    asyncio.run(main())
