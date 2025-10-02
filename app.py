import os
import io
import json
from flask import Flask, render_template_string, request, send_file
from flask_sock import Sock
import random
import string

# Initialize the Flask app and the Sock extension for WebSocket support
app = Flask(__name__)
sock = Sock(app)

# A dictionary to store active sharing "rooms"
# Each key is a unique code. The value is a dictionary containing
# websocket connections and file data.
# Format: { 'CODE': {'sender': ws, 'receiver': ws, 'filename': name, 'file_data': data} }
rooms = {}

def generate_code(length=5):
    """Generates a unique random code for a room."""
    while True:
        # Generate a random uppercase alphanumeric code
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        # Ensure the code is not already in use
        if code not in rooms:
            return code

@app.route('/')
def index():
    """Serves the main HTML page."""
    # The entire frontend is contained within this HTML string
    return render_template_string(HTML_TEMPLATE)

@sock.route('/ws')
def websocket(ws):
    """Handles all WebSocket connections and messaging."""
    print("WebSocket connection established.")
    my_code = None
    my_role = None
    
    try:
        while True:
            # Wait for a message from the client
            data = ws.receive()
            if not data:
                continue

            message = json.loads(data)
            msg_type = message.get('type')

            # --- Sender Logic ---
            if msg_type == 'register_sender':
                my_role = 'sender'
                my_code = generate_code()
                rooms[my_code] = {
                    'sender': ws,
                    'receiver': None,
                    'filename': None,
                    'file_data': None
                }
                # Send the generated code back to the sender's browser
                ws.send(json.dumps({'type': 'code_generated', 'code': my_code}))
                print(f"Sender registered with code: {my_code}")

            # --- Receiver Logic ---
            elif msg_type == 'register_receiver':
                code = message.get('code', '').upper()
                if code in rooms and not rooms[code]['receiver']:
                    my_role = 'receiver'
                    my_code = code
                    rooms[my_code]['receiver'] = ws
                    
                    # Notify the sender that the receiver has connected
                    sender_ws = rooms[my_code].get('sender')
                    if sender_ws:
                        sender_ws.send(json.dumps({'type': 'receiver_joined'}))
                    
                    # Confirm connection with the receiver
                    ws.send(json.dumps({'type': 'wating_for_file'}))
                    print(f"Receiver connected to room: {my_code}")
                else:
                    # Inform the client if the code is invalid or the room is full
                    ws.send(json.dumps({'type': 'error', 'message': 'Invalid or expired code.'}))

    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        # --- Cleanup Logic ---
        # When a connection closes (or an error occurs), clean up the room
        if my_code and my_code in rooms:
            print(f"Cleaning up room: {my_code} due to {my_role} disconnect.")
            
            # If the sender disconnects, notify the receiver
            if my_role == 'sender' and rooms[my_code].get('receiver'):
                try:
                    rooms[my_code]['receiver'].send(json.dumps({'type': 'error', 'message': 'Sender disconnected.'}))
                except:
                    pass # Receiver might already be disconnected
            
            # If the receiver disconnects, notify the sender
            elif my_role == 'receiver' and rooms[my_code].get('sender'):
                try:
                     rooms[my_code]['sender'].send(json.dumps({'type': 'error', 'message': 'Receiver disconnected.'}))
                except:
                    pass # Sender might already be disconnected

            del rooms[my_code]
            print(f"Room {my_code} has been closed.")
        
        print("WebSocket connection closed.")


@app.route('/upload', methods=['POST'])
def upload_file():
    """Handles the file upload from the sender."""
    code = request.form.get('code')
    if 'file' not in request.files or not code or code not in rooms:
        return 'Invalid request', 400

    file = request.files['file']
    if file.filename == '':
        return 'No selected file', 400

    # Store file data in memory
    file_data = file.read()
    rooms[code]['filename'] = file.filename
    rooms[code]['file_data'] = file_data
    
    # Notify the receiver that the file is ready for download
    receiver_ws = rooms[code].get('receiver')
    if receiver_ws:
        receiver_ws.send(json.dumps({
            'type': 'file_ready', 
            'filename': file.filename, 
            'filesize': len(file_data)
        }))
        return 'File uploaded and receiver notified.', 200
    else:
        return 'Receiver not connected.', 400


@app.route('/download')
def download_file():
    """Serves the file to the receiver for download."""
    code = request.args.get('code')
    if not code or code not in rooms:
        return 'Invalid download link.', 400
    
    room = rooms.get(code)
    if room and room.get('file_data') is not None:
        # Serve the file from memory
        return send_file(
            io.BytesIO(room['file_data']),
            as_attachment=True,
            download_name=room['filename']
        )
    else:
        return 'File not found or link expired.', 404

# --- HTML Template ---
# This single string contains all the necessary HTML, CSS (via Tailwind), and JavaScript
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PeerDrop - Simple File Sharing</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Inter', sans-serif; }
        .tab-button.active {
            background-color: #4f46e5;
            color: white;
        }
        .code-display {
            letter-spacing: 0.25em;
        }
    </style>
</head>
<body class="bg-gray-100 flex items-center justify-center min-h-screen">

    <div class="w-full max-w-md bg-white rounded-2xl shadow-xl p-8 space-y-6">
        <div class="text-center">
            <h1 class="text-3xl font-bold text-gray-800">PeerDrop</h1>
            <p class="text-gray-500 mt-1">Share files directly and securely</p>
        </div>

        <!-- Tab Controls -->
        <div class="flex border border-gray-200 rounded-lg p-1 bg-gray-50">
            <button id="send-tab-btn" class="tab-button w-1/2 p-2 rounded-md font-semibold text-gray-600 transition-all duration-300">Send</button>
            <button id="receive-tab-btn" class="tab-button w-1/2 p-2 rounded-md font-semibold text-gray-600 transition-all duration-300">Receive</button>
        </div>

        <!-- Send Panel -->
        <div id="send-panel" class="space-y-4">
            <div class="text-center">
                <input type="file" id="file-input" class="hidden"/>
                <label for="file-input" class="cursor-pointer w-full inline-block px-6 py-3 bg-indigo-50 text-indigo-700 font-semibold rounded-lg hover:bg-indigo-100 transition-colors duration-300">
                    Select a File
                </label>
                <p id="file-name" class="mt-2 text-sm text-gray-500">No file selected.</p>
            </div>
            <button id="send-btn" class="w-full bg-indigo-600 text-white font-bold py-3 px-4 rounded-lg hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 transition-transform duration-200 active:scale-95 disabled:bg-gray-300 disabled:cursor-not-allowed">
                Send
            </button>
            <div id="code-container" class="hidden text-center p-4 border-2 border-dashed border-gray-300 rounded-lg">
                <p class="text-gray-500 mb-2">Share this code with the receiver:</p>
                <p id="send-code" class="text-3xl font-bold text-gray-800 code-display"></p>
            </div>
        </div>

        <!-- Receive Panel -->
        <div id="receive-panel" class="hidden space-y-4">
            <input type="text" id="code-input" placeholder="Enter 5-digit code" class="w-full text-center p-3 border-2 border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 text-2xl uppercase code-display" maxlength="5">
            <button id="receive-btn" class="w-full bg-indigo-600 text-white font-bold py-3 px-4 rounded-lg hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 transition-transform duration-200 active:scale-95">
                Receive
            </button>
             <div id="download-container" class="hidden text-center p-4 border-2 border-dashed border-gray-300 rounded-lg">
                <p id="download-filename" class="text-gray-800 font-semibold mb-2"></p>
                <a id="download-link" href="#" class="w-full inline-block bg-green-500 text-white font-bold py-3 px-4 rounded-lg hover:bg-green-600 transition-all duration-200">
                    Download File
                </a>
            </div>
        </div>
        
        <!-- Status Area -->
        <div id="status" class="text-center text-gray-600 h-5"></div>
    </div>

    <script>
        const sendTabBtn = document.getElementById('send-tab-btn');
        const receiveTabBtn = document.getElementById('receive-tab-btn');
        const sendPanel = document.getElementById('send-panel');
        const receivePanel = document.getElementById('receive-panel');
        
        const fileInput = document.getElementById('file-input');
        const fileNameDisplay = document.getElementById('file-name');
        const sendBtn = document.getElementById('send-btn');
        const sendCodeDisplay = document.getElementById('send-code');
        const codeContainer = document.getElementById('code-container');
        
        const codeInput = document.getElementById('code-input');
        const receiveBtn = document.getElementById('receive-btn');
        const downloadContainer = document.getElementById('download-container');
        const downloadLink = document.getElementById('download-link');
        const downloadFilename = document.getElementById('download-filename');

        const statusDisplay = document.getElementById('status');
        
        let ws;
        let myCode = null;
        let isSender = true;

        // --- WebSocket Logic ---
        function connectWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws`);

            ws.onopen = () => {
                console.log('WebSocket connection opened.');
                statusDisplay.textContent = 'Connected to server.';
            };

            ws.onmessage = (event) => {
                const message = JSON.parse(event.data);
                console.log('Received message:', message);
                handleServerMessage(message);
            };

            ws.onclose = () => {
                console.log('WebSocket connection closed.');
                statusDisplay.textContent = 'Connection lost. Please refresh.';
                sendBtn.disabled = true;
                receiveBtn.disabled = true;
            };

            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
                statusDisplay.textContent = 'Connection error.';
            };
        }

        function handleServerMessage(message) {
            switch (message.type) {
                case 'code_generated':
                    myCode = message.code;
                    sendCodeDisplay.textContent = myCode;
                    codeContainer.classList.remove('hidden');
                    statusDisplay.textContent = 'Waiting for receiver to connect...';
                    break;
                
                case 'receiver_joined':
                    statusDisplay.textContent = 'Receiver connected! Uploading file...';
                    uploadFile();
                    break;

                case 'wating_for_file':
                    statusDisplay.textContent = 'Connected! Waiting for sender to send file...';
                    receiveBtn.disabled = true;
                    codeInput.disabled = true;
                    break;

                case 'file_ready':
                    downloadFilename.textContent = message.filename;
                    downloadLink.href = `/download?code=${codeInput.value.toUpperCase()}`;
                    downloadContainer.classList.remove('hidden');
                    statusDisplay.textContent = 'File is ready for download!';
                    break;

                case 'error':
                    statusDisplay.textContent = `Error: ${message.message}`;
                    resetUI();
                    break;
            }
        }
        
        // --- UI Logic ---
        function switchTab(isSend) {
            isSender = isSend;
            if (isSend) {
                sendTabBtn.classList.add('active');
                receiveTabBtn.classList.remove('active');
                sendPanel.classList.remove('hidden');
                receivePanel.classList.add('hidden');
            } else {
                sendTabBtn.classList.remove('active');
                receiveTabBtn.classList.add('active');
                sendPanel.classList.add('hidden');
                receivePanel.classList.remove('hidden');
            }
            resetUI();
        }

        function resetUI() {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.close();
            }
            connectWebSocket();

            fileInput.value = '';
            fileNameDisplay.textContent = 'No file selected.';
            sendBtn.disabled = true;
            receiveBtn.disabled = false;
            
            codeContainer.classList.add('hidden');
            sendCodeDisplay.textContent = '';
            
            codeInput.value = '';
            codeInput.disabled = false;
            
            downloadContainer.classList.add('hidden');
            statusDisplay.textContent = 'Select a role to start.';
            myCode = null;
        }

        // --- Event Listeners ---
        sendTabBtn.addEventListener('click', () => switchTab(true));
        receiveTabBtn.addEventListener('click', () => switchTab(false));

        fileInput.addEventListener('change', () => {
            if (fileInput.files.length > 0) {
                fileNameDisplay.textContent = fileInput.files[0].name;
                sendBtn.disabled = false;
            } else {
                fileNameDisplay.textContent = 'No file selected.';
                sendBtn.disabled = true;
            }
        });

        sendBtn.addEventListener('click', () => {
            if (!ws || ws.readyState !== WebSocket.OPEN) {
                statusDisplay.textContent = 'Not connected. Retrying...';
                connectWebSocket();
                return;
            }
            sendBtn.disabled = true;
            statusDisplay.textContent = 'Generating code...';
            ws.send(JSON.stringify({ type: 'register_sender' }));
        });
        
        receiveBtn.addEventListener('click', () => {
            const code = codeInput.value.trim().toUpperCase();
            if (code.length !== 5) {
                statusDisplay.textContent = 'Please enter a valid 5-digit code.';
                return;
            }
            statusDisplay.textContent = 'Connecting...';
            ws.send(JSON.stringify({ type: 'register_receiver', code: code }));
        });
        
        // --- File Upload ---
        function uploadFile() {
            const file = fileInput.files[0];
            const formData = new FormData();
            formData.append('file', file);
            formData.append('code', myCode);

            fetch('/upload', {
                method: 'POST',
                body: formData
            })
            .then(response => {
                if (response.ok) {
                    statusDisplay.textContent = 'File sent! Receiver can now download.';
                } else {
                   return response.text().then(text => { throw new Error(text) });
                }
            })
            .catch(error => {
                console.error('Upload error:', error);
                statusDisplay.textContent = `Upload failed: ${error.message}`;
            });
        }

        // --- Initial State ---
        window.onload = () => {
            switchTab(true);
        };

    </script>
</body>
</html>
"""

if __name__ == '__main__':
    # Get port from environment variable or default to 5000
    port = int(os.environ.get('PORT', 5000))
    # Running with debug=False is recommended for production
    # Use '0.0.0.0' to make it accessible on your network
    app.run(host='0.0.0.0', port=port, debug=True)
