"""Audio capture and streaming from M8X USB audio via subprocess

Uses arecord subprocess to capture audio because sounddevice doesn't work
properly inside uvicorn's async event loop context.
"""
import subprocess
import threading
import numpy as np
import io
import wave
import struct
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
    alsa_device: str = "hw:2,0"  # ALSA device for arecord
    sample_rate: int = 44100
    capture_channels: int = 8   # Montage Generic USB exposes 8 channels
    output_channels: int = 2    # We only stream first 2 (Main L/R)
    chunk_bytes: int = 4096     # Bytes per chunk to read from arecord


class AudioCapture:
    """Captures audio from Montage M USB audio interface using arecord subprocess"""

    def __init__(self, config: AudioConfig | None = None):
        self.config = config or AudioConfig()
        self._process: subprocess.Popen | None = None
        self._capturing = False
        self._callbacks: list[Callable[[bytes], None]] = []
        self._capture_thread: threading.Thread | None = None
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

    def _capture_loop(self):
        """Thread loop that reads from arecord via FIFO"""
        import os
        import tempfile
        
        print(f"[AUDIO] Capture thread started (using FIFO)")
        
        # Create a named pipe (FIFO)
        fifo_path = "/tmp/juno_audio_fifo"
        try:
            os.unlink(fifo_path)
        except FileNotFoundError:
            pass
        os.mkfifo(fifo_path)
        
        # Start arecord writing to the FIFO
        cmd = f"arecord -D {self.config.alsa_device} -f S32_LE -r {self.config.sample_rate} -c {self.config.capture_channels} -t raw > {fifo_path}"
        print(f"[AUDIO] Starting: {cmd}")
        
        self._process = subprocess.Popen(cmd, shell=True, stderr=subprocess.PIPE)
        
        bytes_per_sample = 4  # S32_LE
        frame_size = self.config.capture_channels * bytes_per_sample  # 32 bytes per frame
        bytes_to_read = 1024 * frame_size  # Read 1024 frames at a time
        
        try:
            # Open FIFO for reading (this blocks until arecord starts writing)
            with open(fifo_path, 'rb') as fifo:
                print(f"[AUDIO] FIFO opened, reading audio...")
                
                while self._capturing:
                    raw_data = fifo.read(bytes_to_read)
                    if not raw_data:
                        # Check if process died
                        if self._process.poll() is not None:
                            stderr = self._process.stderr.read().decode() if self._process.stderr else ""
                            print(f"[AUDIO] arecord exited: {self._process.returncode}, stderr: {stderr}")
                            break
                        continue
                    
                    self._chunk_count += 1
                    
                    # Convert S32_LE to float32
                    num_samples = len(raw_data) // bytes_per_sample
                    int32_data = struct.unpack(f'<{num_samples}i', raw_data)
                    
                    frames = num_samples // self.config.capture_channels
                    audio_data = np.array(int32_data, dtype=np.float32).reshape(frames, self.config.capture_channels)
                    audio_data /= 2147483648.0  # Normalize S32 to -1.0 to 1.0
                    
                    # Debug: log levels periodically
                    raw_peak = np.max(np.abs(audio_data))
                    if self._chunk_count % 50 == 1:
                        print(f"[AUDIO] raw peak: {raw_peak:.6f}, shape: {audio_data.shape}, callbacks: {len(self._callbacks)}")
                    
                    # Extract stereo (first 2 channels)
                    stereo_data = audio_data[:, :self.config.output_channels]
                    
                    # Convert to 16-bit PCM for streaming
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
        finally:
            try:
                os.unlink(fifo_path)
            except:
                pass
        
        print(f"[AUDIO] Capture thread stopped")

    def start(self) -> bool:
        """Start audio capture using arecord via FIFO"""
        if self._capturing:
            print("[AUDIO] Already capturing")
            return True

        try:
            self._capturing = True
            self._chunk_count = 0
            self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._capture_thread.start()
            
            print(f"[AUDIO] Capture starting on {self.config.alsa_device}")
            return True
            
        except Exception as e:
            print(f"[AUDIO] Failed to start capture: {e}")
            self._capturing = False
            return False

    def stop(self):
        """Stop audio capture"""
        self._capturing = False
        
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
            
        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None
            
        print("[AUDIO] Capture stopped")

    def is_capturing(self) -> bool:
        """Check if currently capturing"""
        return self._capturing

    def record(self, duration: float, extra_time: float = 0.5) -> bytes | None:
        """Record audio for a specified duration and return as WAV bytes."""
        total_duration = duration + extra_time

        try:
            # Use arecord to record to a temporary WAV
            cmd = [
                "arecord",
                "-D", self.config.alsa_device,
                "-f", "S32_LE",
                "-r", str(self.config.sample_rate),
                "-c", str(self.config.capture_channels),
                "-d", str(int(total_duration + 1)),  # Duration in seconds
                "-t", "wav",
                "-q",
            ]
            
            print(f"[AUDIO] Recording {total_duration:.1f}s...")
            result = subprocess.run(cmd, capture_output=True, timeout=total_duration + 10)
            
            if result.returncode != 0:
                print(f"[AUDIO] arecord failed: {result.stderr.decode()}")
                return None
            
            # result.stdout contains WAV data
            # Need to convert from 8ch S32_LE to 2ch S16_LE
            # For now, just return raw - can process later if needed
            print(f"[AUDIO] Recording complete: {len(result.stdout)} bytes")
            return result.stdout

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
