// Shapes returned by the shop server (scanner/api.py).

export type Currency = 'MXN' | 'USD'

export interface Settings {
  languages: string[]
  convert_to_mxn: boolean
  currency: Currency
  conditions: { code: string; factor: number }[]
  default_condition: string
  cash_pct: number
  credit_pct: number
  min_offer: number
}

export interface Candidate {
  id: string
  name: string
  set: string
  set_name: string
  number: string
  language: string
  confidence: number
  image_url: string
}

export interface IdentifiedCard {
  index: number
  language: string | null
  confident: boolean
  needs_review: boolean
  ocr_used: boolean
  detected_language: string | null
  warning: string | null
  candidates: Candidate[]
  crop_url: string
}

export interface IdentifyResponse {
  scan_id: number
  seconds: number
  cards: IdentifiedCard[]
}

export interface Price {
  usd: number
  source: string
  provider: string | null
  date: string | null
  manual: boolean
  approximate: boolean
  stale: boolean
}

export interface SessionCard {
  id: number
  card_id: string
  name: string
  set_name: string
  number: string
  catalog_language: string
  printed_language: string
  scan_id: number | null
  card_index: number | null
  condition: string
  variant: string | null
  variants: string[]
  price: Price | null
  fx: { rate: number; date: string } | null
  currency: Currency
  market: number | null
  cash_offer: number | null
  credit_offer: number | null
  buying: boolean | null
  accepted: boolean
  ebay_url: string
}

export interface Session {
  id: number
  created_at: string
  currency: Currency
  fx: { rate: number; date: string; series: string; stale: boolean } | null
  cards: SessionCard[]
  totals: {
    cash: number
    credit: number
    cards_buying: number
    cards_not_buying: number
    cards_without_price: number
  }
}

export interface CardPatch {
  condition?: string
  variant?: string | null
  manual_price_usd?: number | null
  accepted?: boolean
}

// What the phone keeps besides the server's session: the crop and official image per card,
// cards waiting for the employee to pick among 3 options, and changes not yet sent.
export interface CardExtras {
  crop_url: string
  image_url: string
  warning: string | null
}

export interface PendingReview {
  key: string
  scan_id: number
  card: IdentifiedCard
}

export interface QueuedPatch {
  sessionId: number
  cardId: number
  changes: CardPatch
}
