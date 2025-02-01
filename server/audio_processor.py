import asyncio
import logging
import tempfile
import time
from pathlib import Path

import av
import edge_tts
from aiortc.mediastreams import MediaStreamError, MediaStreamTrack

logger = logging.getLogger(__name__)

VOICE = "en-US-ChristopherNeural"
OUTPUT_FORMAT = "wav"


class TTSAudioTrack(MediaStreamTrack):
    """An audio track that generates speech from text."""

    kind = "audio"

    def __init__(self) -> None:
        super().__init__()
        self._timestamp = 0
        self._samples_per_frame = 960  # 20ms at 48kHz
        self._sample_rate = 48000
        self._audio_frame = None
        self._audio_container = None
        self._audio_stream = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self.running = True
        self._current_file = None

    async def generate_speech(self, text: str) -> None:
        """Generate speech from text and prepare it for streaming."""
        try:
            start_time = time.time()
            logger.info(f"Starting speech generation for text: {text}")

            # Create a temporary file for the audio
            logger.info("Creating temporary file...")
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                temp_path = Path(temp_file.name)
            logger.info(f"Temporary file created at: {temp_path}")

            # Generate speech
            logger.info("Initializing TTS engine...")
            communicate = edge_tts.Communicate(text, VOICE)
            
            logger.info("Generating speech audio...")
            tts_start = time.time()
            await communicate.save(str(temp_path))
            tts_time = time.time() - tts_start
            logger.info(f"Speech generation completed in {tts_time:.2f} seconds")

            # Open the generated audio file
            if self._audio_container:
                self._audio_container.close()

            logger.info("Opening audio file for streaming...")
            self._current_file = temp_path
            self._audio_container = av.open(str(temp_path))
            self._audio_stream = self._audio_container.streams.audio[0]

            # Read all frames and put them in the queue
            logger.info("Reading audio frames...")
            frame_count = 0
            queue_start = time.time()
            for frame in self._audio_container.decode(audio=0):
                await self._queue.put(frame)
                frame_count += 1
                if frame_count % 100 == 0:  # Log progress every 100 frames
                    logger.info(f"Processed {frame_count} frames...")

            queue_time = time.time() - queue_start
            total_time = time.time() - start_time
            logger.info(
                f"Audio processing completed:\n"
                f"- TTS Generation: {tts_time:.2f}s\n"
                f"- Frame Processing: {queue_time:.2f}s\n"
                f"- Total Frames: {frame_count}\n"
                f"- Frames/Second: {frame_count/queue_time:.1f}\n"
                f"- Total Time: {total_time:.2f}s",
            )

        except Exception as e:
            logger.error(f"Error generating speech: {e}")
            raise MediaStreamError from e

    async def recv(self) -> av.AudioFrame:
        """Get the next frame of audio."""
        if not self.running:
            raise MediaStreamError

        try:
            if self._queue.empty():
                # Create a frame of silence while waiting
                frame = av.AudioFrame.silence(
                    samples=self._samples_per_frame,
                    layout="stereo",
                    rate=self._sample_rate,
                )
                frame.pts = self._timestamp
                frame.time_base = av.Fraction(1, self._sample_rate)
                self._timestamp += self._samples_per_frame
                return frame

            # Get frame from queue
            frame = await self._queue.get()
            if frame.rate != self._sample_rate:
                # Resample if necessary
                frame = frame.reformat(rate=self._sample_rate, layout="stereo")

            # Set timestamp
            frame.pts = self._timestamp
            frame.time_base = av.Fraction(1, self._sample_rate)
            self._timestamp += frame.samples

            return frame

        except Exception as e:
            logger.error(f"Error getting audio frame: {e}")
            raise MediaStreamError from e

    def stop(self) -> None:
        """Stop the audio track."""
        self.running = False
        if self._audio_container:
            self._audio_container.close()
        if self._current_file and self._current_file.exists():
            self._current_file.unlink()
        super().stop()
