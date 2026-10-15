import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { DISMISS_KEY, InstallHint, type Platform } from '../components/InstallHint'

const IPHONE_SAFARI = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1'
const IPHONE_CHROME = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/130.0 Mobile/15E148 Safari/604.1'
const IPAD_DESKTOP_MODE = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15'
const ANDROID = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36'

const iphone = (over: Partial<Platform> = {}): Platform => ({
  userAgent: IPHONE_SAFARI, platform: 'iPhone', maxTouchPoints: 5, standalone: false, secure: true, ...over,
})

describe('iPhone install notice', () => {
  it('shows the Safari steps on an iPhone that has not installed the app', () => {
    render(<InstallHint platform={iphone()} />)
    expect(screen.getByRole('complementary', { name: 'Instalar la app' })).toBeInTheDocument()
    expect(screen.getByText(/Agregar a pantalla de inicio/)).toBeInTheDocument()
    expect(screen.getByText('Compartir')).toBeInTheDocument()
    expect(screen.queryByText(/sin candado/)).toBeNull()
  })

  it('is gone once the app runs from the home screen', () => {
    render(<InstallHint platform={iphone({ standalone: true })} />)
    expect(screen.queryByText(/Instala la app/)).toBeNull()
  })

  it('stays closed after "Entendido", also on the next visit', async () => {
    const user = userEvent.setup()
    const { unmount } = render(<InstallHint platform={iphone()} />)
    await user.click(screen.getByRole('button', { name: 'Entendido' }))
    expect(screen.queryByText(/Instala la app/)).toBeNull()
    expect(localStorage.getItem(DISMISS_KEY)).toBe('1')
    unmount()
    render(<InstallHint platform={iphone()} />)
    expect(screen.queryByText(/Instala la app/)).toBeNull()
  })

  it('tells Chrome-on-iPhone users to open the page in Safari', () => {
    render(<InstallHint platform={iphone({ userAgent: IPHONE_CHROME })} />)
    expect(screen.getByText(/Abre esta página en/)).toBeInTheDocument()
    expect(screen.queryByText('Compartir')).toBeNull()
  })

  it('also shows on an iPad that reports itself as a Mac', () => {
    render(<InstallHint platform={iphone({ userAgent: IPAD_DESKTOP_MODE, platform: 'MacIntel', maxTouchPoints: 5 })} />)
    expect(screen.getByText(/Instala la app/)).toBeInTheDocument()
  })

  it('warns when the page was opened over http', () => {
    render(<InstallHint platform={iphone({ secure: false })} />)
    expect(screen.getByText(/sin candado/)).toBeInTheDocument()
  })

  it('does not show on Android or on a Mac without touch', () => {
    const { unmount } = render(<InstallHint platform={iphone({ userAgent: ANDROID, platform: 'Linux armv8l' })} />)
    expect(screen.queryByText(/Instala la app/)).toBeNull()
    unmount()
    render(<InstallHint platform={iphone({ userAgent: IPAD_DESKTOP_MODE, platform: 'MacIntel', maxTouchPoints: 0 })} />)
    expect(screen.queryByText(/Instala la app/)).toBeNull()
  })
})
