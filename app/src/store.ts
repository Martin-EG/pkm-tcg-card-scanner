import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ServerError, ServerUnreachable } from './api'
import type {
  Candidate, CardExtras, CardPatch, IdentifiedCard, PendingReview, QueuedPatch, Session, SessionCard, Settings,
} from './types'

export const STORAGE_KEY = 'tcg-scanner-state-v1'
const POLL_OFFLINE_MS = 5000
const POLL_ONLINE_MS = 30000

export interface CounterState {
  settings: Settings | null
  session: Session | null
  extras: Record<number, CardExtras>
  reviews: PendingReview[]
  queue: QueuedPatch[]
}

const EMPTY: CounterState = { settings: null, session: null, extras: {}, reviews: [], queue: [] }

export function loadState(): CounterState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? { ...EMPTY, ...JSON.parse(raw) } : EMPTY
  } catch {
    return EMPTY
  }
}

function saveState(s: CounterState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(s))
  } catch {
    /* storage full or blocked: the session still lives on the server */
  }
}

function withCard(session: Session, card: SessionCard): Session {
  const exists = session.cards.some((c) => c.id === card.id)
  return { ...session, cards: exists ? session.cards.map((c) => (c.id === card.id ? card : c)) : [...session.cards, card] }
}

export function useCounter() {
  const [state, setState] = useState<CounterState>(loadState)
  const [online, setOnline] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const stateRef = useRef(state)
  stateRef.current = state

  const update = useCallback((fn: (s: CounterState) => CounterState) => {
    setState((prev) => {
      const next = fn(prev)
      saveState(next)
      return next
    })
  }, [])

  const handle = useCallback((e: unknown) => {
    if (e instanceof ServerUnreachable) {
      setOnline(false)
      setMessage(null)
    } else if (e instanceof ServerError) {
      setMessage(e.message)
    } else {
      setMessage('Algo salió mal. Intenta de nuevo.')
    }
  }, [])

  // Send queued changes in order, then refresh the session from the server.
  const flush = useCallback(async () => {
    const { queue, session } = stateRef.current
    for (const q of queue) {
      const card = await api.patchCard(q.sessionId, q.cardId, q.changes)
      update((s) => ({
        ...s,
        queue: s.queue.slice(1),
        session: s.session && s.session.id === q.sessionId ? withCard(s.session, card) : s.session,
      }))
    }
    if (session) {
      const fresh = await api.getSession(session.id)
      update((s) => ({ ...s, session: fresh }))
    }
  }, [update])

  const check = useCallback(async () => {
    try {
      const settings = await api.settings()
      update((s) => ({ ...s, settings }))
      setOnline(true)
      await flush()
    } catch (e) {
      handle(e)
    }
  }, [flush, handle, update])

  useEffect(() => {
    check()
  }, [check])

  useEffect(() => {
    const t = setInterval(check, online ? POLL_ONLINE_MS : POLL_OFFLINE_MS)
    return () => clearInterval(t)
  }, [check, online])

  const ensureSession = useCallback(async (): Promise<Session> => {
    if (stateRef.current.session) return stateRef.current.session
    const session = await api.createSession()
    update((s) => ({ ...s, session, extras: {}, reviews: [] }))
    return session
  }, [update])

  const addCard = useCallback(async (scanId: number, card: IdentifiedCard, chosen: Candidate) => {
    const session = await ensureSession()
    const added = await api.addCard(session.id, {
      card_id: chosen.id,
      printed_language: card.detected_language && card.detected_language !== chosen.language ? card.detected_language : null,
      scan_id: scanId,
      card_index: card.index,
    })
    update((s) => ({
      ...s,
      session: s.session ? withCard(s.session, added) : s.session,
      extras: { ...s.extras, [added.id]: { crop_url: card.crop_url, image_url: chosen.image_url, warning: card.warning } },
    }))
  }, [ensureSession, update])

  const scan = useCallback(async (photo: Blob) => {
    setBusy('Identificando…')
    setMessage(null)
    try {
      await ensureSession()
      const res = await api.identify(photo)
      for (const card of res.cards) {
        if (card.confident && !card.needs_review && card.candidates.length) {
          await addCard(res.scan_id, card, card.candidates[0])
        } else {
          update((s) => ({ ...s, reviews: [...s.reviews, { key: `${res.scan_id}-${card.index}`, scan_id: res.scan_id, card }] }))
        }
      }
      setOnline(true)
      return res
    } catch (e) {
      handle(e)
      return null
    } finally {
      setBusy(null)
    }
  }, [addCard, ensureSession, handle, update])

  // The employee picked one of the 3 options (or none of them).
  const resolveReview = useCallback(async (review: PendingReview, chosen: Candidate | null) => {
    try {
      if (chosen) {
        if (chosen.id !== review.card.candidates[0]?.id) {
          await api.correction(review.scan_id, review.card.index, chosen.id, chosen.language)
        }
        await addCard(review.scan_id, review.card, chosen)
      }
      update((s) => ({ ...s, reviews: s.reviews.filter((r) => r.key !== review.key) }))
    } catch (e) {
      handle(e)
    }
  }, [addCard, handle, update])

  const changeCard = useCallback(async (cardId: number, changes: CardPatch) => {
    const session = stateRef.current.session
    if (!session) return
    // Show the change right away; the server recalculates the offer.
    update((s) => ({
      ...s,
      session: s.session && {
        ...s.session,
        cards: s.session.cards.map((c) => (c.id === cardId ? {
          ...c,
          ...(changes.condition !== undefined ? { condition: changes.condition } : {}),
          ...(changes.variant !== undefined ? { variant: changes.variant } : {}),
          ...(changes.accepted !== undefined ? { accepted: changes.accepted } : {}),
        } : c)),
      },
    }))
    if (stateRef.current.queue.length) {
      update((s) => ({ ...s, queue: [...s.queue, { sessionId: session.id, cardId, changes }] }))
      return
    }
    try {
      const card = await api.patchCard(session.id, cardId, changes)
      const fresh = await api.getSession(session.id)
      update((s) => ({ ...s, session: s.session && withCard(fresh, card) }))
    } catch (e) {
      if (e instanceof ServerUnreachable) {
        update((s) => ({ ...s, queue: [...s.queue, { sessionId: session.id, cardId, changes }] }))
      }
      handle(e)
    }
  }, [handle, update])

  const newSession = useCallback(() => {
    update((s) => ({ ...EMPTY, settings: s.settings }))
    setMessage(null)
  }, [update])

  return { state, online, busy, message, scan, resolveReview, changeCard, newSession, retry: check, dismissMessage: () => setMessage(null) }
}

export type Counter = ReturnType<typeof useCounter>
