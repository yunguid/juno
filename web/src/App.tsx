import { useState, useEffect, useRef, useCallback } from 'react'
import './App.css'
import { KEYS, STEPS } from './constants'
import { WS_URL } from './config'
import { useAudioStream } from './hooks/useAudioStream'
import type { LLMConfig, Patch, PatchCategory, Sample, SoundType, Step } from './types'
import {
  exportAudio as exportAudioFile,
  exportMidi as exportMidiFile,
  fetchLlmConfig,
  fetchPatches as fetchPatchesFromApi,
  generateLayer as generateLayerFromApi,
  getCurrentSounds,
  improveLayers as improveLayersFromApi,
  playSample,
  selectPatch as selectPatchFromApi,
  startSession as startSessionFromApi,
  stopSample,
  updateLlmConfig as updateLlmConfigFromApi,
} from './services/api'

// #region agent log
const clientDbg = (
  hypothesisId: string,
  location: string,
  message: string,
  data: Record<string, unknown> = {},
  runId: string = 'run1'
) => {
  if (!import.meta.env.PROD) return
  fetch('/api/_client_log', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      sessionId: 'debug-session',
      runId,
      hypothesisId,
      location,
      message,
      data,
      timestamp: Date.now(),
    }),
  }).catch(() => {})
}
// #endregion agent log

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
  const [feedback, setFeedback] = useState<Record<SoundType, string>>({ pad: '', lead: '', bass: '' })
  const [improving, setImproving] = useState(false)
  const [showSoundPicker, setShowSoundPicker] = useState<SoundType | null>(null)
  const [patches, setPatches] = useState<Patch[]>([])
  const [patchTotal, setPatchTotal] = useState<number | null>(null)
  const [patchCategories, setPatchCategories] = useState<PatchCategory[]>([])
  const [patchSearch, setPatchSearch] = useState('')
  const [patchCategory, setPatchCategory] = useState('')
  const [patchOffset, setPatchOffset] = useState(0)
  const [patchLoading, setPatchLoading] = useState(false)
  const patchLimit = 60
  const [currentSounds, setCurrentSounds] = useState<Record<SoundType, Patch | null>>({
    bass: null,
    pad: null,
    lead: null,
  })
  const wsRef = useRef<WebSocket | null>(null)
  
  // Audio streaming for real-time playback from Montage
  const { startStreaming, stopStreaming } = useAudioStream(WS_URL)

  // Fetch LLM config on mount
  useEffect(() => {
    fetchLlmConfig()
      .then(setLlmConfig)
      .catch(console.error)
  }, [])

  const updateLlmConfig = async (provider?: string, model?: string) => {
    try {
      const updated = await updateLlmConfigFromApi(provider, model)
      setLlmConfig(updated)
    } catch (e) {
      console.error('Failed to update LLM config:', e)
    }
  }

  useEffect(() => {
    const ws = new WebSocket(`${WS_URL}/ws`)
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
        startStreaming().catch((e) => console.warn('Audio streaming unavailable:', e))
      } else if (data.type === 'playback_complete' || data.type === 'playback_stopped') {
        setPlaying(false)
        // Stop audio streaming when playback ends
        stopStreaming()
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
  }, [startStreaming, stopStreaming])

  const startSession = async () => {
    if (!prompt.trim()) return
    setLoading(true)
    setError(null)
    try {
      const newSample = await startSessionFromApi(prompt, key, bpm, bars)
      setSample(newSample)
      setStep('pad')
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to start')
    } finally {
      setLoading(false)
    }
  }

  const generateLayer = async (sound: SoundType, isRedo = false) => {
    // Stop playback first if regenerating
    if (isRedo && playing) {
      await stop()
    }
    setLoading(true)
    setError(null)
    try {
      const updatedSample = await generateLayerFromApi(sound)
      setSample(updatedSample)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Generation failed')
    } finally {
      setLoading(false)
    }
  }

  const play = async (layers?: SoundType[]) => {
    // #region agent log
    clientDbg('C0', 'web/src/App.tsx:play', 'play_clicked', { layers: layers ?? null })
    // #endregion agent log

    // Start audio streaming (best-effort; don't block MIDI playback if streaming fails)
    startStreaming().catch((e) => console.warn('Audio streaming unavailable:', e))

    try {
      await playSample(layers)
    } catch (e) {
      console.error('Play failed:', e)
      stopStreaming()
    }
  }

  const stop = async () => {
    try {
      await stopSample()
      stopStreaming()
    } catch (e) {
      console.error('Stop failed:', e)
    }
  }

  const exportMidi = async () => {
    try {
      const data = await exportMidiFile()
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
      const data = await exportAudioFile()
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
      const updatedSample = await improveLayersFromApi(feedback)
      setSample(updatedSample)
      setFeedback({ pad: '', lead: '', bass: '' }) // Clear feedback after success
    } catch (e) {
      console.error('Improve failed:', e)
      setError(e instanceof Error ? e.message : 'Failed to improve')
    } finally {
      setImproving(false)
    }
  }

  const getLayer = (sound: SoundType) => sample?.layers.find(l => l.sound === sound)

  // Sound selection functions
  const fetchPatches = useCallback(async (soundType: SoundType, append = false, offsetOverride?: number) => {
    try {
      setPatchLoading(true)
      const offset = typeof offsetOverride === 'number' ? offsetOverride : append ? patchOffset : 0
      const data = await fetchPatchesFromApi(soundType, {
        search: patchSearch.trim() || undefined,
        category: patchCategory || undefined,
        limit: patchLimit,
        offset,
      })
      setPatchCategories(data.categories)
      setPatchTotal(data.total)
      setPatches(prev => (append ? [...prev, ...data.patches] : data.patches))
    } catch (e) {
      console.error('Failed to fetch patches:', e)
    } finally {
      setPatchLoading(false)
    }
  }, [patchCategory, patchOffset, patchSearch])

  const openSoundPicker = useCallback((soundType: SoundType) => {
    setShowSoundPicker(soundType)
    setPatchSearch('')
    setPatchCategory('')
    setPatchOffset(0)
  }, [])

  const selectPatch = async (patch: Patch) => {
    if (!showSoundPicker) return
    try {
      await selectPatchFromApi(showSoundPicker, patch.id)
      setCurrentSounds(prev => ({ ...prev, [showSoundPicker]: patch }))
      setShowSoundPicker(null)
    } catch (e) {
      console.error('Select failed:', e)
    }
  }

  useEffect(() => {
    if (!showSoundPicker) return
    const timeout = setTimeout(() => {
      setPatchOffset(0)
      fetchPatches(showSoundPicker, false)
    }, 200)
    return () => clearTimeout(timeout)
  }, [fetchPatches, showSoundPicker, patchSearch, patchCategory])

  const loadMorePatches = useCallback(() => {
    if (!showSoundPicker || patchLoading) return
    const nextOffset = patchOffset + patchLimit
    setPatchOffset(nextOffset)
    fetchPatches(showSoundPicker, true, nextOffset)
  }, [fetchPatches, patchLimit, patchLoading, patchOffset, showSoundPicker])

  // Fetch current sounds on mount
  useEffect(() => {
    getCurrentSounds()
      .then((data) => setCurrentSounds({ bass: data.bass, pad: data.pad, lead: data.lead }))
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
                  {patches.length} / {patchTotal ?? '…'}
                </span>
              </div>
              <button onClick={() => setShowSoundPicker(null)}>×</button>
            </div>
            <div className="sound-picker-controls">
              <div className="sound-picker-search">
                <span className="sound-picker-icon">⌕</span>
                <input
                  type="text"
                  placeholder="Search sounds…"
                  value={patchSearch}
                  onChange={(e) => setPatchSearch(e.target.value)}
                />
                {patchSearch && (
                  <button
                    className="sound-picker-clear"
                    onClick={() => setPatchSearch('')}
                    aria-label="Clear search"
                  >
                    ×
                  </button>
                )}
              </div>
              <div className="sound-picker-filters">
                <select
                  value={patchCategory}
                  onChange={(e) => setPatchCategory(e.target.value)}
                >
                  <option value="">All categories</option>
                  {patchCategories.map((cat) => (
                    <option key={cat.id} value={cat.name}>
                      {cat.name} ({cat.count})
                    </option>
                  ))}
                </select>
                <button
                  className="sound-picker-reset"
                  onClick={() => {
                    setPatchSearch('')
                    setPatchCategory('')
                  }}
                >
                  Reset
                </button>
              </div>
            </div>
            <div className="sound-picker-list">
              {patchLoading && patches.length === 0 && (
                <div className="sound-picker-empty">Loading sounds…</div>
              )}
              {!patchLoading && patches.length === 0 && (
                <div className="sound-picker-empty">No matches. Try another search.</div>
              )}
              {patches.map(patch => (
                <button
                  key={patch.id}
                  className={`sound-option ${currentSounds[showSoundPicker]?.id === patch.id ? 'selected' : ''}`}
                  onClick={() => selectPatch(patch)}
                >
                  <span className="sound-option-name">{patch.name}</span>
                  <span className="sound-option-meta">{patch.category}</span>
                </button>
              ))}
            </div>
            {patches.length < patchTotal && (
              <div className="sound-picker-footer">
                <button
                  className="sound-picker-load"
                  onClick={loadMorePatches}
                  disabled={patchLoading}
                >
                  {patchLoading ? 'Loading…' : 'Load more'}
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default App
