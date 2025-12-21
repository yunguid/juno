export type SoundType = 'bass' | 'pad' | 'lead'

export type Step = 'setup' | 'pad' | 'lead' | 'bass' | 'complete'

export interface Note {
  pitch: string | string[]
  start: number
  duration: number
  velocity: number
}

export interface Layer {
  id: string
  name: string
  sound: SoundType
  notes: Note[]
  muted: boolean
  volume: number
  portamento?: boolean
  portamento_time?: number
  patch_id?: string
  patch_name?: string
}

export interface Patch {
  id: string
  name: string
  category: string
  sub_category?: string | null
  bank_msb: number
  bank_lsb: number
  program: number
  tags: string[]
}

export interface PatchCategory {
  id: string
  name: string
  count: number
}

export interface Sample {
  id: string
  name: string
  prompt: string
  key: string
  bpm: number
  bars: number
  layers: Layer[]
}

export interface LLMConfig {
  provider: string
  model: string
  available_providers: string[]
  available_models: Record<string, string[]>
  default_models: Record<string, string>
}
