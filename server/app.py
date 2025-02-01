import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from aiortc import (
    RTCConfiguration,
    RTCIceServer,
    RTCPeerConnection,
    RTCRtpSender,
    RTCSessionDescription,
)
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from video_processor import VideoFileTrack

# Setup logging
logging.basicConfig(level=logging.INFO)
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
pcs = set()


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
app = FastAPI(title="WebRTC Stream Server", lifespan=lifespan)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
app.mount("/static", StaticFiles(directory=str(static_path), html=True), name="static")
templates = Jinja2Templates(directory=str(template_path))


class OfferModel(BaseModel):
    """Model for WebRTC offer data."""

    sdp: str
    type: str
    video_file: str


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
    try:
        # Validate video file
        video_path = videos_path / params.video_file
        if not video_path.exists():
            logger.error(f"Video file not found: {params.video_file}")
            return JSONResponse(
                status_code=404,
                content={"error": f"Video file not found: {params.video_file}"},
            )

        # Create peer connection with STUN server
        pc = RTCPeerConnection(
            configuration=RTCConfiguration(
                iceServers=[RTCIceServer(urls="stun:stun.l.google.com:19302")],
            ),
        )
        pcs.add(pc)

        # Create unique ID for this connection
        connection_id = str(id(pc))
        logger.info(f"New connection established: {connection_id}")

        @pc.on("connectionstatechange")
        async def on_connectionstatechange() -> None:
            logger.info(
                "Connection %d state changed to: %s",
                connection_id,
                pc.connectionState,
            )
            if pc.connectionState == "failed":
                await pc.close()
                pcs.discard(pc)

        try:
            # Parse and validate the offer
            try:
                offer = RTCSessionDescription(sdp=params.sdp, type=params.type)
            except Exception as e:
                logger.error(f"Invalid session description: {e}")
                return JSONResponse(
                    status_code=400,
                    content={"error": f"Invalid session description: {str(e)}"},
                )

            # Create video track
            logger.info(f"Creating video track for file: {params.video_file}")
            video_file_path = str(video_path)
            video_track = VideoFileTrack(video_file_path)
            video_track.kind = "video"
            pc.addTrack(video_track)

            # Set remote description first
            logger.info("Setting remote description...")
            await pc.setRemoteDescription(offer)

            # Get transceiver
            transceiver = pc.getTransceivers()[0]

            # Set codec preferences
            codecs = RTCRtpSender.getCapabilities("video").codecs
            preferred_codecs = [
                codec for codec in codecs 
                if codec.mimeType.lower() in ["video/h264", "video/vp8"]
            ]
            transceiver.setCodecPreferences(preferred_codecs)

            # Create answer
            logger.info("Creating answer...")
            answer = await pc.createAnswer()
            if not answer:
                raise ValueError("Failed to create answer")

            # Set local description
            logger.info("Setting local description...")
            await pc.setLocalDescription(answer)

            return JSONResponse(
                content={
                    "sdp": pc.localDescription.sdp,
                    "type": pc.localDescription.type,
                    "connection_id": connection_id,
                },
            )

        except Exception as e:
            logger.error(f"Error during WebRTC setup: {e}")
            # Clean up on error
            await pc.close()
            pcs.discard(pc)
            return JSONResponse(
                status_code=500,
                content={"error": f"WebRTC setup failed: {str(e)}"},
            )

    except Exception as e:
        logger.error(f"Unexpected error in handle_offer: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Server error: {str(e)}"},
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True)
