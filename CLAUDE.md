# CLAUDE.md - Juno Project Guide

## Project Overview

Juno is a web-based AI-powered music composer for the Yamaha MONTAGE M8x synthesizer. It generates layered MIDI compositions from text prompts using LLMs (Claude/OpenAI), plays them on the synth via MIDI, and streams the synth's audio back to the browser in real time.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    BROWSER (Frontend)                        │
│  React 19 + TypeScript + Vite                               │
│  - Step-by-step UI for prompt → music flow                  │
│  - WebSocket/WebRTC for real-time audio streaming           │
│  - AudioWorklet for PCM playback                            │
└─────────────────────┬───────────────────────────────────────┘
                      │ REST API + WebSocket
┌─────────────────────▼───────────────────────────────────────┐
│              FASTAPI BACKEND (Python)                        │
│  - LLM integration for music generation                      │
│  - MIDI playback engine (mido + python-rtmidi)              │
│  - Audio capture & streaming (sounddevice)                  │
└─────────────────────┬───────────────────────────────────────┘
                      │ MIDI + USB Audio
┌─────────────────────▼───────────────────────────────────────┐
│        YAMAHA MONTAGE M8x (Hardware Synthesizer)            │
│  - Receives MIDI on 3 channels (bass/pad/lead)             │
│  - Outputs stereo audio via USB                            │
└─────────────────────────────────────────────────────────────┘
```

## Key Files

| File | Purpose |
|------|---------|
| `server/app.py` | FastAPI server with all REST endpoints and WebSocket handlers |
| `server/player.py` | MIDI playback engine - sends notes to synthesizer |
| `server/audio.py` | Audio capture from synth USB and streaming |
| `server/llm.py` | LLM integration for music generation |
| `server/models.py` | Pydantic data models (Sample, Layer, Note, Patch) |
| `server/patches.py` | Patch database (3,487 MONTAGE M presets) |
| `server/data/patches.json` | All synth presets with bank/program numbers |
| `server/prompts/system/*.txt` | AI system prompts for each layer type |
| `web/src/App.tsx` | Main React UI component |
| `web/src/hooks/useAudioStream.ts` | Real-time audio streaming hook |
| `web/public/audio-processor.js` | AudioWorklet processor for PCM playback |

## Development Commands

```bash
# Start dev mode (auto-reload backend + frontend HMR)
./dev.sh

# Or manually:
# Terminal 1: Backend
uvicorn server.app:app --reload --host 0.0.0.0 --port 8000

# Terminal 2: Frontend
cd web && npm run dev
```

## Key API Endpoints

- `POST /api/session/start` - Create new session with initial settings
- `POST /api/session/generate-layer` - Generate a layer (pad/lead/bass)
- `POST /api/play` - Start MIDI playback
- `POST /api/stop` - Stop playback
- `POST /api/export/audio` - Export sample as WAV
- `GET /api/patches` - Get filtered patch list
- `POST /api/sound/{channel}/select` - Select patch for a channel
- `WS /ws/audio` - Real-time audio streaming (WebSocket)
- `WS /ws/rtc` - WebRTC signaling for audio

## Audio Flow

1. **Capture**: `sounddevice` captures USB audio from MONTAGE (44.1kHz, stereo)
2. **Transport**: PCM bytes sent via WebSocket or WebRTC
3. **Playback**: Browser's AudioWorklet decodes Int16LE → Float32 and plays

---

# Known Issues with Audio Playback and Recording

## CRITICAL: Export Timing Race Condition

**Location**: `server/app.py:552-554`

```python
def play_and_signal():
    playback_started.set()  # BUG: Signals BEFORE playback starts!
    player.play_sync(current_sample)
```

**Problem**: The `playback_started` event is signaled BEFORE MIDI playback actually begins. This causes:
- Recording may start before any MIDI notes are sent
- First notes can be clipped or missing from the recording
- The 50ms fixed delay (line 562) is a band-aid that doesn't reliably fix the timing

**Fix Required**: Signal the event AFTER the first MIDI message is sent, not before.

---

## Issue: No Synchronization Between MIDI Send and Audio Capture

**Location**: `server/app.py:560-565`

```python
playback_started.wait(timeout=1.0)
time.sleep(0.05)  # Fixed 50ms delay - not reliable
wav_bytes = audio.record(duration, extra_time=1.0)
```

**Problem**:
- The 50ms delay is arbitrary and may not account for USB audio latency
- No handshake to confirm audio is actually flowing
- MIDI → Synth → USB Audio path has variable latency (10-50ms typically)

**Impact**: Recordings may miss the attack of the first notes or have unwanted silence at the start.

---

## Issue: Queue Overflow Drops Audio Silently

**Location**: `server/audio.py:148`, `server/app.py:1066-1070`

```python
# In _audio_capture_process (audio.py:148)
audio_queue.put_nowait(buffer)  # Silently fails if queue full

# In WebSocket handler (app.py:1066-1070)
while not audio_queue.empty():
    try:
        audio_queue.get_nowait()  # Drops oldest on overflow
```

**Problem**: When queue is full, audio chunks are silently dropped causing:
- Audible clicks and gaps in playback
- No error reporting or metrics
- No smooth fallback (unlike the AudioWorklet which fades out)

---

## Issue: AudioWorklet Buffer Recovery Oscillation

**Location**: `web/public/audio-processor.js:157-165`

```javascript
if (availableSamples < totalSamples) {
    // Increase target by 20% on underrun
    this._targetBufferMs = Math.min(
        this._targetBufferMs * 1.2,
        this._maxTargetMs
    );
    this._underrunOccurred = true;
```

**Problem**:
- 1.2x multiplier may not recover fast enough from severe underruns
- No maximum retry count before giving up
- Buffer decrease (15ms per check) may cause oscillation between underrun and overflow

---

## Issue: Device Selection Uncertainty

**Location**: `server/audio.py:51-70`

```python
for dev in devices:
    name = dev['name'].lower()
    if 'montage' in name:  # Substring match - may select wrong device
        return dev['index']
```

**Problem**:
- Case-insensitive substring matching may select wrong device
- Multiple MONTAGE devices (e.g., MIDI and Audio) could cause confusion
- Fallback to system default device may not be the synth

---

## Issue: WebRTC Frame Dropping Too Aggressive

**Location**: `server/app.py:104-116`

```python
if self._audio_queue.qsize() >= 6:  # 75% full
    self._dropped_frames += 1
    return  # Drops frame
```

**Problem**:
- Drops frames at 75% queue capacity (6/8)
- May cause unnecessary audio gaps
- No prioritization (all frames treated equally)

---

## Issue: Extra Time in Recording May Clip Tail

**Location**: `server/app.py:565`

```python
wav_bytes = audio.record(duration, extra_time=1.0)
```

**Problem**:
- Fixed 1.0 second extra time may not match actual note release times
- Notes with long release/decay may be clipped
- No detection of when audio actually ends (silence detection)

---

## Recommended Fixes Priority

1. **HIGH**: Fix export timing race condition (app.py:552-554) - signal AFTER playback starts
2. **HIGH**: Add proper MIDI→Audio synchronization handshake
3. **MEDIUM**: Implement graceful audio drop handling with crossfade
4. **MEDIUM**: Improve device selection with explicit configuration option
5. **LOW**: Add silence detection for smarter recording end
6. **LOW**: Implement buffer recovery damping to prevent oscillation

---

## Audio Configuration Reference

```python
# server/audio.py
sample_rate = 44100
capture_channels = 8  # MONTAGE sends 8 channels
output_channels = 2   # We output stereo
chunk_frames = 512    # ~12ms at 44.1kHz
max_backlog_chunks = 2

# web/public/audio-processor.js
minTargetMs = 40
maxTargetMs = 240
initialTargetMs = 90
ringBufferSeconds = 0.9
```

## Testing Audio

1. Check MIDI connection: `GET /api/status` should show `midi_connected: true`
2. Test audio capture: Start streaming at `ws://localhost:8000/ws/audio`
3. Verify patches: Play a note and confirm sound on each channel
4. Test export: Use `POST /api/export/audio` and verify WAV contains audio

## Environment Variables

```bash
ANTHROPIC_API_KEY=...     # For Claude-based generation
OPENAI_API_KEY=...        # For GPT-based generation (alternative)
SUPABASE_URL=...          # For cloud library storage
SUPABASE_KEY=...          # Supabase service key
JUNO_AUDIO_MAX_BACKLOG_CHUNKS=2  # Tune audio buffer depth
JUNO_RTC_ENABLED=true     # Enable WebRTC transport
```
