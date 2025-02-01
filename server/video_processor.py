import asyncio
import av
import fractions
import logging
import time
from collections import deque
from typing import Deque, Optional

from aiortc.mediastreams import MediaStreamTrack, Frame, MediaStreamError

# Configure logging
logger = logging.getLogger(__name__)

# Constants for video streaming
VIDEO_CLOCK_RATE = 90000  # 90kHz clock rate
VIDEO_PTIME = 1 / 30  # 30 fps
FRAME_BUFFER_SIZE = 30  # Pre-buffer frames

class VideoFileTrack(MediaStreamTrack):
    """A video track that reads from a file and streams it."""
    kind = "video"  # Important: explicitly set the track kind

    def __init__(self, file_path: str) -> None:
        super().__init__()
        self.file_path = file_path
        self._file = None
        self._stream = None
        self._start = time.time()
        self._frame_count = 0
        self._timestamp = 0
        self.running = True
        self._frame_buffer: Deque[Frame] = deque(maxlen=FRAME_BUFFER_SIZE)
        self._buffer_task = None
        self._buffer_ready = asyncio.Event()

        try:
            self._open_video()
            # Start buffer filling task
            self._buffer_task = asyncio.create_task(self._fill_buffer())
        except Exception as e:
            logger.error(f"Error opening video: {e}")
            raise MediaStreamError from e

    def _open_video(self) -> None:
        """Open the video file and initialize stream."""
        start_time = time.time()
        self._file = av.open(self.file_path, "r")
        self._stream = self._file.streams.video[0]
        self._stream.thread_type = "AUTO"

        # Log video properties
        open_time = time.time() - start_time
        logger.info(
            f"Opened video in {open_time:.3f}s:\n"
            f"- Path: {self.file_path}"
        )

    async def _fill_buffer(self) -> None:
        """Continuously fill the frame buffer."""
        try:
            while self.running:
                if len(self._frame_buffer) < FRAME_BUFFER_SIZE:
                    frame = await self._get_next_frame()
                    if frame is not None:
                        self._frame_buffer.append(frame)
                    if len(self._frame_buffer) >= FRAME_BUFFER_SIZE // 2:
                        self._buffer_ready.set()
                else:
                    await asyncio.sleep(0.01)
        except Exception as e:
            logger.error(f"Error filling buffer: {e}")
            self.stop()

    async def _get_next_frame(self) -> Optional[Frame]:
        """Get the next frame from the video, restarting when EOF is reached."""
        try:
            return next(self._file.decode(video=0))
        except (StopIteration, av.EOFError):
            # End of file reached, reopen the video
            self._file.close()
            self._file = av.open(self.file_path, "r")
            return next(self._file.decode(video=0))
        except Exception as e:
            logger.error(f"Error getting next frame: {e}")
            return None

    async def recv(self) -> Frame:
        """Receive the next frame."""
        if self.readyState != "live":
            raise MediaStreamError

        # Wait for buffer to have frames
        await self._buffer_ready.wait()
        
        if not self._frame_buffer:
            raise MediaStreamError("No frames available")

        frame = self._frame_buffer.popleft()
        
        # Calculate pts based on frame count and maintain consistent timing
        self._frame_count += 1
        frame.pts = int(self._frame_count * VIDEO_PTIME * VIDEO_CLOCK_RATE)
        frame.time_base = fractions.Fraction(1, VIDEO_CLOCK_RATE)
        
        # Add a small delay to maintain proper frame rate
        wait_time = max(
            0,
            self._start + (self._frame_count * VIDEO_PTIME) - time.time()
        )
        if wait_time > 0:
            await asyncio.sleep(wait_time)
        
        return frame

    def stop(self) -> None:
        """Stop the video track."""
        self.running = False
        if hasattr(self, '_file'):
            self._file.close()
        super().stop()

    async def __anext__(self) -> Frame:
        """
        Get the next frame from the video file.
        """
        if not self.running:
            raise StopAsyncIteration
        try:
            return await self.recv()
        except MediaStreamError as e:
            raise StopAsyncIteration from e
