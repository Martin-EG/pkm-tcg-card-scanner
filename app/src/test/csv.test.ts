import { describe, expect, it } from 'vitest'
import { CSV_COLUMNS, sessionCsv } from '../csv'
import { card, sessionMXN } from './fixtures'

describe('CSV export', () => {
  it('has the agreed columns and one row per card', () => {
    const s = sessionMXN([card(), card({ id: 2, name: 'Mew, "promo"', accepted: false,
      price: { usd: 3, source: 'manual', provider: null, date: '2026-10-14', manual: true, approximate: false, stale: false } })])
    const [header, first, second] = sessionCsv(s).trim().split('\n')
    expect(header).toBe(CSV_COLUMNS.join(','))
    expect(header).toBe('id,name,set,number,language,variant,condition,price_usd,source,exchange_rate,cash_offer,credit_offer,accepted')
    expect(first).toBe('sv05-177,Gastly,Temporal Forces,177,en,holofoil,NM,91.16,tcgplayer,18.4888,1432.62,1516.9,yes')
    expect(second).toContain('"Mew, ""promo"""')
    expect(second).toContain(',manual,')
    expect(second.endsWith(',no')).toBe(true)
  })
})
