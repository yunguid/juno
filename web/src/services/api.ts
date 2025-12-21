import { API_URL } from '../config'
import type { LLMConfig, Patch, PatchCategory, Sample, SoundType } from '../types'

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init)
  if (!res.ok) {
    let detail = ''
    try {
      const data = await res.json()
      detail = typeof data?.detail === 'string' ? data.detail : ''
    } catch {
      detail = ''
    }
    const message = detail || `Request failed (${res.status})`
    throw new Error(message)
  }
  return res.json() as Promise<T>
}

export async function fetchLlmConfig(): Promise<LLMConfig> {
  return requestJson(`${API_URL}/api/llm/config`)
}

export async function updateLlmConfig(provider?: string, model?: string): Promise<LLMConfig> {
  await requestJson(`${API_URL}/api/llm/config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, model }),
  })
  return fetchLlmConfig()
}

export async function startSession(prompt: string, key: string, bpm: number, bars: number): Promise<Sample> {
  const data = await requestJson<{ sample: Sample }>(`${API_URL}/api/session/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, key, bpm, bars }),
  })
  return data.sample
}

export async function generateLayer(sound: SoundType): Promise<Sample> {
  const data = await requestJson<{ sample: Sample }>(`${API_URL}/api/session/generate-layer`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sound }),
  })
  return data.sample
}

export async function improveLayers(feedback: Record<SoundType, string>): Promise<Sample> {
  const data = await requestJson<{ sample: Sample }>(`${API_URL}/api/session/improve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ feedback }),
  })
  return data.sample
}

export async function playSample(layers?: SoundType[]): Promise<void> {
  await requestJson(`${API_URL}/api/play`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(layers || null),
  })
}

export async function stopSample(): Promise<void> {
  await requestJson(`${API_URL}/api/stop`, { method: 'POST' })
}

export async function exportMidi(): Promise<{ data: string; filename: string }> {
  return requestJson(`${API_URL}/api/export`)
}

export async function exportAudio(): Promise<{ data: string; filename: string }> {
  return requestJson(`${API_URL}/api/export/audio`)
}

export async function fetchPatches(
  soundType: SoundType,
  params: {
    search?: string
    category?: string
    subCategory?: string
    limit?: number
    offset?: number
    allSounds?: boolean
  } = {}
): Promise<{ patches: Patch[]; total: number; categories: PatchCategory[]; subcategories: string[] }> {
  const url = new URL(`${API_URL}/api/patches`, window.location.origin)
  url.searchParams.set('sound_type', soundType)
  if (params.search) url.searchParams.set('search', params.search)
  if (params.category) url.searchParams.set('category', params.category)
  if (params.subCategory) url.searchParams.set('sub_category', params.subCategory)
  if (typeof params.limit === 'number') url.searchParams.set('limit', String(params.limit))
  if (typeof params.offset === 'number') url.searchParams.set('offset', String(params.offset))
  if (params.allSounds) url.searchParams.set('all_sounds', 'true')
  return requestJson(url.toString())
}

export async function selectPatch(soundType: SoundType, patchId: string): Promise<void> {
  await requestJson(`${API_URL}/api/sound/${soundType}/select`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ patch_id: patchId }),
  })
}

export async function getCurrentSounds(): Promise<Record<SoundType, Patch | null>> {
  return requestJson(`${API_URL}/api/sounds/current`)
}
