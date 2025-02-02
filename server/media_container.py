import asyncio
import logging
import threading
import time
from pathlib import Path
import av
import numpy as np
import soundfile as sf
import edge_tts
from io import BytesIO
from queue import Queue, Empty
from enum import Enum

logger = logging.getLogger(__name__)

class State(Enum):
    RUNNING = 0
    PAUSE = 1

class MediaContainer:
    def __init__(self, video_path):
        self.video_path = Path(video_path)
        self.container = av.open(str(video_path))
        self.video_stream = self.container.streams.video[0]
        
        # TTS settings
        self.fps = 50  # 20ms chunks = 50fps
        self.sample_rate = 16000
        self.chunk = self.sample_rate // self.fps  # 320 samples per chunk
        self.input_stream = BytesIO()
        self.msg_queue = Queue()
        self.state = State.RUNNING
        
        # Threads
        self.__thread_quit = None
        self.__process_thread = None
        self.__tts_thread = None

    def render(self, quit_event, loop, audio_track, video_track):
        """Start rendering threads."""
        logger.debug("Starting render threads")
        self.__thread_quit = quit_event
        
        # Start TTS processing thread
        logger.debug("Starting TTS processing thread")
        self.__tts_thread = threading.Thread(
            target=self._process_tts_thread,
            args=(quit_event, loop, audio_track)
        )
        self.__tts_thread.start()
        
        # Start video processing thread
        logger.debug("Starting video processing thread")
        self.__process_thread = threading.Thread(
            target=self._process_video_thread,
            args=(quit_event, loop, video_track)
        )
        self.__process_thread.start()
        logger.debug("All render threads started")

    def _process_video_thread(self, quit_event, loop, video_track):
        """Process video frames in a separate thread."""
        logger.debug("Video processing thread started")
        try:
            for frame in self.container.decode(video=0):
                if quit_event.is_set():
                    logger.debug("Quit event set, stopping video processing")
                    break
                    
                # Convert frame to RGB
                img = frame.to_ndarray(format="rgb24")
                
                # Create video frame
                new_frame = av.VideoFrame.from_ndarray(img, format="rgb24")
                
                # Queue the frame
                asyncio.run_coroutine_threadsafe(
                    video_track._queue.put(new_frame),
                    loop
                ).result()
                
                # Sleep if queue is getting too full
                if video_track._queue.qsize() >= 5:
                    logger.debug('Video queue full (size=%d), sleeping', video_track._queue.qsize())
                    time.sleep(0.04 * video_track._queue.qsize() * 0.8)

            # Close video container
            logger.debug("Closing video container")
            self.container.close()

        except Exception as e:
            logger.exception("Error in video thread")
            if not quit_event.is_set():
                quit_event.set()

    def _process_tts_thread(self, quit_event, loop, audio_track):
        """Process TTS messages in a separate thread."""
        logger.debug("TTS processing thread started")
        while not quit_event.is_set():
            try:
                msg = self.msg_queue.get(timeout=1)
                logger.debug("Processing TTS message: %s", msg)
                self.state = State.RUNNING
                self._generate_speech(msg, loop, audio_track)
            except Exception as e:
                if not isinstance(e, Empty):
                    logger.exception("TTS thread error")
                continue
        logger.debug('TTS thread stopped')

    def _generate_speech(self, text, loop, audio_track):
        """Generate speech from text."""
        try:
            logger.debug("Creating TTS event loop")
            tts_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(tts_loop)
            
            async def process_tts():
                logger.debug("Starting TTS stream")
                communicate = edge_tts.Communicate(text, voice="en-US-ChristopherNeural")
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio" and self.state == State.RUNNING:
                        self.input_stream.write(chunk["data"])
            
            tts_loop.run_until_complete(process_tts())
            logger.debug("TTS stream complete")
            
            if self.input_stream.getbuffer().nbytes <= 0:
                logger.error('EdgeTTS error: no audio data generated')
                return
            
            # Process audio stream
            logger.debug("Processing audio stream")
            self.input_stream.seek(0)
            stream = self._create_bytes_stream(self.input_stream)
            streamlen = stream.shape[0]
            idx = 0
            
            # Convert and queue chunks
            chunks_processed = 0
            while streamlen >= self.chunk and self.state == State.RUNNING:
                chunk = stream[idx:idx + self.chunk]
                # Convert to int16 for WebRTC
                chunk = (chunk * 32768).astype(np.int16)
                frame = av.AudioFrame(format='s16', layout='mono', samples=chunk.shape[0])
                frame.planes[0].update(chunk.tobytes())
                frame.sample_rate = self.sample_rate
                
                # Queue the frame
                asyncio.run_coroutine_threadsafe(
                    audio_track._queue.put(frame),
                    loop
                ).result()
                
                streamlen -= self.chunk
                idx += self.chunk
                chunks_processed += 1
            
            logger.debug("Processed %d audio chunks", chunks_processed)
            
            # Clear input stream
            self.input_stream.seek(0)
            self.input_stream.truncate()
            
        except Exception as e:
            logger.exception("TTS generation error")

    def _create_bytes_stream(self, byte_stream):
        """Convert bytes to audio stream."""
        stream, sample_rate = sf.read(byte_stream)
        logger.info(f'[INFO]tts audio stream {sample_rate}: {stream.shape}')
        stream = stream.astype(np.float32)

        if stream.ndim > 1:
            logger.warning(f'[WARN] audio has {stream.shape[1]} channels, only use the first.')
            stream = stream[:, 0]

        if sample_rate != self.sample_rate and stream.shape[0] > 0:
            logger.warning(f'[WARN] audio sample rate is {sample_rate}, resampling to {self.sample_rate}.')
            from resampy import resample
            stream = resample(x=stream, sr_orig=sample_rate, sr_new=self.sample_rate)

        return stream

    def put_msg_txt(self, text):
        """Add text to TTS queue."""
        if text:
            logger.debug("Adding text to TTS queue: %s", text)
            self.msg_queue.put(text)

    def flush_talk(self):
        """Clear TTS queue and pause."""
        logger.debug("Flushing TTS queue")
        while not self.msg_queue.empty():
            self.msg_queue.get()
        self.state = State.PAUSE
        logger.debug("TTS queue flushed")
