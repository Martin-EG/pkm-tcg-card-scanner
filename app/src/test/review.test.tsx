import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { STORAGE_KEY } from '../store'
import type { IdentifiedCard } from '../types'
import { card, sessionMXN, settingsMXN } from './fixtures'

const ok = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))

const lowConfidence: IdentifiedCard = {
  index: 0, language: 'en', confident: true, needs_review: true, ocr_used: true,
  detected_language: 'en', warning: null, crop_url: '/scans/3/card_0.jpg',
  candidates: [
    { id: 'me01-060', name: 'Mega Gardevoir ex', set: 'me01', set_name: 'Mega Evolution', number: '060', language: 'en', confidence: 0.79, image_url: '/images/a.webp' },
    { id: 'me04-048', name: 'Mega Gallade ex', set: 'me04', set_name: 'Chaos Rising', number: '048', language: 'en', confidence: 0.77, image_url: '/images/b.webp' },
    { id: 'me02.5-089', name: 'Mega Gardevoir ex', set: 'me02.5', set_name: 'Ascended Heroes', number: '089', language: 'en', confidence: 0.7, image_url: '/images/c.webp' },
  ],
}

afterEach(() => vi.unstubAllGlobals())

describe('low-confidence card', () => {
  it('shows the 3 options, sends a correction for the one picked, and adds it', async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
      settings: settingsMXN, session: sessionMXN([]), extras: {}, queue: [],
      reviews: [{ key: '3-0', scan_id: 3, card: lowConfidence }],
    }))
    const gallade = card({ id: 9, card_id: 'me04-048', name: 'Mega Gallade ex', set_name: 'Chaos Rising', number: '048' })
    const calls: { url: string; method: string; body?: unknown }[] = []
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push({ url, method, body: init?.body ? JSON.parse(init.body as string) : undefined })
      if (url === '/settings') return ok(settingsMXN)
      if (url === '/sessions/7' && method === 'GET') return ok(sessionMXN([]))
      if (url === '/corrections') return ok({ correction_id: 1 })
      if (url === '/sessions/7/cards') return ok(gallade)
      return Promise.reject(new Error(`unexpected ${method} ${url}`))
    }))
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: /Cartas/ }))

    expect(screen.getByText('¿Cuál es?')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Mega G/ })).toHaveLength(3)
    await user.click(screen.getByRole('button', { name: /Mega Gallade ex/ }))

    await waitFor(() => expect(screen.queryByText('¿Cuál es?')).toBeNull())
    expect(calls.find((c) => c.url === '/corrections')?.body).toEqual(
      { scan_id: 3, card_index: 0, card_id: 'me04-048', language: 'en' })
    expect(calls.find((c) => c.url === '/sessions/7/cards')?.body).toMatchObject({ card_id: 'me04-048', scan_id: 3, card_index: 0 })
    expect(screen.getByRole('heading', { name: 'Mega Gallade ex' })).toBeInTheDocument()
  })
})
