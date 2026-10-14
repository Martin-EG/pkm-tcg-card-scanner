import type { Session, SessionCard, Settings } from '../types'

export const settingsMXN: Settings = {
  languages: ['en'], convert_to_mxn: true, currency: 'MXN',
  conditions: [{ code: 'NM', factor: 1 }, { code: 'LP', factor: 0.85 }, { code: 'MP', factor: 0.7 },
    { code: 'HP', factor: 0.5 }, { code: 'DMG', factor: 0.3 }],
  default_condition: 'NM', cash_pct: 0.85, credit_pct: 0.9, min_offer: 10,
}

export const settingsUSD: Settings = { ...settingsMXN, convert_to_mxn: false, currency: 'USD', min_offer: 0.5 }

export function card(over: Partial<SessionCard> = {}): SessionCard {
  return {
    id: 1, card_id: 'sv05-177', name: 'Gastly', set_name: 'Temporal Forces', number: '177',
    catalog_language: 'en', printed_language: 'en', scan_id: 1, card_index: 0,
    condition: 'NM', variant: 'holofoil', variants: ['holofoil'],
    price: { usd: 91.16, source: 'tcgplayer', provider: 'tcgdex', date: '2026-10-13', manual: false, approximate: false, stale: false },
    fx: { rate: 18.4888, date: '2026-10-14' }, currency: 'MXN',
    market: 1685.44, cash_offer: 1432.62, credit_offer: 1516.9, buying: true, accepted: true,
    ebay_url: 'https://www.ebay.com/sch/i.html?_nkw=Gastly', ...over,
  }
}

export function sessionMXN(cards: SessionCard[] = [card()]): Session {
  return {
    id: 7, created_at: '2026-10-14T22:00:00+00:00', currency: 'MXN',
    fx: { rate: 18.4888, date: '2026-10-14', series: 'SF43718', stale: false },
    cards,
    totals: { cash: 1432.62, credit: 1516.9, cards_buying: 1, cards_not_buying: 0, cards_without_price: 0 },
  }
}

export function sessionUSD(): Session {
  return {
    ...sessionMXN([card({ fx: null, currency: 'USD', market: 91.16, cash_offer: 77.49, credit_offer: 82.04 })]),
    currency: 'USD', fx: null,
    totals: { cash: 77.49, credit: 82.04, cards_buying: 1, cards_not_buying: 0, cards_without_price: 0 },
  }
}
