# Audio Streaming Performance Improvement Prompt

## Context

We have a real-time audio streaming system that captures audio from a Yamaha MONTAGE synthesizer and streams it to a web browser for playback. The system has been recently improved with AudioWorklet-based playback, but still experiences noticeable lag, buffering issues, and occasional jitteriness.

## Current Architecture

### Server-Side (`server/audio.py` and `server/app.py`)

1. **Audio Capture Process** (`_audio_capture_process`):
   - Runs in separate process (spawn context) for reliability
   - Captures audio using `sounddevice` at 44100Hz, 8 input channels
   - Converts to stereo (2 channels) Int16 PCM
   - Chunk size: **4096 frames** (~93ms per chunk at 44100Hz)
   - Sends chunks via multiprocessing Queue (maxsize=500)

2. **WebSocket Streaming** (`/ws/audio` endpoint):
   - FastAPI WebSocket endpoint
   - Uses `asyncio.Queue` (maxsize=100) as intermediate buffer
   - Sends audio config JSON message first, then streams binary PCM chunks
   - Drops frames silently if client queue is full

### Client-Side (`web/src/App.tsx` and `web/public/audio-processor.js`)

1. **AudioWorklet Processor** (`audio-processor.js`):
   - Ring buffer: **176400 samples** (2 seconds at 44100Hz stereo)
   - Receives Int16 PCM via MessagePort from main thread
   - Converts Int16 → Float32 and writes to ring buffer
   - Reads from ring buffer in `process()` callback (runs on audio thread)
   - Handles underruns with smooth fade-out
   - Reports buffer status every 2 seconds

2. **React Hook** (`useAudioStream`):
   - Initializes AudioContext (44100Hz)
   - Loads AudioWorklet module (`/audio-processor.js`)
   - Creates AudioWorkletNode and connects to destination
   - Receives WebSocket messages and forwards PCM data to worklet
   - No intermediate buffering - direct pass-through to worklet

## Current Issues

### 1. **Latency/Lag**
- **Symptom**: Noticeable delay between MIDI playback and audio output in browser
- **Potential Causes**:
  - Large ring buffer (2 seconds) creates inherent latency
  - WebSocket network latency
  - Server-side buffering (multiprocessing Queue + asyncio Queue)
  - No adaptive buffering - always waits for full buffer before starting

### 2. **Buffering/Jitteriness**
- **Symptom**: Occasional stutters, pops, or brief pauses during playback
- **Potential Causes**:
  - Network jitter causing irregular chunk arrival
  - Ring buffer underruns despite large buffer size
  - MessagePort transfer overhead (copying ArrayBuffer to worklet)
  - Browser event loop blocking causing delayed message delivery
  - No dynamic buffer size adjustment based on network conditions

### 3. **Performance Concerns**
- **MessagePort Transfer**: Each chunk requires copying ArrayBuffer from main thread to audio thread
- **Synchronous Processing**: Ring buffer writes happen synchronously in message handler
- **No Backpressure**: Client doesn't signal server about buffer state
- **Fixed Buffer Size**: Doesn't adapt to network conditions or device capabilities

## Performance Goals

1. **Latency**: Reduce end-to-end latency to <200ms (currently ~500ms+)
2. **Smoothness**: Eliminate audible stutters, pops, or gaps
3. **Adaptability**: Dynamically adjust buffering based on network conditions
4. **Efficiency**: Minimize CPU usage and memory allocations

## Areas for Investigation and Improvement

### A. Buffer Management Strategy

**Current**: Fixed 2-second ring buffer, always fills before playback

**Consider**:
- **Adaptive Buffering**: Start playback with smaller initial buffer (e.g., 200-300ms), expand dynamically if underruns occur
- **Target Buffer Level**: Maintain optimal buffer level (e.g., 400-600ms) rather than maximum
- **Buffer Monitoring**: Track buffer fill rate vs. consumption rate to predict underruns
- **Pre-buffering**: Pre-fill buffer before starting playback, but use smaller target size

### B. Network Optimization

**Current**: Simple WebSocket streaming, no backpressure or adaptation

**Consider**:
- **Backpressure Signaling**: Client reports buffer state to server, server adjusts send rate
- **Chunk Size Adaptation**: Dynamically adjust server chunk size based on network conditions
- **Priority Queue**: Prioritize audio chunks over other WebSocket messages
- **Compression**: Consider Opus codec for lower bandwidth (requires decoding in browser)
- **WebRTC DataChannel**: Lower latency alternative to WebSocket for binary streaming

### C. AudioWorklet Optimization

**Current**: Synchronous ring buffer writes, Int16→Float32 conversion per chunk

**Consider**:
- **SharedArrayBuffer**: Use SharedArrayBuffer for zero-copy transfer (requires CORS headers)
- **Batch Processing**: Accumulate multiple chunks before writing to reduce lock contention
- **SIMD Operations**: Use SIMD for faster Int16→Float32 conversion
- **Worker Thread**: Move WebSocket handling to Worker thread to avoid blocking main thread
- **Direct Float32 Streaming**: Server sends Float32 directly to avoid conversion overhead

### D. Timing and Synchronization

**Current**: No explicit timing synchronization

**Consider**:
- **Timestamp Tracking**: Add timestamps to chunks to detect network jitter
- **Clock Synchronization**: Sync client/server clocks for accurate latency measurement
- **Drift Compensation**: Detect and compensate for sample rate drift
- **Playback Rate Adjustment**: Slightly adjust playback rate to maintain buffer level

### E. Browser-Specific Optimizations

**Consider**:
- **AudioContext Latency Mode**: Use `latencyHint: 'interactive'` for lower latency
- **OfflineAudioContext**: Pre-process chunks in offline context if applicable
- **Web Audio API Best Practices**: Ensure optimal buffer sizes, avoid unnecessary nodes
- **Browser Compatibility**: Handle different browsers' AudioWorklet implementations

### F. Server-Side Improvements

**Current**: Two-stage buffering (multiprocessing Queue + asyncio Queue)

**Consider**:
- **Reduce Buffering**: Smaller or eliminate intermediate queues
- **Direct Streaming**: Stream directly from capture process to WebSocket
- **Chunk Batching**: Send multiple chunks in single WebSocket message
- **Priority Scheduling**: Prioritize audio streaming over other server tasks

## Implementation Priorities

1. **High Priority**:
   - Implement adaptive buffering (start small, expand if needed)
   - Add backpressure signaling (client → server buffer state)
   - Optimize MessagePort transfers (consider SharedArrayBuffer or batching)

2. **Medium Priority**:
   - Add timestamp tracking for jitter detection
   - Implement dynamic chunk size adjustment
   - Move WebSocket handling to Worker thread

3. **Low Priority**:
   - Consider WebRTC DataChannel migration
   - Implement Opus compression
   - Add SIMD optimizations

## Testing and Validation

When implementing improvements, validate:

1. **Latency Measurement**: Measure end-to-end latency (MIDI note → audio output)
2. **Buffer Stability**: Monitor buffer levels during playback, ensure stable operation
3. **Underrun Frequency**: Count and minimize underrun events
4. **CPU Usage**: Ensure optimizations don't increase CPU usage significantly
5. **Network Resilience**: Test with various network conditions (WiFi, mobile, high latency)
6. **Browser Compatibility**: Test across Chrome, Firefox, Safari

## Success Criteria

- **Latency**: <200ms end-to-end latency
- **Smoothness**: Zero audible stutters or pops during normal playback
- **Stability**: Buffer level remains stable (±50ms) during playback
- **Efficiency**: <5% CPU usage for audio processing on modern hardware

## Technical Constraints

- Must work in modern browsers (Chrome, Firefox, Safari)
- Server runs Python/FastAPI on Linux
- Audio format: 44100Hz, stereo, Int16 PCM (can be changed if beneficial)
- WebSocket is current transport (can consider alternatives)
- AudioWorklet is required (no fallback to ScriptProcessorNode)

## Files to Review

- `web/src/App.tsx` - React hook for audio streaming
- `web/public/audio-processor.js` - AudioWorklet processor
- `server/audio.py` - Audio capture implementation
- `server/app.py` - WebSocket endpoint (lines 594-634)

## Notes

- The system works but needs refinement for production-quality performance
- Current implementation is functional but not optimized
- Focus on practical improvements that provide measurable benefits
- Maintain code clarity and avoid over-engineering

