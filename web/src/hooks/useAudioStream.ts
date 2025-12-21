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
  const rtcWsRef = useRef<WebSocket | null>(null)
  const rtcPcRef = useRef<RTCPeerConnection | null>(null)
  const rtcAudioElRef = useRef<HTMLAudioElement | null>(null)
  const rtcSourceNodeRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const rtcStatsTimerRef = useRef<number | null>(null)
  const transportRef = useRef<'webrtc' | 'ws' | null>(null)
  const isStreamingRef = useRef(false)
  const audioConfigRef = useRef<{ sampleRate: number; channels: number } | null>(null)
  const lastStatusLogMsRef = useRef(0)
  const lastUnderrunsRef = useRef(0)
  const initialTargetBufferMs = IS_IOS ? 260 : 180
  const iceServersRef = useRef<RTCIceServer[] | null>(null)

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

  const loadIceServers = useCallback(() => {
    if (iceServersRef.current) return iceServersRef.current
    const raw = import.meta.env.VITE_ICE_SERVERS
    if (!raw) {
      iceServersRef.current = [{ urls: ['stun:stun.l.google.com:19302'] }]
      return iceServersRef.current
    }
    try {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) {
        iceServersRef.current = parsed
      } else {
        iceServersRef.current = []
      }
    } catch {
      iceServersRef.current = []
    }
    return iceServersRef.current
  }, [])

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

  const startStreamingWebSocket = useCallback(async () => {
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
      isStreamingRef.current = true
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

  const stopStreamingWebSocket = useCallback(() => {
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

  const stopStreamingWebRtc = useCallback(() => {
    if (rtcStatsTimerRef.current) {
      window.clearInterval(rtcStatsTimerRef.current)
      rtcStatsTimerRef.current = null
    }
    if (rtcSourceNodeRef.current) {
      try {
        rtcSourceNodeRef.current.disconnect()
      } catch {
        // Ignore disconnect errors
      }
      rtcSourceNodeRef.current = null
    }
    if (rtcAudioElRef.current) {
      rtcAudioElRef.current.pause()
      rtcAudioElRef.current.srcObject = null
    }
    if (rtcWsRef.current) {
      rtcWsRef.current.close()
      rtcWsRef.current = null
    }
    if (rtcPcRef.current) {
      rtcPcRef.current.close()
      rtcPcRef.current = null
    }
    isStreamingRef.current = false
  }, [])

  const startStreamingWebRtc = useCallback(async () => {
    if (!('RTCPeerConnection' in window)) {
      throw new Error('WebRTC not supported')
    }

    const iceServers = loadIceServers()
    const pc = new RTCPeerConnection({ iceServers })
    rtcPcRef.current = pc
    pc.addTransceiver('audio', { direction: 'recvonly' })

    const signalWs = new WebSocket(`${wsUrl}/ws/rtc`)
    rtcWsRef.current = signalWs

    const waitForOpen = new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(() => reject(new Error('WebRTC signaling timeout')), 5000)
      signalWs.onopen = () => {
        window.clearTimeout(timeout)
        resolve()
      }
      signalWs.onerror = () => {
        window.clearTimeout(timeout)
        reject(new Error('WebRTC signaling error'))
      }
    })

    const trackReady = new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(() => reject(new Error('WebRTC track timeout')), 8000)
      pc.ontrack = async (event) => {
        window.clearTimeout(timeout)
        const stream = event.streams?.[0] ?? new MediaStream([event.track])
        try {
          const audioEl = rtcAudioElRef.current ?? new Audio()
          audioEl.autoplay = true
          audioEl.playsInline = true
          audioEl.srcObject = stream
          rtcAudioElRef.current = audioEl
          try {
            await audioEl.play()
          } catch (e) {
            console.warn('Audio element play failed, trying AudioContext:', e)
            const ctx = await ensureAudioUnlocked()
            const source = ctx.createMediaStreamSource(stream)
            source.connect(ctx.destination)
            rtcSourceNodeRef.current = source
          }
        } catch (e) {
          console.warn('Failed to attach WebRTC audio:', e)
        }
        resolve()
      }
      pc.onconnectionstatechange = () => {
        if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
          window.clearTimeout(timeout)
          reject(new Error(`WebRTC connection ${pc.connectionState}`))
        }
      }
    })

    pc.onicecandidate = (event) => {
      if (!event.candidate || !signalWs || signalWs.readyState !== WebSocket.OPEN) return
      signalWs.send(JSON.stringify({
        type: 'candidate',
        candidate: event.candidate.candidate,
        sdpMid: event.candidate.sdpMid,
        sdpMLineIndex: event.candidate.sdpMLineIndex,
      }))
    }

    signalWs.onmessage = async (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'answer' && msg.sdp) {
          await pc.setRemoteDescription({ type: 'answer', sdp: msg.sdp })
        } else if (msg.type === 'candidate' && msg.candidate) {
          await pc.addIceCandidate({
            candidate: msg.candidate,
            sdpMid: msg.sdpMid ?? null,
            sdpMLineIndex: msg.sdpMLineIndex ?? null,
          })
        } else if (msg.type === 'error') {
          console.warn('WebRTC error:', msg.reason)
        }
      } catch (e) {
        console.warn('Failed to handle WebRTC signaling message:', e)
      }
    }

    await waitForOpen
    const offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    signalWs.send(JSON.stringify({ type: 'offer', sdp: offer.sdp }))

    await trackReady
    isStreamingRef.current = true

    rtcStatsTimerRef.current = window.setInterval(async () => {
      if (!rtcPcRef.current) return
      try {
        const stats = await rtcPcRef.current.getStats()
        stats.forEach((report) => {
          if (report.type === 'inbound-rtp' && report.kind === 'audio') {
            const loss = report.packetsLost ?? 0
            const jitter = report.jitter ?? 0
            if (loss > 0) {
              console.warn(`[WebRTC] audio loss=${loss} jitter=${jitter}`)
            }
          }
        })
      } catch {
        // Ignore stats errors
      }
    }, 4000)
  }, [ensureAudioUnlocked, loadIceServers, wsUrl])

  const startStreaming = useCallback(async () => {
    if (transportRef.current) return
    try {
      await startStreamingWebRtc()
      transportRef.current = 'webrtc'
      return
    } catch (error) {
      console.warn('WebRTC stream failed, falling back to WebSocket:', error)
      stopStreamingWebRtc()
    }

    await startStreamingWebSocket()
    transportRef.current = 'ws'
  }, [startStreamingWebRtc, startStreamingWebSocket, stopStreamingWebRtc])

  const stopStreaming = useCallback(() => {
    if (transportRef.current === 'webrtc') {
      stopStreamingWebRtc()
    } else if (transportRef.current === 'ws') {
      stopStreamingWebSocket()
    } else {
      stopStreamingWebRtc()
      stopStreamingWebSocket()
    }
    transportRef.current = null
  }, [stopStreamingWebRtc, stopStreamingWebSocket])

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
