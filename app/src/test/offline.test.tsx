import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { STORAGE_KEY } from '../store'
import { card, sessionMXN, settingsMXN } from './fixtures'

function seed() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    settings: settingsMXN, session: sessionMXN(), extras: {}, reviews: [], queue: [],
  }))
}

function stored() {
  return JSON.parse(localStorage.getItem(STORAGE_KEY)!)
}

const ok = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status: 200 }))

afterEach(() => vi.unstubAllGlobals())

describe('server connection drops', () => {
  it('shows a notice and keeps the session on the phone', async () => {
    seed()
    vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))))
    const user = userEvent.setup()
    render(<App />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Sin conexión con el servidor')
    expect(screen.getByRole('alert')).toHaveTextContent('Tu compra está guardada en este teléfono')
    expect(screen.getByRole('button', { name: /Sin conexión/ })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Resumen' }))
    expect(screen.getByTestId('total-cash')).toHaveTextContent('$1,432.62')
    expect(stored().session.id).toBe(7)
  })

  it('queues changes made offline and sends them when the server is back', async () => {
    seed()
    const fetchMock = vi.fn<(...args: unknown[]) => Promise<Response>>(() => Promise.reject(new TypeError('Failed to fetch')))
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    render(<App />)
    await screen.findByRole('alert')

    await user.click(screen.getByRole('button', { name: /Cartas/ }))
    await user.click(screen.getByRole('button', { name: 'LP' }))
    await waitFor(() => expect(stored().queue).toEqual([{ sessionId: 7, cardId: 1, changes: { condition: 'LP' } }]))
    expect(screen.getByRole('button', { name: 'LP' })).toHaveClass('on')  // shown right away
    expect(screen.getByRole('alert')).toHaveTextContent('1 cambio se enviará al reconectar')

    // Server comes back.
    const lp = card({ condition: 'LP', cash_offer: 1217.73, credit_offer: 1289.36 })
    fetchMock.mockImplementation((...args: unknown[]) => {
      const url = String(args[0])
      const method = (args[1] as RequestInit | undefined)?.method ?? 'GET'
      if (url === '/settings') return ok(settingsMXN)
      if (url === '/sessions/7/cards/1' && method === 'PATCH') return ok(lp)
      if (url === '/sessions/7') return ok({ ...sessionMXN([lp]), totals: { ...sessionMXN().totals, cash: 1217.73, credit: 1289.36 } })
      return Promise.reject(new Error(`unexpected ${method} ${url}`))
    })
    await user.click(within(screen.getByRole('alert')).getByRole('button', { name: 'Reintentar' }))

    await waitFor(() => expect(screen.queryByText(/Sin conexión con el servidor/)).toBeNull())
    expect(stored().queue).toEqual([])
    const patch = fetchMock.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === 'PATCH')!
    expect(JSON.parse((patch[1] as RequestInit).body as string)).toEqual({ condition: 'LP' })
    await user.click(screen.getByRole('button', { name: 'Resumen' }))
    expect(screen.getByTestId('total-cash')).toHaveTextContent('$1,217.73')
  })
})
