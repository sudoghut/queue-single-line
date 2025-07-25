# Queue-Based API Request System with WebSocket

A Rust-based queue management system that handles API requests through WebSocket connections with real-time position updates.

## Features

- **FIFO Queue System**: First-in-first-out queue with maximum capacity of 30 users
- **WebSocket Communication**: Real-time bidirectional communication for status updates
- **Request Processing**: 10-second minimum delay between requests to target API
- **Database Logging**: SQLite database logging of all requests and responses
- **Real-time Updates**: Continuous queue position broadcasting to waiting users
- **Error Handling**: Comprehensive error handling and user feedback

## System Architecture

### Components

1. **Queue Manager**: Handles user queue operations (add, remove, position tracking)
2. **WebSocket Server**: Manages real-time communication with clients
3. **Request Processor**: Processes API requests with rate limiting
4. **Database Logger**: Logs all requests and responses to SQLite database
5. **Position Broadcaster**: Sends real-time queue position updates

### Message Types

#### Client to Server
```json
{
  "parameters": {
    "key": "value",
    "data": "user_request_data"
  }
}
```

#### Server to Client
- **queue_position**: `{"type": "queue_position", "position": 1, "total_ahead": 0}`
- **processing**: `{"type": "processing"}`
- **result**: `{"type": "result", "data": {...}}`
- **error**: `{"type": "error", "message": "Error description"}`
- **queue_full**: `{"type": "queue_full", "message": "Queue is full"}`

## Setup and Usage

### Prerequisites

- Rust (latest stable version)
- Cargo package manager

### Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   cargo build
   ```

## Building with Docker (Alternative)

You can build a release binary within a Fedora Docker container:

1.  **Build Image:** `docker build -t queue-fedora .`
2.  **Create Container:** `docker create --name queue-fedora-container queue-fedora`
3.  **Copy Binary:** `docker cp queue-fedora-container:/app/target/release/queue-fedora .`
4.  **Cleanup (Optional):** `docker rm queue-fedora-container`
5.  **Remove Image (Optional):** `docker rmi queue-fedora`

Now you have the `queue-fedora` binary built in your host server, ready to run on a compatible system.

### Configuration

1. **Target API URL**: Update the `URL.txt` file with your target API endpoint
   ```
   https://your-api-endpoint.com/api/endpoint
   ```

### Running the System

1. **Start the server**:
   ```bash
   cargo run
   ```
   The WebSocket server will start on `ws://127.0.0.1:8080`

2. **Test with the HTML client**:
   - Open `client.html` in a web browser
   - Enter your request parameters in JSON format
   - Click "Connect & Send Request"
   - Monitor real-time queue position updates

### Database Schema

The system automatically creates a SQLite database (`queue_log.db`) with the following schema:

```sql
CREATE TABLE log (
    time TEXT NOT NULL,        -- Timestamp: "YYYY-MM-DD HH:MM:SS"
    request TEXT NOT NULL,     -- JSON string of user request
    response TEXT NOT NULL     -- JSON string of server response
);
```

## API Behavior

### Queue Management
- Maximum 30 users in queue
- FIFO processing order
- Real-time position updates every second
- Automatic user removal on disconnect

### Request Processing
- 10-second minimum delay between requests
- HTTP POST requests to target API
- Success (200 status): Returns JSON response to user
- Failure (non-200 status): Returns error message to user

### Error Handling
- Queue full: Immediate rejection with apology message
- Connection errors: Automatic cleanup and user removal
- API errors: Logged and forwarded to user
- Invalid JSON: Connection termination

## Development

### Code Structure

```
src/
├── main.rs              # Main application entry point
├── queue_system/        # Queue management logic
├── websocket_handler/   # WebSocket connection handling
├── request_processor/   # API request processing
└── database/           # Database operations
```

### Key Constants

- `MAX_QUEUE_SIZE`: 30 users
- `PROCESSING_DELAY`: 10 seconds
- `QUEUE_UPDATE_INTERVAL`: 1 second
- `SERVER_ADDRESS`: 127.0.0.1:8080

### Dependencies

- `tokio`: Async runtime
- `tokio-tungstenite`: WebSocket implementation
- `reqwest`: HTTP client
- `rusqlite`: SQLite database
- `serde`: JSON serialization
- `chrono`: Date/time handling
- `uuid`: Unique ID generation

## Monitoring and Logging

The system provides comprehensive logging:

- **INFO**: User connections, queue operations, processing status
- **WARN**: Connection issues, failed message sends
- **ERROR**: Processing errors, database errors, WebSocket errors

Enable detailed logging by setting the `RUST_LOG` environment variable:
```bash
RUST_LOG=info cargo run
```

## Testing

Use the included `client.html` for testing:

1. **Single User Test**: Connect with one client
2. **Queue Test**: Open multiple browser tabs to test queue behavior
3. **Capacity Test**: Try connecting more than 30 users
4. **Error Test**: Send invalid JSON or test with unreachable API

## Production Considerations

- **Security**: Add authentication and rate limiting
- **Scalability**: Consider Redis for queue storage in distributed systems
- **Monitoring**: Add metrics collection and health checks
- **SSL/TLS**: Use secure WebSocket connections (WSS) in production
- **Database**: Consider PostgreSQL for production workloads

