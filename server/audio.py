"""Audio capture and streaming from M8X USB audio"""
import asyncio
import threading
import numpy as np
import io
import wave
import time
from dataclasses import dataclass
from typing import Callable

try:
    import sounddevice as sd
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False
    sd = None


@dataclass
class AudioConfig:
    """Audio capture configuration"""
    device_names: tuple[str, ...] = ("MONTAGE M", "MONTAGE", "hw:2,0", "hw:M,0")
    sample_rate: int = 44100
    capture_channels: int = 8  # Montage Generic USB exposes 8 channels
    output_channels: int = 2   # We only stream first 2 (Main L/R)
    chunk_size: int = 1024     # Samples per chunk


class AudioCapture:
    """Captures audio from Montage M USB audio interface using thread-based polling"""

    def __init__(self, config: AudioConfig | None = None):
        self.config = config or AudioConfig()
        self._stream: sd.InputStream | None = None
        self._capturing = False
        self._callbacks: list[Callable[[bytes], None]] = []
        self._device_id: int | str | None = None
        self._capture_thread: threading.Thread | None = None
        self._chunk_count = 0

    def find_device(self) -> int | str | None:
        """Find the Montage audio device (supports Generic USB mode)"""
        if not AUDIO_AVAILABLE:
            return None

        devices = sd.query_devices()
        
        # Try each device name pattern
        for name_pattern in self.config.device_names:
            # Check if it's an ALSA device string (hw:X,Y)
            if name_pattern.startswith("hw:"):
                try:
                    info = sd.query_devices(name_pattern)
                    if info and info.get('max_input_channels', 0) >= self.config.capture_channels:
                        return name_pattern
                except Exception:
                    continue
            else:
                # Search by name substring
                for i, device in enumerate(devices):
                    if name_pattern.lower() in device['name'].lower():
                        if device['max_input_channels'] >= self.config.capture_channels:
                            return i
        
        return None

    def list_devices(self) -> list[dict]:
        """List available audio input devices"""
        if not AUDIO_AVAILABLE:
            return []

        devices = []
        for i, device in enumerate(sd.query_devices()):
            if device['max_input_channels'] > 0:
                devices.append({
                    'id': i,
                    'name': device['name'],
                    'channels': device['max_input_channels'],
                    'sample_rate': device['default_samplerate']
                })
        return devices

    def add_callback(self, callback: Callable[[bytes], None]):
        """Add a callback to receive audio data"""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[bytes], None]):
        """Remove a callback"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _capture_loop(self):
        """Thread loop that reads audio and dispatches to callbacks"""
        print(f"[AUDIO] Capture thread started")
        
        try:
            with sd.InputStream(
                device=self._device_id,
                samplerate=self.config.sample_rate,
                channels=self.config.capture_channels,
                blocksize=self.config.chunk_size,
                dtype=np.float32
            ) as stream:
                print(f"[AUDIO] Stream opened: {stream.samplerate}Hz, {stream.channels}ch")
                
                while self._capturing:
                    # Read audio data (blocking)
                    indata, overflowed = stream.read(self.config.chunk_size)
                    
                    if overflowed:
                        print(f"[AUDIO] Buffer overflow!")
                    
                    self._chunk_count += 1
                    
                    # Debug: log raw input levels periodically
                    raw_peak = np.max(np.abs(indata))
                    if self._chunk_count % 50 == 1:
                        print(f"[AUDIO] raw peak: {raw_peak:.6f}, shape: {indata.shape}, callbacks: {len(self._callbacks)}")
                    
                    # Extract stereo (first 2 channels)
                    stereo_data = indata[:, :self.config.output_channels]
                    
                    # Convert to 16-bit PCM
                    audio_int16 = (stereo_data * 32767).astype(np.int16)
                    audio_bytes = audio_int16.tobytes()
                    
                    # Dispatch to callbacks
                    for callback in self._callbacks:
                        try:
                            callback(audio_bytes)
                        except Exception as e:
                            print(f"[AUDIO] Callback error: {e}")
                            
        except Exception as e:
            print(f"[AUDIO] Capture thread error: {e}")
        
        print(f"[AUDIO] Capture thread stopped")

    def start(self) -> bool:
        """Start audio capture in a background thread"""
        if not AUDIO_AVAILABLE:
            print("sounddevice not installed. Run: pip install sounddevice")
            return False

        if self._capturing:
            print("[AUDIO] Already capturing")
            return True

        self._device_id = self.find_device()
        if self._device_id is None:
            print(f"Could not find audio device matching any of: {self.config.device_names}")
            print("Available devices:", [d['name'] for d in self.list_devices()])
            return False

        try:
            self._capturing = True
            self._chunk_count = 0
            self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._capture_thread.start()
            print(f"[AUDIO] Capture started on device {self._device_id} ({self.config.capture_channels} channels)")
            return True
        except Exception as e:
            print(f"[AUDIO] Failed to start capture: {e}")
            self._capturing = False
            return False

    def stop(self):
        """Stop audio capture"""
        self._capturing = False
        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None
        print("[AUDIO] Capture stopped")

    def is_capturing(self) -> bool:
        """Check if currently capturing"""
        return self._capturing

    def record(self, duration: float, extra_time: float = 0.5) -> bytes | None:
        """Record audio for a specified duration and return as WAV bytes."""
        if not AUDIO_AVAILABLE:
            print("sounddevice not installed")
            return None

        device_id = self.find_device()
        if device_id is None:
            print(f"Could not find audio device matching any of: {self.config.device_names}")
            return None

        total_duration = duration + extra_time

        try:
            print(f"Recording {total_duration:.1f}s from device {device_id} ({self.config.capture_channels} channels)...")
            recording = sd.rec(
                int(total_duration * self.config.sample_rate),
                samplerate=self.config.sample_rate,
                channels=self.config.capture_channels,
                device=device_id,
                dtype=np.float32
            )
            sd.wait()
            print(f"Recording complete: {len(recording)} samples, peak: {np.max(np.abs(recording)):.6f}")

            # Extract stereo
            stereo_recording = recording[:, :self.config.output_channels]

            # Convert to 16-bit PCM
            audio_int16 = (stereo_recording * 32767).astype(np.int16)

            # Write to WAV
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(self.config.output_channels)
                wav_file.setsampwidth(2)
                wav_file.setframerate(self.config.sample_rate)
                wav_file.writeframes(audio_int16.tobytes())

            wav_buffer.seek(0)
            return wav_buffer.read()

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
