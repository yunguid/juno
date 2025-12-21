const DEFAULT_WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}`

export const API_URL = import.meta.env.VITE_API_URL || ''
export const WS_URL = import.meta.env.VITE_WS_URL || DEFAULT_WS_URL
