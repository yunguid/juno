// AudioWorklet processor for smooth PCM streaming
// Runs on dedicated audio thread with precise timing

class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    
    // Interleaved ring buffer (Float32) sized for headroom; target latency is managed separately.
    this.capacitySeconds = 1.5;
    this.bufferSize = 0;
    this.buffer = new Float32Array(0);
    this.writePos = 0;
    this.readPos = 0;
    this.availableSamples = 0;
    
    // Configuration
    this.sampleRate = 44100;
    this.channels = 2;

    // Adaptive buffering - tuned for low latency with WebRTC/WebSocket
    this.started = false; // prebuffer gate
    this.minTargetMs = 60;   // Lower floor for faster recovery
    this.maxTargetMs = 400;  // Lower ceiling to cap worst-case latency
    this.targetBufferMs = 120; // Start with tighter buffer
    this.maxExtraBufferMs = 150; // Drop sooner to prevent runaway lag
    
    // Underrun handling
    this.underrunCount = 0;
    this.lastUnderrunFrame = 0;
    this.frameCount = 0;
    this.droppedSamples = 0;
    this.lastTargetDecreaseFrame = 0;

    // Status reporting
    this.statusIntervalFrames = Math.floor(this.sampleRate * 0.25);
    this.framesUntilStatus = this.statusIntervalFrames;

    this._configureBuffer();
    
    // Message handler for receiving PCM data from main thread
    this.port.onmessage = (event) => {
      const { type, data } = event.data;
      
      if (type === 'config') {
        this.sampleRate = data.sampleRate || 44100;
        this.channels = data.channels || 2;
        if (typeof data.targetBufferMs === 'number') {
          this.targetBufferMs = this._clampTargetMs(data.targetBufferMs);
        }
        this._reset();
        this._configureBuffer();
      } else if (type === 'pcm') {
        // Receive Int16 PCM data; convert directly into ring buffer to avoid allocations.
        this._writeInt16PCM(new Int16Array(data));
      } else if (type === 'reset') {
        // Reset buffer (e.g., on stop)
        this._reset();
      }
    };
  }
  
  _clampTargetMs(value) {
    return Math.max(this.minTargetMs, Math.min(this.maxTargetMs, value));
  }

  _reset() {
    this.writePos = 0;
    this.readPos = 0;
    this.availableSamples = 0;
    this.started = false;
    this.underrunCount = 0;
    this.lastUnderrunFrame = 0;
    this.droppedSamples = 0;
    this.frameCount = 0;
    this.statusIntervalFrames = Math.floor(this.sampleRate * 0.25);
    this.framesUntilStatus = this.statusIntervalFrames;
    this.lastTargetDecreaseFrame = 0;
  }

  _configureBuffer() {
    const capacityFrames = Math.max(1, Math.ceil(this.sampleRate * this.capacitySeconds));
    this.bufferSize = capacityFrames * this.channels;
    this.buffer = new Float32Array(this.bufferSize);
  }

  _bufferMs() {
    return (this.availableSamples / this.channels / this.sampleRate) * 1000;
  }

  _dropOldestSamples(samplesToDrop) {
    if (samplesToDrop <= 0) return;
    let alignedDrop = samplesToDrop - (samplesToDrop % this.channels);
    if (alignedDrop <= 0) return;
    if (alignedDrop > this.availableSamples) {
      alignedDrop = this.availableSamples - (this.availableSamples % this.channels);
    }
    if (alignedDrop <= 0) return;
    this.readPos = (this.readPos + alignedDrop) % this.bufferSize;
    this.availableSamples -= alignedDrop;
    this.droppedSamples += alignedDrop;
  }

  _writeInt16PCM(int16Data) {
    const totalSamples = int16Data.length;
    if (totalSamples === 0) return;
    if (totalSamples % this.channels !== 0) return;

    const bufferAvailable = this.bufferSize - this.availableSamples;
    if (totalSamples > bufferAvailable) {
      // Drop oldest audio to keep latency bounded.
      this._dropOldestSamples(totalSamples - bufferAvailable);
    }

    const invScale = 1.0 / 32768.0;
    const buffer = this.buffer;
    const bufferSize = this.bufferSize;
    let writePos = this.writePos;

    let srcIndex = 0;
    let remaining = totalSamples;
    while (remaining > 0) {
      const chunk = Math.min(remaining, bufferSize - writePos);
      for (let i = 0; i < chunk; i++) {
        buffer[writePos + i] = int16Data[srcIndex + i] * invScale;
      }
      writePos += chunk;
      if (writePos >= bufferSize) writePos = 0;
      srcIndex += chunk;
      remaining -= chunk;
    }

    this.writePos = writePos;
    this.availableSamples += totalSamples;

    // If the client got too far behind, drop additional audio to prevent runaway lag.
    const maxHoldMs = Math.min(this.capacitySeconds * 1000, this.targetBufferMs + this.maxExtraBufferMs);
    const maxSamples = Math.floor((maxHoldMs / 1000) * this.sampleRate * this.channels);
    if (this.availableSamples > maxSamples) {
      this._dropOldestSamples(this.availableSamples - maxSamples);
    }

    if (!this.started && this._bufferMs() >= this.targetBufferMs) {
      this.started = true;
    }
  }
  
  readPCM(output, frameCount) {
    const samplesNeeded = frameCount * this.channels;
    
    if (!this.started) {
      for (let ch = 0; ch < this.channels; ch++) {
        output[ch].fill(0);
      }
      return;
    }

    if (this.availableSamples < samplesNeeded) {
      // Underrun - output silence with smooth fade to avoid clicks
      this.underrunCount++;
      this.lastUnderrunFrame = this.frameCount;
      // Less aggressive buffer increase on underrun (was 1.35)
      this.targetBufferMs = this._clampTargetMs(this.targetBufferMs * 1.2);
      this.started = false;
      
      const availableFrames = Math.floor(this.availableSamples / this.channels);
      const framesToRead = Math.min(frameCount, availableFrames);
      const fadeFrames = Math.min(64, framesToRead);

      const buffer = this.buffer;
      const bufferSize = this.bufferSize;
      let readPos = this.readPos;

      for (let i = 0; i < framesToRead; i++) {
        let fade = 1.0;
        if (fadeFrames > 0 && i >= framesToRead - fadeFrames) {
          fade = (framesToRead - i) / fadeFrames;
        }
        for (let ch = 0; ch < this.channels; ch++) {
          output[ch][i] = buffer[readPos + ch] * fade;
        }
        readPos += this.channels;
        if (readPos >= bufferSize) readPos = 0;
      }

      for (let ch = 0; ch < this.channels; ch++) {
        output[ch].fill(0, framesToRead);
      }

      this.readPos = readPos;
      this.availableSamples -= framesToRead * this.channels;
      return;
    }
    
    // Normal read from ring buffer
    const buffer = this.buffer;
    const bufferSize = this.bufferSize;
    let readPos = this.readPos;

    for (let i = 0; i < frameCount; i++) {
      for (let ch = 0; ch < this.channels; ch++) {
        output[ch][i] = buffer[readPos + ch];
      }
      readPos += this.channels;
      if (readPos >= bufferSize) readPos = 0;
    }

    this.readPos = readPos;
    this.availableSamples -= samplesNeeded;
  }
  
  process(inputs, outputs, parameters) {
    const output = outputs[0];
    if (!output || output.length === 0) {
      return true;
    }
    
    const frameCount = output[0].length;
    this.readPCM(output, frameCount);
    
    this.frameCount += frameCount;
    
    // Report buffer status periodically (~4Hz) for backpressure + debugging.
    this.framesUntilStatus -= frameCount;
    if (this.framesUntilStatus <= 0) {
      const bufferMs = this._bufferMs();
      const secondsSinceUnderrun = (this.frameCount - this.lastUnderrunFrame) / this.sampleRate;
      this.port.postMessage({
        type: 'status',
        bufferMs: bufferMs,
        targetMs: this.targetBufferMs,
        underruns: this.underrunCount,
        droppedSamples: this.droppedSamples,
        started: this.started
      });
      // Faster recovery when stable - reduce buffer more aggressively
      if (
        secondsSinceUnderrun > 8 &&
        this.targetBufferMs > this.minTargetMs &&
        (this.frameCount - this.lastTargetDecreaseFrame) > (this.sampleRate * 1.5)
      ) {
        this.targetBufferMs = this._clampTargetMs(this.targetBufferMs - 15);
        this.lastTargetDecreaseFrame = this.frameCount;
      }
      this.framesUntilStatus = this.statusIntervalFrames;
    }
    
    return true; // Keep processor alive
  }
}

registerProcessor('pcm-processor', PCMProcessor);
