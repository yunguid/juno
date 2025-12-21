# Juno

Juno is a web-based composer for the Yamaha MONTAGE M8x. It generates layered MIDI parts, plays them on the synth, and streams the synth’s audio back to the browser in real time.

## Architecture

- **Frontend**: React + Vite app in `web/` for prompt-to-music flow, sound selection, and live playback.
- **Backend**: FastAPI app in `server/` for MIDI playback, sound selection, and audio streaming.
- **Audio**: The synth’s USB audio is captured on the server and streamed over WebSocket as raw PCM.

## Quick start

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cd web
npm install
npm run build
```

Run the backend (serves the built frontend from `web/dist`):

```bash
python -m server.app
```

## Key flows

### 1) Generate and play
- Frontend calls `POST /api/session/start` to generate the base layer.
- Additional layers are generated via `POST /api/session/generate-layer`.
- Playback is triggered via `POST /api/play`.

### 2) Live audio streaming
- Frontend opens `ws://<host>/ws/audio`.
- Server sends an `audio_config` JSON message, then raw PCM bytes.
- The browser plays PCM via an `AudioWorklet` (`web/public/audio-processor.js`).

### 3) Sound selection
- The UI opens a sound picker filtered by sound type.
- Backend provides filtered patches via `GET /api/patches`.
- Patch selection is applied via `POST /api/sound/{channel}/select`.

## Patch list generation (Montage M Data List)

The authoritative performance names and bank/program values come from Yamaha’s official **MONTAGE M Data List** (Excel ZIP).

### Update patches from Data List ZIP

1. Download the latest `MONTAGE-M_data_list_*.zip` from Yamaha.
2. Run:

```bash
python server/scripts/generate_patches_from_datalist.py /path/to/MONTAGE-M_data_list_En_*.zip
```

This regenerates `server/data/patches.json` with:
- Performance names (3,487 total in the current Data List)
- Main category tags
- Bank MSB/LSB and program numbers

## Known device notes

- **iOS (Chrome/Safari)**: Audio can be suspended until user interaction. The frontend resumes `AudioContext` on user gestures.
- **Sample rates**: The AudioWorklet resamples when the input sample rate differs from the device output rate.

## Important files

- `server/app.py` — API endpoints and WebSocket handlers
- `server/player.py` — MIDI playback engine
- `server/audio.py` — audio capture and streaming
- `server/data/patches.json` — current performance list
- `web/src/App.tsx` — main UI flow
- `web/src/hooks/useAudioStream.ts` — live audio streaming hook
- `web/public/audio-processor.js` — AudioWorklet processor
