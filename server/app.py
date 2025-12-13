"""FastAPI backend for Juno"""
import asyncio
import json
import base64
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import mido

from .models import Sample, Layer, SoundType, GenerateRequest, LayerEditRequest, AddLayerRequest
from .player import get_player, SamplePlayer
from .llm import generate_sample, edit_layer, add_layer
from .audio import get_audio_capture
from .export import sample_to_midi_file


# Store current sample in memory (would use DB in production)
current_sample: Sample | None = None
connected_clients: list[WebSocket] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    player = get_player()
    if player.connect():
        print("Connected to MIDI port")
    else:
        print("Warning: Could not connect to MIDI port")
        print("Available ports:", player.list_ports())

    yield

    player.disconnect()
    get_audio_capture().stop()


app = FastAPI(title="Juno", lifespan=lifespan)

# CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def broadcast(message: dict):
    """Send message to all connected WebSocket clients"""
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
    return {
        "status": "ok",
        "midi_connected": player.is_connected(),
        "midi_ports": player.list_ports(),
        "audio_devices": get_audio_capture().list_devices()
    }


@app.get("/api/sample")
async def get_sample():
    """Get current sample"""
    global current_sample
    if current_sample is None:
        return {"sample": None}
    return {"sample": current_sample.model_dump()}


@app.post("/api/generate")
async def api_generate(request: GenerateRequest):
    """Generate a new sample from prompt"""
    global current_sample

    try:
        sample = generate_sample(request.prompt, request.bpm, request.bars)
        current_sample = sample
        await broadcast({"type": "sample_updated", "sample": sample.model_dump()})
        return {"sample": sample.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/play")
async def api_play(layers: list[str] | None = None):
    """Play current sample (or specific layers)"""
    global current_sample

    if current_sample is None:
        raise HTTPException(status_code=400, detail="No sample loaded")

    player = get_player()
    if not player.is_connected():
        raise HTTPException(status_code=500, detail="MIDI not connected")

    # If specific layers requested, create a filtered sample
    if layers:
        filtered_layers = [l for l in current_sample.layers if l.sound.value in layers]
        play_sample = Sample(
            id=current_sample.id,
            name=current_sample.name,
            bpm=current_sample.bpm,
            bars=current_sample.bars,
            layers=filtered_layers
        )
    else:
        play_sample = current_sample

    def on_complete():
        asyncio.create_task(broadcast({"type": "playback_complete"}))

    player.play(play_sample, on_complete=on_complete)
    await broadcast({"type": "playback_started", "duration": play_sample.duration_seconds})
    return {"status": "playing", "duration": play_sample.duration_seconds}


@app.post("/api/stop")
async def api_stop():
    """Stop playback"""
    player = get_player()
    player.stop()
    await broadcast({"type": "playback_stopped"})
    return {"status": "stopped"}


@app.post("/api/layer/{layer_id}/edit")
async def api_edit_layer(layer_id: str, request: LayerEditRequest):
    """Edit a specific layer"""
    global current_sample

    if current_sample is None:
        raise HTTPException(status_code=400, detail="No sample loaded")

    try:
        updated = edit_layer(current_sample, layer_id, request.prompt)
        current_sample = updated
        await broadcast({"type": "sample_updated", "sample": updated.model_dump()})
        return {"sample": updated.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/layer/{layer_id}/delete")
async def api_delete_layer(layer_id: str):
    """Delete a layer"""
    global current_sample

    if current_sample is None:
        raise HTTPException(status_code=400, detail="No sample loaded")

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

    try:
        updated = add_layer(current_sample, request.prompt, request.sound)
        current_sample = updated
        await broadcast({"type": "sample_updated", "sample": updated.model_dump()})
        return {"sample": updated.model_dump()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/layer/{layer_id}/mute")
async def api_mute_layer(layer_id: str, muted: bool = True):
    """Mute/unmute a layer"""
    global current_sample

    if current_sample is None:
        raise HTTPException(status_code=400, detail="No sample loaded")

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

    midi_bytes = sample_to_midi_file(current_sample)
    b64 = base64.b64encode(midi_bytes).decode()

    return {
        "filename": f"{current_sample.name.replace(' ', '_')}.mid",
        "data": b64
    }


# --- WebSocket for real-time communication ---

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for real-time updates"""
    await websocket.accept()
    connected_clients.append(websocket)

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
    except Exception as e:
        print(f"WebSocket error: {e}")
        if websocket in connected_clients:
            connected_clients.remove(websocket)


# --- WebSocket for audio streaming ---

@app.websocket("/ws/audio")
async def audio_websocket(websocket: WebSocket):
    """WebSocket for streaming audio from M8X"""
    await websocket.accept()

    audio = get_audio_capture()
    audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)

    def audio_callback(data: bytes):
        try:
            audio_queue.put_nowait(data)
        except asyncio.QueueFull:
            pass  # Drop frames if client is slow

    audio.add_callback(audio_callback)

    if not audio.is_capturing():
        audio.start()

    try:
        # Send audio config
        await websocket.send_json({
            "type": "audio_config",
            "sample_rate": audio.config.sample_rate,
            "channels": audio.config.channels
        })

        while True:
            # Get audio data and send
            data = await audio_queue.get()
            await websocket.send_bytes(data)

    except WebSocketDisconnect:
        pass
    finally:
        audio.remove_callback(audio_callback)
