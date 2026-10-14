import type { Session } from './types'

export const CSV_COLUMNS = [
  'id', 'name', 'set', 'number', 'language', 'variant', 'condition', 'price_usd', 'source',
  'exchange_rate', 'cash_offer', 'credit_offer', 'accepted',
] as const

function cell(v: unknown): string {
  const s = v === null || v === undefined ? '' : String(v)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export function sessionCsv(session: Session): string {
  const rows = session.cards.map((c) => [
    c.card_id, c.name, c.set_name, c.number, c.printed_language, c.variant ?? '', c.condition,
    c.price?.usd ?? '', c.price ? (c.price.manual ? 'manual' : c.price.source) : '',
    c.fx?.rate ?? '', c.cash_offer ?? '', c.credit_offer ?? '', c.accepted ? 'yes' : 'no',
  ])
  return [CSV_COLUMNS.join(','), ...rows.map((r) => r.map(cell).join(','))].join('\n') + '\n'
}

export function downloadCsv(session: Session) {
  const blob = new Blob(['﻿' + sessionCsv(session)], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `compra-${session.id}-${session.created_at.slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}
