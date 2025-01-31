import asyncio
import fractions
import logging
import time
from collections import deque
from typing import Deque

import av
from aiortc.mediastreams import MediaStreamError, MediaStreamTrack
from av.frame import Frame

logger = logging.getLogger(__name__)

# Pre-buffer this many frames for smoother playback
FRAME_BUFFER_SIZE = 30


class VideoFileTrack(MediaStreamTrack):
    """
    A video track that reads from a file and streams it.
    Handles frame timing and EOF conditions.
    """

    kind = "video"

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
        logger.info(f"Opening video file: {self.file_path}")

        if self._file:
            self._file.close()

        # Open the video file
        self._file = av.open(self.file_path, "r")
        self._stream = self._file.streams.video[0]

        # Get video properties
        self._time_base = fractions.Fraction(1, 90000)  # Common time base for WebRTC
        self._frame_rate = fractions.Fraction(
            self._stream.average_rate.numerator,
            self._stream.average_rate.denominator,
        )
        self._frame_time = float(1 / float(self._frame_rate))

        # Log video properties
        open_time = time.time() - start_time
        logger.info(
            f"Video loaded in {open_time:.2f}s:\n"
            f"- Path: {self.file_path}\n"
            f"- Frame rate: {float(self._frame_rate):.2f} fps\n"
            f"- Frame time: {self._frame_time:.6f}s\n"
            f"- Time base: {float(self._time_base):.6f}"
        )

    async def _fill_buffer(self) -> None:
        """Continuously fill the frame buffer."""
        try:
            while self.running:
                if len(self._frame_buffer) < FRAME_BUFFER_SIZE:
                    frame = await self._get_next_frame()
                    if frame:
                        self._frame_buffer.append(frame)
                        if len(self._frame_buffer) >= FRAME_BUFFER_SIZE // 2:
                            self._buffer_ready.set()
                    else:
                        # End of file reached, wait a bit before trying again
                        await asyncio.sleep(0.1)
                else:
                    # Buffer is full, wait a bit
                    await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Error in buffer task: {e}")
            raise MediaStreamError from e

    async def _get_next_frame(self) -> Frame | None:
        """Get the next frame from the video, handling EOF."""
        try:
            # Read frame
            return next(self._file.decode(video=0))
        except StopIteration:
            # End of file reached, reopen the video
            logger.info("End of video reached, restarting...")
            self._frame_count = 0
            self._start = time.time()
            self._open_video()
            try:
                return next(self._file.decode(video=0))
            except StopIteration as e:
                logger.error("Failed to get frame after reopening video")
                raise MediaStreamError from e
        except Exception as e:
            logger.error(f"Error reading frame: {e}")
            raise MediaStreamError from e

    async def recv(self) -> Frame:
        """
        Receive the next frame.
        
        Returns:
            Frame: The next video frame to be displayed
        """
        if not self.running:
            raise MediaStreamError

        # Wait for buffer to have some frames
        if not self._buffer_ready.is_set():
            logger.info("Waiting for frame buffer to fill...")
            await self._buffer_ready.wait()

        try:
            # Get frame from buffer
            if not self._frame_buffer:
                frame = await self._get_next_frame()
                if frame is None:
                    raise MediaStreamError from None
            else:
                frame = self._frame_buffer.popleft()

            # Calculate when this frame should be shown
            wait_time = max(
                0,
                self._start + (self._frame_count * self._frame_time) - time.time(),
            )
            if wait_time > 0:
                await asyncio.sleep(wait_time)

            # Set frame timing for WebRTC
            frame.pts = int(90000 * self._frame_count * self._frame_time)
            frame.time_base = self._time_base

            # Increment frame counter
            self._frame_count += 1

            return frame

        except Exception as e:
            logger.error(f"Error in recv: {e}")
            raise MediaStreamError from e

    def stop(self) -> None:
        """Stop the video track."""
        self.running = False
        if self._buffer_task:
            self._buffer_task.cancel()
        if self._file:
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
