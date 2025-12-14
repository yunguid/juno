"""Audio capture and streaming from M8X USB audio via multiprocessing

Uses a separate process for audio capture because sounddevice/arecord don't work
properly inside uvicorn's async event loop context.
"""
import subprocess
import threading
import multiprocessing
import numpy as np
import io
import wave
import struct
import queue
from dataclasses import dataclass
from typing import Callable

try:
    import sounddevice as sd
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False
    sd = None


def _audio_capture_process(alsa_device: str, sample_rate: int, channels: int, audio_queue: multiprocessing.Queue, stop_event: multiprocessing.Event):
    """Runs in a separate process to capture audio"""
    import sounddevice as sd
    import numpy as np
    
    print(f"[AUDIO PROC] Starting capture process on {alsa_device}")
    
    try:
        # Find the device
        devices = sd.query_devices()
        device_id = None
        for i, d in enumerate(devices):
            if 'MONTAGE' in d['name'].upper():
                device_id = i
                break
        
        if device_id is None:
            print(f"[AUDIO PROC] Montage not found! Available: {[d['name'] for d in devices]}")
            return
        
        print(f"[AUDIO PROC] Using device {device_id}: {devices[device_id]['name']}")
        
        chunk_size = 1024
        chunk_count = 0
        
        while not stop_event.is_set():
            # Use sd.rec() which we know works in standalone Python
            recording = sd.rec(
                chunk_size,
                samplerate=sample_rate,
                channels=channels,
                device=device_id,
                dtype=np.float32
            )
            sd.wait()
            
            chunk_count += 1
            peak = np.max(np.abs(recording))
            
            if chunk_count % 50 == 1:
                print(f"[AUDIO PROC] chunk {chunk_count}: peak {peak:.6f}")
            
            # Put audio data in queue (extract first 2 channels, convert to int16)
            stereo = recording[:, :2]
            audio_int16 = (stereo * 32767).astype(np.int16)
            
            try:
                audio_queue.put_nowait(audio_int16.tobytes())
            except:
                pass  # Queue full, drop frame
                
    except Exception as e:
        print(f"[AUDIO PROC] Error: {e}")
    
    print(f"[AUDIO PROC] Capture process stopped")


@dataclass
class AudioConfig:
    """Audio capture configuration"""
    alsa_device: str = "hw:2,0"  # ALSA device for arecord
    sample_rate: int = 44100
    capture_channels: int = 8   # Montage Generic USB exposes 8 channels
    output_channels: int = 2    # We only stream first 2 (Main L/R)
    chunk_bytes: int = 4096     # Bytes per chunk to read from arecord


class AudioCapture:
    """Captures audio from Montage M USB audio interface using multiprocessing"""

    def __init__(self, config: AudioConfig | None = None):
        self.config = config or AudioConfig()
        self._capturing = False
        self._callbacks: list[Callable[[bytes], None]] = []
        self._capture_process: multiprocessing.Process | None = None
        self._audio_queue: multiprocessing.Queue | None = None
        self._stop_event: multiprocessing.Event | None = None
        self._reader_thread: threading.Thread | None = None
        self._chunk_count = 0

    def list_devices(self) -> list[str]:
        """List available audio input devices using arecord"""
        try:
            result = subprocess.run(
                ["arecord", "-l"],
                capture_output=True,
                text=True,
                timeout=5
            )
            # Parse output to find devices
            devices = []
            for line in result.stdout.split('\n'):
                if 'card' in line.lower():
                    devices.append(line.strip())
            return devices if devices else [f"Default ALSA device: {self.config.alsa_device}"]
        except Exception as e:
            return [f"Error listing devices: {e}"]

    def add_callback(self, callback: Callable[[bytes], None]):
        """Add a callback to receive audio data"""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[bytes], None]):
        """Remove a callback"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _reader_loop(self):
        """Thread that reads from the audio queue and dispatches to callbacks"""
        print(f"[AUDIO] Reader thread started")
        
        while self._capturing:
            try:
                # Get audio data from the queue (blocks with timeout)
                audio_bytes = self._audio_queue.get(timeout=0.1)
                self._chunk_count += 1
                
                if self._chunk_count % 50 == 1:
                    # Calculate peak for debugging
                    audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
                    peak = np.max(np.abs(audio_int16)) / 32767.0
                    print(f"[AUDIO] chunk {self._chunk_count}: peak {peak:.6f}, callbacks: {len(self._callbacks)}")
                
                # Dispatch to callbacks
                for callback in self._callbacks:
                    try:
                        callback(audio_bytes)
                    except Exception as e:
                        print(f"[AUDIO] Callback error: {e}")
                        
            except:
                continue  # Timeout, check if still capturing
        
        print(f"[AUDIO] Reader thread stopped")

    def start(self) -> bool:
        """Start audio capture using multiprocessing"""
        if self._capturing:
            print("[AUDIO] Already capturing")
            return True

        try:
            # Create IPC primitives
            self._audio_queue = multiprocessing.Queue(maxsize=100)
            self._stop_event = multiprocessing.Event()
            
            # Start capture process
            self._capture_process = multiprocessing.Process(
                target=_audio_capture_process,
                args=(
                    self.config.alsa_device,
                    self.config.sample_rate,
                    self.config.capture_channels,
                    self._audio_queue,
                    self._stop_event
                ),
                daemon=True
            )
            self._capture_process.start()
            
            # Start reader thread
            self._capturing = True
            self._chunk_count = 0
            self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self._reader_thread.start()
            
            print(f"[AUDIO] Capture started (multiprocessing) on {self.config.alsa_device}")
            return True
            
        except Exception as e:
            print(f"[AUDIO] Failed to start capture: {e}")
            self._capturing = False
            return False

    def stop(self):
        """Stop audio capture"""
        self._capturing = False
        
        # Signal the capture process to stop
        if self._stop_event:
            self._stop_event.set()
        
        # Wait for capture process
        if self._capture_process:
            self._capture_process.join(timeout=2.0)
            if self._capture_process.is_alive():
                self._capture_process.terminate()
            self._capture_process = None
            
        # Wait for reader thread
        if self._reader_thread:
            self._reader_thread.join(timeout=2.0)
            self._reader_thread = None
        
        # Clean up queue
        if self._audio_queue:
            self._audio_queue.close()
            self._audio_queue = None
            
        self._stop_event = None
            
        print("[AUDIO] Capture stopped")

    def is_capturing(self) -> bool:
        """Check if currently capturing"""
        return self._capturing

    def record(self, duration: float, extra_time: float = 0.5) -> bytes | None:
        """Record audio for a specified duration and return as WAV bytes.
        
        Uses multiprocessing to run sounddevice in a separate process.
        """
        total_duration = duration + extra_time

        def _record_process(duration_sec, sample_rate, channels, result_queue):
            import sounddevice as sd
            import numpy as np
            import io
            import wave
            
            try:
                # Find device
                device_id = None
                for i, d in enumerate(sd.query_devices()):
                    if 'MONTAGE' in d['name'].upper():
                        device_id = i
                        break
                
                if device_id is None:
                    result_queue.put(None)
                    return
                
                print(f"[RECORD] Recording {duration_sec:.1f}s from device {device_id}...")
                recording = sd.rec(
                    int(duration_sec * sample_rate),
                    samplerate=sample_rate,
                    channels=channels,
                    device=device_id,
                    dtype=np.float32
                )
                sd.wait()
                
                peak = np.max(np.abs(recording))
                print(f"[RECORD] Complete: {len(recording)} samples, peak: {peak:.6f}")
                
                # Extract stereo, convert to 16-bit
                stereo = recording[:, :2]
                audio_int16 = (stereo * 32767).astype(np.int16)
                
                # Write to WAV
                wav_buffer = io.BytesIO()
                with wave.open(wav_buffer, 'wb') as wav_file:
                    wav_file.setnchannels(2)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(sample_rate)
                    wav_file.writeframes(audio_int16.tobytes())
                
                wav_buffer.seek(0)
                result_queue.put(wav_buffer.read())
                
            except Exception as e:
                print(f"[RECORD] Error: {e}")
                result_queue.put(None)

        try:
            result_queue = multiprocessing.Queue()
            proc = multiprocessing.Process(
                target=_record_process,
                args=(total_duration, self.config.sample_rate, self.config.capture_channels, result_queue)
            )
            proc.start()
            proc.join(timeout=total_duration + 10)
            
            if proc.is_alive():
                proc.terminate()
                return None
            
            return result_queue.get_nowait() if not result_queue.empty() else None

        except Exception as e:
            print(f"Recording failed: {e}")
            return None


# Singleton instance
_audio_capture: AudioCapture | None = None


def get_audio_capture() -> AudioCapture:
    """Get the global audio capture instance"""
    global _audio_capture
    if _audio_capture is None:
        _audio_capture = AudioCapture()
    return _audio_capture
