import { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import './App.css'
import { useAudioStream } from './hooks/useAudioStream'

interface Note {
  pitch: string | string[]
  start: number
  duration: number
  velocity: number
}

interface Layer {
  id: string
  name: string
  sound: 'bass' | 'pad' | 'lead'
  notes: Note[]
  muted: boolean
  volume: number
  patch_id?: string
  patch_name?: string
}

interface Patch {
  id: string
  name: string
  category: string
  sub_category?: string | null
  bank_msb: number
  bank_lsb: number
  program: number
  tags: string[]
}

interface PatchCategory {
  id: string
  name: string
  count: number
}

interface Sample {
  id: string
  name: string
  prompt: string
  key: string
  bpm: number
  bars: number
  layers: Layer[]
}

interface LLMConfig {
  provider: string
  model: string
  available_providers: string[]
  available_models: Record<string, string[]>
  default_models: Record<string, string>
}

type Step = 'setup' | 'pad' | 'lead' | 'bass' | 'complete'

const STEPS: { id: Step; label: string; sound?: 'pad' | 'lead' | 'bass' }[] = [
  { id: 'setup', label: '1. Describe' },
  { id: 'pad', label: '2. Chords', sound: 'pad' },
  { id: 'lead', label: '3. Melody', sound: 'lead' },
  { id: 'bass', label: '4. Bass', sound: 'bass' },
  { id: 'complete', label: '5. Export' },
]

const KEYS = [
  'C major', 'C minor', 'D major', 'D minor',
  'E major', 'E minor', 'F major', 'F minor',
  'G major', 'G minor', 'A major', 'A minor',
  'Bb major', 'Bb minor', 'Eb major', 'Eb minor',
]

// Use relative URLs when served from same origin (Pi), otherwise use env vars
const API_URL = (() => {
  if (import.meta.env.VITE_API_URL) return import.meta.env.VITE_API_URL
  const { hostname, port, protocol } = window.location
  if (port === '5173' || port === '3000') {
    return `${protocol}//${hostname}:8000`
  }
  return ''
})()
const WS_URL = (() => {
  if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL
  if (API_URL) {
    try {
      const api = new URL(API_URL, window.location.origin)
      const wsProto = api.protocol === 'https:' ? 'wss:' : 'ws:'
      return `${wsProto}//${api.host}`
    } catch {
      // Fall through to same-origin
    }
  }
  return `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`
})()

function App() {
  const [step, setStep] = useState<Step>('setup')
  const [prompt, setPrompt] = useState('')
  const [key, setKey] = useState('C minor')
  const [bpm, setBpm] = useState(90)
  const [bpmInput, setBpmInput] = useState('90')
  const [bars, setBars] = useState(4)
  const [sample, setSample] = useState<Sample | null>(null)
  const [loading, setLoading] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [llmConfig, setLlmConfig] = useState<LLMConfig | null>(null)
  const [feedback, setFeedback] = useState<Record<string, string>>({ pad: '', lead: '', bass: '' })
  const [improving, setImproving] = useState(false)
  const [showSoundPicker, setShowSoundPicker] = useState<'bass' | 'pad' | 'lead' | null>(null)
  const [patches, setPatches] = useState<Patch[]>([])
  const [patchTotal, setPatchTotal] = useState<number | null>(null)
  const [patchCategories, setPatchCategories] = useState<PatchCategory[]>([])
  const [patchSubcategories, setPatchSubcategories] = useState<string[]>([])
  const [patchSearch, setPatchSearch] = useState('')
  const [patchCategory, setPatchCategory] = useState('')
  const [patchSubCategory, setPatchSubCategory] = useState('')
  const [patchOffset, setPatchOffset] = useState(0)
  const [patchLoading, setPatchLoading] = useState(false)
  const [showAllSounds, setShowAllSounds] = useState(true)
  const [favoritePatchIds, setFavoritePatchIds] = useState<string[]>([])
  const [recentPatchIds, setRecentPatchIds] = useState<string[]>([])
  const [showFavoritesOnly, setShowFavoritesOnly] = useState(false)
  const [showRecentOnly, setShowRecentOnly] = useState(false)
  const [sortMode, setSortMode] = useState<'az' | 'category'>('az')
  const patchLimit = 60
  const [currentSounds, setCurrentSounds] = useState<Record<string, Patch | null>>({ bass: null, pad: null, lead: null })
  const soundPickerListRef = useRef<HTMLDivElement | null>(null)
  const FAVORITES_KEY = 'juno-favorite-patches'
  const RECENTS_KEY = 'juno-recent-patches'
  const wsRef = useRef<WebSocket | null>(null)
  
  // Audio streaming for real-time playback from Montage
  const { startStreaming, stopStreaming } = useAudioStream(WS_URL)

  // Fetch LLM config on mount
  useEffect(() => {
    fetch(`${API_URL}/api/llm/config`)
      .then(res => res.json())
      .then(setLlmConfig)
      .catch(console.error)
  }, [])

  useEffect(() => {
    try {
      const favRaw = localStorage.getItem(FAVORITES_KEY)
      if (favRaw) setFavoritePatchIds(JSON.parse(favRaw))
      const recentRaw = localStorage.getItem(RECENTS_KEY)
      if (recentRaw) setRecentPatchIds(JSON.parse(recentRaw))
    } catch {
      // Ignore storage errors
    }
  }, [])

  useEffect(() => {
    try {
      localStorage.setItem(FAVORITES_KEY, JSON.stringify(favoritePatchIds))
    } catch {
      // Ignore storage errors
    }
  }, [favoritePatchIds])

  useEffect(() => {
    try {
      localStorage.setItem(RECENTS_KEY, JSON.stringify(recentPatchIds))
    } catch {
      // Ignore storage errors
    }
  }, [recentPatchIds])

  const updateLlmConfig = async (provider?: string, model?: string) => {
    try {
      const res = await fetch(`${API_URL}/api/llm/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, model })
      })
      if (res.ok) {
        const updated = await fetch(`${API_URL}/api/llm/config`).then(r => r.json())
        setLlmConfig(updated)
      }
    } catch (e) {
      console.error('Failed to update LLM config:', e)
    }
  }

  useEffect(() => {
    let isMounted = true
    const ws = new WebSocket(`${WS_URL}/ws`)
    ws.onopen = () => {
      if (!isMounted) return
      console.log('Connected to server')
      setError(null) // Clear any previous connection errors
    }
    ws.onmessage = (event) => {
      if (!isMounted) return
      const data = JSON.parse(event.data)
      if (data.type === 'sample_updated') {
        setSample(data.sample)
        setLoading(false)
      } else if (data.type === 'playback_started') {
        setPlaying(true)
      } else if (data.type === 'playback_complete' || data.type === 'playback_stopped') {
        setPlaying(false)
        // Stop audio streaming when playback ends
        stopStreaming()
      }
    }
    ws.onclose = () => {
      // Only show error if we're not intentionally closing
      if (isMounted && wsRef.current === ws) {
        setError('Disconnected from server')
      }
    }
    wsRef.current = ws
    return () => {
      isMounted = false
      wsRef.current = null
      ws.close()
    }
  }, [stopStreaming])

  const startSession = async () => {
    if (!prompt.trim()) return
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/session/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, key, bpm, bars })
      })
      if (!res.ok) throw new Error((await res.json()).detail)
      const data = await res.json()
      setSample(data.sample)
      setStep('pad')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start')
    } finally {
      setLoading(false)
    }
  }

  const generateLayer = async (sound: 'pad' | 'lead' | 'bass', isRedo = false) => {
    // Stop playback first if regenerating
    if (isRedo && playing) {
      await stop()
    }
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/session/generate-layer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sound })
      })
      if (!res.ok) throw new Error((await res.json()).detail)
      const data = await res.json()
      setSample(data.sample)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Generation failed')
    } finally {
      setLoading(false)
    }
  }

  const play = async (layers?: string[]) => {
    try {
      // Start audio streaming BEFORE playback so we don't miss any audio
      await startStreaming()
      
      await fetch(`${API_URL}/api/play`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(layers || null)
      })
    } catch (e) {
      console.error('Play failed:', e)
      stopStreaming()
    }
  }

  const stop = async () => {
    try {
      await fetch(`${API_URL}/api/stop`, { method: 'POST' })
      stopStreaming()
    } catch (e) {
      console.error('Stop failed:', e)
    }
  }

  const exportMidi = async () => {
    try {
      const res = await fetch(`${API_URL}/api/export`)
      const data = await res.json()
      const bytes = atob(data.data)
      const buffer = new Uint8Array(bytes.length)
      for (let i = 0; i < bytes.length; i++) buffer[i] = bytes.charCodeAt(i)
      const blob = new Blob([buffer], { type: 'audio/midi' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = data.filename
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      console.error('Export failed:', e)
    }
  }

  const [exporting, setExporting] = useState(false)

  const exportAudio = async () => {
    setExporting(true)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/export/audio`)
      if (!res.ok) throw new Error((await res.json()).detail)
      const data = await res.json()
      const bytes = atob(data.data)
      const buffer = new Uint8Array(bytes.length)
      for (let i = 0; i < bytes.length; i++) buffer[i] = bytes.charCodeAt(i)
      const blob = new Blob([buffer], { type: 'audio/wav' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = data.filename
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      console.error('Audio export failed:', e)
      setError(e instanceof Error ? e.message : 'Audio export failed')
    } finally {
      setExporting(false)
    }
  }

  const improveLayers = async () => {
    // Check if any feedback provided
    const hasFeedback = Object.values(feedback).some(f => f.trim())
    if (!hasFeedback) {
      setError('Please provide feedback for at least one layer')
      return
    }

    if (playing) await stop()

    setImproving(true)
    setError(null)
    try {
      const res = await fetch(`${API_URL}/api/session/improve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ feedback })
      })
      if (!res.ok) throw new Error((await res.json()).detail)
      const data = await res.json()
      setSample(data.sample)
      setFeedback({ pad: '', lead: '', bass: '' }) // Clear feedback after success
    } catch (e) {
      console.error('Improve failed:', e)
      setError(e instanceof Error ? e.message : 'Failed to improve')
    } finally {
      setImproving(false)
    }
  }

  const getLayer = (sound: string) => sample?.layers.find(l => l.sound === sound)

  // Sound selection functions
  const fetchPatches = useCallback(async (soundType: string, append = false, offsetOverride?: number) => {
    try {
      setPatchLoading(true)
      const offset = typeof offsetOverride === 'number' ? offsetOverride : append ? patchOffset : 0
      const params = new URLSearchParams({ sound_type: soundType })
      if (patchSearch.trim()) params.set('search', patchSearch.trim())
      if (patchCategory) params.set('category', patchCategory)
      if (patchSubCategory) params.set('sub_category', patchSubCategory)
      if (showAllSounds) params.set('all_sounds', 'true')
      params.set('limit', String(patchLimit))
      params.set('offset', String(offset))
      const res = await fetch(`${API_URL}/api/patches?${params.toString()}`)
      const data = await res.json()
      setPatchCategories(data.categories || [])
      setPatchSubcategories(data.subcategories || [])
      setPatchTotal(data.total ?? null)
      setPatches(prev => (append ? [...prev, ...data.patches] : data.patches))
    } catch (e) {
      console.error('Failed to fetch patches:', e)
    } finally {
      setPatchLoading(false)
    }
  }, [patchCategory, patchOffset, patchSearch, patchSubCategory, showAllSounds])

  const openSoundPicker = useCallback((soundType: 'bass' | 'pad' | 'lead') => {
    setShowSoundPicker(soundType)
    setPatchSearch('')
    setPatchCategory('')
    setPatchSubCategory('')
    setPatchOffset(0)
  }, [])

  useEffect(() => {
    if (!showSoundPicker) return
    const timeout = setTimeout(() => {
      setPatchOffset(0)
      fetchPatches(showSoundPicker, false)
    }, 200)
    return () => clearTimeout(timeout)
  }, [fetchPatches, showSoundPicker, patchSearch, patchCategory, patchSubCategory, showAllSounds])

  const loadMorePatches = useCallback(() => {
    if (!showSoundPicker || patchLoading) return
    const nextOffset = patchOffset + patchLimit
    setPatchOffset(nextOffset)
    fetchPatches(showSoundPicker, true, nextOffset)
  }, [fetchPatches, patchLimit, patchLoading, patchOffset, showSoundPicker])

  const selectPatch = async (patch: Patch) => {
    if (!showSoundPicker) return
    try {
      await fetch(`${API_URL}/api/sound/${showSoundPicker}/select`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ patch_id: patch.id })
      })
      setCurrentSounds(prev => ({ ...prev, [showSoundPicker]: patch }))
      setRecentPatchIds(prev => {
        const next = [patch.id, ...prev.filter(id => id !== patch.id)].slice(0, 24)
        return next
      })
      setShowSoundPicker(null)
    } catch (e) {
      console.error('Select failed:', e)
    }
  }

  const toggleFavorite = (patchId: string) => {
    setFavoritePatchIds(prev => {
      if (prev.includes(patchId)) {
        return prev.filter(id => id !== patchId)
      }
      return [patchId, ...prev].slice(0, 200)
    })
  }

  const visiblePatches = useMemo(() => {
    let list = patches
    if (showFavoritesOnly) {
      list = list.filter(p => favoritePatchIds.includes(p.id))
    }
    if (showRecentOnly) {
      list = list.filter(p => recentPatchIds.includes(p.id))
    }
    if (sortMode === 'az') {
      list = [...list].sort((a, b) => a.name.localeCompare(b.name))
    } else {
      list = [...list].sort((a, b) => {
        const cat = a.category.localeCompare(b.category)
        if (cat !== 0) return cat
        return a.name.localeCompare(b.name)
      })
    }
    return list
  }, [patches, favoritePatchIds, recentPatchIds, showFavoritesOnly, showRecentOnly, sortMode])

  const letterIndex = useMemo(() => {
    const letters = new Set<string>()
    for (const patch of visiblePatches) {
      const letter = patch.name.trim().charAt(0).toUpperCase()
      if (letter) letters.add(letter)
    }
    return Array.from(letters).sort()
  }, [visiblePatches])

  const jumpToLetter = (letter: string) => {
    if (!soundPickerListRef.current) return
    const target = soundPickerListRef.current.querySelector(`[data-letter="${letter}"]`)
    if (target instanceof HTMLElement) {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }

  // Fetch current sounds on mount
  useEffect(() => {
    fetch(`${API_URL}/api/sounds/current`)
      .then(res => res.json())
      .then(data => setCurrentSounds({ bass: data.bass, pad: data.pad, lead: data.lead }))
      .catch(console.error)
  }, [])

  const currentStepInfo = STEPS.find(s => s.id === step)
  const currentSound = currentStepInfo?.sound

  const nextStep = async () => {
    // Stop playback before moving to next step
    if (playing) {
      await stop()
    }
    const order: Step[] = ['setup', 'pad', 'lead', 'bass', 'complete']
    const idx = order.indexOf(step)
    if (idx < order.length - 1) setStep(order[idx + 1])
  }

  return (
    <div className="app">
      <header>
        <h1>JUNO</h1>
        <button className="settings-btn" onClick={() => setShowSettings(!showSettings)}>
          {showSettings ? '×' : '⚙'}
        </button>
      </header>

      {/* Settings Panel */}
      {showSettings && llmConfig && (
        <div className="settings-panel">
          <div className="settings-row">
            <label>Provider</label>
            <select
              value={llmConfig.provider}
              onChange={(e) => updateLlmConfig(e.target.value, undefined)}
            >
              {llmConfig.available_providers.map(p => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </div>
          <div className="settings-row">
            <label>Model</label>
            <select
              value={llmConfig.model}
              onChange={(e) => updateLlmConfig(undefined, e.target.value)}
            >
              {llmConfig.available_models[llmConfig.provider]?.map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>
        </div>
      )}

      {/* Progress */}
      <div className="progress">
        {STEPS.map((s, i) => (
          <div
            key={s.id}
            className={`progress-step ${step === s.id ? 'active' : ''} ${STEPS.findIndex(x => x.id === step) > i ? 'done' : ''}`}
            onClick={() => {
              const currentIdx = STEPS.findIndex(x => x.id === step)
              if (i < currentIdx) setStep(s.id)
            }}
          >
            <span className="step-num">{i + 1}</span>
            <span className="step-label">{s.label.split('. ')[1]}</span>
          </div>
        ))}
      </div>

      {error && <div className="error">{error}</div>}

      {/* Step 1: Setup */}
      {step === 'setup' && (
        <section className="step-content">
          <h2>What do you want to create?</h2>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Describe the vibe... e.g., 'Vangelis-style atmospheric piece with lush pads and soaring melody'"
            rows={4}
          />
          <div className="settings">
            <div className="setting">
              <label>Key</label>
              <select value={key} onChange={(e) => setKey(e.target.value)}>
                {KEYS.map(k => <option key={k} value={k}>{k}</option>)}
              </select>
            </div>
            <div className="setting">
              <label>BPM</label>
              <input
                type="text"
                inputMode="numeric"
                value={bpmInput}
                onChange={(e) => {
                  const val = e.target.value.replace(/[^0-9]/g, '')
                  setBpmInput(val)
                  const num = parseInt(val, 10)
                  if (!isNaN(num) && num >= 40 && num <= 200) {
                    setBpm(num)
                  }
                }}
                onBlur={() => {
                  const num = parseInt(bpmInput, 10)
                  if (isNaN(num) || num < 40) {
                    setBpm(40)
                    setBpmInput('40')
                  } else if (num > 200) {
                    setBpm(200)
                    setBpmInput('200')
                  } else {
                    setBpmInput(String(num))
                  }
                }}
                onFocus={(e) => e.target.select()}
                placeholder="40-200"
              />
            </div>
            <div className="setting">
              <label>Bars</label>
              <select value={bars} onChange={(e) => setBars(Number(e.target.value))}>
                {[2, 4, 8, 16].map(b => <option key={b} value={b}>{b}</option>)}
              </select>
            </div>
          </div>
          <button onClick={startSession} disabled={loading || !prompt.trim()} className="primary-btn">
            {loading ? 'Starting...' : 'Start Creating'}
          </button>
        </section>
      )}

      {/* Layer steps */}
      {['pad', 'lead', 'bass'].includes(step) && sample && (
        <section className="step-content">
          <div className="sample-meta">
            <span className="prompt-preview">"{sample.prompt.slice(0, 50)}..."</span>
            <span>{sample.key}</span>
            <span>{sample.bpm} BPM</span>
            <span>{sample.bars} bars</span>
          </div>

          <h2>
            {step === 'pad' && 'Step 2: Generate Chords'}
            {step === 'lead' && 'Step 3: Generate Melody'}
            {step === 'bass' && 'Step 4: Generate Bass'}
          </h2>

          <p className="hint">
            {step === 'pad' && 'The pad creates the harmonic foundation.'}
            {step === 'lead' && 'The melody plays on top of your chords.'}
            {step === 'bass' && 'The bass locks in with chords and melody.'}
          </p>

          {/* Show previous layers */}
          {sample.layers.length > 0 && (
            <div className="layers-preview">
              {sample.layers.map(layer => (
                <div key={layer.id} className={`layer-chip ${layer.sound === currentSound ? 'current' : ''}`}>
                  <span className="chip-sound">{layer.sound}</span>
                  <span className="chip-name">{layer.name}</span>
                  <button
                    onClick={() => openSoundPicker(layer.sound)}
                    className="chip-patch"
                    title="Change sound"
                  >
                    {layer.patch_name || currentSounds[layer.sound]?.name || 'Default'}
                  </button>
                  <button onClick={() => play([layer.sound])} disabled={playing} className="chip-play">▶</button>
                </div>
              ))}
            </div>
          )}

          {/* Current layer */}
          {currentSound && (
            <div className="current-layer">
              {!getLayer(currentSound) ? (
                <button onClick={() => generateLayer(currentSound)} disabled={loading} className="generate-btn large">
                  {loading ? 'Generating...' : `Generate ${currentSound.toUpperCase()}`}
                </button>
              ) : (
                <div className={`layer-result ${loading ? 'regenerating' : ''}`}>
                  {loading && <div className="regen-overlay">Regenerating...</div>}
                  <div className="layer-info">
                    <span className="layer-sound">{currentSound.toUpperCase()}</span>
                    <span className="layer-name">{getLayer(currentSound)?.name}</span>
                    <span className="layer-notes">{getLayer(currentSound)?.notes.length} notes</span>
                  </div>
                  <button
                    onClick={() => openSoundPicker(currentSound)}
                    className="sound-select-btn"
                  >
                    Sound: {getLayer(currentSound)?.patch_name || currentSounds[currentSound]?.name || 'Default'}
                  </button>
                  <div className="layer-actions">
                    <button onClick={() => play([currentSound])} disabled={playing || loading} className="action-btn play">
                      {playing ? '...' : '▶ Play'}
                    </button>
                    <button onClick={stop} disabled={!playing} className="action-btn stop">■</button>
                    <button onClick={() => generateLayer(currentSound, true)} disabled={loading} className="action-btn regen">
                      {loading ? '↻' : '↻ Redo'}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Play all */}
          {sample.layers.length > 1 && (
            <button onClick={() => play()} disabled={playing} className="play-all-btn">
              ▶ Play All Together
            </button>
          )}

          {/* Next */}
          {currentSound && getLayer(currentSound) && (
            <button onClick={nextStep} className="next-btn">
              {step === 'bass' ? 'Finish →' : 'Next →'}
            </button>
          )}
        </section>
      )}

      {/* Complete */}
      {step === 'complete' && sample && (
        <section className="step-content complete">
          <h2>Sample Complete!</h2>
          <div className="sample-meta">
            <span>{sample.key}</span>
            <span>{sample.bpm} BPM</span>
            <span>{sample.bars} bars</span>
          </div>

          <div className="final-layers">
            {sample.layers.map(layer => (
              <div key={layer.id} className="final-layer">
                <span className="fl-sound">{layer.sound.toUpperCase()}</span>
                <span className="fl-name">{layer.name}</span>
                <button
                  onClick={() => openSoundPicker(layer.sound)}
                  className="fl-patch"
                >
                  {layer.patch_name || currentSounds[layer.sound]?.name || 'Default'}
                </button>
                <button onClick={() => play([layer.sound])} disabled={playing} className="fl-play">▶</button>
              </div>
            ))}
          </div>

          <div className="final-controls">
            <button onClick={() => play()} disabled={playing || exporting || improving} className="big-btn play">
              {playing ? 'Playing...' : '▶ Play All'}
            </button>
            <button onClick={stop} disabled={!playing} className="big-btn stop">■ Stop</button>
          </div>

          {/* Improve Section */}
          <div className="improve-section">
            <h3>Improve with AI</h3>
            <p className="improve-hint">Give feedback on each layer and let AI iterate on the patterns</p>

            <div className="feedback-inputs">
              {sample.layers.map(layer => (
                <div key={layer.id} className="feedback-row">
                  <label>{layer.sound.toUpperCase()}</label>
                  <input
                    type="text"
                    placeholder={`e.g., "make it more ${layer.sound === 'pad' ? 'dramatic' : layer.sound === 'lead' ? 'melodic' : 'groovy'}"`}
                    value={feedback[layer.sound] || ''}
                    onChange={(e) => setFeedback(prev => ({ ...prev, [layer.sound]: e.target.value }))}
                    disabled={improving}
                  />
                </div>
              ))}
            </div>

            <button
              onClick={improveLayers}
              disabled={improving || playing || !Object.values(feedback).some(f => f.trim())}
              className="improve-btn"
            >
              {improving ? 'Improving...' : 'Improve'}
            </button>
          </div>

          <div className="final-controls">
            <button onClick={exportAudio} disabled={exporting || playing || improving} className="big-btn export">
              {exporting ? 'Recording...' : '↓ Export WAV'}
            </button>
            <button onClick={exportMidi} disabled={exporting || improving} className="big-btn export">↓ Export MIDI</button>
          </div>

          <button onClick={() => { setSample(null); setStep('setup'); setPrompt(''); setFeedback({ pad: '', lead: '', bass: '' }); }} className="restart-btn">
            Start Over
          </button>
        </section>
      )}

      {/* Sound Picker */}
      {showSoundPicker && (
        <div className="sound-picker-overlay" onClick={() => setShowSoundPicker(null)}>
          <div className="sound-picker" onClick={e => e.stopPropagation()}>
            <div className="sound-picker-header">
              <div className="sound-picker-title">
                <span>{showSoundPicker.toUpperCase()} Sound</span>
                <span className="sound-picker-count">
                  {showFavoritesOnly || showRecentOnly
                    ? `${visiblePatches.length} sounds`
                    : patchTotal
                      ? `${patches.length} of ${patchTotal}`
                      : `${patches.length} sounds`}
                </span>
              </div>
              <button onClick={() => setShowSoundPicker(null)}>×</button>
            </div>
            <div className="sound-picker-controls">
              <div className="sound-picker-search">
                <span className="sound-picker-icon">🔎</span>
                <input
                  type="text"
                  placeholder="Search by name, category, or vibe"
                  value={patchSearch}
                  onChange={(e) => setPatchSearch(e.target.value)}
                />
                {patchSearch && (
                  <button className="sound-picker-clear" onClick={() => setPatchSearch('')}>×</button>
                )}
              </div>
              <div className="sound-picker-filters">
                <div className="sound-picker-chips">
                  {patchCategories.slice(0, 8).map(cat => (
                    <button
                      key={cat.id}
                      className={`sound-chip ${patchCategory === cat.name ? 'active' : ''}`}
                      onClick={() => {
                        setPatchCategory(prev => (prev === cat.name ? '' : cat.name))
                        setPatchSubCategory('')
                      }}
                    >
                      {cat.name}
                    </button>
                  ))}
                </div>
                <select
                  value={patchCategory}
                  onChange={(e) => {
                    setPatchCategory(e.target.value)
                    setPatchSubCategory('')
                  }}
                >
                  <option value="">All Categories</option>
                  {patchCategories.map(cat => (
                    <option key={cat.id} value={cat.name}>{cat.name}</option>
                  ))}
                </select>
                <select
                  value={patchSubCategory}
                  onChange={(e) => setPatchSubCategory(e.target.value)}
                  disabled={!patchSubcategories.length}
                >
                  <option value="">All Subcategories</option>
                  {patchSubcategories.map(sub => (
                    <option key={sub} value={sub}>{sub}</option>
                  ))}
                </select>
                <button
                  className="sound-picker-reset"
                  onClick={() => {
                    setPatchSearch('')
                    setPatchCategory('')
                    setPatchSubCategory('')
                    setShowFavoritesOnly(false)
                    setShowRecentOnly(false)
                    setShowAllSounds(true)
                  }}
                >
                  Reset
                </button>
              </div>
              <div className="sound-picker-toggles">
                <label className="sound-picker-toggle">
                  <input
                    type="checkbox"
                    checked={showAllSounds}
                    onChange={(e) => setShowAllSounds(e.target.checked)}
                  />
                  Show all categories
                </label>
                <label className="sound-picker-toggle">
                  <input
                    type="checkbox"
                    checked={showFavoritesOnly}
                    onChange={(e) => {
                      setShowFavoritesOnly(e.target.checked)
                      if (e.target.checked) setShowRecentOnly(false)
                    }}
                  />
                  Favorites
                </label>
                <label className="sound-picker-toggle">
                  <input
                    type="checkbox"
                    checked={showRecentOnly}
                    onChange={(e) => {
                      setShowRecentOnly(e.target.checked)
                      if (e.target.checked) setShowFavoritesOnly(false)
                    }}
                  />
                  Recent
                </label>
                <select
                  className="sound-picker-sort"
                  value={sortMode}
                  onChange={(e) => setSortMode(e.target.value as 'az' | 'category')}
                >
                  <option value="az">Sort A-Z</option>
                  <option value="category">Sort by Category</option>
                </select>
              </div>
            </div>
            {letterIndex.length > 0 && (
              <div className="sound-picker-letterbar">
                {letterIndex.map(letter => (
                  <button key={letter} onClick={() => jumpToLetter(letter)}>
                    {letter}
                  </button>
                ))}
              </div>
            )}
            <div className="sound-picker-list" ref={soundPickerListRef}>
              {visiblePatches.length === 0 && !patchLoading && (
                <div className="sound-picker-empty">No sounds found. Try a broader search.</div>
              )}
              {visiblePatches.map((patch) => (
                <div
                  key={patch.id}
                  className={`sound-option ${currentSounds[showSoundPicker]?.id === patch.id ? 'selected' : ''}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => selectPatch(patch)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      selectPatch(patch)
                    }
                  }}
                  data-letter={patch.name.trim().charAt(0).toUpperCase()}
                >
                  <span className="sound-option-name">
                    {patch.name}
                    <button
                      className={`sound-favorite ${favoritePatchIds.includes(patch.id) ? 'active' : ''}`}
                      onClick={(e) => {
                        e.stopPropagation()
                        toggleFavorite(patch.id)
                      }}
                      aria-label="Favorite"
                    >
                      ★
                    </button>
                  </span>
                  <span className="sound-option-meta">
                    {patch.category}{patch.sub_category ? ` - ${patch.sub_category}` : ''}
                  </span>
                </div>
              ))}
            </div>
            <div className="sound-picker-footer">
              <button
                className="sound-picker-load"
                onClick={loadMorePatches}
                disabled={patchLoading || (patchTotal !== null && patches.length >= patchTotal)}
              >
                {patchLoading ? 'Loading...' : patchTotal !== null && patches.length >= patchTotal ? 'All loaded' : 'Load more'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
