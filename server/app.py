"""FastAPI backend for Juno"""
import asyncio
import base64
import json
import os
import sys
import threading
from fractions import Fraction
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import numpy as np

try:
    from aiortc import (
        MediaStreamTrack,
        RTCPeerConnection,
        RTCSessionDescription,
        RTCIceCandidate,
        RTCConfiguration,
        RTCIceServer,
    )
    from aiortc.sdp import candidate_from_sdp
    import av
    AIORTC_AVAILABLE = True
    AIORTC_IMPORT_ERROR = ""
except Exception as e:
    MediaStreamTrack = None
    RTCPeerConnection = None
    RTCSessionDescription = None
    RTCIceCandidate = None
    RTCConfiguration = None
    RTCIceServer = None
    candidate_from_sdp = None
    av = None
    AIORTC_AVAILABLE = False
    AIORTC_IMPORT_ERROR = str(e)

from .models import Sample, Layer, SoundType, GenerateRequest, LayerEditRequest, AddLayerRequest, StartSessionRequest, GenerateLayerRequest, SelectPatchRequest, Patch, SaveToLibraryRequest, LibrarySample, LibraryListResponse, SaveToLibraryResponse
from .player import get_player
from .llm import generate_sample, edit_layer, add_layer, generate_single_layer, improve_layers
from .llm_providers import get_config, set_config, Provider, DEFAULT_MODELS, AVAILABLE_MODELS
from .audio import get_audio_capture
from .export import sample_to_midi_file
from .patches import get_patches, get_patch_by_id, get_categories, get_subcategories
from .logger import setup_logging, get_logger

# Set up logging
setup_logging("DEBUG")
log = get_logger("app")

# Store current sample in memory (would use DB in production)
current_sample: Sample | None = None
connected_clients: list[WebSocket] = []
rtc_peers: set = set()


def _parse_ice_servers(raw: str | None):
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        log.warning("Invalid JUNO_RTC_ICE_SERVERS JSON")
        return None
    if not isinstance(data, list):
        return None
    servers = []
    for item in data:
        if not isinstance(item, dict):
            continue
        urls = item.get("urls")
        if not urls:
            continue
        username = item.get("username")
        credential = item.get("credential")
        servers.append(RTCIceServer(urls=urls, username=username, credential=credential))
    return servers or None


if AIORTC_AVAILABLE:
    class JunoAudioTrack(MediaStreamTrack):
        """WebRTC audio track that streams audio from MONTAGE capture.
        
        Optimized for low-latency streaming with adaptive queue management.
        """
        kind = "audio"

        def __init__(self, audio_capture, loop: asyncio.AbstractEventLoop):
            super().__init__()
            self._audio = audio_capture
            self._loop = loop
            # Larger queue for burst handling, but we'll drop old frames aggressively
            self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=8)
            self._channels = max(1, int(self._audio.config.output_channels or 2))
            self._sample_rate = int(self._audio.config.sample_rate or 48000)
            self._timestamp = 0
            self._time_base = Fraction(1, self._sample_rate)
            self._callback = None
            self._dropped_frames = 0
            self._total_frames = 0

            def _enqueue(data: bytes):
                # Drop oldest frames if queue is getting full (keep latency bounded)
                while self._queue.qsize() >= 6:  # Keep ~2 frames of headroom
                    try:
                        self._queue.get_nowait()
                        self._dropped_frames += 1
                    except asyncio.QueueEmpty:
                        break
                try:
                    self._queue.put_nowait(data)
                    self._total_frames += 1
                except asyncio.QueueFull:
                    self._dropped_frames += 1

            def _callback(data: bytes):
                try:
                    self._loop.call_soon_threadsafe(_enqueue, data)
                except RuntimeError:
                    pass

            self._callback = _callback
            self._audio.add_callback(self._callback)

        async def recv(self):
            while True:
                try:
                    # Use timeout to detect stalls
                    data = await asyncio.wait_for(self._queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    # Return silence frame to keep connection alive
                    samples = self._sample_rate // 50  # 20ms of silence
                    # s16 packed format requires shape (1, samples * channels)
                    silence = np.zeros((1, samples * self._channels), dtype=np.int16)
                    layout = "stereo" if self._channels == 2 else "mono"
                    frame = av.AudioFrame.from_ndarray(silence, format="s16", layout=layout)
                    frame.sample_rate = self._sample_rate
                    frame.pts = self._timestamp
                    frame.time_base = self._time_base
                    self._timestamp += samples
                    return frame

                if not data:
                    continue
                    
                samples = len(data) // (2 * self._channels)
                if samples <= 0:
                    continue
                    
                # Audio comes in as interleaved int16: L0, R0, L1, R1, ...
                # s16 packed format expects shape (1, total_samples) where total = samples * channels
                audio = np.frombuffer(data, dtype=np.int16).reshape(1, -1)
                audio = np.ascontiguousarray(audio)

                layout = "stereo" if self._channels == 2 else "mono"
                # Use s16 (packed/interleaved) format - aiortc Opus encoder requires this
                frame = av.AudioFrame.from_ndarray(audio, format="s16", layout=layout)
                frame.sample_rate = self._sample_rate
                frame.pts = self._timestamp
                frame.time_base = self._time_base
                self._timestamp += samples

                # Log stats periodically
                if self._total_frames > 0 and self._total_frames % 500 == 0:
                    drop_rate = (self._dropped_frames / self._total_frames) * 100
                    if drop_rate > 1:
                        log.warning(f"[WebRTC] Frame drop rate: {drop_rate:.1f}% ({self._dropped_frames}/{self._total_frames})")

                return frame

        def stop(self):
            if self._callback:
                try:
                    self._audio.remove_callback(self._callback)
                except Exception:
                    pass
                self._callback = None
            super().stop()
else:
    JunoAudioTrack = None

# Track current patch selections per channel
current_patches: dict[str, Patch] = {}  # {"bass": Patch, "pad": Patch, "lead": Patch}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    log.info("=" * 50)
    log.info("JUNO SERVER STARTING")
    log.info("=" * 50)
    log.info(f"PID: {os.getpid()} Python: {sys.executable} ({sys.version.split()[0]})")

    try:
        import sounddevice as sd

        log.info(f"sounddevice: {sd.__version__}")
    except Exception as e:
        log.warning(f"sounddevice unavailable: {e}")

    player = get_player()
    if player.connect():
        log.info(f"MIDI connected: {player.port_name}")
    else:
        log.warning("MIDI not connected!")
        log.info(f"Available MIDI ports: {player.list_ports()}")

    audio = get_audio_capture()
    log.info(f"Available audio devices: {audio.list_devices()}")

    log.info("Server ready! Waiting for connections...")
    log.info("=" * 50)

    yield

    log.info("Shutting down...")
    player.disconnect()
    get_audio_capture().stop()


app = FastAPI(title="Juno", lifespan=lifespan)

# CORS - allow frontend origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "https://juno-wheat.vercel.app",
        "https://*.vercel.app",
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",  # Allow all Vercel preview deployments
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def broadcast(message: dict):
    """Send message to all connected WebSocket clients"""
    if connected_clients:
        log.debug(f"Broadcasting to {len(connected_clients)} clients: {message.get('type')}")
    for client in connected_clients:
        try:
            await client.send_json(message)
        except Exception:
            pass


# --- REST Endpoints ---

@app.get("/api/health")
async def health():
    """Health check"""
    player = get_player()
    log.debug("Health check requested")
    return {
        "status": "ok",
        "midi_connected": player.is_connected(),
        "midi_ports": player.list_ports(),
        "audio_device": get_audio_capture().config.alsa_device
    }


class LLMConfigRequest(BaseModel):
    provider: str | None = None  # "anthropic" or "openai"
    model: str | None = None


@app.get("/api/llm/config")
async def get_llm_config():
    """Get current LLM configuration"""
    cfg = get_config()
    return {
        "provider": cfg.provider.value,
        "model": cfg.get_model(),
        "available_providers": [p.value for p in Provider],
        "available_models": {p.value: models for p, models in AVAILABLE_MODELS.items()},
        "default_models": {p.value: m for p, m in DEFAULT_MODELS.items()}
    }


@app.post("/api/llm/config")
async def update_llm_config(request: LLMConfigRequest):
    """Update LLM configuration"""
    log.info(f"Updating LLM config: provider={request.provider}, model={request.model}")
    try:
        cfg = set_config(provider=request.provider, model=request.model)
        return {
            "provider": cfg.provider.value,
            "model": cfg.get_model()
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/sample")
async def get_sample():
    """Get current sample"""
    global current_sample
    log.debug(f"Get sample: {'exists' if current_sample else 'none'}")
    if current_sample is None:
        return {"sample": None}
    return {"sample": current_sample.model_dump()}


@app.post("/api/generate")
async def api_generate(request: GenerateRequest):
    """Generate a new sample from prompt"""
    global current_sample

    log.info(f"Generating sample from prompt: '{request.prompt[:50]}...'")
    log.info(f"  BPM: {request.bpm or 'auto'}, Bars: {request.bars or 'auto'}")

    try:
        sample = generate_sample(request.prompt, request.bpm, request.bars)
        current_sample = sample

        log.info(f"Sample generated: '{sample.name}'")
        log.info(f"  {len(sample.layers)} layers, {sample.bpm} BPM, {sample.bars} bars")
        for layer in sample.layers:
            log.info(f"  - {layer.sound.value}: '{layer.name}' ({len(layer.notes)} notes)")

        await broadcast({"type": "sample_updated", "sample": sample.model_dump()})
        return {"sample": sample.model_dump()}
    except Exception as e:
        log.error(f"Generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/play")
async def api_play(layers: list[str] | None = None):
    """Play current sample (or specific layers)"""
    global current_sample

    if current_sample is None:
        log.warning("Play requested but no sample loaded")
        raise HTTPException(status_code=400, detail="No sample loaded")

    player = get_player()
    if not player.is_connected():
        log.error("Play requested but MIDI not connected")
        raise HTTPException(status_code=500, detail="MIDI not connected")

    # If specific layers requested, create a filtered sample
    if layers:
        log.info(f"Playing layers: {layers}")
        filtered_layers = [l for l in current_sample.layers if l.sound.value in layers]
        play_sample = Sample(
            id=current_sample.id,
            name=current_sample.name,
            bpm=current_sample.bpm,
            bars=current_sample.bars,
            layers=filtered_layers
        )
    else:
        log.info("Playing all layers")
        play_sample = current_sample

    log.info(f"  Duration: {play_sample.duration_seconds:.1f}s")

    # Start audio capture for streaming
    audio = get_audio_capture()
    if not audio.is_capturing():
        if audio.start():
            log.info("Audio capture started for playback")
        else:
            log.warning("Audio capture failed to start - streaming won't work")

    # Capture the running event loop from this async context
    loop = asyncio.get_running_loop()

    def on_complete():
        log.info("Playback complete")
        # Stop audio capture when playback ends
        audio.stop()
        log.info("Audio capture stopped")
        # Schedule broadcast on the captured event loop (called from thread)
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(broadcast({"type": "playback_complete"}))
        )

    player.play(play_sample, on_complete=on_complete)
    await broadcast({"type": "playback_started", "duration": play_sample.duration_seconds})
    return {"status": "playing", "duration": play_sample.duration_seconds}


@app.post("/api/stop")
async def api_stop():
    """Stop playback"""
    log.info("Stopping playback")
    player = get_player()
    player.stop()
    # Stop audio capture
    audio = get_audio_capture()
    if audio.is_capturing():
        audio.stop()
        log.info("Audio capture stopped")
    await broadcast({"type": "playback_stopped"})
    return {"status": "stopped"}


@app.post("/api/layer/{layer_id}/edit")
async def api_edit_layer(layer_id: str, request: LayerEditRequest):
    """Edit a specific layer"""
    global current_sample

    if current_sample is None:
        raise HTTPException(status_code=400, detail="No sample loaded")

    log.info(f"Editing layer {layer_id}: '{request.prompt[:50]}...'")

    try:
        updated = edit_layer(current_sample, layer_id, request.prompt)
        current_sample = updated
        log.info(f"Layer updated successfully")
        await broadcast({"type": "sample_updated", "sample": updated.model_dump()})
        return {"sample": updated.model_dump()}
    except Exception as e:
        log.error(f"Layer edit failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/layer/{layer_id}/delete")
async def api_delete_layer(layer_id: str):
    """Delete a layer"""
    global current_sample

    if current_sample is None:
        raise HTTPException(status_code=400, detail="No sample loaded")

    log.info(f"Deleting layer {layer_id}")

    new_layers = [l for l in current_sample.layers if l.id != layer_id]
    current_sample = Sample(
        id=current_sample.id,
        name=current_sample.name,
        bpm=current_sample.bpm,
        bars=current_sample.bars,
        layers=new_layers
    )

    await broadcast({"type": "sample_updated", "sample": current_sample.model_dump()})
    return {"sample": current_sample.model_dump()}


@app.post("/api/layer/add")
async def api_add_layer(request: AddLayerRequest):
    """Add a new layer"""
    global current_sample

    if current_sample is None:
        raise HTTPException(status_code=400, detail="No sample loaded")

    log.info(f"Adding {request.sound} layer: '{request.prompt[:50]}...'")

    try:
        updated = add_layer(current_sample, request.prompt, request.sound)
        current_sample = updated
        log.info(f"Layer added successfully")
        await broadcast({"type": "sample_updated", "sample": updated.model_dump()})
        return {"sample": updated.model_dump()}
    except Exception as e:
        log.error(f"Add layer failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/layer/{layer_id}/mute")
async def api_mute_layer(layer_id: str, muted: bool = True):
    """Mute/unmute a layer"""
    global current_sample

    if current_sample is None:
        raise HTTPException(status_code=400, detail="No sample loaded")

    log.info(f"{'Muting' if muted else 'Unmuting'} layer {layer_id}")

    new_layers = []
    for layer in current_sample.layers:
        if layer.id == layer_id:
            new_layers.append(Layer(
                id=layer.id,
                name=layer.name,
                sound=layer.sound,
                notes=layer.notes,
                muted=muted,
                volume=layer.volume
            ))
        else:
            new_layers.append(layer)

    current_sample = Sample(
        id=current_sample.id,
        name=current_sample.name,
        bpm=current_sample.bpm,
        bars=current_sample.bars,
        layers=new_layers
    )

    await broadcast({"type": "sample_updated", "sample": current_sample.model_dump()})
    return {"sample": current_sample.model_dump()}


@app.get("/api/export")
async def api_export():
    """Export sample as MIDI file"""
    global current_sample

    if current_sample is None:
        raise HTTPException(status_code=400, detail="No sample loaded")

    log.info(f"Exporting sample as MIDI: '{current_sample.name}'")

    midi_bytes = sample_to_midi_file(current_sample)
    b64 = base64.b64encode(midi_bytes).decode()

    filename = f"{current_sample.name.replace(' ', '_')}.mid"
    log.info(f"  File: {filename} ({len(midi_bytes)} bytes)")

    return {
        "filename": filename,
        "data": b64
    }


@app.get("/api/export/audio")
async def api_export_audio():
    """Export sample as WAV audio file (records from Montage while playing)"""
    global current_sample
    import threading
    import time

    if current_sample is None:
        raise HTTPException(status_code=400, detail="No sample loaded")

    player = get_player()
    if not player.is_connected():
        raise HTTPException(status_code=500, detail="MIDI not connected")

    audio = get_audio_capture()
    duration = current_sample.duration_seconds

    log.info(f"Exporting sample as audio: '{current_sample.name}' ({duration:.1f}s)")

    # We need to start playback and recording almost simultaneously
    # Use a thread to handle MIDI playback while we record
    playback_started = threading.Event()

    def play_and_signal():
        playback_started.set()
        player.play_sync(current_sample)

    # Start playback thread
    play_thread = threading.Thread(target=play_and_signal, daemon=True)
    play_thread.start()

    # Wait for playback to start, then record
    playback_started.wait(timeout=1.0)
    time.sleep(0.05)  # Small delay to ensure MIDI notes are sent

    # Record audio (blocking)
    wav_bytes = audio.record(duration, extra_time=1.0)

    if wav_bytes is None:
        raise HTTPException(status_code=500, detail="Audio recording failed. Check if Montage audio is connected.")

    # Wait for playback thread to finish
    play_thread.join(timeout=duration + 2.0)

    b64 = base64.b64encode(wav_bytes).decode()
    filename = f"{current_sample.name.replace(' ', '_')}.wav"
    log.info(f"  Audio file: {filename} ({len(wav_bytes)} bytes)")

    return {
        "filename": filename,
        "data": b64
    }


# --- Library endpoints ---

@app.post("/api/library/save", response_model=SaveToLibraryResponse)
async def api_library_save(request: SaveToLibraryRequest):
    """Save current sample to library (exports audio and uploads to Supabase)"""
    global current_sample
    import uuid
    import threading
    import time

    if current_sample is None:
        raise HTTPException(status_code=400, detail="No sample loaded")

    player = get_player()
    if not player.is_connected():
        raise HTTPException(status_code=500, detail="MIDI not connected")

    # Import supabase helpers
    try:
        from .supabase import upload_audio, save_sample_metadata
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    audio = get_audio_capture()
    duration = current_sample.duration_seconds
    sample_id = str(uuid.uuid4())

    log.info(f"Saving to library: '{current_sample.name}' ({duration:.1f}s)")

    # Record audio (same logic as export)
    playback_started = threading.Event()

    def play_and_signal():
        playback_started.set()
        player.play_sync(current_sample)

    play_thread = threading.Thread(target=play_and_signal, daemon=True)
    play_thread.start()

    playback_started.wait(timeout=1.0)
    time.sleep(0.05)

    wav_bytes = audio.record(duration, extra_time=1.0)

    if wav_bytes is None:
        raise HTTPException(status_code=500, detail="Audio recording failed")

    play_thread.join(timeout=duration + 2.0)

    # Upload to Supabase Storage
    try:
        audio_url = upload_audio(request.device_id, sample_id, wav_bytes)
    except Exception as e:
        log.error(f"Failed to upload audio: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload audio: {e}")

    # Save metadata to database
    layers_json = [
        {"sound": layer.sound.value, "name": layer.name, "patch_name": layer.patch_name}
        for layer in current_sample.layers
    ]

    metadata = {
        "id": sample_id,
        "device_id": request.device_id,
        "name": current_sample.name,
        "prompt": current_sample.prompt,
        "key": current_sample.key,
        "bpm": current_sample.bpm,
        "bars": current_sample.bars,
        "duration_seconds": current_sample.duration_seconds,
        "audio_url": audio_url,
        "layers_json": layers_json,
    }

    try:
        result = save_sample_metadata(metadata)
        log.info(f"Saved to library: {sample_id}")
    except Exception as e:
        log.error(f"Failed to save metadata: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save metadata: {e}")

    return SaveToLibraryResponse(
        id=result["id"],
        audio_url=result["audio_url"],
        created_at=result["created_at"]
    )


@app.get("/api/library", response_model=LibraryListResponse)
async def api_library_list(device_id: str, limit: int = 20, offset: int = 0):
    """List samples in library for a device"""
    try:
        from .supabase import get_samples
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    try:
        samples_data, total = get_samples(device_id, limit, offset)
    except Exception as e:
        log.error(f"Failed to fetch library: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch library: {e}")

    samples = [
        LibrarySample(
            id=s["id"],
            name=s["name"],
            prompt=s.get("prompt"),
            key=s.get("key"),
            bpm=s.get("bpm"),
            bars=s.get("bars"),
            duration_seconds=s.get("duration_seconds"),
            audio_url=s["audio_url"],
            layers=s.get("layers_json"),
            created_at=s["created_at"]
        )
        for s in samples_data
    ]

    return LibraryListResponse(samples=samples, total=total)


@app.delete("/api/library/{sample_id}")
async def api_library_delete(sample_id: str, device_id: str):
    """Delete a sample from library"""
    try:
        from .supabase import delete_sample
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    try:
        success = delete_sample(sample_id, device_id)
    except Exception as e:
        log.error(f"Failed to delete sample: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete: {e}")

    if not success:
        raise HTTPException(status_code=404, detail="Sample not found or not owned by you")

    log.info(f"Deleted from library: {sample_id}")
    return {"success": True}


# --- Step-by-step generation endpoints ---

@app.post("/api/session/start")
async def api_start_session(request: StartSessionRequest):
    """Start a new step-by-step session with initial settings"""
    global current_sample
    import uuid

    log.info(f"Starting new session: '{request.prompt[:50]}...'")
    log.info(f"  Key: {request.key}, BPM: {request.bpm}, Bars: {request.bars}")

    # Create empty sample with settings
    current_sample = Sample(
        id=str(uuid.uuid4())[:8],
        name="New Sample",
        prompt=request.prompt,
        key=request.key,
        bpm=request.bpm,
        bars=request.bars,
        layers=[]
    )

    await broadcast({"type": "sample_updated", "sample": current_sample.model_dump()})
    return {"sample": current_sample.model_dump()}


@app.post("/api/session/generate-layer")
async def api_generate_layer(request: GenerateLayerRequest):
    """Generate a single layer for the current session"""
    global current_sample

    if current_sample is None:
        raise HTTPException(status_code=400, detail="No session started. Call /api/session/start first")

    log.info(f"Generating {request.sound.value} layer...")

    try:
        layer = generate_single_layer(
            sound_type=request.sound,
            prompt=current_sample.prompt,
            key=current_sample.key,
            bpm=current_sample.bpm,
            bars=current_sample.bars,
            existing_layers=current_sample.layers if current_sample.layers else None
        )

        # Add or replace layer of this sound type
        new_layers = [l for l in current_sample.layers if l.sound != request.sound]
        new_layers.append(layer)

        # Sort layers: pad, lead, bass (logical order)
        order = {SoundType.PAD: 0, SoundType.LEAD: 1, SoundType.BASS: 2}
        new_layers.sort(key=lambda l: order.get(l.sound, 99))

        current_sample = Sample(
            id=current_sample.id,
            name=current_sample.name,
            prompt=current_sample.prompt,
            key=current_sample.key,
            bpm=current_sample.bpm,
            bars=current_sample.bars,
            layers=new_layers
        )

        log.info(f"Layer added: {request.sound.value} - '{layer.name}'")
        await broadcast({"type": "sample_updated", "sample": current_sample.model_dump()})
        return {"sample": current_sample.model_dump(), "layer": layer.model_dump()}

    except Exception as e:
        log.error(f"Layer generation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/session/regenerate-layer")
async def api_regenerate_layer(request: GenerateLayerRequest):
    """Regenerate a layer (delete and create new)"""
    return await api_generate_layer(request)


class ImproveRequest(BaseModel):
    feedback: dict[str, str]  # {"pad": "make it more dramatic", "lead": "...", "bass": "..."}


@app.post("/api/session/improve")
async def api_improve_layers(request: ImproveRequest):
    """Improve layers based on user feedback"""
    global current_sample

    if current_sample is None:
        raise HTTPException(status_code=400, detail="No session started")

    if not current_sample.layers:
        raise HTTPException(status_code=400, detail="No layers to improve")

    # Check if any feedback was provided
    has_feedback = any(f.strip() for f in request.feedback.values())
    if not has_feedback:
        raise HTTPException(status_code=400, detail="No feedback provided")

    log.info(f"Improving layers with feedback: {request.feedback}")

    try:
        updated_sample = improve_layers(current_sample, request.feedback)
        current_sample = updated_sample

        log.info(f"Layers improved successfully")
        await broadcast({"type": "sample_updated", "sample": current_sample.model_dump()})
        return {"sample": current_sample.model_dump()}

    except Exception as e:
        log.error(f"Layer improvement failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# --- Patch/Sound Selection Endpoints ---

@app.get("/api/patches")
async def api_get_patches(
    category: str | None = None,
    sub_category: str | None = None,
    search: str | None = None,
    sound_type: str | None = None,
    all_sounds: bool = False,
    limit: int = 50,
    offset: int = 0
):
    """Get available patches with optional filtering"""
    log.debug(f"Get patches: category={category}, search={search}, sound_type={sound_type}, all_sounds={all_sounds}")

    # Convert sound_type string to enum if provided
    sound_type_enum = None
    if sound_type:
        try:
            sound_type_enum = SoundType(sound_type)
        except ValueError:
            pass

    patches, total = get_patches(
        category=category,
        sub_category=sub_category,
        search=search,
        sound_type=sound_type_enum,
        all_sounds=all_sounds,
        limit=limit,
        offset=offset
    )

    categories = get_categories()
    subcategories = get_subcategories(category=category)

    return {
        "patches": [p.model_dump() for p in patches],
        "total": total,
        "categories": [c.model_dump() for c in categories],
        "subcategories": subcategories
    }


@app.get("/api/patches/categories")
async def api_get_patch_categories():
    """Get all patch categories with counts"""
    categories = get_categories()
    return {"categories": [c.model_dump() for c in categories]}


@app.post("/api/sound/{channel}/select")
async def api_select_sound(channel: str, request: SelectPatchRequest):
    """Select a patch for a channel (bass, pad, lead)"""
    global current_patches, current_sample

    # Validate channel
    try:
        sound_type = SoundType(channel)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid channel: {channel}. Must be bass, pad, or lead")

    # Get the patch
    patch = get_patch_by_id(request.patch_id)
    if not patch:
        raise HTTPException(status_code=404, detail=f"Patch not found: {request.patch_id}")

    log.info(f"Selecting {channel} patch: {patch.name} (id={patch.id})")

    # Send MIDI program change
    player = get_player()
    if player.is_connected():
        player.select_patch(sound_type, patch)

    # Store current selection
    current_patches[channel] = patch

    # Update current sample's layer if it exists
    if current_sample:
        new_layers = []
        for layer in current_sample.layers:
            if layer.sound == sound_type:
                # Update this layer with the new patch
                new_layers.append(Layer(
                    id=layer.id,
                    name=layer.name,
                    sound=layer.sound,
                    notes=layer.notes,
                    muted=layer.muted,
                    volume=layer.volume,
                    portamento=layer.portamento,
                    portamento_time=layer.portamento_time,
                    patch_id=patch.id,
                    patch_name=patch.name
                ))
            else:
                new_layers.append(layer)

        current_sample = Sample(
            id=current_sample.id,
            name=current_sample.name,
            prompt=current_sample.prompt,
            key=current_sample.key,
            bpm=current_sample.bpm,
            bars=current_sample.bars,
            layers=new_layers
        )
        await broadcast({"type": "sample_updated", "sample": current_sample.model_dump()})

    await broadcast({"type": "patch_selected", "channel": channel, "patch": patch.model_dump()})
    return {"patch": patch.model_dump()}


@app.post("/api/sound/{channel}/preview")
async def api_preview_sound(channel: str, request: SelectPatchRequest):
    """Preview a patch by sending program change and playing a test note"""
    # Validate channel
    try:
        sound_type = SoundType(channel)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid channel: {channel}. Must be bass, pad, or lead")

    # Get the patch
    patch = get_patch_by_id(request.patch_id)
    if not patch:
        raise HTTPException(status_code=404, detail=f"Patch not found: {request.patch_id}")

    log.info(f"Previewing {channel} patch: {patch.name}")

    player = get_player()
    if not player.is_connected():
        raise HTTPException(status_code=500, detail="MIDI not connected")

    # Preview runs synchronously and plays test notes
    player.preview_patch(sound_type, patch)

    return {"status": "previewed", "patch": patch.model_dump()}


@app.get("/api/sounds/current")
async def api_get_current_sounds():
    """Get currently selected sounds for all channels"""
    global current_patches

    return {
        "bass": current_patches.get("bass").model_dump() if current_patches.get("bass") else None,
        "pad": current_patches.get("pad").model_dump() if current_patches.get("pad") else None,
        "lead": current_patches.get("lead").model_dump() if current_patches.get("lead") else None
    }


# --- WebSocket for real-time communication ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time updates"""
    await websocket.accept()
    connected_clients.append(websocket)
    log.info(f"WebSocket client connected ({len(connected_clients)} total)")

    try:
        # Send current state
        if current_sample:
            await websocket.send_json({
                "type": "sample_updated",
                "sample": current_sample.model_dump()
            })

        # Handle incoming messages
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            log.debug(f"WebSocket message: {msg_type}")

            if msg_type == "play":
                layers = data.get("layers")  # Optional: specific layers to play
                await api_play(layers)

            elif msg_type == "stop":
                await api_stop()

            elif msg_type == "generate":
                prompt = data.get("prompt", "")
                bpm = data.get("bpm")
                bars = data.get("bars")
                await api_generate(GenerateRequest(prompt=prompt, bpm=bpm, bars=bars))

    except WebSocketDisconnect:
        connected_clients.remove(websocket)
        log.info(f"WebSocket client disconnected ({len(connected_clients)} remaining)")
        # Stop playback and silence all notes when client disconnects
        player = get_player()
        player.stop()
    except Exception as e:
        log.error(f"WebSocket error: {e}")
        if websocket in connected_clients:
            connected_clients.remove(websocket)
        # Also stop on error
        player = get_player()
        player.stop()


# --- WebSocket for audio streaming ---

@app.websocket("/ws/audio")
async def audio_websocket(websocket: WebSocket):
    """WebSocket for streaming audio from M8X"""
    await websocket.accept()
    log.info("Audio WebSocket client connected")

    audio = get_audio_capture()
    loop = asyncio.get_running_loop()
    audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=8)
    throttle_event = threading.Event()
    client_buffer_ms: float = 0.0
    recv_task: asyncio.Task | None = None

    # When client buffer grows too large, stop sending to avoid runaway latency.
    # The worklet continues consuming buffered audio, reducing latency until we resume.
    low_water_ms = 80.0
    high_water_ms = 160.0

    def _enqueue_audio(data: bytes):
        if throttle_event.is_set():
            return

        if audio_queue.full():
            # Prefer dropping oldest audio to keep latency bounded.
            try:
                audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                return

        try:
            audio_queue.put_nowait(data)
        except asyncio.QueueFull:
            pass

    def audio_callback(data: bytes):
        try:
            loop.call_soon_threadsafe(_enqueue_audio, data)
        except RuntimeError:
            # Event loop may be closed during shutdown.
            pass

    audio.add_callback(audio_callback)

    if not audio.is_capturing():
        if audio.start():
            log.info("Audio capture started")
        else:
            log.warning("Failed to start audio capture")

    try:
        # Send audio config (output channels, not capture channels)
        await websocket.send_json({
            "type": "audio_config",
            "sample_rate": audio.config.sample_rate,
            "channels": audio.config.output_channels,
            "chunk_frames": audio.config.chunk_frames,
            "bytes_per_sample": 2,
            "sample_format": "s16le",
            "interleaved": True,
            "stream_version": 1,
        })

        async def receive_control():
            nonlocal client_buffer_ms, low_water_ms, high_water_ms
            try:
                while True:
                    msg = await websocket.receive_json()
                    if not isinstance(msg, dict):
                        continue
                    if msg.get("type") != "buffer_status":
                        continue

                    try:
                        client_buffer_ms = float(msg.get("buffer_ms", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        continue

                    try:
                        target_ms = float(msg.get("target_ms", 0.0) or 0.0)
                    except (TypeError, ValueError):
                        target_ms = 0.0

                    # Track client-provided target to favor smooth playback while keeping bounded latency.
                    if target_ms > 0:
                        low_water_ms = max(40.0, target_ms - 15.0)
                        high_water_ms = max(low_water_ms + 40.0, target_ms + 50.0)

                    if client_buffer_ms > high_water_ms:
                        throttle_event.set()
                    elif client_buffer_ms < low_water_ms:
                        throttle_event.clear()
            except WebSocketDisconnect:
                pass
            except Exception:
                pass

        recv_task = asyncio.create_task(receive_control())

        while True:
            # Get audio data and send
            data = await audio_queue.get()
            if throttle_event.is_set():
                continue
            try:
                await websocket.send_bytes(data)
            except Exception:
                # WebSocket closed or error - exit send loop gracefully
                break

    except WebSocketDisconnect:
        log.info("Audio WebSocket client disconnected")
    finally:
        if recv_task is not None:
            try:
                recv_task.cancel()
                await recv_task
            except Exception:
                pass
        audio.remove_callback(audio_callback)


@app.websocket("/ws/rtc")
async def rtc_websocket(websocket: WebSocket):
    """WebRTC signaling endpoint for audio streaming."""
    await websocket.accept()

    if not AIORTC_AVAILABLE:
        await websocket.send_json({"type": "error", "reason": f"aiortc unavailable: {AIORTC_IMPORT_ERROR}"})
        await websocket.close()
        return

    if os.getenv("JUNO_RTC_ENABLED", "1").strip() not in ("1", "true", "True"):
        await websocket.send_json({"type": "error", "reason": "WebRTC disabled on server"})
        await websocket.close()
        return

    ice_servers = _parse_ice_servers(os.getenv("JUNO_RTC_ICE_SERVERS"))
    config = RTCConfiguration(iceServers=ice_servers) if ice_servers else None
    pc = RTCPeerConnection(configuration=config) if config else RTCPeerConnection()
    rtc_peers.add(pc)
    audio = get_audio_capture()
    loop = asyncio.get_running_loop()
    track = JunoAudioTrack(audio, loop)

    if not audio.is_capturing():
        if audio.start():
            log.info("Audio capture started for WebRTC")
        else:
            log.warning("Failed to start audio capture for WebRTC")

    pc.addTrack(track)

    @pc.on("icecandidate")
    async def on_icecandidate(candidate):
        if candidate is None:
            return
        try:
            await websocket.send_json({
                "type": "candidate",
                "candidate": candidate.to_sdp(),
                "sdpMid": candidate.sdpMid,
                "sdpMLineIndex": candidate.sdpMLineIndex,
            })
        except Exception:
            pass

    try:
        while True:
            msg = await websocket.receive_json()
            if not isinstance(msg, dict):
                continue

            msg_type = msg.get("type")
            if msg_type == "offer":
                sdp = msg.get("sdp")
                if not sdp:
                    continue
                offer = RTCSessionDescription(sdp=sdp, type="offer")
                await pc.setRemoteDescription(offer)
                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)
                await websocket.send_json({
                    "type": "answer",
                    "sdp": pc.localDescription.sdp,
                })
            elif msg_type == "candidate":
                candidate_sdp = msg.get("candidate")
                if not candidate_sdp:
                    continue
                try:
                    candidate = candidate_from_sdp(candidate_sdp)
                    candidate.sdpMid = msg.get("sdpMid")
                    candidate.sdpMLineIndex = msg.get("sdpMLineIndex")
                    await pc.addIceCandidate(candidate)
                except Exception as e:
                    log.warning(f"WebRTC ICE candidate error: {e}")
            elif msg_type == "close":
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning(f"WebRTC signaling error: {e}")
    finally:
        try:
            await pc.close()
        except Exception:
            pass
        rtc_peers.discard(pc)
        try:
            track.stop()
        except Exception:
            pass
