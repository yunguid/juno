// AudioWorklet processor for smooth PCM streaming
// Runs on dedicated audio thread with precise timing

class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    
    // Ring buffer for lock-free audio streaming
    // Buffer size: 2 seconds at 44100Hz stereo = 176400 samples (~500ms target latency with headroom)
    this.bufferSize = 176400;
    this.buffer = new Float32Array(this.bufferSize);
    this.writePos = 0;
    this.readPos = 0;
    this.availableSamples = 0;
    
    // Configuration
    this.sampleRate = 44100;
    this.channels = 2;
    
    // Underrun handling
    this.underrunCount = 0;
    this.lastLogTime = 0;
    this.frameCount = 0;
    
    // Message handler for receiving PCM data from main thread
    this.port.onmessage = (event) => {
      const { type, data } = event.data;
      
      if (type === 'config') {
        this.sampleRate = data.sampleRate || 44100;
        this.channels = data.channels || 2;
        // Recalculate buffer size for new sample rate
        this.bufferSize = this.sampleRate * this.channels;
        this.buffer = new Float32Array(this.bufferSize);
        this.writePos = 0;
        this.readPos = 0;
        this.availableSamples = 0;
        console.log(`[AudioWorklet] Config: ${this.sampleRate}Hz, ${this.channels}ch`);
      } else if (type === 'pcm') {
        // Receive Int16 PCM data and convert to Float32
        const int16Data = new Int16Array(data);
        const samples = int16Data.length;
        
        // Convert Int16 to Float32 and deinterleave
        const samplesPerChannel = samples / this.channels;
        const float32Data = new Float32Array(samples);
        
        for (let i = 0; i < samples; i++) {
          float32Data[i] = int16Data[i] / 32768.0;
        }
        
        // Write to ring buffer
        this.writePCM(float32Data, samplesPerChannel);
      } else if (type === 'reset') {
        // Reset buffer (e.g., on stop)
        this.writePos = 0;
        this.readPos = 0;
        this.availableSamples = 0;
      }
    };
  }
  
  writePCM(float32Data, samplesPerChannel) {
    const totalSamples = float32Data.length;
    const bufferAvailable = this.bufferSize - this.availableSamples;
    
    if (totalSamples > bufferAvailable) {
      // Buffer overflow - drop oldest samples
      const dropCount = totalSamples - bufferAvailable;
      this.readPos = (this.readPos + dropCount) % this.bufferSize;
      this.availableSamples -= dropCount;
      console.warn(`[AudioWorklet] Buffer overflow, dropped ${dropCount} samples`);
    }
    
    // Write samples to ring buffer
    for (let i = 0; i < totalSamples; i++) {
      this.buffer[this.writePos] = float32Data[i];
      this.writePos = (this.writePos + 1) % this.bufferSize;
    }
    
    this.availableSamples += totalSamples;
  }
  
  readPCM(output, frameCount) {
    const samplesNeeded = frameCount * this.channels;
    
    if (this.availableSamples < samplesNeeded) {
      // Underrun - output silence with smooth fade to avoid clicks
      this.underrunCount++;
      const currentTime = this.frameCount / this.sampleRate;
      if (currentTime - this.lastLogTime > 1.0) {
        console.warn(`[AudioWorklet] Underrun (${this.availableSamples}/${samplesNeeded} samples available)`);
        this.lastLogTime = currentTime;
      }
      
      // Fade out last samples to prevent clicks
      const fadeSamples = Math.min(128, this.availableSamples);
      if (fadeSamples > 0) {
        const fadeStart = this.availableSamples - fadeSamples;
        for (let ch = 0; ch < this.channels; ch++) {
          const channelData = output[ch];
          for (let i = 0; i < frameCount; i++) {
            const sampleIdx = i * this.channels + ch;
            if (sampleIdx < fadeSamples) {
              const fadeFactor = 1.0 - (sampleIdx / fadeSamples);
              const bufferIdx = (this.readPos + sampleIdx) % this.bufferSize;
              channelData[i] = this.buffer[bufferIdx] * fadeFactor;
            } else {
              channelData[i] = 0;
            }
          }
        }
        this.readPos = (this.readPos + fadeSamples) % this.bufferSize;
        this.availableSamples -= fadeSamples;
      } else {
        // Complete underrun - output silence
        for (let ch = 0; ch < this.channels; ch++) {
          output[ch].fill(0);
        }
      }
      return;
    }
    
    // Normal read from ring buffer
    for (let ch = 0; ch < this.channels; ch++) {
      const channelData = output[ch];
      for (let i = 0; i < frameCount; i++) {
        const bufferIdx = (this.readPos + i * this.channels + ch) % this.bufferSize;
        channelData[i] = this.buffer[bufferIdx];
      }
    }
    
    this.readPos = (this.readPos + samplesNeeded) % this.bufferSize;
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
    
    // Report buffer status periodically (every 2 seconds)
    if (this.frameCount % (this.sampleRate * 2) < frameCount) {
      const bufferMs = (this.availableSamples / this.channels / this.sampleRate) * 1000;
      this.port.postMessage({
        type: 'status',
        bufferMs: bufferMs,
        underruns: this.underrunCount
      });
    }
    
    return true; // Keep processor alive
  }
}

registerProcessor('pcm-processor', PCMProcessor);

