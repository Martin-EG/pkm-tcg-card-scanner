import type { CardPatch, IdentifyResponse, Session, SessionCard, Settings } from './types'

// The app is served by the shop server itself, so API calls go to the same origin.
const BASE = ''

export class ServerUnreachable extends Error {
  constructor() {
    super('Sin conexión con el servidor')
  }
}

export class ServerError extends Error {
  status: number
  code: string | undefined
  constructor(status: number, message: string, code?: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 20000): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  let res: Response
  try {
    res = await fetch(BASE + path, { ...init, signal: controller.signal })
  } catch {
    throw new ServerUnreachable()
  } finally {
    clearTimeout(timer)
  }
  if (!res.ok) {
    let message = `Error ${res.status}`
    let code: string | undefined
    try {
      const body = await res.json()
      message = body.message ?? body.detail ?? message
      code = body.error
    } catch {
      /* not JSON */
    }
    throw new ServerError(res.status, message, code)
  }
  return res.json() as Promise<T>
}

const json = (body: unknown): RequestInit => ({
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const api = {
  settings: () => request<Settings>('/settings', {}, 5000),
  identify: (photo: Blob) => {
    const form = new FormData()
    form.append('photo', photo, 'foto.jpg')
    return request<IdentifyResponse>('/identify', { method: 'POST', body: form }, 60000)
  },
  correction: (scan_id: number, card_index: number, card_id: string, language = 'en') =>
    request('/corrections', { method: 'POST', ...json({ scan_id, card_index, card_id, language }) }),
  createSession: () => request<Session>('/sessions', { method: 'POST' }),
  getSession: (id: number) => request<Session>(`/sessions/${id}`),
  addCard: (sessionId: number, body: {
    card_id: string; printed_language?: string | null; scan_id?: number; card_index?: number
  }) => request<SessionCard>(`/sessions/${sessionId}/cards`, { method: 'POST', ...json(body) }),
  patchCard: (sessionId: number, cardId: number, changes: CardPatch) =>
    request<SessionCard>(`/sessions/${sessionId}/cards/${cardId}`, { method: 'PATCH', ...json(changes) }),
}
