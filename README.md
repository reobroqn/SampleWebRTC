# Sample WebRTC Streaming Project

This is a simplified version of a WebRTC streaming system, demonstrating the core concepts of real-time video streaming using WebRTC technology.

## Features

- WebRTC video streaming
- Simple animated avatar generation
- Clean and responsive web interface
- Real-time video processing pipeline

## Project Structure

```
.
├── README.md
├── requirements.txt
├── server/
│   ├── app.py              # Main server application
│   └── video_processor.py  # Video processing and frame generation
├── static/
│   └── js/
│       └── client.js       # Client-side WebRTC handling
└── templates/
    └── index.html          # Web interface
```

## Prerequisites

- Python 3.8+
- pip (Python package manager)

## Installation

1. Create a virtual environment (recommended):
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Running the Application

1. Start the server:
   ```bash
   python server/app.py
   ```

2. Open a web browser and navigate to:
   ```
   http://localhost:8080
   ```

3. Click the "Start Stream" button to begin streaming.

## How It Works

1. The server generates a simple animated avatar using OpenCV
2. WebRTC is used to establish a peer connection between the browser and server
3. The video stream is sent in real-time to the browser
4. The browser displays the stream in a video element

## Key Components

- `app.py`: Main server application handling WebRTC signaling
- `video_processor.py`: Generates video frames for streaming
- `client.js`: Handles WebRTC connection on the browser side
- `index.html`: Provides the user interface

## Learning Points

- WebRTC connection establishment
- SDP (Session Description Protocol) exchange
- Video track handling
- Real-time streaming pipeline
- Basic video frame generation and processing

## Next Steps

You can extend this project by:
1. Adding audio support
2. Implementing more complex avatar animations
3. Adding interactive controls
4. Implementing multiple stream support
5. Adding data channels for bi-directional communication

## Troubleshooting

If you encounter issues:
1. Make sure all dependencies are installed correctly
2. Check that no other service is using port 8080
3. Ensure your browser supports WebRTC (most modern browsers do)
4. Check the browser console for error messages
# SampleWebRTC
