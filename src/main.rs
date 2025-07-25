use std::collections::{HashMap, VecDeque};
use std::fs;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use chrono::Utc;
use futures_util::{SinkExt, StreamExt};
use log::{error, info, warn};
use reqwest::Client;
use rusqlite::Connection;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::{Mutex, RwLock};
use tokio::time::{interval, sleep};
use tokio_tungstenite::{accept_async, tungstenite::Message, WebSocketStream};
use uuid::Uuid;

const MAX_QUEUE_SIZE: usize = 30;
const PROCESSING_DELAY: Duration = Duration::from_secs(10);
const QUEUE_UPDATE_INTERVAL: Duration = Duration::from_secs(1);
const ENABLE_IP_RESTRICTION: bool = false; // Set to true/false to switch IP-based restrictions

#[derive(Debug, Clone, Serialize, Deserialize)]
struct UserRequest {
    id: String,
    parameters: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct QueuePosition {
    position: usize,
    total_ahead: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
enum ServerMessage {
    #[serde(rename = "queue_position")]
    QueuePosition { position: usize, total_ahead: usize },
    #[serde(rename = "processing")]
    Processing,
    #[serde(rename = "result")]
    Result { data: Value },
    #[serde(rename = "error")]
    Error { message: String },
    #[serde(rename = "queue_full")]
    QueueFull { message: String },
    #[serde(rename = "ip_restricted")]
    IpRestricted { message: String },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
enum ClientMessage {
    #[serde(rename = "request")]
    Request { parameters: Value },
    #[serde(rename = "cancel")]
    Cancel,
}

struct QueuedUser {
    id: String,
    ip_address: String,
    request: UserRequest,
    websocket: Arc<Mutex<WebSocketStream<TcpStream>>>,
}

struct QueueSystem {
    queue: Arc<Mutex<VecDeque<QueuedUser>>>,
    processing_user: Arc<Mutex<Option<String>>>,
    processing_ip: Arc<Mutex<Option<String>>>,
    queued_ips: Arc<RwLock<HashMap<String, String>>>, // IP -> User ID mapping
    user_connections: Arc<RwLock<HashMap<String, Arc<Mutex<WebSocketStream<TcpStream>>>>>>,
    http_client: Client,
    target_url: String,
    db_connection: Arc<Mutex<Connection>>,
}

impl QueueSystem {
    fn new(target_url: String) -> Result<Self> {
        let conn = Connection::open("queue_log.db")?;
        
        // Create the log table if it doesn't exist
        conn.execute(
            "CREATE TABLE IF NOT EXISTS log (
                time TEXT NOT NULL,
                request TEXT NOT NULL,
                response TEXT NOT NULL
            )",
            [],
        )?;

        Ok(QueueSystem {
            queue: Arc::new(Mutex::new(VecDeque::new())),
            processing_user: Arc::new(Mutex::new(None)),
            processing_ip: Arc::new(Mutex::new(None)),
            queued_ips: Arc::new(RwLock::new(HashMap::new())),
            user_connections: Arc::new(RwLock::new(HashMap::new())),
            http_client: Client::new(),
            target_url,
            db_connection: Arc::new(Mutex::new(conn)),
        })
    }

    async fn add_user(&self, user: QueuedUser) -> Result<bool> {
        // Check if IP restriction is enabled and IP is already in queue or being processed
        if ENABLE_IP_RESTRICTION {
            {
                let queued_ips = self.queued_ips.read().await;
                if queued_ips.contains_key(&user.ip_address) {
                    let message = ServerMessage::IpRestricted {
                        message: "您的IP地址已有请求在处理中，请等待完成后再试".to_string(),
                    };
                    
                    if let Ok(msg_str) = serde_json::to_string(&message) {
                        println!("Sent to client {}: {}", user.id, msg_str);
                        let _ = user.websocket.lock().await.send(Message::Text(msg_str)).await;
                    }
                    
                    return Ok(false);
                }
            }

            {
                let processing_ip = self.processing_ip.lock().await;
                if processing_ip.as_ref() == Some(&user.ip_address) {
                    let message = ServerMessage::IpRestricted {
                        message: "您的IP地址已有请求在处理中，请等待完成后再试".to_string(),
                    };
                    
                    if let Ok(msg_str) = serde_json::to_string(&message) {
                        println!("Sent to client {}: {}", user.id, msg_str);
                        let _ = user.websocket.lock().await.send(Message::Text(msg_str)).await;
                    }
                    
                    return Ok(false);
                }
            }
        }

        let mut queue = self.queue.lock().await;
        
        if queue.len() >= MAX_QUEUE_SIZE {
            // Send queue full message
            let message = ServerMessage::QueueFull {
                message: "Sorry, the queue is currently full. Please try again later.".to_string(),
            };
            
if let Ok(msg_str) = serde_json::to_string(&message) {
    // DEBUG: print sent info
    println!("Sent to client {}: {}", user.id, msg_str);
    let _ = user.websocket.lock().await.send(Message::Text(msg_str)).await;
}
            
            return Ok(false);
        }

        // Add user to connections map and IP tracking
        {
            let mut connections = self.user_connections.write().await;
            connections.insert(user.id.clone(), user.websocket.clone());
        }

        if ENABLE_IP_RESTRICTION {
            let mut queued_ips = self.queued_ips.write().await;
            queued_ips.insert(user.ip_address.clone(), user.id.clone());
        }

        queue.push_back(user);
        info!("User added to queue. Current queue size: {}", queue.len());
        
        Ok(true)
    }

    async fn remove_user(&self, user_id: &str) {
        let user_ip = if ENABLE_IP_RESTRICTION {
            let queue = self.queue.lock().await;
            queue.iter().find(|user| user.id == user_id).map(|user| user.ip_address.clone())
        } else {
            None
        };

        {
            let mut queue = self.queue.lock().await;
            queue.retain(|user| user.id != user_id);
        }

        {
            let mut connections = self.user_connections.write().await;
            connections.remove(user_id);
        }

        // Remove from IP tracking only if IP restriction is enabled
        if ENABLE_IP_RESTRICTION {
            if let Some(ip) = user_ip {
                let mut queued_ips = self.queued_ips.write().await;
                queued_ips.remove(&ip);
            }
        }

        {
            let mut processing = self.processing_user.lock().await;
            if processing.as_ref() == Some(&user_id.to_string()) {
                *processing = None;
            }
        }

        if ENABLE_IP_RESTRICTION {
            let mut processing_ip = self.processing_ip.lock().await;
            *processing_ip = None;
        }

        info!("User {} removed from queue", user_id);
    }

    async fn cancel_user(&self, user_id: &str) {
        info!("Cancelling user: {}", user_id);
        self.remove_user(user_id).await;
    }

    async fn broadcast_queue_positions(&self) {
        let queue = self.queue.lock().await;
        let processing_user = self.processing_user.lock().await;

        for (index, user) in queue.iter().enumerate() {
            // Skip if user is currently being processed
            if processing_user.as_ref() == Some(&user.id) {
                continue;
            }

            let message = ServerMessage::QueuePosition {
                position: index + 1,
                total_ahead: index,
            };

if let Ok(msg_str) = serde_json::to_string(&message) {
    // DEBUG: print sent info
    println!("Sent to client {}: {}", user.id, msg_str);
    if let Ok(mut ws) = user.websocket.try_lock() {
        if let Err(e) = ws.send(Message::Text(msg_str)).await {
            warn!("Failed to send position update to user {}: {}", user.id, e);
        }
    }
}
        }
    }

    async fn process_next_user(&self) -> Result<()> {
        let next_user = {
            let mut queue = self.queue.lock().await;
            queue.pop_front()
        };

        if let Some(user) = next_user {
            info!("Processing user: {}", user.id);
            
            // Set processing user and IP
            {
                let mut processing = self.processing_user.lock().await;
                *processing = Some(user.id.clone());
            }

            if ENABLE_IP_RESTRICTION {
                let mut processing_ip = self.processing_ip.lock().await;
                *processing_ip = Some(user.ip_address.clone());
            }

            // Remove from queued IPs since it's now processing (only if IP restriction is enabled)
            if ENABLE_IP_RESTRICTION {
                let mut queued_ips = self.queued_ips.write().await;
                queued_ips.remove(&user.ip_address);
            }

            // Send processing message
            let processing_msg = ServerMessage::Processing;
if let Ok(msg_str) = serde_json::to_string(&processing_msg) {
    // DEBUG: print sent info
    println!("Sent to client {}: {}", user.id, msg_str);
    let _ = user.websocket.lock().await.send(Message::Text(msg_str)).await;
}

            // Wait for the required delay
            sleep(PROCESSING_DELAY).await;

            // Make HTTP request
            let response_result = self.http_client
                .post(&self.target_url)
                .json(&user.request.parameters)
                .send()
                .await;
            // // Print the response_result for testing
            // println!("Response result: {:?}", response_result);
            let (message, log_response) = match response_result {
                Ok(response) => {
                    if response.status().is_success() {
                        match response.json::<Value>().await {
                            Ok(data) => {
                                let msg = ServerMessage::Result { data: data.clone() };
                                (msg, serde_json::to_string(&data).unwrap_or_else(|_| "{}".to_string()))
                            }
                            Err(e) => {
                                let error_msg = format!("Failed to parse response: {}", e);
                                let msg = ServerMessage::Error { message: error_msg.clone() };
                                (msg, error_msg)
                            }
                        }
                    } else {
                        let error_msg = format!("Sorry, the request failed with status: {}", response.status());
                        let msg = ServerMessage::Error { message: error_msg.clone() };
                        (msg, error_msg)
                    }
                }
                Err(e) => {
                    let error_msg = format!("Sorry, failed to make request: {}", e);
                    let msg = ServerMessage::Error { message: error_msg.clone() };
                    (msg, error_msg)
                }
            };

            // Send response to user
if let Ok(msg_str) = serde_json::to_string(&message) {
    // DEBUG: print sent info
    println!("Sent to client {}: {}", user.id, msg_str);
    let _ = user.websocket.lock().await.send(Message::Text(msg_str)).await;
}

            // Log to database
            self.log_request(&user.request, &log_response).await?;

            // Remove user from processing and connections
            {
                let mut processing = self.processing_user.lock().await;
                *processing = None;
            }

            if ENABLE_IP_RESTRICTION {
                let mut processing_ip = self.processing_ip.lock().await;
                *processing_ip = None;
            }

            self.remove_user(&user.id).await;
        }

        Ok(())
    }

    async fn log_request(&self, request: &UserRequest, response: &str) -> Result<()> {
        let conn = self.db_connection.lock().await;
        let timestamp = Utc::now().format("%Y-%m-%d %H:%M:%S").to_string();
        let request_json = serde_json::to_string(request)?;

        conn.execute(
            "INSERT INTO log (time, request, response) VALUES (?1, ?2, ?3)",
            [&timestamp, &request_json, response],
        )?;

        Ok(())
    }

    fn start_queue_processor(self: Arc<Self>) {
        let processor_queue_system = Arc::clone(&self);
        
        tokio::spawn(async move {
            let mut interval_timer = interval(Duration::from_millis(500));
            
            loop {
                interval_timer.tick().await;
                
                // Check if there's a user to process and no one is currently being processed
                {
                    let processing = processor_queue_system.processing_user.lock().await;
                    if processing.is_some() {
                        continue;
                    }
                }

                let queue_len = {
                    let queue = processor_queue_system.queue.lock().await;
                    queue.len()
                };

                if queue_len > 0 {
                    if let Err(e) = processor_queue_system.process_next_user().await {
                        error!("Error processing user: {}", e);
                    }
                }
            }
        });
    }

    fn start_position_broadcaster(self: Arc<Self>) {
        let broadcaster_queue_system = Arc::clone(&self);
        
        tokio::spawn(async move {
            let mut interval_timer = interval(QUEUE_UPDATE_INTERVAL);
            
            loop {
                interval_timer.tick().await;
                broadcaster_queue_system.broadcast_queue_positions().await;
            }
        });
    }
}

async fn handle_websocket(stream: TcpStream, queue_system: Arc<QueueSystem>, client_ip: String) -> Result<()> {
    let websocket = accept_async(stream).await?;
    let user_id = Uuid::new_v4().to_string();
    info!("New WebSocket connection: {}", user_id);

    let (ws_sender, mut ws_receiver) = websocket.split();

    // Wait for initial message with parameters
    if let Some(msg_result) = ws_receiver.next().await {
        match msg_result {
            Ok(Message::Text(text)) => {
                match serde_json::from_str::<ClientMessage>(&text) {
                    Ok(ClientMessage::Request { parameters }) => {
                        // DEBUG: print received info
                        println!("Received request from client {}: {:?}", user_id, parameters);
                        let user_request = UserRequest {
                            id: user_id.clone(),
                            parameters,
                        };

                        // Reunite the WebSocket streams
                        let websocket = ws_sender.reunite(ws_receiver)?;

                        let queued_user = QueuedUser {
                            id: user_id.clone(),
                            ip_address: client_ip,
                            request: user_request,
                            websocket: Arc::new(Mutex::new(websocket)),
                        };

                        if queue_system.add_user(queued_user).await? {
                            info!("User {} added to queue successfully", user_id);
                            
                            // Start listening for additional messages (like cancel)
                            let queue_system_clone = Arc::clone(&queue_system);
                            let user_id_clone = user_id.clone();
                            
                            tokio::spawn(async move {
                                handle_user_messages(queue_system_clone, user_id_clone).await;
                            });
                        } else {
                            warn!("Failed to add user {} to queue (queue full)", user_id);
                            return Ok(());
                        }
                    }
                    Ok(ClientMessage::Cancel) => {
                        // Handle cancel message on initial connection (shouldn't happen normally)
                        info!("User {} sent cancel before being queued", user_id);
                        return Ok(());
                    }
                    Err(e) => {
                        error!("Failed to parse client message: {}", e);
                        return Ok(());
                    }
                }
            }
            Ok(Message::Close(_)) => {
                info!("WebSocket connection closed by client: {}", user_id);
                return Ok(());
            }
            Err(e) => {
                error!("WebSocket error for user {}: {}", user_id, e);
                return Ok(());
            }
            _ => {}
        }
    }

    // Keep connection alive and handle disconnections
    let connections = Arc::clone(&queue_system.user_connections);
    let user_id_clone = user_id.clone();
    
    tokio::spawn(async move {
        loop {
            tokio::time::sleep(Duration::from_secs(30)).await;
            
            let should_remove = {
                let connections_read = connections.read().await;
                if let Some(ws) = connections_read.get(&user_id_clone) {
                    // Try to send a ping to check if connection is alive
                    let mut ws_lock = ws.lock().await;
                    ws_lock.send(Message::Ping(vec![])).await.is_err()
                } else {
                    true
                }
            };

            if should_remove {
                queue_system.remove_user(&user_id_clone).await;
                break;
            }
        }
    });

    Ok(())
}

async fn handle_user_messages(queue_system: Arc<QueueSystem>, user_id: String) {
    loop {
        tokio::time::sleep(Duration::from_millis(100)).await;
        
        // Get websocket connection
        let ws_option = {
            let connections = queue_system.user_connections.read().await;
            connections.get(&user_id).cloned()
        };
        
        if let Some(ws) = ws_option {
            // Try to read a message without blocking
            let message_result = {
                let mut ws_lock = ws.lock().await;
                // We'll use a timeout to avoid blocking indefinitely
                tokio::time::timeout(Duration::from_millis(10), ws_lock.next()).await
            };
            
            match message_result {
                Ok(Some(Ok(Message::Text(text)))) => {
                    match serde_json::from_str::<ClientMessage>(&text) {
                        Ok(ClientMessage::Cancel) => {
                            info!("User {} requested cancellation", user_id);
                            queue_system.cancel_user(&user_id).await;
                            break;
                        }
                        Ok(ClientMessage::Request { .. }) => {
                            // Ignore additional request messages
                            warn!("User {} sent additional request after being queued", user_id);
                        }
                        Err(e) => {
                            error!("Failed to parse message from user {}: {}", user_id, e);
                        }
                    }
                }
                Ok(Some(Ok(Message::Close(_)))) => {
                    info!("WebSocket connection closed by user {}", user_id);
                    queue_system.remove_user(&user_id).await;
                    break;
                }
                Ok(Some(Ok(Message::Binary(_)))) => {
                    // Ignore binary messages
                    continue;
                }
                Ok(Some(Ok(Message::Ping(_)))) => {
                    // Ignore ping messages
                    continue;
                }
                Ok(Some(Ok(Message::Pong(_)))) => {
                    // Ignore pong messages
                    continue;
                }
                Ok(Some(Ok(Message::Frame(_)))) => {
                    // Ignore frame messages
                    continue;
                }
                Ok(Some(Err(e))) => {
                    error!("WebSocket error for user {}: {}", user_id, e);
                    queue_system.remove_user(&user_id).await;
                    break;
                }
                Ok(None) => {
                    // Connection closed
                    queue_system.remove_user(&user_id).await;
                    break;
                }
                Err(_) => {
                    // Timeout - no message available, continue listening
                    continue;
                }
            }
        } else {
            // User connection not found, stop listening
            break;
        }
    }
}

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::init();
    
    // Read target URL from file
    let target_url = fs::read_to_string("URL.txt")?.trim().to_string();
    info!("Target API URL: {}", target_url);

    // Initialize queue system
    let queue_system = Arc::new(QueueSystem::new(target_url)?);

    // Start background tasks
    queue_system.clone().start_queue_processor();
    queue_system.clone().start_position_broadcaster();

    // Start WebSocket server
    let listener = TcpListener::bind("127.0.0.1:3002").await?;
    info!("WebSocket server listening on ws://127.0.0.1:3002");

    while let Ok((stream, addr)) = listener.accept().await {
        info!("New connection from: {}", addr);
        let client_ip = addr.ip().to_string();
        let queue_system_clone = Arc::clone(&queue_system);
        
        tokio::spawn(async move {
            if let Err(e) = handle_websocket(stream, queue_system_clone, client_ip).await {
                error!("Error handling WebSocket connection: {}", e);
            }
        });
    }

    Ok(())
}
