import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { UNDO_MS, UndoToast } from '../components/UndoToast'
import { STORAGE_KEY } from '../store'
import type { Session } from '../types'
import { card, sessionMXN, settingsMXN } from './fixtures'

const gastly = card()
const charmander = card({ id: 2, card_id: 'sv03.5-004', name: 'Charmander', cash_offer: 157.25, credit_offer: 166.5 })
const both = (): Session => ({ ...sessionMXN([gastly, charmander]),
  totals: { cash: 1589.87, credit: 1683.4, cards_buying: 2, cards_not_buying: 0, cards_without_price: 0 } })
const onlyCharmander = (): Session => ({ ...sessionMXN([charmander]),
  totals: { cash: 157.25, credit: 166.5, cards_buying: 1, cards_not_buying: 0, cards_without_price: 0 } })

function seed(queue: unknown[] = []) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ settings: settingsMXN, session: both(), extras: {}, reviews: [], queue, undo: null }))
}
const stored = () => JSON.parse(localStorage.getItem(STORAGE_KEY)!)
const ok = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))
const cardNames = () => screen.getAllByRole('heading', { level: 3 }).map((h) => h.textContent)

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('removing a card', () => {
  it('removes it right away and "Deshacer" puts it back in place', async () => {
    seed()
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push(`${method} ${url}`)
      if (url === '/settings') return ok(settingsMXN)
      if (url === '/sessions/7' && method === 'GET') return ok(calls.some((c) => c.startsWith('DELETE')) && !calls.some((c) => c.includes('restore')) ? onlyCharmander() : both())
      if (url === '/sessions/7/cards/1' && method === 'DELETE') return ok(onlyCharmander())
      if (url === '/sessions/7/cards/1/restore') return ok(both())
      return Promise.reject(new Error(`unexpected ${method} ${url}`))
    }))
    const user = userEvent.setup()
    render(<App />)
    await user.click(screen.getByRole('button', { name: /Cartas/ }))
    expect(cardNames()).toEqual(['Charmander', 'Gastly'])  // newest first

    await user.click(screen.getByRole('button', { name: 'Quitar Gastly de la compra' }))
    expect(cardNames()).toEqual(['Charmander'])
    expect(screen.getByRole('status')).toHaveTextContent('Quitaste Gastly')
    await waitFor(() => expect(calls).toContain('DELETE /sessions/7/cards/1'))

    await user.click(within(screen.getByRole('status')).getByRole('button', { name: 'Deshacer' }))
    expect(cardNames()).toEqual(['Charmander', 'Gastly'])
    expect(screen.queryByRole('status')).toBeNull()
    await waitFor(() => expect(calls).toContain('POST /sessions/7/cards/1/restore'))
  })

  it('works offline: the removal is queued, totals update, and undo just drops it', async () => {
    seed()
    const fetchMock = vi.fn<(...args: unknown[]) => Promise<Response>>(() => Promise.reject(new TypeError('Failed to fetch')))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)
    await screen.findByText(/Sin conexión con el servidor/)
    await user.click(screen.getByRole('button', { name: /Cartas/ }))

    await user.click(screen.getByRole('button', { name: 'Quitar Gastly de la compra' }))
    await waitFor(() => expect(stored().queue).toEqual([{ kind: 'remove', sessionId: 7, cardId: 1 }]))
    expect(stored().session.totals.cash).toBe(157.25)
    await user.click(screen.getByRole('button', { name: 'Resumen' }))
    expect(screen.getByTestId('total-cash')).toHaveTextContent('$157.25')

    const callsBefore = fetchMock.mock.calls.length
    await user.click(screen.getByRole('button', { name: 'Deshacer' }))
    expect(stored().queue).toEqual([])
    expect(stored().session.cards.map((c: { id: number }) => c.id)).toEqual([1, 2])
    expect(screen.getByTestId('total-cash')).toHaveTextContent('$1,589.87')
    const restoreCalls = fetchMock.mock.calls.slice(callsBefore).filter((c) => String(c[0]).includes('restore'))
    expect(restoreCalls).toEqual([])  // never reached the server, nothing to restore
  })

  it('sends a queued removal when the server is back', async () => {
    seed([{ kind: 'remove', sessionId: 7, cardId: 1 }])
    const calls: string[] = []
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      calls.push(`${method} ${url}`)
      if (url === '/settings') return ok(settingsMXN)
      if (url === '/sessions/7/cards/1' && method === 'DELETE') return ok(onlyCharmander())
      if (url === '/sessions/7') return ok(onlyCharmander())
      return Promise.reject(new Error(`unexpected ${method} ${url}`))
    }))
    render(<App />)
    await waitFor(() => expect(stored().queue).toEqual([]))
    expect(calls).toContain('DELETE /sessions/7/cards/1')
    expect(stored().session.cards.map((c: { id: number }) => c.id)).toEqual([2])
  })
})

describe('undo notice', () => {
  it('closes itself after a few seconds', () => {
    vi.useFakeTimers()
    const onTimeout = vi.fn()
    render(<UndoToast removed={{ card: gastly, position: 0 }} onUndo={() => {}} onTimeout={onTimeout} />)
    expect(screen.getByRole('status')).toHaveTextContent('Quitaste Gastly')
    act(() => { vi.advanceTimersByTime(UNDO_MS - 1) })
    expect(onTimeout).not.toHaveBeenCalled()
    act(() => { vi.advanceTimersByTime(1) })
    expect(onTimeout).toHaveBeenCalledTimes(1)
  })
})
