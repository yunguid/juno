import { useState, useEffect, useRef } from 'react'
import './App.css'

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

const API_URL = 'http://localhost:8000'

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
  const wsRef = useRef<WebSocket | null>(null)

  // Fetch LLM config on mount
  useEffect(() => {
    fetch(`${API_URL}/api/llm/config`)
      .then(res => res.json())
      .then(setLlmConfig)
      .catch(console.error)
  }, [])

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
    const ws = new WebSocket(`ws://localhost:8000/ws`)
    ws.onopen = () => {
      console.log('Connected to server')
      setError(null) // Clear any previous connection errors
    }
    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'sample_updated') {
        setSample(data.sample)
        setLoading(false)
      } else if (data.type === 'playback_started') {
        setPlaying(true)
      } else if (data.type === 'playback_complete' || data.type === 'playback_stopped') {
        setPlaying(false)
      }
    }
    ws.onclose = () => {
      // Only show error if we're not intentionally closing
      if (wsRef.current === ws) {
        setError('Disconnected from server')
      }
    }
    wsRef.current = ws
    return () => {
      wsRef.current = null
      ws.close()
    }
  }, [])

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
      await fetch(`${API_URL}/api/play`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(layers || null)
      })
    } catch (e) {
      console.error('Play failed:', e)
    }
  }

  const stop = async () => {
    try {
      await fetch(`${API_URL}/api/stop`, { method: 'POST' })
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
    </div>
  )
}

export default App
