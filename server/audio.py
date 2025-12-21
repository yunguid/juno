"""Audio capture and streaming from Montage USB audio.

Audio backends can behave differently under Uvicorn (reload/workers/threads).
To keep capture reliable, we run capture in a separate process (spawn start
method) and forward chunks to the main process via a queue.
"""

from __future__ import annotations

import io
import multiprocessing
import os
import queue
import subprocess
import threading
import time
import wave
from dataclasses import dataclass
from typing import Callable

import numpy as np


def _env_int(name: str) -> int | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _select_input_device_index(
    sd,
    *,
    required_channels: int,
    device_index: int | None,
    device_name_substring: str,
) -> int | None:
    devices = sd.query_devices()

    if device_index is not None:
        if 0 <= device_index < len(devices):
            return device_index
        return None

    needle = device_name_substring.strip().upper() if device_name_substring else ""
    if needle:
        for i, d in enumerate(devices):
            if needle in d.get("name", "").upper() and d.get("max_input_channels", 0) >= required_channels:
                return i
        for i, d in enumerate(devices):
            if needle in d.get("name", "").upper() and d.get("max_input_channels", 0) > 0:
                return i

    try:
        default_in = sd.default.device[0]
    except Exception:
        default_in = None
    if isinstance(default_in, int) and default_in >= 0:
        return default_in

    for i, d in enumerate(devices):
        if d.get("max_input_channels", 0) > 0:
            return i
    return None


def _audio_capture_process(
    device_name_substring: str,
    device_index: int | None,
    sample_rate: int,
    channels: int,
    chunk_frames: int,
    audio_queue: multiprocessing.Queue,
    stop_event: multiprocessing.Event,
):
    """Runs in a separate process to capture audio chunks as int16 stereo bytes."""
    try:
        import sounddevice as sd
    except ImportError as e:
        print(f"[AUDIO PROC] sounddevice not available: {e}", flush=True)
        return

    env_device_index = _env_int("JUNO_AUDIO_DEVICE_INDEX")
    env_device_substring = os.getenv("JUNO_AUDIO_DEVICE_SUBSTRING")
    resolved_device_index = env_device_index if env_device_index is not None else device_index
    resolved_substring = (env_device_substring or device_name_substring or "MONTAGE").strip()

    print(f"[AUDIO PROC] Starting capture (pid={os.getpid()})", flush=True)

    try:
        device_id = _select_input_device_index(
            sd,
            required_channels=channels,
            device_index=resolved_device_index,
            device_name_substring=resolved_substring,
        )
        if device_id is None:
            devices = sd.query_devices()
            names = [d.get("name", "<unknown>") for d in devices]
            print(f"[AUDIO PROC] No input device found. Devices: {names}", flush=True)
            return

        device_info = sd.query_devices(device_id)
        max_in = int(device_info.get("max_input_channels", 0) or 0)
        if max_in <= 0:
            print(f"[AUDIO PROC] Selected device has no inputs: {device_info}", flush=True)
            return
        if max_in < channels:
            print(
                f"[AUDIO PROC] Warning: device has {max_in} input channels, requested {channels}; using {max_in}",
                flush=True,
            )
            channels = max_in

        print(f"[AUDIO PROC] Using device {device_id}: {device_info.get('name')}", flush=True)

        chunk_count = 0
        with sd.InputStream(
            samplerate=sample_rate,
            channels=channels,
            device=device_id,
            dtype="int16",
            blocksize=chunk_frames,
        ) as stream:
            while not stop_event.is_set():
                data, overflowed = stream.read(chunk_frames)
                chunk_count += 1

                if chunk_count % 200 == 1:
                    peak = 0.0
                    if len(data):
                        peak_i16 = int(np.max(np.abs(data.astype(np.int32))))
                        peak = float(peak_i16) / 32767.0
                    print(f"[AUDIO PROC] chunk {chunk_count}: peak {peak:.6f}, overflow={overflowed}", flush=True)

                if data.shape[1] >= 2:
                    stereo = data[:, :2]
                else:
                    stereo = np.repeat(data, 2, axis=1)

                try:
                    audio_queue.put_nowait(np.ascontiguousarray(stereo).tobytes())
                except Exception:
                    pass

    except Exception as e:
        print(f"[AUDIO PROC] Error: {e}", flush=True)

    print("[AUDIO PROC] Capture stopped", flush=True)


def _audio_record_process(
    device_name_substring: str,
    device_index: int | None,
    duration_sec: float,
    sample_rate: int,
    channels: int,
    result_queue: multiprocessing.Queue,
):
    """Runs in a separate process to record a stereo WAV and return bytes."""
    try:
        import sounddevice as sd
    except ImportError as e:
        print(f"[RECORD] sounddevice not available: {e}", flush=True)
        result_queue.put(None)
        return

    env_device_index = _env_int("JUNO_AUDIO_DEVICE_INDEX")
    env_device_substring = os.getenv("JUNO_AUDIO_DEVICE_SUBSTRING")
    resolved_device_index = env_device_index if env_device_index is not None else device_index
    resolved_substring = (env_device_substring or device_name_substring or "MONTAGE").strip()

    try:
        device_id = _select_input_device_index(
            sd,
            required_channels=channels,
            device_index=resolved_device_index,
            device_name_substring=resolved_substring,
        )
        if device_id is None:
            result_queue.put(None)
            return

        device_info = sd.query_devices(device_id)
        max_in = int(device_info.get("max_input_channels", 0) or 0)
        if max_in <= 0:
            result_queue.put(None)
            return
        if max_in < channels:
            channels = max_in

        frames = int(duration_sec * sample_rate)
        print(f"[RECORD] Recording {duration_sec:.2f}s from device {device_id}...", flush=True)
        recording = sd.rec(
            frames,
            samplerate=sample_rate,
            channels=channels,
            device=device_id,
            dtype=np.float32,
        )
        sd.wait()

        stereo = recording[:, :2] if recording.shape[1] >= 2 else np.repeat(recording, 2, axis=1)
        stereo = np.clip(stereo, -1.0, 1.0)
        audio_int16 = (stereo * 32767.0).astype(np.int16)

        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wav_file:
            wav_file.setnchannels(2)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_int16.tobytes())

        wav_buffer.seek(0)
        result_queue.put(wav_buffer.read())

    except Exception as e:
        print(f"[RECORD] Error: {e}", flush=True)
        result_queue.put(None)


@dataclass
class AudioConfig:
    """Audio capture configuration."""

    alsa_device: str = "hw:2,0"
    device_name_substring: str = "MONTAGE"
    device_index: int | None = None
    sample_rate: int = 44100
    capture_channels: int = 8
    output_channels: int = 2
    chunk_frames: int = 1024  # ~23ms at 44100Hz for lower latency
    max_backlog_chunks: int = 4  # Fewer chunks = lower latency, slight jitter risk

    def __post_init__(self) -> None:
        env_chunk = _env_int("JUNO_AUDIO_CHUNK_FRAMES")
        if env_chunk is not None and env_chunk > 0:
            self.chunk_frames = env_chunk
        env_backlog = _env_int("JUNO_AUDIO_MAX_BACKLOG_CHUNKS")
        if env_backlog is not None and env_backlog > 0:
            self.max_backlog_chunks = env_backlog


class AudioCapture:
    """Captures Montage USB audio in a separate process and dispatches chunks to callbacks."""

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
        """List available audio devices (arecord when available, else sounddevice)."""
        try:
            result = subprocess.run(
                ["arecord", "-l"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            devices = []
            for line in result.stdout.split("\n"):
                if "card" in line.lower():
                    devices.append(line.strip())
            return devices if devices else [f"Default ALSA device: {self.config.alsa_device}"]
        except FileNotFoundError:
            pass
        except Exception:
            pass

        try:
            import sounddevice as sd

            devices = []
            for i, d in enumerate(sd.query_devices()):
                in_ch = d.get("max_input_channels", 0)
                out_ch = d.get("max_output_channels", 0)
                if not in_ch and not out_ch:
                    continue
                devices.append(f"{i}: {d.get('name')} (in={in_ch} out={out_ch})")
            return devices or ["No sounddevice devices found"]
        except Exception as e:
            return [f"Error listing devices: {e}"]

    def add_callback(self, callback: Callable[[bytes], None]):
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[bytes], None]):
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _reader_loop(self):
        print("[AUDIO] Reader thread started")

        while self._capturing:
            try:
                audio_bytes = self._audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            except Exception:
                continue

            # If capture got ahead (e.g., event loop pause), trim backlog to preserve continuity.
            try:
                backlog = self._audio_queue.qsize()
            except Exception:
                backlog = 0
            if backlog > self.config.max_backlog_chunks:
                drop_count = backlog - self.config.max_backlog_chunks
                for _ in range(drop_count):
                    try:
                        self._audio_queue.get_nowait()
                    except queue.Empty:
                        break
                    except Exception:
                        break

            self._chunk_count += 1
            if self._chunk_count % 200 == 1:
                audio_int16 = np.frombuffer(audio_bytes, dtype=np.int16)
                peak = (
                    float(np.max(np.abs(audio_int16.astype(np.int32)))) / 32767.0
                    if len(audio_int16)
                    else 0.0
                )
                print(f"[AUDIO] chunk {self._chunk_count}: peak {peak:.6f}, callbacks={len(self._callbacks)}")

            for callback in self._callbacks:
                try:
                    callback(audio_bytes)
                except Exception as e:
                    print(f"[AUDIO] Callback error: {e}")

        print("[AUDIO] Reader thread stopped")

    def start(self) -> bool:
        if self._capturing:
            return True

        try:
            ctx = multiprocessing.get_context("spawn")
            self._audio_queue = ctx.Queue(maxsize=32)
            self._stop_event = ctx.Event()

            self._capture_process = ctx.Process(
                target=_audio_capture_process,
                args=(
                    self.config.device_name_substring,
                    self.config.device_index,
                    self.config.sample_rate,
                    self.config.capture_channels,
                    self.config.chunk_frames,
                    self._audio_queue,
                    self._stop_event,
                ),
                daemon=True,
            )
            self._capture_process.start()

            time.sleep(0.15)
            if self._capture_process.exitcode is not None:
                print(f"[AUDIO] Capture process exited early (exitcode={self._capture_process.exitcode})")
                self.stop()
                return False

            self._capturing = True
            self._chunk_count = 0
            self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self._reader_thread.start()
            return True

        except Exception as e:
            print(f"[AUDIO] Failed to start capture: {e}")
            self._capturing = False
            return False

    def stop(self):
        self._capturing = False

        if self._stop_event:
            self._stop_event.set()

        if self._capture_process:
            self._capture_process.join(timeout=2.0)
            if self._capture_process.is_alive():
                self._capture_process.terminate()
            self._capture_process = None

        if self._reader_thread:
            self._reader_thread.join(timeout=2.0)
            self._reader_thread = None

        if self._audio_queue:
            self._audio_queue.close()
            self._audio_queue = None

        self._stop_event = None
        print("[AUDIO] Capture stopped")

    def is_capturing(self) -> bool:
        return self._capturing

    def record(self, duration: float, extra_time: float = 0.5) -> bytes | None:
        total_duration = duration + extra_time

        try:
            ctx = multiprocessing.get_context("spawn")
            result_queue = ctx.Queue()
            proc = ctx.Process(
                target=_audio_record_process,
                args=(
                    self.config.device_name_substring,
                    self.config.device_index,
                    total_duration,
                    self.config.sample_rate,
                    self.config.capture_channels,
                    result_queue,
                ),
            )
            proc.start()
            proc.join(timeout=total_duration + 10)

            if proc.is_alive():
                proc.terminate()
                return None

            return result_queue.get_nowait() if not result_queue.empty() else None

        except Exception as e:
            print(f"[AUDIO] Recording failed: {e}")
            return None


_audio_capture: AudioCapture | None = None


def get_audio_capture() -> AudioCapture:
    global _audio_capture
    if _audio_capture is None:
        _audio_capture = AudioCapture()
    return _audio_capture
