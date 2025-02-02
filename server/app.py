import asyncio
import logging
import threading
from pathlib import Path
from typing import Set
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
    RTCRtpSender,
)

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .media_container import MediaContainer
from .webrtc import HumanPlayer

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create paths
BASE_DIR = Path(__file__).parent.parent
static_path = BASE_DIR / "static"
template_path = BASE_DIR / "templates"
videos_path = BASE_DIR / "videos"

# Create videos directory if it doesn't exist
videos_path.mkdir(exist_ok=True)
logger.info(f"Base directory: {BASE_DIR}")
logger.info(f"Videos directory: {videos_path}")
logger.info(f"Static files directory: {static_path}")
logger.info(f"Templates directory: {template_path}")

# Global set to keep track of peer connections
pcs: Set[RTCPeerConnection] = set()
media_containers: dict = {}

# Initialize FastAPI app
app = FastAPI(title="WebRTC Stream Server", debug=True)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup static files and templates
app.mount("/static", StaticFiles(directory=str(static_path), html=True), name="static")
templates = Jinja2Templates(directory=str(template_path))

# Define request models
class OfferModel(BaseModel):
    """Model for WebRTC offer data."""

    sdp: str
    type: str
    video_file: str

class TTSRequest(BaseModel):
    """Model for TTS request data."""

    text: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager for FastAPI app."""
    # Startup: nothing to do
    yield
    # Shutdown: cleanup connections
    logger.info("Cleaning up connections...")
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()
    logger.info("Cleanup complete")


# Create FastAPI app with lifespan
app.lifespan_context = lifespan


@app.get("/test-static")
async def test_static() -> JSONResponse:
    """Test if static files are accessible."""
    js_file = static_path / "js" / "client.js"
    if not js_file.exists():
        return JSONResponse(
            {"error": "client.js not found", "path": str(js_file), "exists": False},
        )

    content = js_file.read_text()

    return JSONResponse(
        {
            "exists": True,
            "path": str(js_file),
            "size": len(content),
            "preview": content[:200],  # First 200 chars
        },
    )


@app.get("/js-direct")
async def serve_js() -> FileResponse:
    """Serve client.js directly for testing."""
    js_file = static_path / "js" / "client.js"
    if not js_file.exists():
        raise HTTPException(status_code=404, detail="client.js not found")
    return FileResponse(
        js_file, media_type="application/javascript", filename="client.js",
    )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Serve the index page."""
    # Get list of available video files
    video_files = [f.name for f in videos_path.glob("*") if f.is_file()]
    logger.info(f"Available video files: {video_files}")
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "video_files": video_files},
    )


@app.post("/upload")
async def upload_video(file: UploadFile) -> JSONResponse:
    """Handle video file upload."""
    logger.info(f"Received upload request for file: {file.filename}")

    if not file.filename:
        logger.error("No filename provided")
        raise HTTPException(status_code=400, detail="No file provided")

    # Ensure the file has a video extension
    allowed_extensions = {".mp4", ".avi", ".mkv", ".webm"}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        logger.error(f"Invalid file extension: {file_ext}")
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types: {', '.join(allowed_extensions)}",
        )

    try:
        # Save the file
        file_path = videos_path / file.filename
        logger.info(f"Saving file to: {file_path}")

        # Read file content
        content = await file.read()

        # Write to file
        file_path.write_bytes(content)

        logger.info(f"File saved successfully: {file.filename}")

        # Verify file was saved
        if not file_path.exists():
            raise HTTPException(status_code=500, detail="File was not saved properly")

        # Get file size
        file_size = file_path.stat().st_size
        logger.info(f"Saved file size: {file_size} bytes")

        return JSONResponse(
            {
                "filename": file.filename,
                "message": "File uploaded successfully",
                "size": file_size,
            },
        )
    except Exception as e:
        logger.error(f"Error saving file: {str(e)}")
        if "file_path" in locals() and file_path.exists():
            file_path.unlink()  # Clean up failed upload
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/offer")
async def handle_offer(params: OfferModel) -> JSONResponse:
    """Handle WebRTC offer."""
    logger.debug("Received offer params: %s", params)
    offer = RTCSessionDescription(sdp=params.sdp, type=params.type)
    
    # Create peer connection with STUN server
    pc = RTCPeerConnection(
        configuration=RTCConfiguration(
            iceServers=[RTCIceServer(urls=["stun:stun.l.google.com:19302"])]
        )
    )
    pcs.add(pc)
    logger.debug("Created new peer connection: %s", id(pc))

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        logger.debug("Connection state changed to: %s", pc.connectionState)
        if pc.connectionState == "failed":
            logger.error("Connection failed, closing peer connection")
            await pc.close()
            pcs.discard(pc)
        elif pc.connectionState == "closed":
            logger.debug("Connection closed, removing from active connections")
            pcs.discard(pc)

    # Create media source
    video_path = videos_path / params.video_file
    if not video_path.exists():
        logger.error("Video file not found: %s", params.video_file)
        raise HTTPException(status_code=400, detail=f"Video file not found: {params.video_file}")

    logger.debug("Creating media container for video: %s", video_path)
    # Create media container and player
    container = MediaContainer(str(video_path))
    player = HumanPlayer(container)
    media_containers[id(pc)] = container

    # Add tracks first
    logger.debug("Adding audio and video tracks to peer connection")
    audio_sender = pc.addTrack(player.audio)
    video_sender = pc.addTrack(player.video)

    # Start rendering after tracks are added
    logger.debug("Starting media container render")
    container.render(threading.Event(), asyncio.get_event_loop(), player.audio, player.video)

    # Set remote description
    logger.debug("Setting remote description")
    await pc.setRemoteDescription(offer)

    # Create and set local description
    logger.debug("Creating answer")
    answer = await pc.createAnswer()
    logger.debug("Setting local description")
    await pc.setLocalDescription(answer)

    logger.debug("Returning answer to client")
    return JSONResponse(
        content={
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type,
        }
    )


@app.post("/tts")
async def text_to_speech(request: TTSRequest):
    """Handle text-to-speech request."""
    try:
        logger.debug("Received TTS request: %s", request.text)
        # Find audio track
        for pc in pcs:
            container = media_containers.get(id(pc))
            if container:
                logger.debug("Found media container, sending TTS message")
                container.put_msg_txt(request.text)
                return JSONResponse(content={"status": "success"})
        
        logger.error("No active media container found")
        raise HTTPException(status_code=400, detail="No active media container found")
    except Exception as e:
        logger.exception("TTS error")
        raise HTTPException(status_code=500, detail=str(e)) from e


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True)
