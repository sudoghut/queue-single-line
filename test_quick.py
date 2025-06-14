import asyncio
import websockets
import json

async def test_connection():
    try:
        print('Attempting to connect to ws://127.0.0.1:8080...')
        # Use asyncio.wait_for to add timeout to the connection
        websocket = await asyncio.wait_for(
            websockets.connect('ws://127.0.0.1:8080'), 
            timeout=10
        )
        
        print('Connected successfully!')
        
        # Send a test message
        message = {'parameters': {'test': 'hello'}}
        await websocket.send(json.dumps(message))
        print('Message sent')
        
        # Try to receive a response
        response = await asyncio.wait_for(websocket.recv(), timeout=5)
        print(f'Received: {response}')
        
        await websocket.close()
        print('Connection closed successfully!')
        
    except Exception as e:
        print(f'Connection failed: {e}')
        import traceback
        traceback.print_exc()

asyncio.run(test_connection())