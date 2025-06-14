import sqlite3
from datetime import datetime
import json
import os

def create_database():
    """
    Create the queue_log.db database with the log table
    """
    # Database file path
    db_path = 'queue_log.db'
    
    # Check if database already exists
    if os.path.exists(db_path):
        print(f"Database '{db_path}' already exists.")
        response = input("Do you want to recreate it? This will delete all existing data. (y/n): ")
        if response.lower() != 'y':
            print("Database creation cancelled.")
            return
        else:
            os.remove(db_path)
            print(f"Existing database deleted.")
    
    # Create connection to database (this creates the file if it doesn't exist)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Create the log table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                time TEXT NOT NULL,
                request TEXT NOT NULL,
                response TEXT NOT NULL
            )
        ''')
        
        # Create index on time column for faster queries
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_log_time 
            ON log(time)
        ''')
        
        # Commit the changes
        conn.commit()
        print(f"Database '{db_path}' created successfully!")
        print("Table 'log' created with columns: id, time, request, response")
        
        # Insert a test record to verify everything works
        test_data = {
            'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'request': json.dumps({'user_id': 'test', 'endpoint': '/api/test', 'params': {'key': 'value'}}),
            'response': json.dumps({'status': 200, 'data': 'Test successful'})
        }
        
        cursor.execute('''
            INSERT INTO log (time, request, response) 
            VALUES (?, ?, ?)
        ''', (test_data['time'], test_data['request'], test_data['response']))
        
        conn.commit()
        print("\nTest record inserted successfully!")
        
        # Verify by reading the test record
        cursor.execute('SELECT * FROM log WHERE id = 1')
        row = cursor.fetchone()
        if row:
            print("\nTest record verification:")
            print(f"  ID: {row[0]}")
            print(f"  Time: {row[1]}")
            print(f"  Request: {row[2]}")
            print(f"  Response: {row[3]}")
            
            # Delete test record
            cursor.execute('DELETE FROM log WHERE id = 1')
            conn.commit()
            print("\nTest record deleted. Database is ready for use!")
        
    except sqlite3.Error as e:
        print(f"An error occurred: {e}")
        conn.rollback()
    
    finally:
        # Close the connection
        conn.close()

def verify_database():
    """
    Verify the database structure
    """
    db_path = 'queue_log.db'
    
    if not os.path.exists(db_path):
        print(f"Database '{db_path}' does not exist.")
        return
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Get table information
        cursor.execute("PRAGMA table_info(log)")
        columns = cursor.fetchall()
        
        print("\nDatabase structure verification:")
        print("-" * 50)
        print("Table: log")
        print("Columns:")
        for col in columns:
            print(f"  - {col[1]} ({col[2]}){' PRIMARY KEY' if col[5] else ''}")
        
        # Get row count
        cursor.execute("SELECT COUNT(*) FROM log")
        count = cursor.fetchone()[0]
        print(f"\nTotal records: {count}")
        
    except sqlite3.Error as e:
        print(f"An error occurred: {e}")
    
    finally:
        conn.close()

# Helper class for database operations
class QueueLogDB:
    """
    Helper class for database operations
    """
    def __init__(self, db_path='queue_log.db'):
        self.db_path = db_path
    
    def log_request(self, request_params, response_data):
        """
        Log a request and response to the database
        
        Args:
            request_params: Dictionary containing request parameters
            response_data: Dictionary containing response data
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            request_json = json.dumps(request_params)
            response_json = json.dumps(response_data)
            
            cursor.execute('''
                INSERT INTO log (time, request, response) 
                VALUES (?, ?, ?)
            ''', (timestamp, request_json, response_json))
            
            conn.commit()
            return True
            
        except sqlite3.Error as e:
            print(f"Error logging to database: {e}")
            return False
            
        finally:
            conn.close()
    
    def get_logs(self, limit=10):
        """
        Retrieve recent logs from the database
        
        Args:
            limit: Number of recent logs to retrieve
            
        Returns:
            List of log entries
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                SELECT id, time, request, response 
                FROM log 
                ORDER BY time DESC 
                LIMIT ?
            ''', (limit,))
            
            rows = cursor.fetchall()
            logs = []
            
            for row in rows:
                logs.append({
                    'id': row[0],
                    'time': row[1],
                    'request': json.loads(row[2]),
                    'response': json.loads(row[3])
                })
            
            return logs
            
        except sqlite3.Error as e:
            print(f"Error retrieving logs: {e}")
            return []
            
        finally:
            conn.close()

if __name__ == "__main__":
    # Create the database
    create_database()
    
    # Verify the database structure
    verify_database()
    
    # Example usage of the helper class
    print("\n" + "="*50)
    print("Example usage of QueueLogDB helper class:")
    print("="*50)
    
    db = QueueLogDB()
    
    # Log a sample request
    sample_request = {
        'user_id': 'user123',
        'endpoint': 'https://api.example.com/data',
        'parameters': {'param1': 'value1', 'param2': 'value2'}
    }
    
    sample_response = {
        'status': 200,
        'data': {'result': 'success', 'message': 'Data retrieved successfully'}
    }
    
    if db.log_request(sample_request, sample_response):
        print("\nSample log entry added successfully!")
    
    # Retrieve and display logs
    logs = db.get_logs(5)
    if logs:
        print("\nRecent log entries:")
        for log in logs:
            print(f"\nID: {log['id']}")
            print(f"Time: {log['time']}")
            print(f"Request: {log['request']}")
            print(f"Response: {log['response']}")