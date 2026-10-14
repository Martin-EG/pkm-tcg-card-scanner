import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Summary } from '../components/Summary'
import { sessionMXN, sessionUSD, settingsMXN, settingsUSD } from './fixtures'

const noop = () => {}

describe('customer summary', () => {
  it('shows pesos and the exchange rate with its date when conversion is on', () => {
    render(<Summary session={sessionMXN()} settings={settingsMXN} extras={{}} onExport={noop} onNew={noop} />)
    expect(screen.getByTestId('currency')).toHaveTextContent('Precios en pesos mexicanos (MXN)')
    expect(screen.getByTestId('fx')).toHaveTextContent('Tipo de cambio: $18.4888 por dólar · Banxico, 14/10/2026')
    expect(screen.getByTestId('total-cash')).toHaveTextContent('$1,432.62')
    expect(screen.getByTestId('total-credit')).toHaveTextContent('$1,516.90')
    expect(screen.getByText(/TCGplayer/)).toBeInTheDocument()
  })

  it('shows dollars and hides the exchange rate when conversion is off', () => {
    render(<Summary session={sessionUSD()} settings={settingsUSD} extras={{}} onExport={noop} onNew={noop} />)
    expect(screen.getByTestId('currency')).toHaveTextContent('Precios en dólares (USD)')
    expect(screen.queryByTestId('fx')).toBeNull()
    expect(screen.queryByText(/Tipo de cambio/)).toBeNull()
    expect(screen.getByTestId('total-cash')).toHaveTextContent('US$77.49')
  })

  it('shows the currency even before any card is added', () => {
    render(<Summary session={null} settings={settingsUSD} extras={{}} onExport={noop} onNew={noop} />)
    expect(screen.getByTestId('currency')).toHaveTextContent('USD')
    expect(screen.queryByTestId('fx')).toBeNull()
  })

  it('marks manual and below-minimum cards', () => {
    const s = sessionMXN([
      { ...sessionMXN().cards[0], id: 1, price: { ...sessionMXN().cards[0].price!, manual: true } },
      { ...sessionMXN().cards[0], id: 2, name: 'Charmander', buying: false, cash_offer: 4.09 },
    ])
    render(<Summary session={s} settings={settingsMXN} extras={{}} onExport={noop} onNew={noop} />)
    expect(screen.getByText(/precio manual/)).toBeInTheDocument()
    expect(screen.getByText('No se compra')).toBeInTheDocument()
  })
})
