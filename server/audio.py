"""Audio capture and streaming from M8X USB audio"""
import asyncio
import threading
import numpy as np
import io
import wave
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
    channels: int = 2
    chunk_size: int = 1024  # Samples per chunk


class AudioCapture:
    """Captures audio from Montage M USB audio interface"""

    def __init__(self, config: AudioConfig | None = None):
        self.config = config or AudioConfig()
        self._stream: sd.InputStream | None = None
        self._capturing = False
        self._callbacks: list[Callable[[bytes], None]] = []
        self._device_id: int | str | None = None

    def find_device(self) -> int | str | None:
        """Find the Montage audio device (supports Generic USB mode)"""
        if not AUDIO_AVAILABLE:
            return None

        devices = sd.query_devices()
        
        # Try each device name pattern
        for name_pattern in self.config.device_names:
            # Check if it's an ALSA device string (hw:X,Y)
            if name_pattern.startswith("hw:"):
                # Try using it directly - sounddevice accepts ALSA device strings
                try:
                    # Verify the device exists by querying it
                    info = sd.query_devices(name_pattern)
                    if info and info.get('max_input_channels', 0) >= self.config.channels:
                        return name_pattern
                except Exception:
                    continue
            else:
                # Search by name substring
                for i, device in enumerate(devices):
                    if name_pattern.lower() in device['name'].lower():
                        if device['max_input_channels'] >= self.config.channels:
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

    def _audio_callback(self, indata, frames, time_info, status):
        """Called for each audio chunk"""
        if status:
            print(f"Audio status: {status}")

        # Convert float32 numpy array to bytes (16-bit PCM for streaming)
        # Clamp values and convert to int16
        audio_int16 = (indata * 32767).astype(np.int16)
        audio_bytes = audio_int16.tobytes()

        for callback in self._callbacks:
            try:
                callback(audio_bytes)
            except Exception as e:
                print(f"Audio callback error: {e}")

    def start(self) -> bool:
        """Start audio capture"""
        if not AUDIO_AVAILABLE:
            print("sounddevice not installed. Run: pip install sounddevice")
            return False

        self._device_id = self.find_device()
        if self._device_id is None:
            print(f"Could not find audio device matching any of: {self.config.device_names}")
            print("Available devices:", [d['name'] for d in self.list_devices()])
            return False

        try:
            self._stream = sd.InputStream(
                device=self._device_id,
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                blocksize=self.config.chunk_size,
                callback=self._audio_callback,
                dtype=np.float32
            )
            self._stream.start()
            self._capturing = True
            print(f"Audio capture started from device {self._device_id}")
            return True
        except Exception as e:
            print(f"Failed to start audio capture: {e}")
            return False

    def stop(self):
        """Stop audio capture"""
        self._capturing = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def is_capturing(self) -> bool:
        """Check if currently capturing"""
        return self._capturing

    def record(self, duration: float, extra_time: float = 0.5) -> bytes | None:
        """Record audio for a specified duration and return as WAV bytes.

        Args:
            duration: Recording duration in seconds
            extra_time: Extra time to capture release/reverb tails

        Returns:
            WAV file as bytes, or None if recording failed
        """
        if not AUDIO_AVAILABLE:
            print("sounddevice not installed")
            return None

        device_id = self.find_device()
        if device_id is None:
            print(f"Could not find audio device matching any of: {self.config.device_names}")
            return None

        total_duration = duration + extra_time

        try:
            # Record audio
            print(f"Recording {total_duration:.1f}s from device {device_id}...")
            recording = sd.rec(
                int(total_duration * self.config.sample_rate),
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                device=device_id,
                dtype=np.float32
            )
            sd.wait()  # Wait for recording to complete
            print(f"Recording complete: {len(recording)} samples")

            # Convert to 16-bit PCM
            audio_int16 = (recording * 32767).astype(np.int16)

            # Write to WAV in memory
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(self.config.channels)
                wav_file.setsampwidth(2)  # 16-bit = 2 bytes
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
