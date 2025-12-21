import type { Step } from './types'

export const STEPS: { id: Step; label: string; sound?: 'pad' | 'lead' | 'bass' }[] = [
  { id: 'setup', label: '1. Describe' },
  { id: 'pad', label: '2. Chords', sound: 'pad' },
  { id: 'lead', label: '3. Melody', sound: 'lead' },
  { id: 'bass', label: '4. Bass', sound: 'bass' },
  { id: 'complete', label: '5. Export' },
]

export const KEYS = [
  'C major', 'C minor', 'D major', 'D minor',
  'E major', 'E minor', 'F major', 'F minor',
  'G major', 'G minor', 'A major', 'A minor',
  'Bb major', 'Bb minor', 'Eb major', 'Eb minor',
]
