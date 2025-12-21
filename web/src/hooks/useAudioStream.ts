import { useCallback, useEffect, useRef } from 'react'

const IS_IOS = (() => {
  if (typeof navigator === 'undefined') return false
  const ua = navigator.userAgent
  return /iP(ad|hone|od)/.test(ua) || (ua.includes('Mac') && 'ontouchend' in document)
})()

export function useAudioStream(wsUrl: string) {
  const audioContextRef = useRef<AudioContext | null>(null)
  const workletNodeRef = useRef<AudioWorkletNode | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const isStreamingRef = useRef(false)
  const audioConfigRef = useRef<{ sampleRate: number; channels: number } | null>(null)
  const lastStatusLogMsRef = useRef(0)
  const lastUnderrunsRef = useRef(0)
  const initialTargetBufferMs = IS_IOS ? 260 : 180

  const initAudioContext = useCallback(async () => {
    if (!audioContextRef.current) {
      audioContextRef.current = new AudioContext({ latencyHint: 'playback' })
      console.log('AudioContext created, state:', audioContextRef.current.state)
    }
    if (audioContextRef.current.state === 'suspended') {
      console.log('Resuming AudioContext...')
      await audioContextRef.current.resume()
      console.log('AudioContext resumed, state:', audioContextRef.current.state)
    }
    return audioContextRef.current
  }, [])

  const ensureAudioUnlocked = useCallback(async () => {
    const ctx = await initAudioContext()
    if (ctx.state !== 'running') {
      try {
        await ctx.resume()
      } catch (error) {
        console.warn('AudioContext resume failed:', error)
      }
    }
    if (ctx.state !== 'running') {
      console.warn('AudioContext is not running; user gesture may be required.')
    }
    return ctx
  }, [initAudioContext])

  const initAudioWorklet = useCallback(async (audioContext: AudioContext) => {
    if (workletNodeRef.current) {
      return workletNodeRef.current
    }

    try {
      await audioContext.audioWorklet.addModule('/audio-processor.js')
      console.log('AudioWorklet module loaded')

      const workletNode = new AudioWorkletNode(audioContext, 'pcm-processor', {
        numberOfInputs: 0,
        numberOfOutputs: 1,
        outputChannelCount: [2],
      })

      workletNode.port.onmessage = (event) => {
        const { type, bufferMs, targetMs, underruns, droppedSamples } = event.data
        if (type === 'status') {
          const now = performance.now()
          const shouldLog = underruns > lastUnderrunsRef.current || now - lastStatusLogMsRef.current > 2000
          if (shouldLog) {
            lastStatusLogMsRef.current = now
            lastUnderrunsRef.current = underruns

            const targetStr = typeof targetMs === 'number' ? ` (target ${targetMs.toFixed(0)}ms)` : ''
            const droppedStr = typeof droppedSamples === 'number' && droppedSamples > 0 ? ` dropped=${droppedSamples}` : ''
            if (underruns > 0) {
              console.warn(`[AudioStream] Buffer: ${bufferMs.toFixed(0)}ms${targetStr}, underruns=${underruns}${droppedStr}`)
            } else {
              console.log(`[AudioStream] Buffer: ${bufferMs.toFixed(0)}ms${targetStr}${droppedStr}`)
            }
          }

          const ws = wsRef.current
          if (ws && ws.readyState === WebSocket.OPEN && typeof bufferMs === 'number') {
            ws.send(JSON.stringify({ type: 'buffer_status', buffer_ms: bufferMs, target_ms: targetMs, underruns }))
          }
        }
      }

      workletNode.connect(audioContext.destination)
      workletNodeRef.current = workletNode
      console.log('AudioWorklet node created and connected')

      return workletNodeRef.current
    } catch (error) {
      console.error('Failed to initialize AudioWorklet:', error)
      throw error
    }
  }, [])

  const startStreaming = useCallback(async () => {
    if (isStreamingRef.current) return

    try {
      const audioContext = await ensureAudioUnlocked()
      await initAudioWorklet(audioContext)

      isStreamingRef.current = true
      audioConfigRef.current = null

      const ws = new WebSocket(`${wsUrl}/ws/audio`)
      ws.binaryType = 'arraybuffer'

      await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('Audio stream connection timeout')), 5000)
        ws.onopen = () => {
          clearTimeout(timeout)
          console.log('Audio stream connected')
          resolve()
        }
        ws.onerror = (err) => {
          clearTimeout(timeout)
          console.error('Audio stream connection error:', err)
          reject(err)
        }
      })

      ws.onmessage = (event) => {
        if (typeof event.data === 'string') {
          const config = JSON.parse(event.data)
          if (config.type === 'audio_config') {
            audioConfigRef.current = {
              sampleRate: config.sample_rate,
              channels: config.channels,
            }
            console.log('Audio config:', audioConfigRef.current)

            if (workletNodeRef.current) {
              let targetBufferMs = initialTargetBufferMs
              if (typeof config.chunk_frames === 'number' && typeof config.sample_rate === 'number') {
                const chunkMs = (config.chunk_frames / config.sample_rate) * 1000
                if (Number.isFinite(chunkMs) && chunkMs > 0) {
                  targetBufferMs = Math.max(targetBufferMs, Math.min(600, chunkMs * 4))
                }
              }
              workletNodeRef.current.port.postMessage({
                type: 'config',
                data: {
                  inputSampleRate: config.sample_rate,
                  channels: config.channels,
                  targetBufferMs,
                },
              })
            }
          }
        } else {
          if (workletNodeRef.current && audioConfigRef.current) {
            workletNodeRef.current.port.postMessage({
              type: 'pcm',
              data: event.data,
            }, [event.data])
          }
        }
      }

      ws.onclose = () => {
        console.log('Audio stream disconnected')
        isStreamingRef.current = false

        if (workletNodeRef.current) {
          workletNodeRef.current.port.postMessage({ type: 'reset' })
        }
      }

      wsRef.current = ws
    } catch (error) {
      console.error('Failed to start audio streaming:', error)
      isStreamingRef.current = false
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      throw error
    }
  }, [ensureAudioUnlocked, initAudioWorklet, wsUrl, initialTargetBufferMs])

  const stopStreaming = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }

    if (workletNodeRef.current) {
      workletNodeRef.current.port.postMessage({ type: 'reset' })
    }

    isStreamingRef.current = false
    audioConfigRef.current = null
  }, [])

  useEffect(() => {
    const handler = () => {
      const ctx = audioContextRef.current
      if (ctx && ctx.state === 'suspended') {
        ctx.resume().catch(() => {})
      }
    }

    window.addEventListener('touchstart', handler, { passive: true })
    window.addEventListener('click', handler)
    return () => {
      window.removeEventListener('touchstart', handler)
      window.removeEventListener('click', handler)
    }
  }, [])

  useEffect(() => {
    return () => {
      stopStreaming()
      if (audioContextRef.current) {
        audioContextRef.current.close()
      }
    }
  }, [stopStreaming])

  return { startStreaming, stopStreaming }
}
